"""OpenCode Jira 읽기 관문: 사용자 설정 + 사내 확인 통과 기록 (MODULE_SKILLS_DECISIONS "OpenCode Jira 읽기(11/05)").

관문(`state`)은 아래가 모두 맞을 때만 열린다. 하나라도 어긋나면 닫힘이고, `oc_adapter`는 Jira MCP 도구를 모두 거부한다.

1. 사용자 config(`~/.telephony-triage/config.yaml`) `opencode.jira_read: open`. site-defaults로는 열 수 없다(사용자 값만 본다).
   사용자가 터미널에서 `config.py set opencode.jira_read open`으로 쓴다. OpenCode 안에서는 `oc_adapter`가 그 명령, 사용자
   config·통과 기록 편집(edit·write·apply_patch), 그 파일을 가리키는 플러그인 스크립트 인자(`--out` 등)를 거부하고, `config.py`도
   `TT_RUNTIME=opencode`면 거부한다.
2. 통과 기록(`<사용자 홈>/opencode-jira-check.json`, `record_path`)이 있고 성공 경로가 통과(`passed: true`)다. 기록은
   `tools/site_step.py runtime-check opencode --jira`(모델 토큰 0 — 가짜 모델 서버로 실제 opencode와 실제 Jira MCP를 거친다)가 쓴다.
3. 기록의 OpenCode 버전이 `oc_adapter.OPENCODE_VERSION`과 같고, 기록의 플러그인 스크립트 지문(`scripts_digest`)이 지금 플러그인과
   같다(플러그인을 갱신하면 다시 확인해야 열린다).
4. 기록의 오류 경로 행이 `pass`가 아니면 — `warn`(오류 본문이 모델에 갔다)이거나 `skip`(`--missing-key` 없이 돌려 확인하지
   않았다, 건너뛴 확인은 통과가 아니다) — `opencode.jira_read_accept_error_bodies: true`(`set`의 `--accept-error-bodies`)도 있어야 한다.

이 판정은 OpenCode가 시작할 때 한 번만 한다(tt-guard.js → `oc_adapter.py gate` → 이후 adapter 호출 환경
`TT_OC_JIRA_SESSION_GATE`). 세션 중에 쓰인 파일은 그 세션의 도구 호출에 쓰이지 않는다(`oc_adapter.jira_gate_state`).

코멘트 쓰기(`tracker.write_tools.add_comment`)는 이 관문과 무관하게 OpenCode v1에서 늘 거부한다(`oc_adapter.before`).
테스트는 `TT_OC_JIRA_GATE=open`(oc_adapter `JIRA_GATE_ENV`)으로 연다 — 모델은 그 프로세스 환경을 바꾸지 못한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SETTING = "opencode.jira_read"
ACCEPT_SETTING = "opencode.jira_read_accept_error_bodies"
OPEN, CLOSED = "open", "closed"
VALUES = (OPEN, CLOSED)
RECORD_NAME = "opencode-jira-check.json"
RECORD_SCHEMA = 1
ERROR_ROW = "error-path"          # 오류 경로 행 이름(통과 기록 checks[]): pass | warn | skip
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
CHECK_COMMAND = ("python3 tools/site_step.py runtime-check opencode --project <설치 폴더> --jira <있는 티켓 키> "
                 "--missing-key <없는 티켓 키>")


def record_path() -> Path:
    from common import userconfig
    return userconfig.home() / RECORD_NAME


def scripts_digest(plugin_root: Path | str = PLUGIN_ROOT) -> str:
    """플러그인 스크립트(`scripts/**/*.py`) 전체의 지문. `tools/gen_opencode.py`·`opencode/bin/tt-oc` `scripts_digest`와 같은 계산."""
    h = hashlib.sha256()
    base = Path(plugin_root) / "scripts"
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in p.parts or not p.is_file():
            continue
        h.update(f"{p.relative_to(base).as_posix()}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_record(path: Path | None = None) -> tuple[dict | None, str | None]:
    """(기록, 읽지 못한 사유). 파일이 없으면 (None, None)."""
    path = path or record_path()
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path}: 읽지 못함({type(exc).__name__})"
    if not isinstance(data, dict) or data.get("schema") != RECORD_SCHEMA:
        return None, f"{path}: 형식이 다르다(schema {RECORD_SCHEMA} 아님)"
    return data, None


def write_record(record: dict, path: Path | None = None) -> Path:
    from common import userconfig
    path = path or record_path()
    userconfig.ensure_private_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    try:
        tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(tmp, path)
    return path


def error_row(record: dict | None) -> str | None:
    """통과 기록의 오류 경로 행 상태(pass | warn | skip), 없으면 None."""
    for row in (record or {}).get("checks") or []:
        if isinstance(row, dict) and row.get("check") == ERROR_ROW:
            return str(row.get("status"))
    return None


def needs_accept(record: dict | None) -> bool:
    """열 때 `--accept-error-bodies`가 필요한가: 오류 경로 행이 pass가 아니면(warn·skip·없음) 그렇다."""
    return error_row(record) != "pass"


def record_problems(record: dict | None, *, opencode_version: str | None = None,
                    plugin_root: Path | str = PLUGIN_ROOT, digest: str | None = None) -> list[str]:
    """통과 기록이 지금 환경에서 관문을 열 수 있는지: 문제 목록(비면 맞다)."""
    if record is None:
        return ["사내 확인 통과 기록이 없다"]
    if opencode_version is None:
        from common import oc_adapter
        opencode_version = oc_adapter.OPENCODE_VERSION
    out = []
    if record.get("passed") is not True:
        out.append("마지막 사내 확인이 통과하지 않았다(성공 경로 실패)")
    if record.get("opencode_version") != opencode_version:
        out.append(f"기록의 OpenCode 버전 {record.get('opencode_version') or '?'} ≠ {opencode_version}")
    try:
        digest = digest or scripts_digest(plugin_root)
    except OSError:
        digest = "?"
    if record.get("scripts_sha") != digest:
        out.append("플러그인 스크립트가 확인 뒤 바뀌었다(지문 불일치)")
    return out


def summary(record: dict | None) -> str:
    """doctor·안내용 한 줄(내용 없음): 시각·통과·버전·서버·행 상태."""
    if not record:
        return "사내 확인 기록 없음"
    rows = ", ".join(f"{r.get('check')} {r.get('status')}" for r in record.get("checks") or [] if isinstance(r, dict))
    return (f"마지막 확인 {record.get('at') or '?'} {'통과' if record.get('passed') else '실패'} "
            f"(opencode {record.get('opencode_version') or '?'}, 서버 {record.get('jira_server') or '?'}"
            + (f"; {rows}" if rows else "") + ")")


def short_summary(record: dict | None) -> str:
    """doctor 행(80자)용: `확인 <날짜 시각> 통과|실패, 오류 경로 <행>`."""
    if not record:
        return "확인 기록 없음"
    at = str(record.get("at") or "?")[:16].replace("T", " ")
    return f"확인 {at} {'통과' if record.get('passed') else '실패'}, 오류 경로 {error_row(record) or '없음'}"


@dataclass
class GateState:
    open: bool
    setting: str                       # open | closed | (그 밖 값은 그대로 — 닫힘)
    accepted: bool = False             # opencode.jira_read_accept_error_bodies
    problems: list[str] = field(default_factory=list)
    record: dict | None = None


def user_setting(user: dict | None) -> tuple[str, bool]:
    from common import userconfig
    user = user or {}
    raw = userconfig.get(user, SETTING, CLOSED)
    return (str(raw) if raw is not None else CLOSED), userconfig.get(user, ACCEPT_SETTING, False) is True


def state(user: dict | None = None, *, plugin_root: Path | str = PLUGIN_ROOT, opencode_version: str | None = None,
          record_file: Path | None = None) -> GateState:
    """사용자 config(없으면 읽는다)와 통과 기록으로 관문 상태. 읽기 오류는 닫힘 + 문제."""
    if user is None:
        from common import userconfig
        try:
            user = userconfig.load_user() or {}
        except Exception as exc:  # noqa: BLE001 — 설정을 못 읽으면 닫힘
            return GateState(False, CLOSED, problems=[f"사용자 config를 읽지 못함({type(exc).__name__})"])
    setting, accepted = user_setting(user)
    record, err = load_record(record_file)
    problems = [err] if err else []
    if setting != OPEN:
        return GateState(False, setting, accepted, problems, record)
    problems += record_problems(record, opencode_version=opencode_version, plugin_root=plugin_root) if not err else []
    if not problems and needs_accept(record) and not accepted:
        problems.append(f"오류 경로 행이 {error_row(record) or '없음'}(pass 아님)인데 --accept-error-bodies로 받아들이지 않았다")
    return GateState(not problems, setting, accepted, problems, record)


def open_command(plugin_root: Path | str = PLUGIN_ROOT, accept: bool = False) -> str:
    return (f"python3 {Path(plugin_root) / 'scripts' / 'config.py'} set {SETTING} {OPEN}"
            + (" --accept-error-bodies" if accept else ""))
