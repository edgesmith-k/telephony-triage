"""시그니처 컴파일과 평가 (04-parser-matching.md §5.11 (1)).

컴파일 (`compile_signature`) — 매처는 메모리 컴파일로 동작한다 (파일 캐시 없음, 06-collaboration.md §6.8).

의미
- `must_match: [p]` — AND. 줄 레코드(`event: null`)의 `"TAG: msg"`에 `search`.
  항목은 문자열이거나 `{id, pattern, min_count?}`(sequence에서 참조하거나 횟수를 둘 때).
- `min_count: N` (`must_match` 객체·`must_event` 항목, 기본 1) — 구간 안에 그 조건의 레코드가 N개 이상.
  근거는 첫 충족 레코드 하나 + `count`(구간 안 개수, N > 1일 때만).
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
- `sequence_within_sec: T` (`sequence`가 있을 때만, ≤ `window_sec`) — sequence 이웃 조건의 첫 충족 레코드 시각 차가
  모두 T초 이하(`= T`는 충족).
- 패턴이 시간 상한을 넘기면(`common/patterns.py`) 그 시그니처는 `error`이고 불충족이다.
- 시그니처·`must_match` 객체·`must_event` 항목의 모르는 키는 컴파일 오류(`SIGNATURE_KEYS` 등 = 스키마 properties).
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
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
    min_count: int = 1

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
    sequence_within_sec: float | None = None


# 아는 키 (= type.schema.json `$defs`의 properties, tests/test_signatures_window.py가 고정). 모르는 키는 컴파일 오류 —
# 새 필드(예: min_count)를 모르는 매처가 조용히 기본값으로 읽지 않게 한다.
SIGNATURE_KEYS = frozenset({"id", "must_match", "must_event", "must_not_match", "window_sec", "same_phone", "sequence",
                            "sequence_within_sec"})
MATCH_ITEM_KEYS = frozenset({"id", "pattern", "min_count"})
EVENT_ITEM_KEYS = frozenset({"id", "event", "fields", "min_count"})


def _unknown(item: dict, allowed: frozenset, key: str, where: str) -> None:
    extra = set(item) - allowed
    if extra:
        raise SignatureError(f"{key}: {where} 모르는 키 {sorted(extra)}")


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _min_count(item: dict, key: str) -> int:
    value = item.get("min_count", 1)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SignatureError(f"{key}: min_count는 1 이상 정수여야 합니다: {value!r}")
    return value


def _check_regex(text: str, where: str) -> None:
    try:
        re.compile(text)
    except re.error as exc:
        raise SignatureError(f"{where}: 정규식 오류 {text!r}: {exc}") from exc


def compile_signature(raw: dict, owner_id: str) -> Signature:
    if not isinstance(raw, dict) or not raw.get("id"):
        raise SignatureError(f"{owner_id}: 시그니처에 id가 없습니다.")
    key = f"{owner_id}/{raw['id']}"
    _unknown(raw, SIGNATURE_KEYS, key, "시그니처에")
    positives: list[Condition] = []
    for item in raw.get("must_match") or []:
        if isinstance(item, str):
            cond = Condition(id=None, kind="match", pattern=item)
        elif isinstance(item, dict) and isinstance(item.get("pattern"), str):
            _unknown(item, MATCH_ITEM_KEYS, key, "must_match 항목에")
            cond = Condition(id=item.get("id"), kind="match", pattern=item["pattern"], min_count=_min_count(item, key))
        else:
            raise SignatureError(f"{key}: must_match 항목 형식이 잘못됐습니다: {item!r}")
        _check_regex(cond.pattern, key)
        positives.append(cond)
    for item in raw.get("must_event") or []:
        if not isinstance(item, dict) or not item.get("event"):
            raise SignatureError(f"{key}: must_event 항목에 event가 없습니다: {item!r}")
        _unknown(item, EVENT_ITEM_KEYS, key, "must_event 항목에")
        fields = {str(k): str(v) for k, v in (item.get("fields") or {}).items()}
        for value in fields.values():
            _check_regex(value, key)
        positives.append(Condition(id=item.get("id"), kind="event", event=item["event"], fields=fields,
                                   min_count=_min_count(item, key)))
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
    gap = raw.get("sequence_within_sec")
    if gap is not None:
        if not _number(gap) or gap <= 0:
            raise SignatureError(f"{key}: sequence_within_sec는 0보다 큰 수여야 합니다: {gap!r}")
        if not sequence:
            raise SignatureError(f"{key}: sequence_within_sec는 sequence가 있을 때만 쓴다.")
        if gap > window:
            raise SignatureError(f"{key}: sequence_within_sec({gap})가 window_sec({window})보다 큽니다.")
    return Signature(
        key=key,
        id=str(raw["id"]),
        positives=positives,
        negatives=negatives,
        window_sec=float(window),
        same_phone=bool(raw.get("same_phone", True)),
        sequence=sequence,
        sequence_within_sec=None if gap is None else float(gap),
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
        counted = any(c.min_count > 1 for c in sig.positives)
        for slot in groups:
            ok = (lambda i: True) if slot is None else (lambda i, s=slot: phone(i) in (s, None))
            gpos = [[i for i in hits if ok(i)] for hits in pos]
            if any(not hits for hits in gpos):
                continue
            gneg = [i for i in neg if ok(i)]
            found = self._search_window(sig, gpos, gneg, occurred, all_matches)
            if counted and found:     # 근거 `count`: 그 구간·슬롯 안 조건별 레코드 수 (구간 튜플 끝에 붙인다)
                found = ([f + (self._counts(gpos, f),) for f in found] if all_matches
                         else found + (self._counts(gpos, found),))
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
            evidence = self._evidence(sig, indices, found[4] if len(found) > 4 else None)
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

    def _counts(self, gpos: list[list[int]], found: tuple) -> list[int]:
        a, b = found[2], found[3]
        return [sum(a <= self.dts[i] <= b for i in hits) for hits in gpos]

    def _evidence(self, sig: Signature, indices: tuple[int, ...], counts: list[int] | None = None) -> list[dict]:
        evidence = []
        for k, (cond, i) in enumerate(zip(sig.positives, indices)):
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
                **({"count": counts[k]} if counts and cond.min_count > 1 else {}),
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
        need = [c.min_count for c in sig.positives]
        gap = None if sig.sequence_within_sec is None else timedelta(seconds=sig.sequence_within_sec)
        best = None
        matches = []
        for a in sorted(c for c in candidates if lo <= c <= a_max):
            b = a + width
            j = bisect_left(neg_dts, a)
            if j < len(neg_dts) and neg_dts[j] <= b:  # 닫힌 구간 [a, b] 안의 부정 조건
                continue
            firsts = []
            for ks, ds, k in zip(keyed, key_dts, need):
                j = bisect_left(ds, a)
                if j + k > len(ds) or ds[j + k - 1] > b:   # 구간 안 k번째 hit (min_count, 기본 1)
                    break
                firsts.append(ks[j][1])
            else:
                if sig.sequence:
                    seq = [firsts[order[s]] for s in sig.sequence]
                    keys = [(self.dts[i], i) for i in seq]
                    if any(x >= y for x, y in zip(keys, keys[1:])):
                        continue
                    if gap is not None and any(self.dts[y] - self.dts[x] > gap for x, y in zip(seq, seq[1:])):
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

    # -- C′ 부분 일치 (04-parser-matching.md §5.12, 분석 모드 표시 전용 — 판정 `_evaluate`는 쓰지 않는다) ------

    def partial(self, sig: Signature, occurred: datetime | None = None) -> dict | None:
        """완전 일치가 아닌 시그니처가 얼마나 가까운지: `{kind, m, n, hits[인덱스], missing[Condition], blocked_by?,
        order?[id, id], gap_sec?, width_sec?, short?[개수|None], dist}` 또는 None(해당 없음·오류·범위 없음). 호출자는 완전 일치·오류가
        아닌 것에만 부른다. kind: missing(구간 최대 m, 1 ≤ m < n, m/n ≥ 0.5; min_count 모자람은 `short`에 구간 안 개수, 그 조건도
        한 건 있음으로 세어 0.5를 본다) · absent(n=1, 0건) · blocked(양성 n개 구간마다 부정 줄) · order(양성 n개 구간에서 sequence
        어긋남, 순서는 맞고 이웃 간격이 sequence_within_sec를 넘으면 `gap_sec`) · window(양성 n개가 범위엔 있으나 W 구간 하나에 안 듦)."""
        try:
            pos = [self.lines(c.pattern) if c.kind == "match" else self.matching_events(c) for c in sig.positives]
            negs = [self.lines(p) for p in sig.negatives]
        except (PatternTimeout, PatternError):
            return None
        if self.lo is None or self.hi is None:
            return None
        width = timedelta(seconds=sig.window_sec)
        end = max(self.hi, self.lo + width)
        pos = [[i for i in hits if self.lo <= self.dts[i] <= end] for hits in pos]
        phone = lambda i: self.events[i].get("phone_id")  # noqa: E731
        slots = sorted({phone(i) for h in pos for i in h if phone(i) is not None}) if sig.same_phone else []
        best = None
        for slot in slots or [None]:
            ok = (lambda i: True) if slot is None else (lambda i, s=slot: phone(i) in (s, None))
            found = self._partial_group(sig, [[i for i in h if ok(i)] for h in pos],
                                        [[i for i in h if ok(i)] for h in negs], occurred, width)
            if found and (best is None or found["_rank"] < best["_rank"]):
                best = found
        if best:
            best.pop("_rank")
        return best

    def _partial_group(self, sig: Signature, pos, negs, occurred, width) -> dict | None:
        n = len(pos)
        lo, a_max = self.lo, max(self.lo, self.hi - width)
        times = {self.dts[i] for h in pos for i in h} | {self.dts[i] for h in negs for i in h}
        cands = {lo, a_max}
        for t in times:
            cands.update((t - width, t, t + _EPS, t - width + _EPS))
        keyed = [sorted((self.dts[i], i) for i in h) for h in pos]
        key_dts = [[d for d, _ in ks] for ks in keyed]
        neg_dts = [sorted(self.dts[i] for i in h) for h in negs]
        order = {c.id: k for k, c in enumerate(sig.positives) if c.id}
        need = [c.min_count for c in sig.positives]
        best_m, best_seen, best_firsts, best_short, full_free, blocked = 0, 0, None, {}, None, None
        for a in sorted(c for c in cands if lo <= c <= a_max):
            b = a + width
            firsts, short = [], {}
            for k, (ks, ds, nk) in enumerate(zip(keyed, key_dts, need)):
                j = bisect_left(ds, a)
                got = int(j < len(ds) and ds[j] <= b) if nk == 1 else bisect_right(ds, b, j) - j
                firsts.append(ks[j][1] if got >= nk else None)
                if 0 < got < nk:
                    short[k] = got       # 횟수 모자람: missing에 `min_count N 중 got`
            m = sum(f is not None for f in firsts)
            seen = m + len(short)        # 구간 안에 한 건이라도 있는 조건 수 (기본 min_count면 m과 같다)
            if (m, seen) > (best_m, best_seen):
                best_m, best_seen, best_firsts, best_short = m, seen, firsts, short
            if m == n:
                hit_neg = [k for k, ds in enumerate(neg_dts)
                           if (j := bisect_left(ds, a)) < len(ds) and ds[j] <= b]
                if not hit_neg and full_free is None:
                    full_free = firsts
                elif hit_neg and blocked is None:
                    blocked = (firsts, hit_neg[0])
        out: dict = {"n": n}
        if full_free is not None and sig.sequence:
            seq = [full_free[order[s]] for s in sig.sequence]
            pair = next((k for k, (x, y) in enumerate(zip(seq, seq[1:]))
                         if (self.dts[x], x) >= (self.dts[y], y)), None)
            extra = {}
            if pair is None and sig.sequence_within_sec is not None:   # 순서는 맞고 이웃 간격이 T를 넘음: order + gap_sec
                gaps = [self.dts[y] - self.dts[x] for x, y in zip(seq, seq[1:])]
                pair = next((k for k, g in enumerate(gaps) if g > timedelta(seconds=sig.sequence_within_sec)), None)
                if pair is not None:
                    extra["gap_sec"] = round(gaps[pair].total_seconds(), 3)
            pair = pair or 0
            out.update(kind="order", m=n, hits=full_free, missing=[], order=sig.sequence[pair:pair + 2], **extra)
        elif blocked is not None and full_free is None:
            out.update(kind="blocked", m=n, hits=blocked[0], missing=[], blocked_by=sig.negatives[blocked[1]])
        elif full_free is None and not best_short and all(len(h) >= nk for h, nk in zip(pos, need)):
            if any(nk > 1 for nk in need):     # 한 건씩 고른 폭은 min_count와 맞지 않는다 — 폭을 내지 않는다
                out.update(kind="window", m=n, hits=[ks[0][1] for ks in keyed], missing=[])
            else:
                span, picks = self._min_span(keyed)
                out.update(kind="window", m=n, hits=picks, missing=[], width_sec=round(span, 3))
        elif n == 1 and best_seen == 0:
            out.update(kind="absent", m=0, hits=[], missing=[sig.positives[0]])
        elif best_m < n and 1 <= best_seen and best_seen / n >= 0.5:
            missing = [k for k, f in enumerate(best_firsts) if f is None]
            out.update(kind="missing", m=best_m, hits=best_firsts, missing=[sig.positives[k] for k in missing])
            if best_short:
                out["short"] = [best_short.get(k) for k in missing]   # missing과 같은 순서, 횟수 모자람이면 구간 안 개수
        else:
            return None
        out["hits"] = [(sig.positives[k], i) for k, i in enumerate(out["hits"]) if i is not None]   # (조건, 레코드)
        hits = [i for _c, i in out["hits"]]
        if not hits:
            out["dist"] = float("inf")
        elif occurred is not None:
            out["dist"] = min(abs((self.dts[i] - occurred).total_seconds()) for i in hits)
        else:
            out["dist"] = min((self.dts[i] - lo).total_seconds() for i in hits)
        out["_rank"] = (PARTIAL_KINDS.index(out["kind"]), -out["m"] / n, len(out["missing"]), out["dist"])
        return out

    def _min_span(self, keyed) -> tuple[float, list[int]]:
        """조건마다 하나씩 고른 레코드가 드는 가장 짧은 시간 폭(초)과 그 레코드들 (window kind 표시용)."""
        merged = sorted((d, i, k) for k, ks in enumerate(keyed) for d, i in ks)
        need, have, best, left = len(keyed), {}, None, 0
        for right, (d, _i, k) in enumerate(merged):
            have[k] = have.get(k, 0) + 1
            while len(have) == need:
                ld, _li, lk = merged[left]
                span = (d - ld).total_seconds()
                if best is None or span < best[0]:
                    picks: dict[int, int] = {}
                    for _d, wi, wk in merged[left:right + 1]:
                        picks.setdefault(wk, wi)
                    best = (span, [picks[x] for x in range(need)])
                have[lk] -= 1
                if not have[lk]:
                    del have[lk]
                left += 1
        return best or (0.0, [])


PARTIAL_KINDS = ("missing", "absent", "order", "window", "blocked")   # 부분 일치 순위 순 (§5.12)


REGEX_META = set(".^$*+?{}[]\\|()")


def literal_anchor(pattern: str) -> str | None:
    """정규식 앞머리 리터럴의 첫 낱말(첫 메타 문자·공백·`:` 전) — 평가 글 `TAG: msg`의 태그 자리에 올 수 있는 글자. 3자 미만이면 None.
    match_signatures(배제 조건 검증 불가 판정)와 db_lint(태그 자리 낱말이 tags.yaml에 있는지)가 같이 쓴다."""
    lit = []
    for ch in pattern:
        if ch in REGEX_META:
            break
        lit.append(ch)
    word = re.split(r"[\s:]", "".join(lit).strip(), maxsplit=1)[0]
    return word if len(word) >= 3 else None


def tag_position_word(pattern: str) -> str | None:
    """패턴이 **태그 자리**로 시작하는 것으로 보일 때 그 낱말: 앞머리 리터럴 낱말이 대문자로 시작하고 `_`가 없으며(RIL 요청·unsol 이름
    `RIL_REQUEST_DIAL`·`IMS_UNSOL_…`은 메시지 낱말) 바로 뒤가 regex 틈(`.*`·`\\s`)이다(`RILJ.*>\\s*SETUP_DATA_CALL` → RILJ).
    `낱말:`(메시지 키)·`낱말 다음낱말`(메시지 문구)·`|`·끝은 None — 보수적으로, 놓치는 쪽을 택한다."""
    word = literal_anchor(pattern)
    if not word or "_" in word or not re.match(r"^[A-Z][A-Za-z0-9-]*$", word):
        return None
    rest = pattern[len(word):]
    return word if re.match(r"(?:\.\*|\\s)", rest) else None
