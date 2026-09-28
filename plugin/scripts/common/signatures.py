"""시그니처 컴파일과 평가 (04-parser-matching.md §5.11 (1)).

컴파일 (`compile_signature`) — 매처는 메모리 컴파일로 동작한다. 파일 캐시
(`.cache/compiled.json`)는 Phase 5의 `db_build --cache-only`가 이 함수를 공유한다.

의미
- `must_match: [p]` — AND. 줄 레코드(`event: null`)의 `"TAG: msg"`에 `search`.
  항목은 문자열이거나 `{id, pattern}`(sequence에서 참조할 때).
- `must_event: [{id?, event, fields?}]` — AND. `fields` 값은 정규식이고 필드 값 전체에
  `fullmatch`. 필드가 없는 이벤트는 맞지 않는다.
- `must_not_match: [p]` — 같은 윈도우 안에 하나라도 있으면 불충족.
- `window_sec` — 분석 범위 `[lo, hi]` 안의 길이 `window_sec` 구간 `[a, a+W]`
  (`lo ≤ a ≤ max(lo, hi-W)`) 중 조건을 모두 만족하는 구간이 하나라도 있으면 충족.
  범위가 W보다 짧으면 범위 시작에서 시작하는 구간 하나만 본다.
- `same_phone` (기본 true) — 모든 조건(부정 조건 포함)을 같은 `phone_id`의 레코드로
  본다. `phone_id: null` 레코드는 어느 슬롯과도 맞는다. false면 슬롯을 가리지 않는다.
- `sequence: [id...]` — 구간 안에서 각 조건의 **첫 충족 레코드**가 나열 순서대로
  앞선다(시각, 같으면 입력 순서). `must_not_match`는 넣을 수 없다.
- 패턴이 시간 상한을 넘기면(`common/patterns.py`) 그 시그니처는 `error`이고 불충족이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .patterns import PatternError, PatternRunner, PatternTimeout

_EPS = timedelta(microseconds=1)


class SignatureError(Exception):
    pass


@dataclass
class Condition:
    id: str | None
    kind: str  # "match" | "event"
    pattern: str | None = None
    event: str | None = None
    fields: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        if self.kind == "match":
            return f"must_match {self.pattern!r}"
        return f"must_event {self.event}" + (f" {self.fields}" if self.fields else "")


@dataclass
class Signature:
    key: str  # 전역 키 <유형 또는 원인 ID>/<sig id>
    id: str
    positives: list[Condition]
    negatives: list[str]
    window_sec: float
    same_phone: bool
    sequence: list[str]


def _check_regex(text: str, where: str) -> None:
    try:
        re.compile(text)
    except re.error as exc:
        raise SignatureError(f"{where}: 정규식 오류 {text!r}: {exc}") from exc


def compile_signature(raw: dict, owner_id: str) -> Signature:
    if not isinstance(raw, dict) or not raw.get("id"):
        raise SignatureError(f"{owner_id}: 시그니처에 id가 없습니다.")
    key = f"{owner_id}/{raw['id']}"
    positives: list[Condition] = []
    for item in raw.get("must_match") or []:
        if isinstance(item, str):
            cond = Condition(id=None, kind="match", pattern=item)
        elif isinstance(item, dict) and isinstance(item.get("pattern"), str):
            cond = Condition(id=item.get("id"), kind="match", pattern=item["pattern"])
        else:
            raise SignatureError(f"{key}: must_match 항목 형식이 잘못됐습니다: {item!r}")
        _check_regex(cond.pattern, key)
        positives.append(cond)
    for item in raw.get("must_event") or []:
        if not isinstance(item, dict) or not item.get("event"):
            raise SignatureError(f"{key}: must_event 항목에 event가 없습니다: {item!r}")
        fields = {str(k): str(v) for k, v in (item.get("fields") or {}).items()}
        for value in fields.values():
            _check_regex(value, key)
        positives.append(Condition(id=item.get("id"), kind="event", event=item["event"], fields=fields))
    if not positives:
        raise SignatureError(f"{key}: must_match 또는 must_event가 필요합니다.")
    negatives = [str(p) for p in raw.get("must_not_match") or []]
    for pattern in negatives:
        _check_regex(pattern, key)
    ids = [c.id for c in positives if c.id]
    if len(ids) != len(set(ids)):
        raise SignatureError(f"{key}: 조건 id가 겹칩니다: {ids}")
    sequence = [str(s) for s in raw.get("sequence") or []]
    missing = [s for s in sequence if s not in ids]
    if missing:
        raise SignatureError(f"{key}: sequence의 id {missing}가 조건에 없습니다.")
    window = raw.get("window_sec")
    if not isinstance(window, (int, float)) or window <= 0:
        raise SignatureError(f"{key}: window_sec가 필요합니다.")
    return Signature(
        key=key,
        id=str(raw["id"]),
        positives=positives,
        negatives=negatives,
        window_sec=float(window),
        same_phone=bool(raw.get("same_phone", True)),
        sequence=sequence,
    )


def compile_list(raws, owner_id: str) -> list[Signature]:
    return [compile_signature(raw, owner_id) for raw in raws or []]


@dataclass
class Result:
    key: str
    satisfied: bool
    evidence: list[dict] = field(default_factory=list)
    error: str | None = None


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Evaluator:
    """한 이벤트 목록에 대해 시그니처를 평가한다. 패턴 결과는 캐시한다."""

    def __init__(self, events: list[dict], lo: datetime | None, hi: datetime | None,
                 timeout_ms: int | None = None):
        self.events = events
        self.dts = [_parse_ts(e["ts"]) for e in events]
        self.lo, self.hi = lo, hi
        self.line_idx = [i for i, e in enumerate(events) if e.get("event") is None]
        texts = [f"{events[i].get('tag')}: {events[i].get('msg')}" for i in self.line_idx]
        self.runner = PatternRunner(texts, timeout_ms)
        self.by_event: dict[str, list[int]] = {}
        for i, e in enumerate(events):
            if e.get("event"):
                self.by_event.setdefault(e["event"], []).append(i)
        self._cache: dict = {}

    def close(self) -> None:
        self.runner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- 조건 → 레코드 인덱스 --------------------------------------------------

    def _cached(self, key, compute):
        if key not in self._cache:
            try:
                self._cache[key] = compute()
            except (PatternTimeout, PatternError) as exc:
                self._cache[key] = exc
        value = self._cache[key]
        if isinstance(value, Exception):
            raise value
        return value

    def lines(self, pattern: str) -> list[int]:
        return self._cached(("m", pattern), lambda: [self.line_idx[j] for j in self.runner.search(pattern)])

    def matching_events(self, cond: Condition) -> list[int]:
        def compute():
            hits = list(self.by_event.get(cond.event, []))
            for name, regex in sorted(cond.fields.items()):
                values = [self.events[i].get("fields", {}).get(name) for i in hits]
                values = [None if v is None else str(v) for v in values]
                keep = self.runner.search(regex, texts=values, mode="fullmatch")
                hits = [hits[j] for j in keep]
            return hits

        return self._cached(("e", cond.event, tuple(sorted(cond.fields.items()))), compute)

    # -- 평가 -----------------------------------------------------------------

    def evaluate(self, sig: Signature, occurred: datetime | None = None) -> Result:
        try:
            pos = [self.lines(c.pattern) if c.kind == "match" else self.matching_events(c)
                   for c in sig.positives]
            neg = sorted({i for p in sig.negatives for i in self.lines(p)})
        except PatternTimeout as exc:
            return Result(sig.key, False, error=f"timeout: {exc}")
        except PatternError as exc:
            return Result(sig.key, False, error=f"regex: {exc}")
        if self.lo is None or self.hi is None or any(not hits for hits in pos):
            return Result(sig.key, False)

        phone = lambda i: self.events[i].get("phone_id")  # noqa: E731
        if sig.same_phone:
            slots = sorted({phone(i) for hits in pos for i in hits if phone(i) is not None})
            groups = slots or [None]
        else:
            groups = [None]

        best: tuple | None = None
        for slot in groups:
            ok = (lambda i: True) if slot is None else (lambda i, s=slot: phone(i) in (s, None))
            gpos = [[i for i in hits if ok(i)] for hits in pos]
            if any(not hits for hits in gpos):
                continue
            gneg = [i for i in neg if ok(i)]
            found = self._search_window(sig, gpos, gneg, occurred)
            if found and (best is None or found[0] < best[0]):
                best = found
        if best is None:
            return Result(sig.key, False)
        evidence = []
        for cond, i in zip(sig.positives, best[1]):
            e = self.events[i]
            evidence.append({
                "signature": sig.key,
                "condition": cond.id or cond.describe(),
                "ts": e["ts"],
                "tag": e.get("tag"),
                "msg": e.get("msg"),
                "event": e.get("event"),
                "fields": e.get("fields") or {},
                "phone_id": e.get("phone_id"),
            })
        return Result(sig.key, True, evidence=evidence)

    def _search_window(self, sig: Signature, pos: list[list[int]], neg: list[int],
                       occurred: datetime | None):
        width = timedelta(seconds=sig.window_sec)
        lo, hi = self.lo, self.hi
        a_max = max(lo, hi - width)
        times = {self.dts[i] for hits in pos for i in hits} | {self.dts[i] for i in neg}
        candidates = {lo, a_max}
        for t in times:
            candidates.update((t - width, t, t + _EPS, t - width + _EPS))
        order = {c.id: n for n, c in enumerate(sig.positives) if c.id}
        best = None
        for a in sorted(c for c in candidates if lo <= c <= a_max):
            b = a + width
            if any(a <= self.dts[i] <= b for i in neg):
                continue
            firsts = []
            for hits in pos:
                inside = [i for i in hits if a <= self.dts[i] <= b]
                if not inside:
                    break
                firsts.append(min(inside, key=lambda i: (self.dts[i], i)))
            else:
                if sig.sequence:
                    seq = [firsts[order[s]] for s in sig.sequence]
                    keys = [(self.dts[i], i) for i in seq]
                    if any(x >= y for x, y in zip(keys, keys[1:])):
                        continue
                if occurred is not None:
                    rank = min(abs((self.dts[i] - occurred).total_seconds()) for i in firsts)
                else:
                    rank = (a - lo).total_seconds()
                if best is None or rank < best[0]:
                    best = (rank, firsts)
        return best
