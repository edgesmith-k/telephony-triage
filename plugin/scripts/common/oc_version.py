"""OpenCode 바이너리 의존 한 곳(계획 I, 종합 리뷰 F②).

OpenCode 쪽 코드가 기대는 **바이너리의 비공개 표면**을 여기 한 파일에 둔다: 고정 버전, CLI 인자, 환경 변수 이름, 바이너리가 모델에
돌려주는 거부 문구, `opencode run --format json` 이벤트 스키마, 플러그인 hook 이름. OpenCode 버전을 올릴 때 바꿀 곳은 이 파일과
시험의 고정값(`tests/test_oc_version.py`)뿐이며, 아래 항목마다 적힌 실험을 새 버전으로 다시 한 뒤 값을 고친다(`docs/development/
RUNTIMES.md §5`, 우회 금지 — `RUNTIME_ADOPTION.md §6`).

쓰는 곳: `common/oc_adapter.py`(버전·거부 문구·`--version`), `opencode/bin/tt-oc`(전부 — 표준 라이브러리만 쓰는 독립 스크립트라
레포 상대 경로 `../../plugin/scripts/common/oc_version.py`로 읽는다), `tools/gen_opencode.py`(버전), `tests/opencode/ocenv.py`(버전).
`opencode/plugins/tt-guard.js`는 JS라 가져오지 못하므로 시험이 `HOOKS`·`BUILTINS`·버전 주석을 이 파일과 대조한다.

이 파일은 아무것도 import하지 않는다(독립 스크립트·tools·tests가 경로로 바로 읽는다 — JSON 해석은 부르는 쪽이 `loads`로 준다).
"""

# 고정 버전. `tt-oc doctor`·`site_step.py runtime-check opencode`는 `opencode --version`이 이 값과 같을 때만 시작한다.
OPENCODE_VERSION = "1.19.5"

# -- CLI(1.19.5 실험 11/05: `opencode run --format json`·`debug config`·`session delete`) ----------------------------------
VERSION_ARGS = ("--version",)                 # 마지막 줄이 버전
DEBUG_CONFIG_ARGS = ("debug", "config")       # 합쳐진 실제 설정 JSON(관리 설정 포함)
RUN_ARGS = ("run", "--format", "json")        # + `--dir <프로젝트>` `--agent <이름>` [`--command <이름>`] [`-s <세션>`] `-- <메시지>`
SESSION_DELETE_ARGS = ("session", "delete")   # + <세션>
# tt-oc가 거절하는 opencode 옵션: 플러그인·설정·에이전트를 건너뛰거나 바꾸는 것(`--pure`는 플러그인을 아예 싣지 않는다).
REFUSED_ARGS = ("--pure", "--auto", "--attach", "--port", "-i", "--interactive", "--fork", "-c", "--continue",
                "--agent", "-m", "--model")

# -- 환경 변수(계획 I x3b·x4: `OPENCODE_PERMISSION`이 설정 deny를, `OPENCODE_CONFIG_CONTENT`가 `snapshot:false`를 이겼다) ----
# 설정·권한을 덮거나 지우는 것 — 있으면 tt-oc는 시작하지 않고 oc_adapter는 모든 도구를 거부한다.
REFUSED_ENV = ("OPENCODE_PERMISSION", "OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG_DIR",
               "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_PURE", "OPENCODE_AUTO_SHARE", "OPENCODE_ENABLE_EXA",
               "OPENCODE_TEST_HOME", "OPENCODE_TEST_MANAGED_CONFIG_DIR")
REFUSED_ENV_PREFIX = ("OPENCODE_EXPERIMENTAL", "OPENCODE_ENABLE_EXPERIMENTAL")
# tt-oc가 자식에 주는 것: 자동 갱신·모델 목록 받기 끔, `~/.claude/CLAUDE.md`(와 위 폴더의 CLAUDE.md)를 에이전트 프롬프트에 붙이지
# 않음(사용자 결정 ⑤ — 프롬프트는 triage 에이전트 하나).
CHILD_ENV = {"OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
             "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1"}
# 끌 수 없어 사전 점검이 보는 자동 지시 파일(프로젝트 폴더에서 worktree — git 밖이면 `/` — 까지, 전역 `<config>/opencode/AGENTS.md`).
INSTRUCTION_FILES = ("AGENTS.md", "CONTEXT.md")
PLUGIN_DIR = ".opencode/plugins"              # 프로젝트 폴더에서 자동으로 싣는 플러그인 폴더(`gen_opencode.py install`이 복사)

# -- 거부 문구(바이너리가 설정 deny·자동 거절 때 도구 오류로 모델에 돌려주는 영어 — 1.19.5 실험 11/05) -----------------------
# tt-oc는 이 문구가 든 도구 오류를 "막힌 호출"로, oc_adapter.error_class는 `permission-denied`로 본다.
DENY_PHRASES = ("prevents you from using this specific tool call", "rejected permission")

# -- `opencode run --format json` 이벤트 스키마(한 줄 한 JSON, tt-oc.judge가 읽는 것만) ---------------------------------------
EV_STEP_START, EV_TEXT, EV_STEP_FINISH, EV_TOOL_USE, EV_ERROR = "step_start", "text", "step_finish", "tool_use", "error"
EV_SESSION = "sessionID"                      # 모든 이벤트
EV_PART = "part"                              # text·step_finish·tool_use의 본문
PART_TEXT = "text"                            # text: 모델 글 조각
PART_REASON, PART_TOKENS = "reason", "tokens"  # step_finish: 끝난 이유(`stop`이면 정상)·토큰 {input, output, reasoning}
TOKEN_KINDS = ("input", "output", "reasoning")
PART_TOOL, PART_STATE = "tool", "state"       # tool_use: 도구 이름·상태 {status, error, input}
STATE_STATUS, STATE_ERROR, STATE_INPUT = "status", "error", "input"
STATUS_ERROR = "error"                        # 거부·실패한 도구 호출의 status
FINISH_STOP = "stop"                          # 정상 종료의 reason
FINISH_LENGTH = "length"                      # 출력 한도에서 잘림(AI SDK finishReason 이름 — 1.19.5 실제 이벤트로는 아직 못 봄)

# -- 하위 에이전트(task) 세션(1.19.5 실험 11/17) ------------------------------------------------------------------------
# `run --format json`은 sessionID가 다른 part를 내보내지 않는다(하위 세션의 도구 호출·토큰이 안 보인다). task 도구 part의
# `state.metadata.sessionId`로 하위 세션을 찾아 `opencode export <id>`(stdout JSON `{info, messages: [{info: {role}, parts}]}`,
# stderr에 "Exporting session") 로 읽는다. part 본문은 run 이벤트의 `part`와 같고 type 이름만 다르다.
EXPORT_ARGS = ("export",)                     # + <세션>
TASK_TOOL = "task"
STATE_METADATA, META_SESSION = "metadata", "sessionId"
EXPORT_MESSAGES, EXPORT_INFO, EXPORT_ROLE, EXPORT_PARTS = "messages", "info", "role", "parts"
EXPORT_PART_EVENT = {"step-start": EV_STEP_START, "text": EV_TEXT, "step-finish": EV_STEP_FINISH, "tool": EV_TOOL_USE}

# -- 권한 패턴(1.19.5 `Wildcard.match`: `*` 아무 글자열, `?` 한 글자, 전체 일치, 마지막으로 맞는 규칙이 이긴다) ----------------
TASK_AGENT = "tt-explore"                     # task로 부를 수 있는 유일한 하위 에이전트(= oc_adapter.TASK_ALLOWED)
TASK_PROBES = ("general", "~other~")          # 다른 하위 에이전트 이름 대표(내장 하나, 어느 이름 패턴에도 안 맞을 것 하나)


def wildcard_match(pattern: str, text: str) -> bool:
    p = t = 0
    star, mark = -1, 0
    while t < len(text):
        if p < len(pattern) and pattern[p] in ("?", text[t]) and pattern[p] != "*":
            p, t = p + 1, t + 1
        elif p < len(pattern) and pattern[p] == "*":
            star, mark, p = p, t, p + 1
        elif star != -1:
            p, mark = star + 1, mark + 1
            t = mark
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


def task_rule_state(value):
    """설정 `permission.task` 값의 실제 효과: "explore-only"(tt-explore만 allow, 다른 이름 deny), "all-deny", 그 밖은 None.
    글자 그대로 비교하지 않고 마지막 일치 규칙으로 판정한다(순서가 바뀐 객체는 모두 거부가 된다). allow는 `tt-explore` 글자
    그대로인 키에만, 값은 allow·deny만(ask는 `opencode run`을 멈춘다)."""
    if value == "deny":
        return "all-deny"
    if not isinstance(value, dict) or any(v not in ("allow", "deny") for v in value.values()):
        return None
    if any(v == "allow" and k != TASK_AGENT for k, v in value.items()):
        return None

    def last(name):
        out = None
        for k, v in value.items():
            if isinstance(k, str) and wildcard_match(k, name):
                out = v
        return out

    if any(last(n) != "deny" for n in TASK_PROBES):
        return None
    return "explore-only" if last(TASK_AGENT) == "allow" else "all-deny"

# -- 관리 설정(관리자가 배포하는 managed config) -----------------------------------------------------------------------------
# 1.19.5 바이너리에서 확인: 폴더는 darwin `/Library/Application Support/opencode`, win32 `%ProgramData%\opencode`(없으면
# `C:\ProgramData\opencode`), 그 밖 `/etc/opencode`이고(`OPENCODE_TEST_MANAGED_CONFIG_DIR`가 있으면 그것 — tt-oc는 이 변수를
# 거부한다), 그 안의 `opencode.json`·`opencode.jsonc`를 이 순서로 사용자·프로젝트 설정 위에 깊게 합친다(`merge_deep`).
# darwin은 그 뒤 MDM 설정(`ai.opencode.managed`)도 합친다 — 여기서는 읽지 않는다(확인 못 함).
MANAGED_NAMES = ("opencode.json", "opencode.jsonc")


def managed_dir(platform: str, env) -> str:
    if platform == "darwin":
        return "/Library/Application Support/opencode"
    if platform == "win32":
        return (env.get("ProgramData") or "C:\\ProgramData") + "\\opencode"
    return "/etc/opencode"


def merge_deep(base: dict, over: dict) -> dict:
    """OpenCode가 설정을 합치는 방식: 둘 다 객체면 안으로 들어가 합치고, 아니면 뒤 값. 있던 키는 제자리, 새 키는 끝에 붙는다."""
    out = dict(base)
    for k, v in over.items():
        out[k] = merge_deep(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def managed_permission(folder, loads) -> dict:
    """관리 설정 폴더(`pathlib.Path`, `loads` = `json.loads`)의 `permission`을 파일 순서대로 합친 것. 파일이 없으면 {}. 읽기 실패·깨진 JSON·객체가 아닌
    permission은 OSError·ValueError로 올린다(조용히 넘기면 관리자 deny가 빠진 설치가 된다)."""
    out: dict = {}
    for name in MANAGED_NAMES:
        path = folder / name
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        cfg = loads(strip_jsonc(text))
        perm = cfg.get("permission", {}) if isinstance(cfg, dict) else None
        if not isinstance(perm, dict):
            raise ValueError(f"{path}: permission이 객체가 아니다")
        out = merge_deep(out, perm)
    return out


def strip_jsonc(text: str) -> str:
    """JSONC → JSON: 문자열 밖 `//`·`/* */` 주석과 `}`·`]` 앞 쉼표를 뺀다."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(c)
            i += 1
    text, out, i = "".join(out), [], 0      # 둘째 차례: 문자열 밖에서 `}`·`]` 바로 앞(공백만 사이) 쉼표를 뺀다
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
            continue
        if c == ",":
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


# -- 플러그인 hook 이름(`opencode/plugins/tt-guard.js`가 구현, 시험이 대조) -------------------------------------------------
# `tool.execute.after`는 오류로 끝난 MCP 호출에는 돌지 않는다(RUNTIMES.md §5.5) → `experimental.chat.messages.transform`.
HOOKS = ("tool.execute.before", "tool.execute.after", "experimental.chat.messages.transform", "shell.env", "chat.params")
