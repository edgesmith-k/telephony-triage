"""상수·오류(`Fail`·`NeedsInput`·`Stopped`)·하위 스크립트 실행(`Runner`, `_module`)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from common.exitcodes import USAGE

SCRIPTS = Path(__file__).resolve().parents[1]


ANALYSIS_MAX = 4096
STATE_FILE = "triage-state.json"
STATE_SCHEMA = 2                 # 2: `job` 절(로그·실행 이력·재사용 캐시 요약)이 있다. 스키마 표시가 없는 파일은 job = {}
CACHE_FILE = "analysis-cache.json"
CACHE_FORMAT = 3                 # 캐시 형식·`core` 구조를 바꾸면 올린다(plugin 해시에 들어가 이전 캐시가 무효가 된다). 2: 타임라인은 캐시 파일이 아니다. 3: core.unjudged
RUNS_KEEP = 10                   # state.job.runs(실행 이력)에 남기는 수
RUN_DIRS_KEEP = 5                # JOB/runs/<n>/(이전 analysis.json·report.md 보관)에 남기는 수
RUNS_DIR = "runs"
PART_KEYS = ("logs", "jira", "db", "config", "plugin", "args")     # 입력 해시 부분(바뀐 것을 알려 주는 순서)
CACHE_FILES = {"events": "events.json", "match": "match.json"}   # 캐시가 크기·mtime을 기록하는 산출물
ANSWER_KEYS = ("time", "window", "anchor", "year", "code", "code_confirm")   # 결과를 바꾸는 답만 args 해시에 넣는다
SNAPSHOT_DIR = "_snapshot"
TOP = 3
SEARCH_LIMIT = 3
ERROR_EVENT_RE = re.compile(r"(error|timeout|no_response|reject|fail|denied|lost)", re.I)
ERROR_FIELDS = ("request", "error", "code", "reason", "cause")   # 오류 이벤트 줄에 싣는 필드 (analysis.json·report.md)
AUTO_CODE_NOTE = " (자동 선택: code.auto_select)"   # report.md 코드 줄
EXPLORE_WHEN = ("ask", "always", "never")
EXPLORE_MAX_LINES = 200
TIMELINE_FILE = "timeline.md"
EXPLORE_INPUT_FILE = "explore-input.json"   # `triage.py explore`의 입력(마스킹된 값만). run이 쓰고, 탐색 동의 뒤 subcommand가 읽는다
MUST_SHOW_MAX = 6                # render_report가 모으는 must_show 상한
MUST_SHOW_FIT = 4                # fit이 마지막에 남기는 수
MUST_SHOW_CLIP = 160
EXPLORE_HYPOTHESIS = "TODO(LLM) 가설 1~3개 — 로그로 확인 / 코드로 추정 / 반대 근거 / 다음에 받을 로그. 실행하지 않으면 \"탐색 분석 생략: <사유>\". 점수·분류·검증에 쓰지 않는다"
EXPLORE_PENDING_LINE = ("- 탐색 분석 (추정): 미실행 — 동의(또는 --explore·explore.when: always) 뒤 triage.py explore {key}가 "
                        f"{TIMELINE_FILE}를 만든다. " + EXPLORE_HYPOTHESIS)
EXPLORE_DONE_LINE = "- 탐색 분석 (추정, " + TIMELINE_FILE + " {lines}/{total}줄): " + EXPLORE_HYPOTHESIS
_HOT_LEVELS = {"W", "E", "F"}
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_]{2,}")


class Fail(Exception):
    def __init__(self, code: int, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.detail = detail


class NeedsInput(Exception):
    def __init__(self, kind: str, question: str, options: list | None = None, **extra):
        super().__init__(question)
        self.payload = {"kind": kind, "question": question, "options": options or [],
                        "answer": f"--answer {kind}=<값>", **extra}


class Stopped(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clip(text, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# -- 같은 프로세스 호출 ------------------------------------------------------------------------

_MODULES: dict[str, object] = {}


def _module(name: str):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(f"tt_{name}", SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


class Runner:
    """기존 스크립트의 `main(argv)`를 부르고 stdout JSON·종료 코드·stderr를 받는다. 호출마다 trace 한 줄."""

    def __init__(self, plugin_root: str | None):
        self.plugin_root = plugin_root
        self.env: dict[str, str] = {}
        self.trace_path: Path | None = None
        self.pending: list[dict] = []
        self.calls = 0

    def call(self, step: str, script: str, argv: list, expect: tuple = (0,)) -> tuple[int, object, str]:
        args = [str(a) for a in argv]
        if self.plugin_root:
            args += ["--plugin-root", self.plugin_root]
        out, err = io.StringIO(), io.StringIO()
        saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        started = time.monotonic()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = _module(script.removesuffix(".py")).main(args)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else USAGE
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        text, stderr = out.getvalue(), err.getvalue()
        try:
            data = json.loads(text) if text.strip() else None
        except json.JSONDecodeError:
            data = None
        self.calls += 1
        self._trace({"ts": _now(), "step": step, "script": script, "args": args[: args.index("--plugin-root")]
                     if "--plugin-root" in args else args, "exit": code, "ms": int((time.monotonic() - started) * 1000),
                     "out_bytes": len(text.encode("utf-8")), "stderr": _clip(stderr, 300) or None})
        if code not in expect:
            raise Fail(USAGE if code not in (1, 2, 3) else code,
                       f"{script} {' '.join(args[:2])} 종료 코드 {code}: {stderr.strip() or '(메시지 없음)'}",
                       data if isinstance(data, dict) else None)
        return code, data, stderr

    def note(self, step: str, **fields) -> None:
        self._trace({"ts": _now(), "step": step, **fields})

    def _trace(self, row: dict) -> None:
        if self.trace_path is None:
            self.pending.append(row)
            return
        with self.trace_path.open("a", encoding="utf-8", newline="\n") as fh:
            for item in [*self.pending, row]:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        self.pending = []

    def open_trace(self, path: Path) -> None:
        self.trace_path = path
        self._trace({"ts": _now(), "step": "start", "pid": os.getpid()})
