#!/usr/bin/env python3
"""파서 출력 이벤트 레코드 (`common/events.py`, 07-workflow.md §Step 3, 04 §5.8 (6)).

생성 함수(키 순서·기본값·파생 상속), `line_ref` 도우미, `validate_event`(실제 스냅샷은 통과, 깨진 이벤트는 위반).

`pytest tests/test_events.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import events  # noqa: E402

LOG_DIR = REPO / "tests" / "fixtures" / "logs"


def _good(**over) -> dict:
    e = events.make_event(ts="2026-09-20T05:30:03.000Z", source="backend:reference", pid=1, tid=2, level="I",
                          tag="RILJ", msg="x", phone_id=0, line_ref=events.line_ref(0, 5))
    e.update(over)
    return e


def test_make_event_key_order_and_defaults():
    e = events.make_event(ts="t", source="rules")
    assert tuple(e) == events.EVENT_KEYS
    assert e["fields"] == {} and e["msg"] == "" and e["ril"] is None and e["line_ref"] is None
    assert events.make_event(ts="t", source="s", fields={"a": 1})["fields"] == {"a": 1}   # 문자열로 바꾸지 않는다


def test_derived_event_inherits_and_stringifies():
    base = _good(ril=_ril(), category_hint="data")
    d = events.derived_event(base, "ril_timeout", {"n": 5, "s": "a"})
    assert tuple(d) == events.EVENT_KEYS
    assert d["fields"] == {"n": "5", "s": "a"} and d["source"] == "rules" and d["event"] == "ril_timeout"
    assert d["ril"] is None and d["line_ref"] == base["line_ref"] and d["category_hint"] == "data"
    assert all(d[k] == base[k] for k in ("ts", "pid", "tid", "level", "tag", "msg", "phone_id"))
    assert events.derived_event(base, "e", {}, "backend:x")["source"] == "backend:x"
    assert events.validate_event(d) == []


def test_line_ref_helpers():
    assert events.line_ref(2) == {"file_index": 2, "line_no": None}
    assert events.line_ref(2, 7) == {"file_index": 2, "line_no": 7}
    for bad in (None, {}, {"file_index": 0, "line_no": None}, {"file_index": 0, "line_no": 0}, "x", 5):
        assert events.ref_key(bad) is None and events.ref_label(bad) is None
    assert events.ref_key({"file_index": 1, "line_no": 12}) == (1, 12)
    assert events.ref_label({"file_index": 1, "line_no": 12}) == "f1:L12"


def test_fixture_events_validate():
    seen = 0
    for path in sorted(LOG_DIR.glob("*.events.json")):
        evs = json.loads(path.read_text(encoding="utf-8"))["events"]
        assert events.validate_events(evs) == [], path.name
        seen += len(evs)
    assert seen > 0
    ril = json.loads((LOG_DIR / "dual-sim-ril.events.json").read_text(encoding="utf-8"))["events"]
    assert any("observed_until" in (e["ril"] or {}) for e in ril)


def test_good_event_ok():
    assert events.validate_event(_good()) == []
    assert events.validate_event(_good(source="rules", event="data_x")) == []
    assert events.validate_event(_good(source="backend:site", event="builtin.data.x")) == []
    assert events.validate_event(_good(source="external:ad", event="ext.data.x", line_ref=events.line_ref(0))) == []


def _without(key):
    e = _good()
    del e[key]
    return e


def _reorder():
    e = _good()
    return {"tag": e.pop("tag"), **e}


def _ril(**over):
    ril = {"serial": 1, "dir": "req", "request": "X", "error": None, "paired_ts": None, "latency_ms": None}
    ril.update(over)
    return ril


BAD = {
    "missing key": _without("msg"),
    "swapped order": _reorder(),
    "extra _dt": {**_good(), "_dt": 1},
    "bool pid": _good(pid=True),
    "line_no 0": _good(line_ref={"file_index": 0, "line_no": 0}),
    "file_index -1": _good(line_ref={"file_index": -1, "line_no": 1}),
    "line_ref extra key": _good(line_ref={"file_index": 0, "line_no": 1, "x": 1}),
    "int in fields": _good(fields={"a": 1}),
    "rules builtin name": _good(source="rules", event="builtin.x.y"),
    "rules ext name": _good(source="rules", event="ext.x.y"),
    "rules no event": _good(source="rules"),
    "backend without builtin": _good(source="backend:r", event="data_x"),
    "external without ext": _good(source="external:a", event="data_x"),
    "unknown source": _good(source="other"),
    "empty backend source": _good(source="backend:"),
    "ril on named event": _good(source="backend:r", event="builtin.a.b", ril=_ril()),
    "unknown ril key": _good(ril={**_ril(), "extra": 1}),
    "ril key order": _good(ril=dict(reversed(list(_ril().items())))),
    "hal before observed_until": _good(ril={**_ril(), "hal": "reached", "observed_until": "t"}),
    "bad ts": _good(ts="2026-09-20 05:30:03"),
    "ts without ms": _good(ts="2026-09-20T05:30:03Z"),
    "msg None": _good(msg=None),
    "not a dict": [1, 2],
}


@pytest.mark.parametrize("name", list(BAD))
def test_bad_events_flagged(name):
    assert events.validate_event(copy.deepcopy(BAD[name])), name


def test_ril_optional_tail_keys_ok():
    """벤더 RIL 층 `hal`: 응답 레코드엔 `observed_until`이 없으므로 꼬리 4가지를 모두 허용한다."""
    for tail in ({}, {"observed_until": "t"}, {"hal": "reached"}, {"observed_until": "t", "hal": "unknown"}):
        assert events.validate_event(_good(ril={**_ril(), **tail})) == [], tail


def test_validate_events_prefix():
    out = events.validate_events([_good(), _good(pid=True)])
    assert out and all(p.startswith("events[1]: ") for p in out)
    assert events.validate_events("x")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
