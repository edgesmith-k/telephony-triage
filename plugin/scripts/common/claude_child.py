"""자식 `claude -p` 실행 도우미 (모듈 eval·스킬 eval 공용, MODULE_SKILLS_PLAN_IMPL §5.6·IMPL:403).

`tests/skill_evals/run.py`의 자식 실행 도우미(환경 정리·인증 키 전달·transcript 읽기)와 `grade.py`의 `token_record`를
여기로 옮겼다. run.py·grade.py는 같은 이름을 다시 내보낸다(동작 같음). 새 API는 읽기 도구만 쓰는 자식(모듈 eval)용이다:
argv 조립(`build_command`), 환경 준비(`prepare_env`), init 검사(`readonly_init_problem`), 도구 호출 정규화
(`normalize_calls`), 실행(`run_child`). 결과 모양(`ChildResult`)은 런타임 중립이라 나중의 `opencode_child.py`가 같은
dataclass를 채운다. 표준 라이브러리만 쓴다.

Claude Code + 사내 모델(게이트웨이, 계획 I C2i·C3i, docs/development/RUNTIMES.md): 사용자 settings.json env의 게이트웨이 프로필
키(`GATEWAY_ENV_NAMES`)도 자식에 넘기고(`--setting-sources ""`라 그대로면 빠진다), result의 costBasis가 "unknown"이면 비용을
None으로 둔다(`result_cost`·`token_record`). 읽기 전용 자식은 `ChildSpec.bare`로 `--bare`를 쓸 수 있고 인증이 안 되면 한 번
`--bare` 없이 다시 돈다(`run_child`). `gateway_profile_check`는 모델 호출 없이 프로필을 점검한다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path

from common import shown

# --- run.py에서 옮긴 것 (동작 같음) ----------------------------------------------------------------

# 부모(원격 세션)의 정체성을 나르는 환경 변수: 자식 `claude -p`가 상속하면 부모 세션 ID로 동작해
# 커밋에 부모의 `Co-Authored-By`·`Claude-Session` 줄이 붙는다. 인증·프록시(HTTPS_PROXY, ANTHROPIC_*, *_CA_*, GH_TOKEN …)는 남긴다.
PARENT_IDENTITY_PREFIXES = ("CLAUDE_CODE_REMOTE", "CLAUDE_CODE_MESSAGING", "CLAUDE_CODE_ARTIFACT")
PARENT_IDENTITY_NAMES = frozenset({
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CONTAINER_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_USE_CCR_V2",
    "CLAUDE_CODE_POST_FOR_SESSION_INGRESS_V2", "CLAUDE_CODE_SYNC_SESSION_REFS", "CLAUDE_CODE_SYNC_SKILLS",
    "CLAUDE_CODE_WORKER_EPOCH", "TRACEPARENT"})
# 커밋·PR 서명을 끈다(`claude --settings`는 JSON 문자열을 받는다).
NO_ATTRIBUTION_SETTINGS = json.dumps({"includeCoAuthoredBy": False, "attribution": {"commit": "", "pr": ""}})
# 자식은 `--setting-sources ""`로 사용자·프로젝트 설정(플러그인·hook·권한)을 읽지 않는다(재현성).
# 그러면 사용자 settings.json으로 하는 인증(예: 사내 apiKeyHelper)도 빠져 "Not logged in"이 된다.
# 인증·네트워크 관련 키만 사용자 설정에서 골라 넘긴다: 최상위 키는 --settings JSON에(명령 문자열이라 비밀 아님),
# env 블록은 프로세스 환경에(값이 비밀일 수 있어 argv·기록에 넣지 않는다). 기록에는 키 이름만 남긴다.
AUTH_SETTING_KEYS = ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport")
AUTH_ENV_PREFIXES = ("ANTHROPIC_", "AWS_", "VERTEX_", "CLAUDE_CODE_USE_", "CLAUDE_CODE_API_KEY_HELPER")
AUTH_ENV_NAMES = frozenset({"CLOUD_ML_REGION", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
                            "no_proxy", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE"})
# 게이트웨이(사내 모델) 프로필 키(계획 I C2i, docs/development/RUNTIMES.md): 모델 한도·요청 모양을 정하는 CLI 환경 변수.
# 사용자 settings.json env 블록에만 두면 `--setting-sources ""` 자식에서 빠져 자식이 32K 출력·thinking·베타 헤더로 요청한다
# (가짜 서버 실험: max_tokens 32000, thinking adaptive). 모델 이름(`ANTHROPIC_MODEL`·`ANTHROPIC_DEFAULT_*_MODEL`)과 주소·키는
# 위 `ANTHROPIC_` 접두로 이미 넘어간다. 값은 인증 env처럼 프로세스 환경에만 넣고 기록에는 이름만 남긴다.
GATEWAY_ENV_NAMES = frozenset({
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "CLAUDE_CODE_MAX_CONTEXT_TOKENS", "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS",
    "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_DISABLE_THINKING",
    "CLAUDE_CODE_SUBAGENT_MODEL", "API_TIMEOUT_MS", "MAX_THINKING_TOKENS", "DISABLE_PROMPT_CACHING"})
# 권한 모드를 명시한다: 생략하면 CLI 기본값(사내 설치는 auto)이 적용돼 분류기가 허용 목록의 Bash까지 막는다.
# "default"는 옛 CLI의 이름이고 새 CLI(2.1.x, 도움말에는 manual)도 별칭으로 받는다(2.1.296 확인).
CHILD_PERMISSION_MODE = "default"


def child_common_args(settings_json: str, persist: bool = False) -> list[str]:
    """두 모드(plain·plugin) 자식 `claude -p`의 공통 인자. persist(plugin 모드)면 세션 transcript를 남긴다:
    `--no-session-persistence`면 hook 입력의 `transcript_path` 파일이 생기지 않아 표시 보조 hook(show_guard.py)이 아무것도
    판정하지 못한다(fail-open, 08-safety.md §9.1). 남긴 transcript는 실행 뒤 run 디렉토리로 옮긴다(`collect_transcript`)."""
    return ["--output-format", "stream-json", "--verbose", *([] if persist else ["--no-session-persistence"]),
            "--setting-sources", "", "--settings", settings_json, "--strict-mcp-config", "--permission-mode",
            CHILD_PERMISSION_MODE]


def collect_transcript(events: list[dict], env: dict[str, str], run_dir: Path) -> str | None:
    """자식 세션 transcript(`<config>/projects/*/<session_id>.jsonl`)를 run 디렉토리의 `session.jsonl`로 옮긴다(사용자
    projects 디렉토리에 남기지 않는다). session_id는 stream-json init 이벤트. 못 찾으면 None — show_guard가 판정하지 못한 실행이다."""
    sid = next((e.get("session_id") for e in events if e.get("type") == "system" and e.get("session_id")), None)
    if not sid or not re.fullmatch(r"[A-Za-z0-9-]+", str(sid)):
        return None
    base = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else Path(env.get("HOME", str(Path.home()))) / ".claude"
    found = sorted((base / "projects").glob(f"*/{sid}.jsonl"))
    if not found:
        return None
    dest = run_dir / "session.jsonl"
    shutil.move(str(found[0]), dest)
    return dest.name


def carried_env_key(k) -> bool:
    """사용자 settings.json env 블록에서 자식에 넘기는 키인가: 인증·네트워크(`AUTH_ENV_*`)와 게이트웨이 프로필(`GATEWAY_ENV_NAMES`)."""
    return isinstance(k, str) and (k.startswith(AUTH_ENV_PREFIXES) or k in AUTH_ENV_NAMES or k in GATEWAY_ENV_NAMES)


def user_auth_settings(env: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """사용자 settings.json에서 인증·네트워크·게이트웨이 프로필 키만 (최상위 키, env 블록). 없거나 깨졌으면 빈 값."""
    base = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else Path(env.get("HOME", str(Path.home()))) / ".claude"
    try:
        data = json.loads((base / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}
    top = {k: data[k] for k in AUTH_SETTING_KEYS if isinstance(data.get(k), str) and data[k]}
    raw_env = data.get("env") if isinstance(data.get("env"), dict) else {}
    auth_env = {k: str(v) for k, v in raw_env.items() if carried_env_key(k) and v is not None}
    return top, auth_env


# 게이트웨이 프로필 권장값(RUNTIMES.md "Claude Code + 사내 모델"). 모델 호출 없이 환경만 본다 — `site_step.py`의 런타임 점검
# (O10, B1+B2 뒤 통합)이 이 함수를 부른다.
GATEWAY_PROFILE = {
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16000", "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "202000",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1", "CLAUDE_CODE_EFFORT_LEVEL": "unset",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
GATEWAY_CREDENTIALS = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
GATEWAY_UNSET = "unset"      # 권장 값이 "두지 않는다"인 키: 변수 없음·빈 값·글자 그대로 "unset"이 모두 맞다(F, O10 거짓 실패)


def gateway_profile_check(env: dict[str, str]) -> list[dict]:
    """게이트웨이 프로필 점검 행 [{key, status, detail}] (status: ok | missing | differs | info). 프로세스 환경 위에 사용자
    settings.json env 블록을 얹은 값(자식이 실제로 받는 값)을 본다. 비밀 값(주소·키)은 행에 넣지 않는다."""
    top, settings_env = user_auth_settings(env)
    eff = {**env, **settings_env}
    rows = []

    def add(key, status, detail):
        rows.append({"key": key, "status": status, "detail": detail})
    add("ANTHROPIC_BASE_URL", "ok" if eff.get("ANTHROPIC_BASE_URL") else "missing",
        "설정됨(값은 기록하지 않음)" if eff.get("ANTHROPIC_BASE_URL") else "게이트웨이 주소 없음 — 기본 Anthropic API로 간다")
    cred = [k for k in GATEWAY_CREDENTIALS if eff.get(k)] + (["apiKeyHelper"] if top.get("apiKeyHelper") else [])
    add("credential", "ok" if cred else "missing", ", ".join(cred) if cred else "ANTHROPIC_AUTH_TOKEN·ANTHROPIC_API_KEY·apiKeyHelper 없음")
    add("ANTHROPIC_MODEL", "ok" if eff.get("ANTHROPIC_MODEL") else "info",
        eff.get("ANTHROPIC_MODEL") or "없음 — 실행마다 --model <사내 모델>을 준다")
    for key, want in GATEWAY_PROFILE.items():
        have = eff.get(key)
        if want == GATEWAY_UNSET:
            add(key, "ok" if have in (None, "", GATEWAY_UNSET) else "differs",
                f"{have} (권장 {want})" if have else f"없음 (권장 {want} — 두지 않아도 된다)")
            continue
        add(key, "ok" if have == want else ("missing" if have is None else "differs"),
            f"{have} (권장 {want})" if have is not None else f"없음 (권장 {want})")
    add("CLAUDE_CODE_DISABLE_THINKING", "info", f"{eff.get('CLAUDE_CODE_DISABLE_THINKING') or '없음'} — 게이트웨이가 "
        "thinking을 거부할 때만 1(사내 확인 2)")
    return rows


def child_settings(env: dict[str, str]) -> tuple[str, dict[str, str], list[str]]:
    """자식 --settings JSON, 덧붙일 환경, 넘긴 키 이름 목록."""
    top, auth_env = user_auth_settings(env)
    settings = {**json.loads(NO_ATTRIBUTION_SETTINGS), **top}
    return json.dumps(settings), auth_env, sorted(top) + sorted(f"env.{k}" for k in auth_env)


def child_env(env: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """자식 claude에 넘길 환경 (부모 세션 정체성 변수를 뺀 사본, 뺀 이름 목록)."""
    stripped = sorted(k for k in env if k.startswith(PARENT_IDENTITY_PREFIXES) or k in PARENT_IDENTITY_NAMES)
    return {k: v for k, v in env.items() if k not in stripped}, stripped


def read_events(path: Path) -> tuple[list[dict], dict | None]:
    """events.jsonl의 (이벤트 목록, 마지막 result 이벤트). JSON이 아닌 줄은 건너뛴다."""
    events, result = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        if event.get("type") == "result":
            result = event
    return events, result


def merge_results(results: list[dict]) -> dict | None:
    """후속 메시지(`followups`)로 여러 턴을 돈 실행의 result 이벤트들을 하나로. 마지막 result를 바탕으로
    상위 `usage` 수치·`num_turns`·`duration_ms`는 턴별 값이라 더하고, `modelUsage`·`total_cost_usd`는 누적값이라
    마지막 값을 쓴다(CLI 2.1.299 실측: 두 번째 result의 modelUsage cacheRead = 두 턴 합, num_turns는 턴마다 1·1,
    duration_ms는 2441·2377로 턴별 값). 하나라도 오류면 오류."""
    if not results:
        return None
    merged = dict(results[-1])
    usage: dict = {}
    for r in results:
        for k, v in (r.get("usage") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                usage[k] = usage.get(k, 0) + v
            else:
                usage.setdefault(k, v)
    merged["usage"] = usage
    for k in ("num_turns", "duration_ms"):
        vals = [r.get(k) for r in results if isinstance(r.get(k), (int, float))]
        if vals:
            merged[k] = sum(vals)
    merged["is_error"] = any(r.get("is_error") for r in results)
    merged["turn_results"] = len(results)
    return merged


def init_model(events: list[dict]) -> str | None:
    """stream-json init 이벤트가 알려 주는 실제 모델 ID. `--model` 없이 돌렸을 때 기준선 모델의 출처다."""
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    model = (init or {}).get("model")
    return model if isinstance(model, str) and model else None


def classify_result(result: dict | None, returncode: int) -> tuple[str, str]:
    if not result:
        return "error", f"Claude 결과 없음 (exit {returncode})"
    reason = str(result.get("result", ""))
    if result.get("api_error_status") in (401, 403, 429):
        return "blocked", reason
    if returncode or result.get("is_error"):
        return "error", reason or str(result.get("subtype"))
    return "completed", reason


# --- grade.py에서 옮긴 것: 토큰 기록 ----------------------------------------------------------------
_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
_MODEL_KEYS = ("inputTokens", "outputTokens", "cacheCreationInputTokens", "cacheReadInputTokens")
_FIELDS = ("input", "output", "cache_creation", "cache_read")


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _sum(parts):
    """하나라도 없으면(null) 합도 null — 빠진 값을 0으로 채우지 않는다."""
    return sum(parts) if parts and all(p is not None for p in parts) else None


COST_UNKNOWN = "unknown"


def cost_basis(result) -> str | None:
    """result 이벤트 modelUsage의 `costBasis`. 하나라도 "unknown"이면 "unknown"(CLI가 모르는 모델 ID — 사내 게이트웨이 모델 —
    에 자리 표시 단가 $4/$20 per MTok를 매긴 값이다, CLI 2.1.318 가짜 서버 실험), 아니면 있는 값들(정렬, `,`로 이음), 없으면 None."""
    mu = result.get("modelUsage") if isinstance(result, dict) else None
    vals = {str(m.get("costBasis")) for m in (mu.values() if isinstance(mu, dict) else [])
            if isinstance(m, dict) and isinstance(m.get("costBasis"), str) and m.get("costBasis")}
    if COST_UNKNOWN in vals:
        return COST_UNKNOWN
    return ",".join(sorted(vals)) or None


def result_cost(result) -> float | None:
    """보고된 비용(`total_cost_usd`). costBasis가 unknown이면 None — 자리 표시 단가를 비용으로 쓰지 않는다."""
    if cost_basis(result) == COST_UNKNOWN:
        return None
    return _num(result.get("total_cost_usd")) if isinstance(result, dict) else None


def token_record(result) -> dict:
    """stream-json result 이벤트(또는 옛 execution.json)에서 `tokens` 기록을 만든다. None·빠진 값은 null.
    total은 modelUsage 합(서브에이전트·보조 모델 포함)이고, usage_total은 상위 usage 네 값의 합(비교용)이다.
    costBasis가 unknown인 모델의 cost_usd와 total_cost_usd는 null이다(`cost_basis` 키에 사유) — 토큰은 그대로 센다."""
    r = result if isinstance(result, dict) else {}
    usage = r.get("usage") if isinstance(r.get("usage"), dict) else {}
    by_model = {}
    mu = r.get("modelUsage")
    for name, m in (mu.items() if isinstance(mu, dict) else []):
        m = m if isinstance(m, dict) else {}
        vals = [_int(m.get(k)) for k in _MODEL_KEYS]
        basis = m.get("costBasis") if isinstance(m.get("costBasis"), str) else None
        by_model[str(name)] = {**dict(zip(_FIELDS, vals)), "total": _sum(vals),
                               "cost_usd": None if basis == COST_UNKNOWN else _num(m.get("costUSD")),
                               **({"cost_basis": basis} if basis else {})}
    sums = [_sum([m[f] for m in by_model.values()]) for f in _FIELDS]
    return {**dict(zip(_FIELDS, sums)), "total": _sum(sums),
            "usage_total": _sum([_int(usage.get(k)) for k in _USAGE_KEYS]),
            "num_turns": _int(r.get("num_turns")), "duration_ms": _num(r.get("duration_ms")),
            "total_cost_usd": result_cost(r), "cost_basis": cost_basis(r),
            "by_model": by_model, "source": "modelUsage" if by_model else None}


# --- 읽기 도구만 쓰는 자식 (모듈 eval) ---------------------------------------------------------------

READONLY_TOOLS = ("Read", "Glob", "Grep")                   # --tools에 넘기는 이름
READONLY_NORMALIZED = frozenset({"read", "glob", "grep"})   # 채점기가 받는 정규화 이름(Claude 런타임)
OPTIONAL_FLAGS = ("--max-budget-usd", "--disable-slash-commands", "--restricted", "--permission-prompts", "--bare")
CHILD_MODES = ("contract", "restricted")
INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md")
POPPED_ENV = ("CLAUDECODE", "CLAUDE_PLUGIN_ROOT", "CLAUDE_ENV_FILE")
EMPTY_MCP = '{"mcpServers":{}}'
ERROR_TEXT_LIMIT = 200


@dataclass(frozen=True)
class CliInfo:
    path: str
    version: str | None
    flags: frozenset[str]          # `--help` 글에 있는 OPTIONAL_FLAGS


@dataclass(frozen=True)
class ChildSpec:
    prompt: str
    cwd: Path
    model: str | None = None
    timeout: int = 300
    max_budget_usd: float | None = None
    tools: tuple[str, ...] = READONLY_TOOLS
    mode: str = "contract"         # contract | restricted
    bare: bool = False             # `--bare`(계획 I C3i, 기본 끔): 인증이 안 되면 run_child가 --bare 없이 한 번 다시 돈다


@dataclass
class ChildResult:
    runtime: str                   # "claude-code" (나중의 opencode_child.py는 "opencode")
    status: str                    # completed | error | timeout | blocked | env_error
    reason: str
    exit_code: int | None
    final_text: str
    calls: list[dict]
    readonly_tools: frozenset[str]
    init: dict | None
    tokens: dict
    tie_tokens: int | None
    cost_usd: float | None
    model: str | None
    elapsed_s: float
    events_path: Path
    stderr_path: Path
    env_stripped: list[str]
    auth_keys: list[str]
    cost_basis: str | None = None  # modelUsage costBasis — "unknown"이면 cost_usd는 None(`result_cost`)
    bare: str | None = None        # None(안 씀) | "used" | "unsupported"(CLI에 없음) | "fallback: <사유>"(인증 실패로 다시 돎)


def detect_cli(claude: str) -> CliInfo:
    """`claude --version`·`claude --help`만 부른다(API 호출 없음, 각 30초). 실행할 수 없으면 OSError."""
    def out(arg: str) -> str:
        try:
            proc = subprocess.run([claude, arg], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=30, stdin=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired:
            return ""
        return proc.stdout + "\n" + proc.stderr
    version_text = out("--version").strip()
    help_text = out("--help")
    flags = frozenset(f for f in OPTIONAL_FLAGS if re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", help_text))
    return CliInfo(path=claude, version=version_text.splitlines()[0].strip() if version_text else None, flags=flags)


def build_command(cli: CliInfo, spec: ChildSpec, settings_json: str) -> list[str]:
    """자식 argv (순서 고정). contract: `--allowedTools`로 읽기 도구를 미리 허용(IMPL:610). restricted: `--restricted
    --permission-prompts none`(파일 도구를 작업 디렉토리에 가둠, 물을 일은 자동 거부) — `--allowedTools`는 뺀다(있으면 경로와
    무관하게 미리 허용된다). 플래그가 CLI에 없으면 ValueError."""
    if spec.mode not in CHILD_MODES:
        raise ValueError(f"모르는 자식 모드: {spec.mode}")
    tools = ",".join(spec.tools)
    cmd = [cli.path, "-p", *(["--model", spec.model] if spec.model else []), *child_common_args(settings_json),
           "--mcp-config", EMPTY_MCP, "--tools", tools]
    if spec.mode == "contract":
        cmd += ["--allowedTools", tools]
    else:
        missing = [f for f in ("--restricted", "--permission-prompts") if f not in cli.flags]
        if missing:
            raise ValueError(f"이 CLI에 {' '.join(missing)} 없음")
        cmd += ["--restricted", "--permission-prompts", "none"]
    if "--max-budget-usd" in cli.flags and spec.max_budget_usd:
        cmd += ["--max-budget-usd", f"{spec.max_budget_usd:.2f}"]
    if "--disable-slash-commands" in cli.flags:
        cmd += ["--disable-slash-commands"]
    if spec.bare and "--bare" in cli.flags:
        cmd += ["--bare"]      # hook·CLAUDE.md 자동 탐색·키체인·OAuth를 건너뛴다 — 인증은 ANTHROPIC_API_KEY·AUTH_TOKEN·apiKeyHelper만
    return cmd


# `--bare` 인증 실패 모양(CLI 2.1.318 가짜 서버 실험): 키 없음 → 요청 없이 result is_error "Not logged in · Please run /login",
# 게이트웨이 거부 → api_error_status 401/403.
BARE_AUTH_RX = re.compile(r"not logged in|/login|invalid api key|authentication|unauthori[sz]ed|oauth|keychain", re.IGNORECASE)


def bare_auth_failure(events: list[dict], result: dict | None) -> str | None:
    """--bare 실행이 인증 때문에 실패했으면 그 사유(앞 ERROR_TEXT_LIMIT자), 아니면 None. 도구를 한 번이라도 불렀으면 None
    (모델까지 갔다 — 다시 돌리지 않는다)."""
    if not isinstance(result, dict) or normalize_calls(events):
        return None
    text = str(result.get("result") or "")
    if result.get("api_error_status") in (401, 403) or (result.get("is_error") and BARE_AUTH_RX.search(text)):
        return (text or f"api_error_status {result.get('api_error_status')}")[:ERROR_TEXT_LIMIT]
    return None


def prepare_env(base: dict[str, str]) -> tuple[dict[str, str], str, list[str], list[str]]:
    """(자식 환경, --settings JSON, 뺀 변수 이름, 사용자 설정에서 넘긴 인증 키 이름). 인증 env 값은 환경에만 넣는다(argv 아님)."""
    env = dict(base)
    popped = [k for k in POPPED_ENV if env.pop(k, None) is not None]
    env, stripped = child_env(env)
    settings_json, auth_env, auth_keys = child_settings(env)
    env.update(auth_env)
    return env, settings_json, sorted(set(stripped) | set(popped)), auth_keys


def split_plugins(plugins: list | None) -> tuple[list[str], list[dict]]:
    """(내장 플러그인 이름, 그 밖의 항목). 내장 = `path == "builtin"` 또는 source가 `@builtin`으로 끝남 — CLI에 실려 오고
    설정과 무관하다(2.1.299–2.1.318 모든 init에 있다)."""
    builtin, other = [], []
    for p in plugins if isinstance(plugins, list) else []:
        if isinstance(p, dict) and (p.get("path") == "builtin" or str(p.get("source") or "").endswith("@builtin")):
            builtin.append(str(p.get("name") or p.get("source")))
        else:
            other.append(p if isinstance(p, dict) else {"name": str(p)})
    return builtin, other


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _holds_file(path: Path) -> bool:
    try:
        return any(p.is_file() for p in path.rglob("*"))
    except OSError:
        return True              # 못 읽으면 닫힌 쪽


def readonly_init_problem(init: dict | None) -> str | None:
    """init 이벤트(또는 `summarize_init` 결과)가 읽기 도구만·MCP 없음·외부 플러그인 없음·다른 프로젝트 메모리 없음이 아니면 그 사유."""
    if not isinstance(init, dict):
        return "init 이벤트 없음"
    tools = init.get("tools") if isinstance(init.get("tools"), list) else []
    extra = sorted(set(map(str, tools)) - set(READONLY_TOOLS))
    if extra:
        return f"읽기 밖 도구 {', '.join(extra)}"
    if init.get("mcp_servers"):
        names = [str(s.get("name") if isinstance(s, dict) else s) for s in init["mcp_servers"]] \
            if isinstance(init["mcp_servers"], list) else [str(init["mcp_servers"])]
        return f"MCP 서버 {', '.join(names)}"
    _, other = split_plugins(init.get("plugins"))
    if other:
        return "외부 플러그인 " + ", ".join(f"플러그인 {p.get('name')}({p.get('path')})" for p in other)
    for s in _strings(init.get("memory_paths")):
        p = Path(s)
        if p.name in INSTRUCTION_FILES:
            return f"memory_paths에 지시 파일 {p.name}"
        if p.is_dir() and _holds_file(p):
            return "memory_paths 디렉토리에 파일이 있다(다른 프로젝트 메모리)"
    return None


def summarize_init(events: list[dict]) -> dict | None:
    """init 이벤트 요약: {tools, mcp_servers, plugins, builtin_plugins, memory_paths, model, permissionMode, counts}."""
    raw = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    if raw is None:
        return None
    builtin, _ = split_plugins(raw.get("plugins"))

    def count(key):
        v = raw.get(key)
        return len(v) if isinstance(v, (list, dict)) else None
    return {"tools": raw.get("tools"), "mcp_servers": raw.get("mcp_servers"), "plugins": raw.get("plugins"),
            "builtin_plugins": builtin, "memory_paths": raw.get("memory_paths"), "model": raw.get("model"),
            "permissionMode": raw.get("permissionMode"),
            "counts": {k: count(k) for k in ("agents", "skills", "slash_commands")}}


def _ctx(inp: dict) -> int | None:
    vals = [inp.get(k) for k in ("-A", "-B", "-C", "context")]
    vals = [v for v in vals if isinstance(v, int) and not isinstance(v, bool)]
    return max(vals) if vals else None


def normalize_calls(events: list[dict]) -> list[dict]:
    """도구 호출을 런타임 중립 모양으로: [{tool, path, pattern, glob, offset, limit, output_mode, context, raw_name, error,
    error_text, sidechain}]. 하위 에이전트 호출도 넣는다. error는 짝 tool_result의 `is_error is True`, 결과가 없으면 None."""
    side_ids: set = set()
    results: dict = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and (ev.get("parent_tool_use_id") or ev.get("isSidechain")):
                side_ids.add(c.get("id"))
            elif ev.get("type") == "user" and c.get("type") == "tool_result":
                body = c.get("content")
                text = "\n".join(str(b.get("text", "")) for b in body if isinstance(b, dict)) \
                    if isinstance(body, list) else str(body or "")
                results[c.get("tool_use_id")] = (c.get("is_error") is True, text[:ERROR_TEXT_LIMIT])
    calls = []
    for e in shown.parse_events(events, include_user=False, skip_sidechain=False):
        if e.get("kind") != "tool":
            continue
        raw = str(e.get("name") or "")
        tool = raw.lower()
        inp = e.get("input") if isinstance(e.get("input"), dict) else {}
        if tool == "read":
            path = inp.get("file_path")
        elif tool in ("glob", "grep"):
            path = inp.get("path")
        else:
            path = inp.get("file_path") or inp.get("path")
        res = results.get(e.get("id"))
        calls.append({
            "tool": tool, "path": path if isinstance(path, str) else None,
            "pattern": inp.get("pattern") if tool in ("glob", "grep") else None,
            "glob": inp.get("glob") if tool == "grep" else None,
            "offset": inp.get("offset") if tool == "read" else None,
            "limit": inp.get("limit") if tool == "read" else None,
            "output_mode": (inp.get("output_mode") or "files_with_matches") if tool == "grep" else None,
            "context": _ctx(inp) if tool == "grep" else None,
            "raw_name": raw, "error": res[0] if res else None, "error_text": res[1] if res else None,
            "sidechain": e.get("id") in side_ids})
    return calls


def final_text(events: list[dict], result: dict | None) -> str:
    """result 이벤트의 `result`, 없으면 마지막 assistant 텍스트 블록, 그것도 없으면 빈 글."""
    if isinstance(result, dict) and isinstance(result.get("result"), str) and result["result"].strip():
        return result["result"]
    last = ""
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "assistant" or ev.get("parent_tool_use_id"):
            continue
        content = (ev.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "text" and str(c.get("text") or "").strip():
                last = str(c["text"])
    return last


def run_child(spec: ChildSpec, run_dir: Path, cli: CliInfo) -> ChildResult:
    """자식 하나를 돌린다. run_dir에 events.jsonl·stderr.log를 쓴다. 결과 이벤트가 없으면 completed가 아니다.
    spec.bare이고 CLI에 `--bare`가 있는데 인증으로 실패하면(`bare_auth_failure`) 그 기록을 `run_dir/bare-attempt/`로 옮기고
    `--bare` 없이 한 번 다시 돈다(결과의 `bare`에 "fallback: 사유"). CLI에 없으면 `--bare` 없이 돌고 "unsupported"."""
    if not spec.bare:
        return _run_once(spec, run_dir, cli)
    if "--bare" not in cli.flags:
        res = _run_once(replace(spec, bare=False), run_dir, cli)
        res.bare = "unsupported"
        return res
    res = _run_once(spec, run_dir, cli)
    try:
        events, result = read_events(res.events_path)
    except (OSError, UnicodeDecodeError):
        events, result = [], None
    why = bare_auth_failure(events, result) if res.status != "timeout" else None
    if why is None:
        res.bare = "used"
        return res
    attempt = run_dir / "bare-attempt"
    attempt.mkdir(exist_ok=True)
    for p in (res.events_path, res.stderr_path):
        if p.exists():
            shutil.move(str(p), attempt / p.name)
    res = _run_once(replace(spec, bare=False), run_dir, cli)
    res.bare = f"fallback: {why}"
    return res


def _run_once(spec: ChildSpec, run_dir: Path, cli: CliInfo) -> ChildResult:
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path, stderr_path = run_dir / "events.jsonl", run_dir / "stderr.log"
    env, settings_json, stripped, auth_keys = prepare_env(dict(os.environ))
    command = build_command(cli, spec, settings_json)
    start = time.monotonic()
    code: int | None = None
    status = reason = ""
    with events_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        try:
            proc = subprocess.Popen(command, cwd=spec.cwd, env=env, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                    text=True, encoding="utf-8")
        except OSError as exc:
            status, reason = "env_error", f"claude 실행 불가: {type(exc).__name__}"
        else:
            try:
                proc.communicate(spec.prompt, timeout=spec.timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                status, reason = "timeout", f"{spec.timeout}초 제한으로 중단"
            code = proc.returncode
    elapsed = round(time.monotonic() - start, 2)
    try:
        events, result = read_events(events_path)
    except (OSError, UnicodeDecodeError):
        events, result = [], None
    if not status:
        status, reason = classify_result(result, code or 0) if result else ("error", f"Claude 결과 없음 (exit {code})")
    init = summarize_init(events)
    if status == "completed":
        problem = readonly_init_problem(init)
        if problem:
            status, reason = "env_error", f"자식 환경: {problem}"
    tokens = token_record(result)
    return ChildResult(
        runtime="claude-code", status=status, reason=reason, exit_code=code, final_text=final_text(events, result),
        calls=normalize_calls(events), readonly_tools=READONLY_NORMALIZED, init=init, tokens=tokens,
        tie_tokens=tokens["total"], cost_usd=result_cost(result), model=init_model(events),
        elapsed_s=elapsed, events_path=events_path, stderr_path=stderr_path, env_stripped=stripped, auth_keys=auth_keys,
        cost_basis=cost_basis(result))
