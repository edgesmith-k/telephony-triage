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
    assert not patterns._SharedWorker.held     # close()가 본문을 버렸다


def test_timeout_kills_shared_worker_and_next_search_restarts():
    with PatternRunner(["a" * 40 + "!"], timeout_ms=300) as runner:
        runner.search("a")
        pid = patterns._SharedWorker.proc.pid
        with pytest.raises(PatternTimeout):
            runner.search(r"(a+)+$")
        assert patterns._SharedWorker.proc is None
        assert runner.search("!") == [0]    # 새로 띄우고 본문을 다시 보낸다
        assert patterns._SharedWorker.proc.pid != pid


def _held() -> list[int]:
    return list(patterns._SharedWorker.held)


def test_bodies_are_uploaded_once_per_runner_when_interleaved():
    runners = [PatternRunner([f"r{n}-a", f"r{n}-b", "z"]) for n in range(3)]
    try:
        runners[0].search("a")      # 워커를 띄우고 시작
        base = patterns._SharedWorker.loads
        for _ in range(5):          # 번갈아 돌려도 다시 올리지 않는다 (cap 4 안)
            for n, r in enumerate(runners):
                assert r.search(f"r{n}-") == [0, 1]
                assert r.search("z") == [2]
        assert patterns._SharedWorker.loads - base == 2        # runners[1]·[2]만 한 번씩 올렸다
        assert _held() == [r._token for r in runners]
    finally:
        for r in runners:
            r.close()


def test_body_cache_is_lru_capped_and_evicted_runner_reloads():
    cap = patterns.BODY_CACHE_MAX
    runners = [PatternRunner([f"b{n}"]) for n in range(cap + 1)]
    try:
        for n, r in enumerate(runners):
            assert r.search("b") == [0]
        assert len(_held()) == cap and runners[0]._token not in _held()      # 가장 오래된 것이 밀려났다
        before = patterns._SharedWorker.loads
        assert runners[1].search("b1") == [0]                                  # 아직 있다 → 다시 올리지 않음
        assert patterns._SharedWorker.loads == before
        assert runners[0].search("b0") == [0]                                  # 밀려난 것은 다시 올린다
        assert patterns._SharedWorker.loads == before + 1
        assert runners[0]._token in _held() and runners[2]._token not in _held()   # 이번엔 2번이 가장 오래돼 밀려남
        assert len(_held()) == cap
    finally:
        for r in runners:
            r.close()


def test_parent_mirror_recovers_if_worker_lost_the_body():
    r = PatternRunner(["x1", "y"])
    try:
        assert r.search("x") == [0]
        patterns._SharedWorker.conn.send((patterns._DROP, r._token))      # 부모 모르게 워커가 버렸다
        assert r.search("y") == [1]                                        # miss → 다시 올리고 재시도
    finally:
        r.close()


def test_timeout_restart_clears_held_and_reloads_all_bodies():
    slow = PatternRunner(["a" * 40 + "!"], timeout_ms=300)
    other = PatternRunner(["k1"])
    try:
        assert other.search("k") == [0]
        slow.search("a")
        assert len(_held()) == 2
        with pytest.raises(PatternTimeout):
            slow.search(r"(a+)+$")
        assert _held() == [] and patterns._SharedWorker.proc is None
        before = patterns._SharedWorker.loads
        assert other.search("k") == [0]            # 새 워커에 다시 올린다
        assert patterns._SharedWorker.loads == before + 1
        assert _held() == [other._token]
    finally:
        slow.close()
        other.close()


def test_close_drops_body_without_waiting_and_parent_holds_no_runner():
    import gc
    import weakref
    r = PatternRunner(["abc"])
    assert r.search("b") == [0]
    token = r._token
    assert token in _held()
    ref = weakref.ref(r)
    r.close()
    assert token not in _held()
    del r
    gc.collect()
    assert ref() is None                       # 부모(클래스)가 runner를 붙들지 않는다
    # 워커가 죽었어도 close()는 조용하다
    r2 = PatternRunner(["abc"])
    r2.search("a")
    patterns._SharedWorker.stop(kill=True)
    r2.close()
    assert r2.search("c") == [0]               # 닫은 뒤에도 다시 쓸 수 있다 (새로 띄운다)
    r2.close()


def test_explicit_texts_do_not_upload_the_body():
    r = PatternRunner(["unused"])
    try:
        r.search("u")
        before = patterns._SharedWorker.loads
        r2 = PatternRunner(["other"])
        assert r2.search("t", texts=["t", "u"]) == [0]
        assert r2.search("u", texts=["t", "u"], mode="fullmatch") == [1]
        assert patterns._SharedWorker.loads == before and r2._token not in _held()
    finally:
        r.close()
