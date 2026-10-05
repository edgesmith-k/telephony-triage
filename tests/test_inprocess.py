#!/usr/bin/env python3
"""하위 스크립트 같은 프로세스 호출(`common.checks.run_in_process`)과 공유 정규식 작업 프로세스(`common.patterns`).

- 종료 코드·stdout·stderr 계약이 `python <script>`로 부를 때와 같다 (contracts.md §종료 코드).
- 정규식 작업 프로세스는 runner 사이에 다시 쓰고, 본문이 바뀌면 다시 보내고, 시간 초과 뒤에는 새로 띄운다
  (04-parser-matching.md §5.8 (4)).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, plugin_root  # noqa: E402

ROOT = plugin_root()
sys.path.insert(0, str(ROOT / "scripts"))

from common import checks, patterns  # noqa: E402
from common.patterns import PatternRunner, PatternTimeout  # noqa: E402

FAKES = {
    "tt_fake_ok": "import json\ndef main(argv):\n    print(json.dumps({'argv': argv}))\n    return 3\n",
    "tt_fake_none": "def main(argv):\n    print('', end='')\n",
    "tt_fake_exit_int": "import sys\ndef main(argv):\n    print('usage', file=sys.stderr)\n    raise SystemExit(2)\n",
    "tt_fake_exit_str": "def main(argv):\n    raise SystemExit('멈춤')\n",
    "tt_fake_raise": "def main(argv):\n    raise ValueError('깨짐')\n",
    "tt_fake_import": "import tt_module_that_does_not_exist\ndef main(argv):\n    return 0\n",
}


@pytest.fixture(scope="module")
def fakes(tmp_path_factory):
    d = tmp_path_factory.mktemp("fakes")
    for name, body in FAKES.items():
        (d / f"{name}.py").write_text(body, encoding="utf-8")
    sys.path.insert(0, str(d))
    yield d
    sys.path.remove(str(d))


@pytest.mark.parametrize("name, code, out, err", [
    ("tt_fake_ok", 3, '{"argv": ["a", "--plugin-root", "/p"]}', ""),
    ("tt_fake_none", 0, "", ""),
    ("tt_fake_exit_int", 2, "", "usage"),
    ("tt_fake_exit_str", 1, "", "멈춤"),
    ("tt_fake_raise", 1, "", "ValueError: 깨짐"),
    ("tt_fake_import", 1, "", "ModuleNotFoundError"),
])
def test_run_in_process_matches_exit_code_contract(fakes, name, code, out, err):
    got_code, got_out, got_err = checks.run_in_process(f"{name}.py", ["a", "--plugin-root", "/p"])
    assert got_code == code
    assert got_out.strip() == out
    assert err in got_err


def test_run_script_parses_json_and_restores_streams(fakes):
    stdout, stderr = sys.stdout, sys.stderr
    code, data, err = checks.run_script("tt_fake_ok.py", ["x"], plugin_root="/p")
    assert (code, data, err) == (3, {"argv": ["x", "--plugin-root", "/p"]}, "")
    assert sys.stdout is stdout and sys.stderr is stderr


@pytest.mark.parametrize("args", [
    ["--all", "--db", str(SAMPLE)],
    ["--no-such-flag"],
])
def test_in_process_and_subprocess_agree_on_real_script(monkeypatch, args):
    inproc = checks.run_script("db_lint.py", args, plugin_root=str(ROOT))
    monkeypatch.setenv(checks.SUBPROCESS_ENV, "1")
    sub = checks.run_script("db_lint.py", args, plugin_root=str(ROOT))
    assert inproc[0] == sub[0]
    assert inproc[1] == sub[1]


# -- 공유 정규식 작업 프로세스 -------------------------------------------------------------


def test_worker_is_reused_across_runners_and_texts_follow_owner():
    with PatternRunner(["a1", "b1", "a2"]) as first:
        assert first.search("a") == [0, 2]
        pid = patterns._SharedWorker.proc.pid
    second = PatternRunner(["xa", "y"])
    third = PatternRunner(["y", "y", "a"])
    try:
        assert second.search("a") == [0]
        assert third.search("a") == [2]     # 다른 runner가 끼어들면 본문을 다시 보낸다
        assert second.search("y") == [1]
        assert third.search("y", texts=["y"]) == [0]
        assert patterns._SharedWorker.proc.pid == pid
    finally:
        second.close()
        third.close()
    assert patterns._SharedWorker.owner is None


def test_timeout_kills_shared_worker_and_next_search_restarts():
    with PatternRunner(["a" * 40 + "!"], timeout_ms=300) as runner:
        runner.search("a")
        pid = patterns._SharedWorker.proc.pid
        with pytest.raises(PatternTimeout):
            runner.search(r"(a+)+$")
        assert patterns._SharedWorker.proc is None
        assert runner.search("!") == [0]    # 새로 띄우고 본문을 다시 보낸다
        assert patterns._SharedWorker.proc.pid != pid
