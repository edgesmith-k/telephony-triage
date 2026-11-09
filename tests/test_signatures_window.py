#!/usr/bin/env python3
"""`Evaluator._search_window`(bisect 구현)가 예전 구현과 같은 결과를 내는지 본다 (R15, O1).

예전 구현(구간마다 hit 전체를 훑는 O(H²))을 `_legacy_search_window`로 그대로 두고, 같은 무작위 입력에
둘을 돌려 충족 여부·근거·구간이 같은지 비교한다. 시간은 재지 않는다 (측정은 `tools/bench_scale.py`).
"""

from __future__ import annotations

import copy
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import plugin_root  # noqa: E402

sys.path.insert(0, str(plugin_root() / "scripts"))

from common import signatures  # noqa: E402
from common.signatures import _EPS, Evaluator  # noqa: E402

BASE = datetime(2026, 9, 20, 5, 30, 0, tzinfo=timezone.utc)
WORDS = ["alpha", "beta", "gamma", "neg"]


def _legacy_search_window(self, sig, pos, neg, occurred, all_matches=False):
    """bisect 도입 전 구현 (그대로 복사). 비교 기준이다."""
    width = timedelta(seconds=sig.window_sec)
    lo, hi = self.lo, self.hi
    a_max = max(lo, hi - width)
    times = {self.dts[i] for hits in pos for i in hits} | {self.dts[i] for i in neg}
    candidates = {lo, a_max}
    for t in times:
        candidates.update((t - width, t, t + _EPS, t - width + _EPS))
    order = {c.id: n for n, c in enumerate(sig.positives) if c.id}
    best = None
    matches = []
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
                best = (rank, firsts, a, b)
            if all_matches:
                matches.append((rank, firsts, a, b))
    return matches if all_matches else best


def _case(rng: random.Random):
    n = rng.randint(4, 40)
    span_ms = rng.choice([500, 3000, 20000, 120000])
    events = []
    for _ in range(n):
        t = BASE + timedelta(milliseconds=rng.randint(0, span_ms) // rng.choice([1, 100]) * rng.choice([1, 1, 10]))
        word = rng.choice(WORDS)
        named = rng.random() < 0.2
        events.append({
            "ts": f"{t:%Y-%m-%dT%H:%M:%S}.{t.microsecond // 1000:03d}Z", "tag": "T",
            "msg": f"{word} x", "phone_id": rng.choice([0, 1, None]),
            "event": "e.x" if named else None, "fields": {"k": "v"} if named else {},
        })
    events.sort(key=lambda e: e["ts"])  # 매처는 시각순으로 정렬해 넘긴다 (동률은 입력 순서)
    words = rng.sample(WORDS[:3], rng.randint(1, 3))
    raw = {"id": "s", "window_sec": rng.choice([0.5, 1, 3, 10, 300]), "same_phone": rng.random() < 0.6}
    must = [{"id": f"c{i}", "pattern": f"T: {w}"} for i, w in enumerate(words)]
    raw["must_match"] = must
    if rng.random() < 0.3:
        raw["must_event"] = [{"id": "ev", "event": "e.x", "fields": {"k": "v"}}]
    if rng.random() < 0.5:
        raw["must_not_match"] = ["T: neg"]
    ids = [c["id"] for c in raw["must_match"]] + (["ev"] if "must_event" in raw else [])
    if len(ids) >= 2 and rng.random() < 0.5:
        raw["sequence"] = rng.sample(ids, rng.randint(2, len(ids)))
    sig = signatures.compile_signature(raw, "OWN")
    dts = [signatures._parse_ts(e["ts"]) for e in events]
    lo, hi = min(dts), max(dts)
    if rng.random() < 0.3:  # 범위를 줄이거나 넓힌다 (창이 범위보다 긴 경우 포함)
        lo, hi = lo + timedelta(milliseconds=rng.randint(0, 500)), hi + timedelta(seconds=rng.randint(-2, 5))
        hi = max(hi, lo)
    occurred = BASE + timedelta(seconds=rng.randint(0, 60)) if rng.random() < 0.5 else None
    return events, sig, lo, hi, occurred, raw


def _view(results):
    return [(r.satisfied, r.error, r.evidence, r.window) for r in results]


def test_bisect_search_window_matches_legacy():
    """D①: 기본값(`min_count` 없음, `sequence_within_sec` 없음)은 예전 구현과 결과가 같고, 명시한 `min_count: 1`도 같다."""
    rng = random.Random(20261005)
    new = Evaluator._search_window
    satisfied = 0
    for _ in range(300):
        events, sig, lo, hi, occurred, raw = _case(rng)
        explicit = copy.deepcopy(raw)
        for item in explicit["must_match"] + explicit.get("must_event", []):
            item["min_count"] = 1
        explicit_sig = signatures.compile_signature(explicit, "OWN")
        with Evaluator(events, lo, hi, 5000) as ev:
            got = [ev.evaluate(sig, occurred), *ev.evaluate_all(sig, occurred)]
            same = [ev.evaluate(explicit_sig, occurred), *ev.evaluate_all(explicit_sig, occurred)]
            Evaluator._search_window = _legacy_search_window
            try:
                want = [ev.evaluate(sig, occurred), *ev.evaluate_all(sig, occurred)]
            finally:
                Evaluator._search_window = new
        assert _view(got) == _view(want), (sig, lo, hi, occurred)
        assert _view(same) == _view(got), (explicit_sig, lo, hi, occurred)
        assert all("count" not in e for r in got for e in r.evidence)     # 기본 시그니처의 근거 키는 그대로
        satisfied += got[0].satisfied
    assert 30 < satisfied < 290, f"무작위 입력이 한쪽으로 치우쳤습니다: {satisfied}/300 충족"


def _ev(sec: float, word: str, phone=0) -> dict:
    t = BASE + timedelta(seconds=sec)
    return {"ts": f"{t:%Y-%m-%dT%H:%M:%S}.{t.microsecond // 1000:03d}Z", "tag": "T", "msg": f"{word} x",
            "phone_id": phone, "event": None, "fields": {}}


def test_window_bounds_are_inclusive_on_both_ends():
    sig = signatures.compile_signature(
        {"id": "s", "must_match": ["T: alpha", "T: beta"], "must_not_match": ["T: neg"], "window_sec": 10}, "OWN")
    new = Evaluator._search_window
    cases = {
        "양끝의 조건은 구간 안": ([_ev(0, "alpha"), _ev(10, "beta")], True),
        "구간 밖의 조건": ([_ev(0, "alpha"), _ev(10.001, "beta")], False),
        "끝에 걸친 부정 조건은 구간 안": ([_ev(0, "alpha"), _ev(5, "beta"), _ev(10, "neg")], False),
        "구간 밖의 부정 조건": ([_ev(0, "alpha"), _ev(5, "beta"), _ev(10.001, "neg")], True),
    }
    for label, (events, expected) in cases.items():
        dts = [signatures._parse_ts(e["ts"]) for e in events]
        with Evaluator(events, min(dts), max(dts), 5000) as ev:
            got = ev.evaluate(sig)
            Evaluator._search_window = _legacy_search_window
            try:
                want = ev.evaluate(sig)
            finally:
                Evaluator._search_window = new
        assert got.satisfied == want.satisfied == expected, label
        assert _view([got]) == _view([want]), label


# -- D① min_count·sequence_within_sec (04-parser-matching.md §5.11 (1)) ---------------------------------------------


def _oracle_search_window(self, sig, pos, neg, occurred, all_matches=False):
    """`min_count`·`sequence_within_sec`까지 보는 단순 구현(구간마다 hit 전체를 훑는다). bisect 구현의 비교 기준이다.
    구간 튜플 끝에 조건별 구간 안 개수를 직접 세어 붙인다 — `_evaluate`는 다섯째 칸을 근거 `count`로 쓰므로 `_counts`와 대조된다."""
    width = timedelta(seconds=sig.window_sec)
    lo, hi = self.lo, self.hi
    a_max = max(lo, hi - width)
    times = {self.dts[i] for hits in pos for i in hits} | {self.dts[i] for i in neg}
    candidates = {lo, a_max}
    for t in times:
        candidates.update((t - width, t, t + _EPS, t - width + _EPS))
    order = {c.id: n for n, c in enumerate(sig.positives) if c.id}
    best, matches = None, []
    for a in sorted(c for c in candidates if lo <= c <= a_max):
        b = a + width
        if any(a <= self.dts[i] <= b for i in neg):
            continue
        firsts, counts = [], []
        for hits, cond in zip(pos, sig.positives):
            inside = sorted((self.dts[i], i) for i in hits if a <= self.dts[i] <= b)
            if len(inside) < cond.min_count:
                break
            firsts.append(inside[0][1])
            counts.append(len(inside))
        else:
            if sig.sequence:
                seq = [firsts[order[s]] for s in sig.sequence]
                keys = [(self.dts[i], i) for i in seq]
                if any(x >= y for x, y in zip(keys, keys[1:])):
                    continue
                if sig.sequence_within_sec is not None and any(
                        (self.dts[y] - self.dts[x]).total_seconds() > sig.sequence_within_sec for x, y in zip(seq, seq[1:])):
                    continue
            if occurred is not None:
                rank = min(abs((self.dts[i] - occurred).total_seconds()) for i in firsts)
            else:
                rank = (a - lo).total_seconds()
            if best is None or rank < best[0]:
                best = (rank, firsts, a, b, counts)
            if all_matches:
                matches.append((rank, firsts, a, b, counts))
    return matches if all_matches else best


def test_count_and_gap_match_simple_implementation():
    """무작위 `min_count`(1~3)·`sequence_within_sec`에서 bisect 구현이 단순 구현과 같다(근거 `count` 포함)."""
    rng = random.Random(20261108)
    new = Evaluator._search_window
    counted = gapped = 0
    for _ in range(300):
        events, _sig, lo, hi, occurred, raw = _case(rng)
        for item in raw["must_match"] + raw.get("must_event", []):
            item["min_count"] = rng.choice([1, 1, 2, 3])
        if raw.get("sequence") and rng.random() < 0.7:
            raw["sequence_within_sec"] = min(raw["window_sec"], rng.choice([0.001, 0.01, 0.1, 0.5, 1, 3]))
        sig = signatures.compile_signature(raw, "OWN")
        with Evaluator(events, lo, hi, 5000) as ev:
            got = [ev.evaluate(sig, occurred), *ev.evaluate_all(sig, occurred)]
            Evaluator._search_window = _oracle_search_window
            try:
                want = [ev.evaluate(sig, occurred), *ev.evaluate_all(sig, occurred)]
            finally:
                Evaluator._search_window = new
        assert _view(got) == _view(want), (sig, lo, hi, occurred)
        if got[0].satisfied:
            counted += any(c.min_count > 1 for c in sig.positives)
            gapped += sig.sequence_within_sec is not None
    assert counted > 10 and gapped > 3, (counted, gapped)


def _sig(**raw):
    return signatures.compile_signature({"id": "s", "window_sec": 10, **raw}, "OWN")


def _eval(events, sig, all_matches=False):
    dts = [signatures._parse_ts(e["ts"]) for e in events]
    with Evaluator(events, min(dts), max(dts), 5000) as ev:
        return ev.evaluate_all(sig) if all_matches else ev.evaluate(sig)


ALPHA3 = {"must_match": [{"id": "a", "pattern": "T: alpha", "min_count": 3}]}


def test_min_count_boundary_n_minus_one_and_n():
    hit = _eval([_ev(0, "alpha"), _ev(5, "alpha"), _ev(10, "alpha")], _sig(**ALPHA3))
    assert hit.satisfied and [(e["ts"], e["count"]) for e in hit.evidence] == [(_ev(0, "x")["ts"], 3)]   # 첫 줄 + 개수
    assert not _eval([_ev(0, "alpha"), _ev(5, "alpha"), _ev(10.001, "alpha")], _sig(**ALPHA3)).satisfied   # 구간 안 2건
    assert not _eval([_ev(0, "alpha"), _ev(5, "alpha")], _sig(**ALPHA3)).satisfied
    four = _eval([_ev(0, "alpha"), _ev(1, "alpha"), _ev(2, "alpha"), _ev(3, "alpha")], _sig(**ALPHA3))
    assert four.satisfied and four.evidence[0]["count"] == 4                 # 개수는 그 구간 안 전부


def test_min_count_same_timestamp_counts_each_record():
    sig = _sig(must_match=[{"id": "a", "pattern": "T: alpha", "min_count": 2}, "T: beta"])
    hit = _eval([_ev(1, "alpha"), _ev(1, "alpha"), _ev(2, "beta")], sig)
    assert hit.satisfied and [e.get("count") for e in hit.evidence] == [2, None]    # min_count 1 조건엔 count 없음
    assert not _eval([_ev(1, "alpha"), _ev(2, "beta")], sig).satisfied


def test_min_count_with_same_phone():
    two = {"must_match": [{"id": "a", "pattern": "T: alpha", "min_count": 2}]}
    split = [_ev(0, "alpha", phone=0), _ev(1, "alpha", phone=1)]
    assert not _eval(split, _sig(**two)).satisfied                           # 슬롯마다 1건
    assert _eval(split, _sig(**two, same_phone=False)).satisfied             # 슬롯 무관이면 2건
    wild = _eval([_ev(0, "alpha", phone=0), _ev(1, "alpha", phone=None)], _sig(**two))
    assert wild.satisfied and wild.evidence[0]["count"] == 2                  # phone null은 어느 슬롯과도 맞는다
    per_slot = _eval([_ev(0, "alpha", phone=0), _ev(1, "alpha", phone=1), _ev(2, "alpha", phone=1)], _sig(**two), True)
    assert [(r.evidence[0]["phone_id"], r.evidence[0]["count"]) for r in per_slot] == [(1, 2)]


SEQ = {"must_match": [{"id": "a", "pattern": "T: alpha"}, {"id": "b", "pattern": "T: beta"}], "sequence": ["a", "b"]}


def test_sequence_within_sec_boundary():
    assert _eval([_ev(0, "alpha"), _ev(2, "beta")], _sig(**SEQ, sequence_within_sec=2)).satisfied          # = T 통과
    assert not _eval([_ev(0, "alpha"), _ev(2.001, "beta")], _sig(**SEQ, sequence_within_sec=2)).satisfied  # > T 실패
    assert _eval([_ev(0, "alpha"), _ev(2.001, "beta")], _sig(**SEQ)).satisfied                            # 없으면 W까지
    assert _eval([_ev(1, "alpha"), _ev(1, "beta")], _sig(**SEQ, sequence_within_sec=0.5)).satisfied        # 같은 시각(입력 순서)
    assert not _eval([_ev(1, "beta"), _ev(1, "alpha")], _sig(**SEQ, sequence_within_sec=0.5)).satisfied
    # 구간마다 그 구간 안 첫 충족 레코드끼리 잰다: [0, 10]은 5초라 안 되고 4.5초에서 시작하는 구간이 맞는다
    late = _eval([_ev(0, "alpha"), _ev(4.5, "alpha"), _ev(5, "beta"), _ev(30, "other")], _sig(**SEQ, sequence_within_sec=1))
    assert late.satisfied and late.evidence[0]["ts"] == _ev(4.5, "x")["ts"]
    three = {"must_match": SEQ["must_match"] + [{"id": "c", "pattern": "T: gamma"}], "sequence": ["a", "b", "c"]}
    assert _eval([_ev(0, "alpha"), _ev(1, "beta"), _ev(2, "gamma")], _sig(**three, sequence_within_sec=1)).satisfied
    assert not _eval([_ev(0, "alpha"), _ev(1, "beta"), _ev(2.5, "gamma")], _sig(**three, sequence_within_sec=1)).satisfied


def test_sequence_within_sec_with_same_phone_and_min_count():
    sig = _sig(must_match=[{"id": "a", "pattern": "T: alpha", "min_count": 2}, {"id": "b", "pattern": "T: beta"}],
               sequence=["a", "b"], sequence_within_sec=3)
    assert _eval([_ev(0, "alpha"), _ev(1, "alpha"), _ev(3, "beta")], sig).satisfied
    assert not _eval([_ev(0, "alpha"), _ev(1, "alpha"), _ev(3, "beta", phone=1)], sig).satisfied        # beta가 다른 슬롯
    assert not _eval([_ev(0, "alpha"), _ev(1, "alpha", phone=1), _ev(2, "beta")], sig).satisfied        # 슬롯 0에 alpha 1건


def test_compile_rejects_bad_count_and_gap():
    bad = [
        {"must_match": [{"id": "a", "pattern": "x", "min_count": 0}]},
        {"must_match": [{"id": "a", "pattern": "x", "min_count": 1.5}]},
        {"must_match": [{"id": "a", "pattern": "x", "min_count": True}]},
        {"must_event": [{"event": "e", "min_count": "2"}]},
        {**SEQ, "sequence_within_sec": 0},
        {**SEQ, "sequence_within_sec": "1"},
        {**SEQ, "sequence_within_sec": 11},
        {"must_match": ["x"], "sequence_within_sec": 1},
    ]
    for raw in bad:
        try:
            _sig(**raw)
        except signatures.SignatureError:
            continue
        raise AssertionError(raw)
    assert _sig(**SEQ, sequence_within_sec=10).sequence_within_sec == 10.0      # = window_sec는 허용


def test_known_keys_equal_type_schema_properties():
    """compile_signature가 아는 키 = type.schema.json properties. db_lint는 DB 쪽 스키마(additionalProperties: false)와
    compile_signature를 둘 다 쓰므로, 둘이 어긋나면 한쪽만 통과하는 시그니처가 생긴다."""
    defs = json.loads((plugin_root() / "schemas" / "type.schema.json").read_text(encoding="utf-8"))["$defs"]
    obj = next(b for b in defs["signature"]["properties"]["must_match"]["items"]["oneOf"] if b.get("type") == "object")
    assert signatures.SIGNATURE_KEYS == set(defs["signature"]["properties"])
    assert signatures.MATCH_ITEM_KEYS == set(obj["properties"])
    assert signatures.EVENT_ITEM_KEYS == set(defs["mustEventItem"]["properties"])


def test_features_used():
    """선택 필드 사용 = `min_count` ≥ 2(1은 기본값) 또는 `sequence_within_sec` 키. 이름은 모두 `SUPPORTED_FEATURES` 안."""
    base = {"id": "s", "must_match": ["A"], "window_sec": 5}
    assert signatures.features_used(base) == set()
    assert signatures.features_used({**base, "must_match": [{"pattern": "A", "min_count": 1}]}) == set()
    assert signatures.features_used({**base, "must_match": [{"pattern": "A", "min_count": 2}]}) == {"min_count"}
    assert signatures.features_used({**base, "must_event": [{"event": "e", "min_count": 3}]}) == {"min_count"}
    assert signatures.features_used({**SEQ, "sequence_within_sec": 1}) == {"sequence_within_sec"}
    both = {**SEQ, "sequence_within_sec": 1, "must_event": [{"event": "e", "min_count": 2}]}
    assert signatures.features_used(both) == {"min_count", "sequence_within_sec"} == signatures.SUPPORTED_FEATURES


def test_sample_db_signatures_all_compile():
    """샘플 이슈 DB의 모든 시그니처(유형·원인, 네 종류 전부 — 비활성·pending 포함)가 모르는 키 검사를 거쳐 컴파일된다."""
    from common import issuedb

    db = issuedb.load(REPO / "tests" / "fixtures" / "issue-db-sample")
    n = 0
    for itype in db.types:
        n += len(signatures.compile_list(itype.raw.get("symptom_signatures"), itype.id))
        for cause in itype.causes:
            for kind in ("signatures", "recovery_signatures", "scenario_signatures"):
                n += len(signatures.compile_list(cause.raw.get(kind), cause.id))
    assert n >= 10, n


def test_compile_rejects_unknown_keys():
    """모르는 키는 오류 — 새 필드를 모르는 매처가 조용히 기본값으로 읽는 길을 없앤다(예: min_count를 1로)."""
    for raw, needle in (({**SEQ, "within_sec": 1}, "시그니처에 모르는 키 ['within_sec']"),
                        ({"must_match": [{"id": "a", "pattern": "x", "count": 2}]}, "must_match 항목에 모르는 키 ['count']"),
                        ({"must_event": [{"event": "e", "min": 2}]}, "must_event 항목에 모르는 키 ['min']")):
        try:
            _sig(**raw)
        except signatures.SignatureError as exc:
            assert needle in str(exc) and "OWN/s" in str(exc), exc
            continue
        raise AssertionError(raw)
