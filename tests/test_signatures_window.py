#!/usr/bin/env python3
"""`Evaluator._search_window`(bisect 구현)가 예전 구현과 같은 결과를 내는지 본다 (R15, O1).

예전 구현(구간마다 hit 전체를 훑는 O(H²))을 `_legacy_search_window`로 그대로 두고, 같은 무작위 입력에
둘을 돌려 충족 여부·근거·구간이 같은지 비교한다. 시간은 재지 않는다 (측정은 `tools/bench_scale.py`).
"""

from __future__ import annotations

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
    return events, sig, lo, hi, occurred


def _view(results):
    return [(r.satisfied, r.error, r.evidence, r.window) for r in results]


def test_bisect_search_window_matches_legacy():
    rng = random.Random(20261005)
    new = Evaluator._search_window
    satisfied = 0
    for _ in range(300):
        events, sig, lo, hi, occurred = _case(rng)
        with Evaluator(events, lo, hi, 5000) as ev:
            got = [ev.evaluate(sig, occurred), *ev.evaluate_all(sig, occurred)]
            Evaluator._search_window = _legacy_search_window
            try:
                want = [ev.evaluate(sig, occurred), *ev.evaluate_all(sig, occurred)]
            finally:
                Evaluator._search_window = new
        assert _view(got) == _view(want), (sig, lo, hi, occurred)
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
