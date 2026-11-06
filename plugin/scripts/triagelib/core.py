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
PLATFORM_ANSWER = "platform_answer"   # 상태 키: 이 작업 플랫폼을 `--answer platform=`으로 정했다(17-platforms §11-3)
STATE_SCHEMA = 2                 # 2: `job` 절(로그·실행 이력·재사용 캐시 요약)이 있다. 스키마 표시가 없는 파일은 job = {}
CACHE_FILE = "analysis-cache.json"
CACHE_FORMAT = 3                 # 캐시 형식·`core` 구조를 바꾸면 올린다(plugin 해시에 들어가 이전 캐시가 무효가 된다). 2: 타임라인은 캐시 파일이 아니다. 3: core.unjudged
RUNS_KEEP = 10                   # state.job.runs(실행 이력)에 남기는 수
RUN_DIRS_KEEP = 5                # JOB/runs/<n>/(이전 analysis.json·report.md 보관)에 남기는 수
RUNS_DIR = "runs"
PART_KEYS = ("logs", "issue", "db", "config", "plugin", "args")     # 입력 해시 부분(바뀐 것을 알려 주는 순서)
CACHE_FILES = {"events": "events.json", "match": "match.json"}   # 캐시가 크기·mtime을 기록하는 산출물
ANSWER_KEYS = ("time", "window", "anchor", "year", "code", "code_confirm")   # 결과를 바꾸는 답만 args 해시에 넣는다
CARRY_KEYS = ("time", "window", "anchor", "year", "code")   # 분석 전용이 lock을 푼 뒤 새 owner의 첫 실행이 이어받는 답
CARRY_PARTS = ("logs", "issue", "config")      # 이어받은 답을 쓰는 조건: 이 입력 부분 해시가 같을 때만
SNAPSHOT_DIR = "_snapshot"
TOP = 3
# C′ 부분 일치 (04-parser-matching.md §5.12): analysis.json `partial[]` ≤ 3개(목표 ≤ 600 B), report.md 절 ≤ 1,200 B,
# 코드 대조 리터럴 ≤ 9개(부분 일치 3 × 없는 조건 3)
PARTIAL_ANALYSIS_MAX, PARTIAL_REPORT_MAX, FIND_TEXT_ITEMS = 3, 1200, 9
SEARCH_LIMIT = 3
ERROR_EVENT_RE = re.compile(r"(error|timeout|no_response|reject|fail|denied|lost)", re.I)
# 0 값 오류 칸(`errorCode=0`·`RejectCause: 0`·`result=0`·`error(0)`)은 오류가 아니다. 오류 문구 판정(ERROR_EVENT_RE) 전에
# 지운다 — report 타임라인 줄 고르기와 모듈 보기 hot 표시가 같이 쓴다(H C1+D R13, 두 플랫폼)
ZERO_VALUE_RE = re.compile(r"(?i)\b(?:RejectCause|reject\s*cause|errorCode|RilErrorCode|rejectCode|error|result|"
                           r"fail(?:ure)?_?(?:code|cause))\s*[:=(]\s*0\b(?![.\d])")


def is_error_text(text: str | None) -> bool:
    """메시지에 오류 문구가 있는가(0 값 오류 칸을 뺀 뒤 ERROR_EVENT_RE)."""
    return bool(ERROR_EVENT_RE.search(ZERO_VALUE_RE.sub("", text or "")))


ERROR_FIELDS = ("request", "error", "code", "reason", "cause")   # 오류 이벤트 줄에 싣는 필드 (analysis.json·report.md)
AUTO_CODE_NOTE = " (자동 선택: code.auto_select, `--code`로 변경 가능)"   # report.md 코드 줄
EXPLORE_WHEN = ("ask", "always", "never")
EXPLORE_MAX_LINES = 200
TIMELINE_FILE = "timeline.md"
# 기본 아닌 플랫폼의 탐색 분석 지식(플러그인 루트 기준). `<여기>/<플랫폼>/*.md`가 있으면 `triage.py explore`가 `refs`로 알린다
# (17-platforms §10). 스킬 디렉토리 기준 경로는 `reference/platforms/<플랫폼>/<파일>`
PLATFORM_REFS_DIR = ("skills", "telephony-triage", "reference", "platforms")
EXPLORE_INPUT_FILE = "explore-input.json"   # `triage.py explore`의 입력(마스킹된 값만). run이 쓰고, 탐색 동의 뒤 subcommand가 읽는다
MUST_SHOW_MAX = 6                # render_report가 모으는 must_show 상한
MUST_SHOW_FIT = 4                # fit이 마지막에 남기는 수
MUST_SHOW_CLIP = 160
PULL_SKIPPED = "이슈 DB pull 건너뜀"     # must_show 줄 머리(issue_post가 Jira 본문에서 뺀다)
EXPLORE_HYPOTHESIS = "TODO(LLM) 가설 1~3개 — 로그로 확인 / 코드로 추정 / 반대 근거 / 다음에 받을 로그. 실행하지 않으면 \"탐색 분석 생략: <사유>\". 점수·분류·검증에 쓰지 않는다"
EXPLORE_PENDING_LINE = ("- 탐색 분석 (추정): 미실행 — 실행 전(동의 답을 기다리는 동안 포함)엔 로그 원문을 grep·Read하지 않는다. "
                        "동의(또는 --explore·explore.when: always) 뒤 triage.py explore {key}가 "
                        f"{TIMELINE_FILE}를 만든다(가설 근거는 이 파일). " + EXPLORE_HYPOTHESIS)
EXPLORE_DONE_LINE = "- 탐색 분석 (추정, " + TIMELINE_FILE + " {lines}/{total}줄): " + EXPLORE_HYPOTHESIS
# 5-1·5-2 모듈 스킬·출력 검사 줄(B2 §5.5·§6·§7.2). `module`·`check-output`이 report.md의 그 줄만 고친다(`report.rewrite_line`)
DEEP_TODO = "TODO(LLM) 결과는 check-output이 쓴다. 실행 안 함·실패면 \"심층 분석 생략: <사유>\"로"
DEEP_MODULE_PENDING = ("- 심층 분석 (모듈 스킬 {platform}, 1위 카테고리 {category}): 미실행 — 동의 뒤 triage.py module {key} "
                       "--for deep가 받는다. " + DEEP_TODO)
DEEP_MODULE_FETCHED = "- 심층 분석 (모듈 스킬 {module} @{sha7}): " + DEEP_TODO
DEEP_REPO_MISSING = "- 심층 분석: 해당 없음(레포에 {module} 없음 @{sha7}) (만드는 법: 모듈 스킬 레포 README)"
DEEP_FETCH_FAILED = "- 심층 분석 생략: 모듈 스킬 받기 실패({reason})"
DEEP_CONFIG_ERROR = "- 심층 분석 생략: 설정 오류({problem})"
DEEP_SKIPPED = "- 심층 분석 생략: {reason}"
EXPLORE_MODULE_DONE = ("- 탐색 분석 (추정, " + TIMELINE_FILE + " {lines}/{total}줄, 모듈 문서 {module} @{sha7}): "
                       + EXPLORE_HYPOTHESIS)
EXPLORE_MODULE_NONE = ("- 탐색 분석 (추정, " + TIMELINE_FILE + " {lines}/{total}줄, 모듈 문서 없음: {reason}): "
                       + EXPLORE_HYPOTHESIS)
EXPLORE_SKIPPED = "- 탐색 분석 생략: {reason}"
MODULE_TIMELINE_SUB = "  - 모듈 타임라인: {kept}/{pool}줄, 잡음 {noise}, 반복 접음 {collapsed}{uncollected}"   # uncollected = ", 미수집 a·b" | ""
EVIDENCE_SUB = "  - 근거 원문 검사: {text}"
DEEP_PREFIX, EXPLORE_PREFIX = "- 심층 분석", "- 탐색 분석"    # rewrite_line·current_line의 prefix
# check-output 한도(UTF-8 바이트, 한 칸 768바이트 = 한글 약 250자)
OUTPUT_MAX_BYTES, FIELD_MAX_BYTES, DEEP_MAX_BYTES, EXPLORE_MAX_BYTES, QUOTES_MAX, HYPS_MAX = 16384, 768, 6144, 10240, 5, 3
# 실패 JSON의 `next`(B2-24): 스크립트가 줄을 고친 뒤 모델이 할 일 한 줄
NEXT_CONTINUE = "리포트 줄은 스크립트가 고쳤다 — 심층 분석 없이 Step 6로 계속"
NEXT_SKILL_MISSING = ("스킬을 부르는 도구가 있으면 analyzer.skill을 input 파일로 부르고, 없으면 check-output --for deep "
                      "--skipped \"설치 스킬 못 찾음\"")
NEXT_FIX_CALL = "명령을 고쳐 한 번만 다시(module-skills.md) — 또 틀리면 check-output --skipped"
NEXT_BUILTIN = "JOB/timeline.md로 explore.md대로"
NEXT_ASK_BUILTIN = "실패를 보이고 \"탐색 분석을 내장 줄 모양만으로 할까요, 생략할까요?\"를 묻는다"
NEXT_EXPLORE_SKIPPED = "리포트 줄은 스크립트가 고쳤다 — 탐색 분석 없이 Step 6로 계속"
NEXT_CHECK_FAILED = "리포트 줄은 생략으로 고쳐 두었다 — 고쳐 쓰지 말고 Step 6로"
NEXT_CHECK_NA = "리포트 줄은 그대로 둔다 — Step 6로 계속"
MODULE_RECORD_DIR = "module-skill"
# 새 run이 지우는 이전 실행 산출물(B2 §7.4) — 폴더 MODULE_RECORD_DIR도 지운다
STALE_FILES = (TIMELINE_FILE, EXPLORE_INPUT_FILE, "module-skill.json", "deep-input.json", "skill-input.json", "check-output.json",
               "deep-output.md", "explore-output.md")
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
        # v 2: 이 뒤 행으로 운영 지표(usage_stats)를 잰다 — db_pr의 stage·publish·discard 행도 같은 파일(v 2)
        self._trace({"ts": _now(), "step": "start", "v": 2, "pid": os.getpid()})
