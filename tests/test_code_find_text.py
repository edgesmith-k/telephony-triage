"""`code_roots.py find-text` (C′ 코드 대조, 04-parser-matching.md §5.12 (5)): 리터럴 도출(태그·oFono 앞머리 제거),
상태(same·string-only·reworded·not-found·no-literal·limit), 범위 ①②③, ±2줄 로그 호출, --events → log_refs,
출력에 코드 줄 글자가 없음. 합성 트리·합성 마스킹 이벤트만 쓴다."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import plugin_root  # noqa: E402

ROOT = plugin_root()
sys.path.insert(0, str(ROOT / "scripts"))

import code_roots  # noqa: E402
from code_roots import derive_literal  # noqa: E402

TEL = "frameworks/opt/telephony/src/java/com/android/internal/telephony"


def test_derive_literal_cases():
    assert derive_literal("X.*onDataSetupComplete: result=")["literal"] == "onDataSetupComplete"
    assert derive_literal("ImsPhoneCallTracker.*dial", ["ImsPhoneCallTracker"]) is None   # dial < 6자
    assert derive_literal(r"RILJ.*>\s*GET_SIM_STATUS", ["RILJ"])["literal"] == "GET_SIM_STATUS"
    lit = derive_literal(r"src/example\.c:example_cb\(\) /ril_0 SIM ready state")
    assert lit["literal"] == "SIM ready state"
    assert derive_literal(r"DcTracker: \d+ <IMSI#1>", ["DcTracker"]) is None
    assert derive_literal(r"(?i)radio power off")["icase"] is True
    assert derive_literal(r"Tag: (?:foo|bar) value") is None
    assert derive_literal("Tag: 12345678") is None


def _tree(tmp: Path) -> Path:
    files = {
        f"{TEL}/dataconnection/DataNetwork.java": 'void f() {\n  int x = 1;\n  log("onDataSetupComplete: result=" + r);\n}\n',
        f"{TEL}/RIL.java": 'static String requestToString(int r) {\n  case 1: return "GET_SIM_STATUS";\n\n\n\n}\n',
        f"{TEL}/ServiceStateTracker.java": 'void g() {\n  loge("radio state " + s + " power changed");\n}\n',
        f"{TEL}/tests/Fake.java": '"SIM ready state"\n',
        "out/Gen.java": 'log("Never scanned text");\n',
    }
    for rel, text in files.items():
        path = tmp / "aosp" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp / "aosp"


def _run(tmp: Path, items, events=None, code_refs=(), env_sec=None, monkeypatch=None) -> tuple[dict, str]:
    spec = tmp / "lit.json"
    spec.write_text(json.dumps({"tags": ["RILJ", "X"], "code_refs": list(code_refs), "items": items}), encoding="utf-8")
    argv = ["find-text", "--roots", f"aosp={tmp / 'aosp'}", "--literals", str(spec), "--plugin-root", str(ROOT)]
    if events:
        argv += ["--events", str(events)]
    if env_sec is not None:
        monkeypatch.setenv("TT_FIND_TEXT_SEC", str(env_sec))
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        assert code_roots.main(argv) == 0
    return json.loads(out.getvalue()), out.getvalue()


def test_statuses_and_no_code_text(tmp_path):
    _tree(tmp_path)
    events = tmp_path / "events.json"
    events.write_text(json.dumps({"masked": True, "events": [
        {"tag": "SST", "msg": "radio state OFF power changed", "line_ref": {"file_index": 1, "line_no": 42}}]}),
        encoding="utf-8")
    items = [{"id": "c", "pattern": "X.*onDataSetupComplete: result="},
             {"id": "s", "pattern": r"RILJ.*>\s*GET_SIM_STATUS"},
             {"id": "w", "pattern": "SST: radio power changed"},
             {"id": "n", "pattern": "Tag: neverPresentText"},
             {"id": "t", "pattern": "Tag: SIM ready state"},
             {"id": "z", "pattern": "Tag: dial"}]
    out, raw = _run(tmp_path, items, events=events, code_refs=[f"aosp:{TEL}/RIL.java"])
    by = {i["id"]: i for i in out["items"]}
    assert by["c"]["status"] == "same" and by["c"]["refs"] == [f"aosp:{TEL}/dataconnection/DataNetwork.java:3"]
    assert by["s"]["status"] == "string-only" and by["s"]["log_call"] is False
    assert by["w"]["status"] == "reworded" and by["w"]["log_refs"] == ["1:42"]
    assert by["n"]["status"] == "not-found"
    assert by["t"]["status"] == "not-found" and by["t"]["aux_refs"] == [f"aosp:{TEL}/tests/Fake.java:1"]
    assert by["z"]["status"] == "no-literal"
    assert out["scope"] == {"code_refs": "봄", "required_dirs": "봄", "root": "봄"}
    assert out["truncated"] is False
    for text in ("log(", "requestToString", "return", "Never scanned"):
        assert text not in raw      # 코드 줄 글자는 내지 않는다


def test_limit_is_not_not_found(tmp_path, monkeypatch):
    _tree(tmp_path)
    out, _ = _run(tmp_path, [{"id": "n", "pattern": "Tag: neverPresentText"}], env_sec=0, monkeypatch=monkeypatch)
    assert out["truncated"] is True and out["items"][0]["status"] == "limit"
    assert out["scope"]["required_dirs"] == "건너뜀(상한)"
