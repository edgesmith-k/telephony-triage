"""시그니처 컴파일과 평가 (04-parser-matching.md §5.11 (1)).

컴파일 (`compile_signature`) — 매처는 메모리 컴파일로 동작한다 (파일 캐시 없음, 06-collaboration.md §6.8).

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
  시계 이상 구간의 근거·같은 파일 줄 순서 역전은 `Result.flags`로 표시만 한다(판정 불변).
- 패턴이 시간 상한을 넘기면(`common/patterns.py`) 그 시그니처는 `error`이고 불충족이다.
"""

from __future__ import annotations

import re
from bisect import bisect_left
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
    same_phone: bool = True
    window_sec: float = 0
    window: tuple[datetime, datetime] | None = None
    flags: list[str] = field(default_factory=list)  # "clock_anomaly" | "line_order" (표시만)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Evaluator:
    """한 이벤트 목록에 대해 시그니처를 평가한다. 패턴 결과는 캐시한다."""

    def __init__(self, events: list[dict], lo: datetime | None, hi: datetime | None,
                 timeout_ms: int | None = None, ids: list[int] | None = None,
                 anomalies: list[tuple[datetime, datetime]] = (),
                 line_order_tolerance_sec: float | None = None):
        # `ids[i]`: `events[i]`의 원래 입력 문서 `events[]` 안 순번 (근거 `event_index`). 없으면 `i`.
        # `anomalies`: 시계 이상 의심 시각 구간. `line_order_tolerance_sec`: sequence 이웃 근거가
        # 같은 파일에서 줄 순서는 거꾸로인데 시각이 이만큼 이상 앞서면 `line_order`(없으면 검사 안 함).
        self.anomalies = list(anomalies)
        self.line_order_tolerance_sec = line_order_tolerance_sec
        self.events = events
        self.ids = ids
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
        return self._evaluate(sig, occurred, False)[0]

    def evaluate_all(self, sig: Signature, occurred: datetime | None = None) -> list[Result]:
        """Keep distinct matching slots/episodes for analysis candidate joining."""
        return self._evaluate(sig, occurred, True)

    def _evaluate(self, sig: Signature, occurred: datetime | None, all_matches: bool) -> list[Result]:
        try:
            pos = [self.lines(c.pattern) if c.kind == "match" else self.matching_events(c)
                   for c in sig.positives]
            neg = sorted({i for p in sig.negatives for i in self.lines(p)})
        except PatternTimeout as exc:
            return [Result(sig.key, False, error=f"timeout: {exc}")]
        except PatternError as exc:
            return [Result(sig.key, False, error=f"regex: {exc}")]
        if self.lo is None or self.hi is None or any(not hits for hits in pos):
            return [Result(sig.key, False)]

        phone = lambda i: self.events[i].get("phone_id")  # noqa: E731
        if sig.same_phone:
            slots = sorted({phone(i) for hits in pos for i in hits if phone(i) is not None})
            groups = slots or [None]
        else:
            groups = [None]

        best: tuple | None = None
        matches = []
        for slot in groups:
            ok = (lambda i: True) if slot is None else (lambda i, s=slot: phone(i) in (s, None))
            gpos = [[i for i in hits if ok(i)] for hits in pos]
            if any(not hits for hits in gpos):
                continue
            gneg = [i for i in neg if ok(i)]
            found = self._search_window(sig, gpos, gneg, occurred, all_matches)
            if all_matches:
                matches.extend(found)
            elif found and (best is None or found[0] < best[0]):
                best = found
        if all_matches:
            matches.sort(key=lambda found: found[0])
        else:
            matches = [best] if best else []
        if not matches:
            return [Result(sig.key, False)]
        results, seen = [], set()
        for found in matches:
            indices = tuple(found[1])
            if indices in seen:
                continue
            seen.add(indices)
            evidence = self._evidence(sig, indices)
            results.append(Result(sig.key, True, evidence=evidence, same_phone=sig.same_phone,
                                  window_sec=sig.window_sec, window=(found[2], found[3]),
                                  flags=self._flags(sig, indices)))
        return results

    def _flags(self, sig: Signature, indices: tuple[int, ...]) -> list[str]:
        """판정에 쓰지 않는 신뢰 표시. 근거가 시계 이상 구간에 걸치거나 sequence 줄 순서가 역전됐는가."""
        flags = []
        dts = [self.dts[i] for i in indices]
        start, end = min(dts), max(dts)
        if any(a <= end and start <= b for a, b in self.anomalies):
            flags.append("clock_anomaly")
        if sig.sequence and self.line_order_tolerance_sec is not None:
            order = {c.id: n for n, c in enumerate(sig.positives) if c.id}
            seq = [indices[order[s]] for s in sig.sequence]
            for x, y in zip(seq, seq[1:]):
                rx, ry = self.events[x].get("line_ref"), self.events[y].get("line_ref")
                if (rx and ry and rx.get("line_no") and ry.get("line_no")
                        and rx["file_index"] == ry["file_index"] and ry["line_no"] < rx["line_no"]
                        and (self.dts[y] - self.dts[x]).total_seconds() >= self.line_order_tolerance_sec):
                    flags.append("line_order")
                    break
        return sorted(set(flags))

    def _evidence(self, sig: Signature, indices: tuple[int, ...]) -> list[dict]:
        evidence = []
        for cond, i in zip(sig.positives, indices):
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
                "line_ref": e.get("line_ref"),
                "event_index": self.ids[i] if self.ids is not None else i,
            })
        return evidence

    def _search_window(self, sig: Signature, pos: list[list[int]], neg: list[int],
                       occurred: datetime | None, all_matches: bool = False):
        width = timedelta(seconds=sig.window_sec)
        lo, hi = self.lo, self.hi
        a_max = max(lo, hi - width)
        times = {self.dts[i] for hits in pos for i in hits} | {self.dts[i] for i in neg}
        candidates = {lo, a_max}
        for t in times:
            candidates.update((t - width, t, t + _EPS, t - width + _EPS))
        order = {c.id: n for n, c in enumerate(sig.positives) if c.id}
        # 구간마다 조건 hit 전체를 훑지 않도록 (시각, 인덱스) 정렬본에서 bisect로 찾는다.
        # `[a, b]` 안의 최소 (시각, 인덱스)는 정렬본에서 시각 ≥ a인 첫 항목이다(그 시각이 ≤ b일 때 안에 있다).
        keyed = [sorted((self.dts[i], i) for i in hits) for hits in pos]
        key_dts = [[d for d, _ in ks] for ks in keyed]
        neg_dts = sorted(self.dts[i] for i in neg)
        best = None
        matches = []
        for a in sorted(c for c in candidates if lo <= c <= a_max):
            b = a + width
            j = bisect_left(neg_dts, a)
            if j < len(neg_dts) and neg_dts[j] <= b:  # 닫힌 구간 [a, b] 안의 부정 조건
                continue
            firsts = []
            for ks, ds in zip(keyed, key_dts):
                j = bisect_left(ds, a)
                if j == len(ds) or ds[j] > b:
                    break
                firsts.append(ks[j][1])
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
                    best = (rank, firsts, a, b)
                if all_matches:
                    matches.append((rank, firsts, a, b))
        return matches if all_matches else best
