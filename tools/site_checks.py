"""사내 보완 S 단계 자동 점검 (읽기 전용, `site_step.py check`가 부른다. 15-local-draft.md §15.5).

- `CHECKS[S-n]`의 함수마다 `fn(ctx) -> {id, status, evidence, cmd, ask?, propose?}`. status는
  pass | fail | skip(실행 못 함, 사유·ask) | needs-user(사람 정보·판단 필요) | info(판정 아님).
- 판정 근거(evidence)는 개수·종료 코드·파일:행만. 로그·Jira 원문은 넣지 않는다.
- 쓰지 않는다: 사용자 이슈 DB clone은 읽기 전용 임시 clone(`git clone --no-local --no-checkout` → 원본의 origin/main, 없으면 로컬 main)으로만 보고 fetch·브랜치 전환·lock 없음.
  골든 변조 시험은 임시 복사본에서만 한다. `claude`는 `--allow-api`일 때만 부른다.
- 한 점검이 예외를 내면 그 점검만 fail이고 나머지는 계속한다(doctor 방식).
- 사내 값은 코드에 없다: 입력은 `docs/site/steps.yaml`(`propose --apply`로만 씀)·`SITE_PROFILE.md`·사내 파일에서 읽는다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
STATUSES = ("pass", "fail", "skip", "needs-user", "info")
OK_STATUSES = ("pass", "info")

STEPS_FILE = "docs/site/steps.yaml"
EVIDENCE_FILE = "docs/site/evidence.md"
STEP_STATE_DIR = "docs/site/steps"
SITE_BASELINE = "tests/site/token_baseline.json"
EVAL_DIR = "tests/skill_evals"
EVAL_WORKSPACE_PREFIX = "site-s2-"
OFFSITE_FILE = EVAL_DIR + "/offsite_results.json"
BASELINE_EVALS = [1, 2, 39, 45, 58]     # 사내 토큰 기준선(T4) eval — pending.json site의 부분집합이어야 한다(s2.pending)
PROFILE = "SITE_PROFILE.md"
PROFILE_LIMIT = 4096
# steps.yaml에 둘 수 있는 입력(값은 사용자가 준다)
STEP_INPUTS = {
    "ops_db": "운영 이슈 DB clone 경로(읽기 전용, 점검은 임시 clone에서)",
    "ops_db_repo": "운영 이슈 DB GHE 저장소 owner/repo (gh api·pr list 읽기)",
    "sandbox_repo": "S-5 샌드박스 이슈 DB owner/repo",
    "ghe_host": "gh --hostname 값(기본 호스트면 비움)",
    "labelset": "S-5 최종 확인용 라벨셋 경로(기본 tests/site/offline-eval.yaml)",
    "eval_budget_usd": "S-2 eval 전체 예산(USD)",
    "jira_raw_dir": "S-3 jira_fields extract 확인용 저장 raw 디렉토리(마스킹본)",
    "platforms": "S-7 usage_stats 대상 플랫폼 목록",
    "eval_model": "S-2 eval·토큰 기준선 모델 ID(run.py --model)",
}
GATE_RE = re.compile(r"(?m)^- S-5 게이트: top1 ≥ ([0-9.]+), error_rate ≤ ([0-9.]+) \((\d{4}-\d{2}-\d{2}) 합의\)\s*$")
REVIEW_ROW_RE = re.compile(r"(?m)^\|\s*(R\d+)\s*\|")
PLACEHOLDER_RE = re.compile(r"(?m)^\s*reason:\s*['\"]?placeholder\b")
SYNTHETIC_RE = re.compile(r"(?m)^\s*origin:\s*['\"]?synthetic\b")
PILOT_FIELDS = ("처리 건수", "오탐", "누락", "충돌", "온보딩", "PR 소요", "취소 비율")


class CloneUnavailable(Exception):
    """임시 clone은 됐지만 점검할 main이 없다(건너뜀 + 물을 것)."""


@dataclass
class Ctx:
    root: Path
    allow_api: bool = False
    timeout: int = 600
    _tmp: list = field(default_factory=list)
    _clone: Path | None = None
    clone_ref: str = ""
    used_clone: bool = False

    @property
    def profile(self) -> str:
        p = self.root / PROFILE
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    @property
    def inputs(self) -> dict:
        return load_inputs(self.root)

    def run(self, cmd: list[str], cwd: Path | None = None, timeout: int | None = None,
            env: dict | None = None) -> tuple[int, str, str]:
        """자식은 새 프로세스 그룹에서 돌리고 시간 초과면 그룹째 끝낸다(claude mcp list가 띄운 MCP 서버 포함).
        자식 Python은 바이트코드를 쓰지 않는다(레포에 __pycache__를 남기지 않게)."""
        env = dict(os.environ if env is None else env, PYTHONDONTWRITEBYTECODE="1")
        try:
            p = subprocess.Popen(cmd, cwd=cwd or self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", env=env,
                                 start_new_session=True)
        except FileNotFoundError:
            return 127, "", f"{cmd[0]} 없음"
        try:
            out, err = p.communicate(timeout=timeout or self.timeout)
            return p.returncode, out, err
        except subprocess.TimeoutExpired:
            self._kill(p)
            return 124, "", "시간 초과"
        except BaseException:          # KeyboardInterrupt 등: 자식 그룹을 정리하고 다시 올린다
            self._kill(p)
            raise

    @staticmethod
    def _kill(p: subprocess.Popen) -> None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            p.kill()
        try:
            p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass              # 파이프를 쥔 손자가 남아도 더 기다리지 않는다

    def py(self, script: str, *args: str, timeout: int | None = None) -> tuple[int, str, str]:
        return self.run([sys.executable, str(self.root / script), *args], timeout=timeout)

    def tmpdir(self) -> Path:
        d = Path(tempfile.mkdtemp(prefix="site-check-"))
        self._tmp.append(d)
        return d

    def ops_clone(self) -> Path | None:
        """운영 이슈 DB의 읽기 전용 임시 clone. 원본에는 fetch·전환·쓰기를 하지 않는다(clone·fetch는 로컬 경로를 읽기만 한다).
        임시 clone의 `origin/*`은 원본의 **로컬** 브랜치이므로, 원본의 `refs/remotes/origin/main`(마지막 fetch 시점의 원격 main)을
        `src/main`으로 가져와 그것을 본다. 없으면 원본 로컬 main. 근거에 넣을 `clone_ref`를 남긴다."""
        self.used_clone = True
        if self._clone is not None:
            return self._clone
        src = self.inputs.get("ops_db")
        if not src or not (Path(str(src)).expanduser() / ".git").exists():
            return None
        src = str(Path(str(src)).expanduser())
        dst = self.tmpdir() / "ops-db"
        env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
        code, _, err = self.run(["git", "clone", "--quiet", "--no-local", "--no-hardlinks", "--no-checkout", src, str(dst)],
                                timeout=300, env=env)
        if code:
            raise RuntimeError(f"임시 clone 실패(종료 {code}): {err.strip()[:120]}")
        self.run(["git", "-C", str(dst), "fetch", "--quiet", "--no-tags", src,
                  "+refs/remotes/origin/main:refs/remotes/src/main"], timeout=300, env=env)
        for ref, label in (("src/main", "사용자 clone의 origin/main@{}(마지막 fetch)"),
                           ("origin/main", "사용자 clone의 로컬 main@{}")):
            if self.run(["git", "-C", str(dst), "checkout", "-q", "--detach", ref], timeout=120, env=env)[0] == 0:
                sha = self.run(["git", "-C", str(dst), "rev-parse", "--short", "HEAD"], timeout=30)[1].strip()
                self.clone_ref = label.format(sha)
                self._clone = dst
                return dst
        raise CloneUnavailable("운영 DB clone에 origin/main도 로컬 main도 없다")

    def gh(self, *args: str) -> tuple[int, str, str]:
        """모든 gh 호출에 GH_HOST(steps.yaml `ghe_host`)를 준다(auth status·pr list·api 공통)."""
        host = self.inputs.get("ghe_host")
        env = dict(os.environ, GH_PROMPT_DISABLED="1", **({"GH_HOST": str(host)} if host else {}))
        return self.run(["gh", *args], timeout=60, env=env)

    def cleanup(self) -> None:
        for d in self._tmp:
            shutil.rmtree(d, ignore_errors=True)
        self._tmp.clear()
        self._clone = None


def load_inputs(root: Path) -> dict:
    p = root / STEPS_FILE
    if not p.is_file():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    # 값은 한 줄이다(명령 인자·근거 줄에 들어간다): 손으로 넣은 줄바꿈은 공백으로 바꾼다
    return {k: " ".join(v.split()) if isinstance(v, str) else v for k, v in data.items()}


def res(cid: str, status: str, evidence: str, cmd: str | None = None, ask: str | None = None,
        propose: list[dict] | None = None) -> dict:
    assert status in STATUSES, status
    out = {"id": cid, "status": status, "evidence": evidence, "cmd": cmd}
    if ask:
        out["ask"] = ask
    if propose:
        out["propose"] = propose
    return out


def row_item(pid: str, num: str, item: str, value: str, basis: str) -> dict:
    """SITE_PROFILE.md 확인값 행 제안(적용은 `propose --apply`, 확인자·날짜는 그때 채운다)."""
    return {"id": pid, "kind": "profile-row", "num": num, "item": item, "value": value, "basis": basis}


def gate(profile: str) -> tuple[float, float, str] | None:
    m = GATE_RE.search(profile)
    return (float(m.group(1)), float(m.group(2)), m.group(3)) if m else None


def profile_rows(profile: str) -> list[list[str]]:
    """'## 확인값' 표의 행(머리·구분 줄 제외) 셀 목록."""
    sec = profile.split("## 확인값", 1)[1].split("\n## ", 1)[0] if "## 확인값" in profile else ""
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in sec.splitlines() if ln.startswith("|")]
    return [r for r in rows[2:] if r and r[0]]


def review_open_ids(root: Path) -> list[str] | None:
    p = root / "REVIEW-OPEN.md"
    return REVIEW_ROW_RE.findall(p.read_text(encoding="utf-8")) if p.is_file() else None


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or [""])[0][:120]


# --- S-1 ----------------------------------------------------------------------------------------------------

def s1_env(ctx: Ctx) -> dict:
    os_name = ""
    osr = Path("/etc/os-release")
    if osr.is_file():
        m = re.search(r'(?m)^PRETTY_NAME="?([^"\n]*)', osr.read_text(encoding="utf-8", errors="replace"))
        os_name = m.group(1) if m else ""
    pyv = ".".join(map(str, sys.version_info[:3]))
    _, gitv, _ = ctx.run(["git", "--version"], timeout=20)
    gitv = gitv.strip().removeprefix("git version ").strip()
    libyaml = bool(getattr(yaml, "__with_libyaml__", False))
    code, pipc, _ = ctx.run([sys.executable, "-m", "pip", "config", "list"], timeout=60)
    pip_keys = sorted({ln.split("=", 1)[0] for ln in pipc.splitlines() if "=" in ln}) if code == 0 else []
    ev = (f"OS {os_name or '?'} · python {pyv} · git {gitv or '?'} · PyYAML libyaml {libyaml} · "
          f"pip config {len(pip_keys)}키{(' (' + ', '.join(pip_keys) + ')') if pip_keys else ''}")
    props = [row_item("S15.os", "S15", "OS", os_name or "?", "/etc/os-release"),
             row_item("S15.python", "S15", "python3", pyv, "sys.version"),
             row_item("S15.git", "S15", "git", gitv or "?", "git --version"),
             row_item("S15.pip", "S15", "pip 설정 키", ", ".join(pip_keys) or "없음", "pip config list")]
    return res("s1.env", "info", ev, "python3 -m pip config list; git --version", propose=props)


def s1_python(ctx: Ctx) -> dict:
    ok = sys.version_info[:2] >= (3, 10)
    return res("s1.python", "pass" if ok else "fail", ".".join(map(str, sys.version_info[:3])) + " (3.10+ 필요, S15)",
               f"{sys.executable} --version")


def _remote_host_org(url: str) -> str | None:
    """origin URL의 `호스트[:포트]/org`. https·ssh URL은 포트를 호스트에 남기고, scp 형식(`git@host:org/repo`)은 `:` 뒤가 경로다."""
    url = url.strip()
    m = re.match(r"[a-z][a-z0-9+.-]*://(?:[^@/]+@)?([^/]+)/([^/]+)/", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.match(r"(?:[^@/]+@)?([^/:]+):([^/]+)/", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def s1_ghe(ctx: Ctx) -> dict:
    code, out, err = ctx.run(["gh", "auth", "status"], timeout=30)
    rc, url, _ = ctx.run(["git", "-C", str(ctx.root), "remote", "get-url", "origin"], timeout=20)
    hostorg = _remote_host_org(url) if rc == 0 else None
    hosts = sorted(set(re.findall(r"Logged in to (\S+)", out + err)))
    ev = f"gh auth status 종료 {code}" + (f" (호스트 {', '.join(hosts)})" if hosts else "") + \
         f" · origin {hostorg or '없음'}"
    props = [row_item("S5.remote", "S5", "GHE 호스트/org", hostorg, "git remote get-url origin")] if hostorg else None
    if code == 127:
        return res("s1.ghe", "needs-user", ev, "gh auth status", ask="gh CLI가 없다 — 설치 가능 여부(S5)를 알려 주세요",
                   propose=props)
    return res("s1.ghe", "info", ev, "gh auth status; git remote get-url origin", propose=props)


def s1_claude(ctx: Ctx) -> dict:
    if not ctx.allow_api:
        return res("s1.claude", "info", "미실행(--allow-api 없음): claude --version·claude mcp list(MCP 서버 연결 확인, Jira MCP 포함·데이터 없음)는 S-2에서",
                   "claude --version; claude mcp list")
    return _claude_info(ctx, "s1.claude")


def _claude_info(ctx: Ctx, cid: str) -> dict:
    code, ver, _ = ctx.run(["claude", "--version"], timeout=60)
    mcode, mcp, _ = ctx.run(["claude", "mcp", "list"], timeout=120)
    names = sorted({m.group(1) for m in re.finditer(r"(?m)^([\w.@-]+):\s", mcp)}) if mcode == 0 else []
    return res(cid, "info", f"claude --version 종료 {code} ({_first_line(ver) or '?'}) · MCP 서버 {len(names)}개"
               + (f" ({', '.join(names)})" if names else ""), "claude --version; claude mcp list")


def s1_todos(ctx: Ctx) -> dict:
    sys.path.insert(0, str(TOOLS))
    import list_site_todos
    found = list_site_todos.scan(ctx.root.resolve())
    total = sum(map(len, found.values()))
    ev = f"TODO(SITE) {total}곳: " + (", ".join(f"{k} {len(v)}" for k, v in found.items()) or "없음")
    return res("s1.todos", "info", ev, "python3 tools/list_site_todos.py")


def s1_review_open(ctx: Ctx) -> dict:
    return _review_open(ctx, "s1.review_open")


def _review_open(ctx: Ctx, cid: str) -> dict:
    ids = review_open_ids(ctx.root)
    if ids is None:
        return res(cid, "needs-user", "REVIEW-OPEN.md 없음", "cat REVIEW-OPEN.md",
                   ask="REVIEW-OPEN.md가 없다 — 반입본에서 빠졌는지 확인해 주세요(사외 파일)")
    prof = ctx.profile
    missing = [i for i in ids if not re.search(rf"(?<![\w-]){i}(?!\d)", prof)]
    if missing:
        return res(cid, "fail", f"REVIEW-OPEN {len(ids)}건 중 SITE_PROFILE.md에 처리·보류 기록 없음 {len(missing)}건: "
                   + ", ".join(missing), "grep -n 'R[0-9]' SITE_PROFILE.md",
                   ask=f"{', '.join(missing)}의 처리 방식 또는 보류 사유를 정해 주세요")
    return res(cid, "pass", f"REVIEW-OPEN {len(ids)}건 모두 SITE_PROFILE.md에 기록", "grep -n 'R[0-9]' SITE_PROFILE.md")


def s1_profile(ctx: Ctx) -> dict:
    p = ctx.root / PROFILE
    if not p.is_file():
        return res("s1.profile", "fail", "SITE_PROFILE.md 없음", "python3 tools/site_step.py")
    size, text = p.stat().st_size, ctx.profile
    lines = [k for k in ("- 모드:", "- 현재 단계:", "- 완료 단계:") if k not in text]
    if size > PROFILE_LIMIT or lines:
        return res("s1.profile", "fail", f"{size}B (상한 {PROFILE_LIMIT}), 빠진 진행 줄 {lines or '없음'}", "wc -c SITE_PROFILE.md")
    return res("s1.profile", "pass", f"{size}B ≤ {PROFILE_LIMIT}, 진행 상태 줄 있음", "wc -c SITE_PROFILE.md")


def s1_gate(ctx: Ctx) -> dict:
    g = gate(ctx.profile)
    if g is None:
        return res("s1.gate", "needs-user", "SITE_PROFILE.md에 `- S-5 게이트: top1 ≥ …, error_rate ≤ … (YYYY-MM-DD 합의)` 줄 없음",
                   "grep -n 'S-5 게이트' SITE_PROFILE.md",
                   ask="S-5 게이트 기준치(1위 정확도 하한·오류율 상한)를 정해 주세요 → "
                       "`site_step.py propose --set gate.top1=<값> --set gate.error_rate=<값>`")
    return res("s1.gate", "pass", f"top1 ≥ {g[0]}, error_rate ≤ {g[1]} ({g[2]} 합의)", "grep -n 'S-5 게이트' SITE_PROFILE.md")


SAMPLE_ROWS = {"S4": "샘플 Jira 키 2~3개", "S7": "카테고리별 logcat 경로", "S11": "Android 16/17 소스 트리 경로",
               "S12": "빌드명 예시"}


def s1_samples(ctx: Ctx) -> dict:
    have = {r[0] for r in profile_rows(ctx.profile)}
    missing = [k for k in SAMPLE_ROWS if k not in have]
    if missing:
        return res("s1.samples", "needs-user", f"확인값 행 없음: {', '.join(missing)}", "SITE_PROFILE.md ## 확인값",
                   ask="자료를 주세요: " + "; ".join(f"{k} {SAMPLE_ROWS[k]}" for k in missing)
                       + " → `propose --set \"row.<S#>.<항목>=<값>\"`")
    return res("s1.samples", "pass", "S4·S7·S11·S12 행 있음", "SITE_PROFILE.md ## 확인값")


# --- S-2 ----------------------------------------------------------------------------------------------------

def _grade_module():
    """tests/skill_evals/grade.py를 고유 모듈 이름으로 읽는다(`import grade`는 같은 이름 모듈과 sys.modules에서 겹칠 수 있다).
    쓰는 공개 값: safety_failures·safety_undecided·is_safety_eval·TOKEN_BUDGET_TEXT."""
    name = "tt_site_checks_grade"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / EVAL_DIR / "grade.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


def eval_entries(root: Path) -> list[dict]:
    return json.loads((root / EVAL_DIR / "evals.json").read_text(encoding="utf-8"))["evals"]


def load_pending(root: Path) -> dict:
    """`pending.json`(사내 S-2 대상의 단일 출처)을 정규화한다: site·site_if_model_differs는 {id: 사유}, manual은 [id].
    파일이 없거나 site가 비면 site {}(→ `s2.pending` 실패. 전체 실행으로 되돌아가지 않는다)."""
    p = root / EVAL_DIR / "pending.json"
    raw = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    raw = raw if isinstance(raw, dict) else {}

    def ids(v) -> dict[int, str]:
        if isinstance(v, dict):
            return {int(k): str(r) for k, r in v.items()}
        return {int(k): "" for k in v} if isinstance(v, list) else {}

    return {"site": ids(raw.get("site")), "site_if_model_differs": ids(raw.get("site_if_model_differs")),
            "manual": [int(i) for i in raw.get("manual") or []], "offsite": raw.get("offsite") or OFFSITE_FILE,
            "note": raw.get("note") or ""}


def site_ids(root: Path) -> list[int]:
    return sorted(load_pending(root)["site"])


def load_offsite(root: Path) -> dict | None:
    """사외 결과 기록(`tests/skill_evals/offsite.py`가 만든다). 없거나 읽을 수 없으면 None."""
    p = root / load_pending(root)["offsite"]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("evals"), dict) else None


def _norm_model(m) -> str:
    return re.sub(r"\[[^\]]*\]$", "", str(m)).strip() if m else ""


def site_models(root: Path, state: dict[int, dict] | None = None) -> list[str]:
    """사내 eval 모델: steps.yaml `eval_model`과 사내 반복(`site-s2-*`)의 **모든** run의 init_model(없으면 execution.json `model`).
    eval마다 마지막 run만이 아니라 모든 run을 본다(한 run이라도 다른 모델이면 다르다)."""
    ms = {_norm_model(load_inputs(root).get("eval_model"))}
    for it in site_iterations(root):
        for ex_p in it.glob("eval-*/with_skill/execution.json"):
            try:
                ex = json.loads(ex_p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if ex.get("status") != "prepared":
                ms.add(_norm_model(ex.get("init_model") or ex.get("model")))
    ms |= {_norm_model(s.get("model")) for s in (state or {}).values()}
    return sorted(m for m in ms if m)


def model_differs(root: Path, state: dict[int, dict] | None = None) -> tuple[bool | None, str, str]:
    """(사내 모델이 사외 결과 모델과 다른가, 사외 모델, 사내 모델).
    - 사외 기록이 없으면 True(갈음할 근거 없음).
    - 사내 모델을 아직 모르면(eval_model·사내 run 모델 없음) None: 조건부 eval을 빼지도 넣지도 않고 점검이 "사내 모델 미정"으로 묻는다.
    - 비교는 끝의 `[...]`(컨텍스트 창 표기)만 떼고 문자열이 같아야 같다. 날짜 접미사·별칭 등 다른 차이는 모두 다름(fail-closed)."""
    off = load_offsite(root)
    off_m = _norm_model(off.get("model")) if off else ""
    site = site_models(root, state)
    site_s = "/".join(site) or "미정"
    if not off_m:
        return True, "없음", site_s
    if not site:
        return None, off_m, site_s
    return any(m != off_m for m in site), off_m, site_s


def required_ids(root: Path, state: dict[int, dict]) -> list[int]:
    """사내 S-2에서 실행·채점해야 하는 eval: site + (모델이 다르면) site_if_model_differs. 사내 모델 미정이면 조건부는 아직 넣지 않는다
    (그 경우 s2.evals_graded·s2.safety가 사용자 필요로 막는다)."""
    pend = load_pending(root)
    req = set(pend["site"])
    if model_differs(root, state)[0] is True:
        req |= set(pend["site_if_model_differs"])
    return sorted(req & set(state))     # evals.json에 없는 id는 s2.pending이 실패로 본다


def _model_unknown(root: Path, state: dict[int, dict]) -> str | None:
    """사내 모델 미정이고 조건부 eval이 있으면 그 설명(사용자 필요), 아니면 None."""
    cond = sorted(load_pending(root)["site_if_model_differs"])
    if cond and model_differs(root, state)[0] is None:
        return f"사내 모델 미정 — 사외 결과 모델과 다르면 조건부 eval {_ids(cond)}도 사내 필수"
    return None


def site_iterations(root: Path) -> list[Path]:
    ws = root / EVAL_DIR / "workspace"
    return sorted(d for d in ws.glob(EVAL_WORKSPACE_PREFIX + "*") if d.is_dir()) if ws.is_dir() else []


def _run_dir(it: Path, eid: int, name: str | None) -> Path:
    cands = [it / f"eval-{eid}-{name}", it / f"eval-{eid}"]
    return next((c for c in cands if c.is_dir()), cands[-1]) / "with_skill"


def eval_state(root: Path) -> dict[int, dict]:
    """eval id → 사내 S-2 반복(`workspace/site-s2-*`) 중 마지막 결과. 실행 기록이 없으면 status `none`."""
    grade = _grade_module()
    entries = eval_entries(root)
    state = {e["id"]: {"status": "none", "iteration": None, "cost": None} for e in entries}
    for it in site_iterations(root):
        for e in entries:
            run = _run_dir(it, e["id"], e.get("name"))
            ex_p, gr_p = run / "execution.json", run / "grading.json"
            if not ex_p.is_file() and not gr_p.is_file():
                continue
            ex = json.loads(ex_p.read_text(encoding="utf-8")) if ex_p.is_file() else {}
            if ex.get("status") == "prepared":
                continue
            st = {"status": "ungraded", "iteration": it.name, "exec": ex.get("status"),
                  "cost": ex.get("total_cost_usd"), "init_model": ex.get("init_model"),
                  "model": ex.get("init_model") or ex.get("model")}
            if gr_p.is_file():
                g = json.loads(gr_p.read_text(encoding="utf-8"))
                rows = g.get("expectations") or []
                st.update(status=g.get("status"), passed=sum(r.get("passed") is True for r in rows),
                          failed=sum(r.get("passed") is False for r in rows),
                          undecided=sum(r.get("passed") is None for r in rows),
                          safety_fail=grade.safety_failures(e["id"], e.get("batch"), rows),
                          safety_null=grade.safety_undecided(e["id"], e.get("batch"), rows),
                          null_rows=sum(r.get("passed") is None and r.get("text") != grade.TOKEN_BUDGET_TEXT for r in rows),
                          schema_reads=len((g.get("metrics") or {}).get("schema_reads") or []))
            state[e["id"]] = st
    return state


def s2_pending(ctx: Ctx) -> dict:
    ids = {e["id"] for e in eval_entries(ctx.root)}
    pend = load_pending(ctx.root)
    site, cond, manual = set(pend["site"]), set(pend["site_if_model_differs"]), set(pend["manual"])
    cmd = "tests/skill_evals/pending.json"
    if not site:     # 대상이 비면 통과로 보지 않는다(전체 실행으로 되돌아가지도 않는다)
        return res("s2.pending", "fail", "pending.json이 없거나 site(사내 대상)가 비었다", cmd)
    bad = sorted((site | cond | manual) - ids)
    if bad:
        return res("s2.pending", "fail", f"pending.json의 id가 evals.json에 없음: {bad}", cmd)
    problems = []
    if site & cond:
        problems.append(f"site와 site_if_model_differs가 겹침: {sorted(site & cond)}")
    if not manual <= site:
        problems.append(f"manual이 site 밖: {sorted(manual - site)}")
    if not set(BASELINE_EVALS) <= site:
        problems.append(f"기준선 eval이 site 밖: {sorted(set(BASELINE_EVALS) - site)}")
    if problems:
        return res("s2.pending", "fail", " · ".join(problems), cmd)
    return res("s2.pending", "pass", f"사내 대상 {len(site)}/{len(ids)} · 조건부(모델 다를 때) {len(cond)} · 수동 "
               f"{sorted(manual)} · 기준선 ⊆ 사내", cmd)


def s2_graded(ctx: Ctx) -> dict:
    st = eval_state(ctx.root)
    req = required_ids(ctx.root, st)
    missing = [i for i in req if st.get(i, {}).get("status") != "graded"]
    differs, off_m, site_m = model_differs(ctx.root, st)
    scope = f"사내 대상 {len(req)}/{len(st)}" + (f"(모델 다름 사외 {off_m} / 사내 {site_m}: 조건부 포함)"
                                                  if differs and load_pending(ctx.root)["site_if_model_differs"] else "")
    cmd = "python3 tools/site_step.py evals"
    if not req:
        return res("s2.evals_graded", "fail", "사내 대상 eval이 없다(s2.pending)", "tests/skill_evals/pending.json")
    if missing:     # 아직 돌리지 않은 것은 고칠 결함이 아니라 할 일이다(실행·채점 뒤 다시 점검)
        return res("s2.evals_graded", "needs-user", f"{scope} 중 채점 완료 {len(req) - len(missing)}, 남음 "
                   f"{len(missing)}: " + _ids(missing), cmd,
                   ask="eval 배치 실행 비용을 승인해 주세요(`site_step.py evals`가 명령·추정 비용을 낸다)")
    unknown = _model_unknown(ctx.root, st)
    if unknown:     # 조건부를 빼고 통과로 두지 않는다(fail-closed)
        return res("s2.evals_graded", "needs-user", f"{scope} 모두 채점 · {unknown}", cmd,
                   ask="사내 eval 모델을 알려 주세요(`propose --set eval_model=<ID>` → --apply). 사외와 다르면 조건부 eval도 돌린다")
    return res("s2.evals_graded", "pass", f"{scope} 모두 채점(graded) · 나머지는 사외 결과(s2.offsite)", cmd)


def _offsite_latest(entry: dict) -> list[dict]:
    """사외 기록 한 eval의 verdict_commit run들(없으면 마지막 run의 커밋)."""
    runs = (entry or {}).get("runs") or []
    if not runs:
        return []
    commit = entry.get("verdict_commit", runs[-1].get("repo_commit"))
    return [r for r in runs if r.get("repo_commit") == commit]


def _short(sha) -> str:
    return str(sha)[:8] if sha else "?"


def _head(root: Path) -> str:
    try:
        p = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def s2_offsite(ctx: Ctx) -> dict:
    """사내 대상 밖 eval을 갈음하는 사외 결과 기록. 모두 pass일 때만 정보이고, fail·undecided·none이 있으면 사용자 필요
    (사용자가 사유와 함께 `--waive s2.offsite=…`로 받아들이거나 사외에서 다시 잰다)."""
    st = eval_state(ctx.root)
    off = load_offsite(ctx.root)
    path = load_pending(ctx.root)["offsite"]
    if off is None:
        return res("s2.offsite", "needs-user", f"사외 결과 기록 없음: {path}", f"cat {path}",
                   ask="사외 결과 기록(offsite_results.json)을 반입본에 넣어 주세요(사외 PC: `python3 tests/skill_evals/offsite.py "
                       "<iteration>... --out tests/skill_evals/offsite_results.json`)")
    req = set(required_ids(ctx.root, st))
    in_house = sorted(i for i in st if i not in req and st[i]["status"] == "graded")   # 사내 채점이 사외 기록을 대신한다
    rest = _offsite_covered(ctx.root, st, req)
    verdict = {i: (off["evals"].get(str(i)) or {}).get("verdict") or "none" for i in rest}
    groups = {v: [i for i in rest if verdict[i] == v] for v in ("pass", "fail", "undecided", "none")}
    differs, off_m, site_m = model_differs(ctx.root, st)
    commits = sorted({_short(r.get("repo_commit")) for i in rest for r in _offsite_latest(off["evals"].get(str(i)))})
    note = str(off.get("note") or "")
    head = ("잠정 · " if re.search(r"provisional|잠정", note, re.I) else "") + \
        (f"모델 다름(사외 {off_m} / 사내 {site_m}) · " if differs else "") + \
        (f"사내 모델 미정(사외 {off_m}) · " if differs is None else "") + \
        f"사외 {off.get('model')}({off.get('generated')}) 갈음 {len(rest)}개: "
    body = " · ".join(f"{k} {len(v)}" + (f"({_ids(v, 15)})" if v and k != "pass" else "") for k, v in groups.items())
    body += f" · 사내 채점으로 대체 {len(in_house)}" + (f"({_ids(in_house, 15)})" if in_house else "")
    tail = (f" · 채점기 {_short(off.get('grader_commit'))} · 사외 run 커밋 {' '.join(commits) or '없음'} · "
            f"지금 HEAD {_short(_head(ctx.root))}")
    cmd = f"cat {path}"
    open_ = groups["fail"] + groups["undecided"] + groups["none"]
    if open_:
        return res("s2.offsite", "needs-user", head + body + tail, cmd,
                   ask=f"사외 결과가 pass가 아닌 eval {_ids(sorted(open_))}: 사외에서 다시 재고(실패·미결정 원인 확인, 수동 행 채점) "
                       "`offsite.py`로 offsite_results.json을 다시 만들거나, 그 eval을 사내에서 실행·채점하거나(사내 채점이 사외 기록을 "
                       "대신한다), 받아들일 사유를 `--waive s2.offsite=\"사유\"`로 남겨 주세요")
    return res("s2.offsite", "info", head + body + tail, cmd)


def _offsite_covered(root: Path, st: dict[int, dict], req: set[int]) -> list[int]:
    """사외 기록으로 갈음하는 eval: 사내 대상이 아니고 사내에서 채점하지도 않은 것(사내 채점이 있으면 그것이 대신한다)."""
    return sorted(i for i in st if i not in req and st[i]["status"] != "graded")


def _ids(ids: list[int], n: int = 25) -> str:
    return " ".join(map(str, ids[:n])) + (f" …(+{len(ids) - n})" if len(ids) > n else "")


def s2_safety(ctx: Ctx) -> dict:
    grade = _grade_module()
    st = eval_state(ctx.root)
    req = set(required_ids(ctx.root, st))
    batches = {e["id"]: e.get("batch") for e in eval_entries(ctx.root)}
    bad = {i: len(s["safety_fail"]) for i, s in st.items() if s.get("safety_fail")}   # 사내에서 채점한 것은 대상 밖이어도 본다
    off = load_offsite(ctx.root) or {"evals": {}}
    covered = _offsite_covered(ctx.root, st, req)      # 사내 채점이 있는 eval은 사외 기록을 보지 않는다(사내 결과가 대신한다)
    latest = {i: _offsite_latest(off["evals"].get(str(i))) for i in covered}
    off_bad = {i: n for i in covered if (n := sum(r.get("safety_fail") or 0 for r in latest[i]))}   # verdict 커밋 run의 위반
    off_null = {i: n for i in covered if (n := sum(r.get("safety_undecided") or 0 for r in latest[i]))}
    null = {i: s["safety_null"] for i, s in st.items() if s.get("safety_null")}
    safety_ids = [i for i in st if grade.is_safety_eval(i, batches[i])]
    site_safety = [i for i in safety_ids if i in req]
    offsite = [i for i in safety_ids if i in covered]
    open_ = [i for i in site_safety if st[i]["status"] != "graded"]
    note = f" · 사외 결과로 갈음한 안전 eval {len(offsite)}" + (f"({_ids(offsite, 15)}, s2.offsite)" if offsite else "")
    cmd = "python3 tools/site_step.py check S-2 --json"
    if bad or off_bad:
        rows = {i: sorted({t[:80] for r in latest[i] for t in r.get("safety_fail_rows") or []}) for i in off_bad}
        parts = ([f"사내 채점 {sum(bad.values())}행: eval {_ids(sorted(bad))}"] if bad else []) + \
            ([f"사외 기록 {sum(off_bad.values())}행: eval {_ids(sorted(off_bad))}"] if off_bad else []) + \
            [f"eval {i} 사외 실패 행: " + (" / ".join(f"「{t}」" for t in rows[i]) or "문구 없음(옛 기록)") for i in sorted(off_bad)]
        return res("s2.safety", "fail", "안전 위반 " + " · ".join(parts), cmd,
                   ask=("사외 기록의 안전 위반은 면제할 수 없다: 사외에서 다시 재고 `offsite.py`로 offsite_results.json을 다시 만들거나, "
                        f"그 eval({_ids(sorted(off_bad))})을 사내에서 실행·채점한다(사내 채점이 사외 기록을 대신한다)") if off_bad else None)
    if null or off_null:
        parts = ([f"사내 {sum(map(len, null.values()))}행: eval {_ids(sorted(null))}"] if null else []) + \
            ([f"사외 기록 {sum(off_null.values())}행: eval {_ids(sorted(off_null))}"] if off_null else [])
        return res("s2.safety", "needs-user", "안전 위반 0(결정분) · 미결정 안전 행 " + " · ".join(parts), cmd,
                   ask=(f"eval {_ids(sorted(null))}의 미결정 안전 행을 transcript로 채점해 주세요" if null else "")
                   + (" / " if null and off_null else "")
                   + (f"사외 기록의 미결정 안전 행(eval {_ids(sorted(off_null))})은 사외에서 수동 채점 뒤 offsite_results.json을 다시 "
                      "만들거나 그 eval을 사내에서 실행·채점한다" if off_null else ""))
    if open_:
        return res("s2.safety", "needs-user", f"안전 위반 0(채점분) · 사내 대상 안전 eval 미채점 {len(open_)}: {_ids(open_)}"
                   + note, cmd, ask="사내 대상 안전 eval을 먼저 실행·채점한다(`site_step.py evals`)")
    unknown = _model_unknown(ctx.root, st)
    if unknown:
        return res("s2.safety", "needs-user", f"안전 위반 0 · {unknown}" + note, cmd,
                   ask="사내 eval 모델을 알려 주세요(`propose --set eval_model=<ID>` → --apply)")
    return res("s2.safety", "pass", f"사내 대상 안전 eval {len(site_safety)}개·트래커 쓰기 행 위반 0·미결정 0(사외 기록 포함)" + note, cmd)


def s2_manual(ctx: Ctx) -> dict:
    st = eval_state(ctx.root)
    manual = load_pending(ctx.root)["manual"]
    open_ = sorted({i for i in manual if st.get(i, {}).get("status") != "graded"}
                   | {i for i, s in st.items() if s["status"] == "graded" and s.get("null_rows")})
    if open_:
        return res("s2.manual", "needs-user", f"수동 채점 미결정 eval {_ids(open_)} (passed null은 통과가 아니다)",
                   "tests/skill_evals/README.md 채점",
                   ask=f"eval {_ids(open_)} transcript를 읽고 미결정 행을 수동 채점해 주세요(grading.json source: manual)")
    return res("s2.manual", "pass", f"채점된 eval의 미결정 행 0 (수동 eval {manual} 포함)", "tests/skill_evals/README.md 채점")


S2_LINE = re.compile(r"(?m)^- S-2 결과: ")


def s2_summary(ctx: Ctx) -> dict:
    st = eval_state(ctx.root)
    req = required_ids(ctx.root, st)
    graded = {i: st[i] for i in req if st.get(i, {}).get("status") == "graded"}
    f = lambda k: sum(s.get(k) or 0 for s in graded.values())  # noqa: E731
    failed = sorted(i for i, s in graded.items() if s.get("failed"))
    safety = sum(len(s.get("safety_fail") or []) for s in graded.values())
    ev = (f"사내 대상 채점 {len(graded)}/{len(req)} · 실패 eval {len(failed)} · 행 통과 {f('passed')}/실패 {f('failed')}/미결정 "
          f"{f('undecided')} · 안전 위반 {safety} · 스키마 파일 Read {f('schema_reads')}회")
    cmd = "python3 tests/skill_evals/grade.py <iteration>"
    if S2_LINE.search(ctx.profile):
        return res("s2.summary", "pass", "SITE_PROFILE.md에 S-2 결과 줄 있음 · 지금 " + ev, cmd)
    line = (f"- S-2 결과: 사내 대상 채점 {len(graded)}/{len(req)}(나머지 사외 결과), 실패 eval {len(failed)}"
            + (f"({_ids(failed, 10)})" if failed else "") + f", 안전 위반 {safety}, 스키마 Read {f('schema_reads')}회"
            + f" (원인 {EVIDENCE_FILE})")
    return res("s2.summary", "needs-user", ev + " — SITE_PROFILE.md 기록 줄 없음", cmd,
               ask="S-2 결과 줄과 실패 원인(evidence)을 확인해 주세요 → `propose --apply s2-result-line`",
               propose=[{"id": "s2-result-line", "kind": "progress-line", "line": line, "pattern": S2_LINE.pattern,
                         "basis": "실패 원인: 사용자·Claude가 transcript로 적는다 — 실패 eval " + (_ids(failed) or "없음")}])


def s2_probe(ctx: Ctx) -> dict:
    if not ctx.allow_api:
        return res("s2.claude", "skip", "claude 미실행(--allow-api 없음)", "claude --version; claude mcp list",
                   ask="S1 실험(tests/mocks/plugin-probe/README.md)을 할 때 `site_step.py check S-2 --allow-api`를 승인해 주세요 "
                       "(`claude --version`과 `claude mcp list` — 후자는 설정된 MCP 서버(Jira MCP 포함)에 연결 상태만 확인하고 데이터는 읽지 않는다)")
    return _claude_info(ctx, "s2.claude")


def s2_s1_rows(ctx: Ctx) -> dict:
    have = [r for r in profile_rows(ctx.profile) if r[0] == "S1"]
    if not have:
        return res("s2.s1_rows", "needs-user", "SITE_PROFILE.md 확인값에 S1 행 없음", "SITE_PROFILE.md ## 확인값",
                   ask="plugin-probe 17항목 실험 결과(사외와 다른 것 — 10~13 show_guard 전제, 14 AskUserQuestion 선택지 상한, 15 transcript 시각으로 표시 기록 고정, 16 PowerShell 도구, 17 Bash 도구의 python3 포함)를 알려 주세요")
    return res("s2.s1_rows", "pass", f"S1 행 {len(have)}개", "SITE_PROFILE.md ## 확인값")


def s2_baseline(ctx: Ctx) -> dict:
    p = ctx.root / SITE_BASELINE
    site = set(site_ids(ctx.root))
    sub = f"기준선 eval {BASELINE_EVALS} " + ("⊆ 사내 대상" if set(BASELINE_EVALS) <= site else "⊄ 사내 대상(s2.pending)")
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        return res("s2.token_baseline", "pass", f"{SITE_BASELINE}: model {data.get('model')} · eval "
                   f"{len(data.get('evals') or {})}개 · {sub}", f"cat {SITE_BASELINE}")
    return res("s2.token_baseline", "info", f"{SITE_BASELINE} 없음(사내 토큰 기준선 T4) · {sub}",
               "python3 tools/site_step.py evals --baseline")


# --- S-3 ----------------------------------------------------------------------------------------------------

def _site_defaults(ctx: Ctx) -> dict | None:
    p = ctx.root / "plugin" / "site-defaults.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.is_file() else None


def _need_defaults(cid: str) -> dict:
    return res(cid, "skip", "plugin/site-defaults.yaml 없음", None,
               ask="site-defaults.yaml을 먼저 만든다(`site_step.py propose`의 site-defaults 초안 → 사용자 검토)")


def s3_site_defaults(ctx: Ctx) -> dict:
    if _site_defaults(ctx) is None:
        prop = None
        if (ctx.root / "plugin" / "site-defaults.example.yaml").is_file():
            prop = [{"id": "site-defaults-draft", "kind": "draft", "path": "docs/site/site-defaults.draft.yaml"}]
        return res("s3.site_defaults", "fail", "plugin/site-defaults.yaml 없음", "ls plugin/site-defaults.yaml", propose=prop)
    return res("s3.site_defaults", "pass", "plugin/site-defaults.yaml 있음", "ls plugin/site-defaults.yaml")


def s3_tracker_kind(ctx: Ctx) -> dict:
    d = _site_defaults(ctx)
    if d is None:
        return _need_defaults("s3.tracker_kind")
    kind = (d.get("tracker") or {}).get("kind")
    return res("s3.tracker_kind", "pass" if kind == "jira" else "fail", f"tracker.kind = {kind!r} (사내 결정 jira)",
               "grep -n kind plugin/site-defaults.yaml")


def s3_config_check(ctx: Ctx) -> dict:
    if _site_defaults(ctx) is None:
        return _need_defaults("s3.config_check")
    code, _, err = ctx.py("plugin/scripts/config.py", "check", "--plugin-root", str(ctx.root / "plugin"), timeout=120)
    return res("s3.config_check", "pass" if code == 0 else "fail", f"종료 {code}" + (f" — {_first_line(err)}" if code else ""),
               "python3 plugin/scripts/config.py check --plugin-root plugin")


def s3_doctor(ctx: Ctx) -> dict:
    if _site_defaults(ctx) is None:
        return _need_defaults("s3.doctor")
    code, out, err = ctx.py("plugin/scripts/config.py", "doctor", "--format", "json", "--plugin-root",
                            str(ctx.root / "plugin"), timeout=180)
    cmd = "python3 plugin/scripts/config.py doctor --format json --plugin-root plugin"
    try:
        data = json.loads(out)
    except ValueError:
        return res("s3.doctor", "fail", f"종료 {code}, JSON 아님 — {_first_line(err)}", cmd)
    counts = data.get("counts") or {}
    fails = [r.get("check") for r in data.get("rows") or [] if r.get("status") == "fail"]
    return res("s3.doctor", "pass" if not counts.get("fail") else "fail",
               " · ".join(f"{k} {counts.get(k, 0)}" for k in ("ok", "warn", "fail", "skip"))
               + (f" (fail: {', '.join(map(str, fails))})" if fails else ""), cmd)


SYNTHETIC_LOG = ("10-01 10:00:00.000  1000  1000 D RILJ    : [0001]> GET_SIGNAL_STRENGTH\n"
                 "10-01 10:00:00.010  1000  1000 D RILJ    : [0001]< GET_SIGNAL_STRENGTH\n")


def s3_parse_logcat(ctx: Ctx) -> dict:
    if _site_defaults(ctx) is None:
        return _need_defaults("s3.parse_logcat")
    rules = ctx.root / "tests" / "fixtures" / "issue-db-sample" / "parser-rules"
    clone = None
    try:
        clone = ctx.ops_clone()
    except (RuntimeError, CloneUnavailable):
        clone = None
    if clone and (clone / "parser-rules").is_dir():
        rules = clone / "parser-rules"
    log = ctx.tmpdir() / "synthetic.log"
    log.write_text(SYNTHETIC_LOG, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    code, _, err = ctx.run([sys.executable, str(ctx.root / "plugin/scripts/parse_logcat.py"), "parse", str(log), "--full",
                            "--rules", str(rules), "--json"], env=env, timeout=120)
    return res("s3.parse_logcat", "pass" if code == 0 else "fail",
               f"합성 2줄, --plugin-root 없이 종료 {code}" + (f" — {_first_line(err)}" if code else ""),
               "python3 plugin/scripts/parse_logcat.py parse <합성.log> --full --rules <parser-rules> --json")


def s3_tracker_candidates(ctx: Ctx) -> dict:
    if _site_defaults(ctx) is None:
        return _need_defaults("s3.tracker_candidates")
    code, out, err = ctx.py("plugin/scripts/config.py", "tracker-candidates", "--plugin-root", str(ctx.root / "plugin"),
                            timeout=180)
    cmd = "python3 plugin/scripts/config.py tracker-candidates --plugin-root plugin"
    try:
        usable = json.loads(out).get("usable") or []
    except ValueError:
        return res("s3.tracker_candidates", "info", f"종료 {code} — {_first_line(err)}", cmd)
    return res("s3.tracker_candidates", "info", f"사용 가능 서버 {len(usable)}개" + (f": {', '.join(usable)}" if usable else ""),
               cmd)


def s3_jira_fields(ctx: Ctx) -> dict:
    d = ctx.inputs.get("jira_raw_dir")
    raws = sorted(Path(str(d)).expanduser().glob("*.json")) if d else []
    cmd = "python3 plugin/scripts/jira_fields.py extract <raw.json> --origin file --plugin-root plugin"
    if not raws:
        return res("s3.jira_fields", "needs-user", "저장된 Jira raw 없음(steps.yaml jira_raw_dir)", cmd,
                   ask="샘플 Jira 2~3건 raw(마스킹본)를 저장한 디렉토리를 알려 주세요 → `propose --set jira_raw_dir=<경로>`")
    if _site_defaults(ctx) is None:
        return _need_defaults("s3.jira_fields")
    bad = []
    for raw in raws:
        code, out, _ = ctx.py("plugin/scripts/jira_fields.py", "extract", str(raw), "--origin", "file",
                              "--plugin-root", str(ctx.root / "plugin"), timeout=60)
        try:
            missing = json.loads(out).get("missing") or []
        except ValueError:
            missing = [f"종료 {code}"]
        if missing:
            bad.append(f"{raw.name}: {len(missing)} ({', '.join(map(str, missing))})")
    return res("s3.jira_fields", "fail" if bad else "pass",
               f"raw {len(raws)}건, missing 있는 것 {len(bad)}" + (": " + "; ".join(bad) if bad else ""), cmd)


# --- S-4a ---------------------------------------------------------------------------------------------------

def _gh_ready(ctx: Ctx, key: str, cid: str) -> tuple[str | None, dict | None]:
    repo = ctx.inputs.get(key)
    if not repo:
        return None, res(cid, "skip", f"steps.yaml `{key}` 없음", None,
                         ask=f"{STEP_INPUTS[key]}를 알려 주세요 → `propose --set {key}=<owner/repo>`")
    code, _, _ = ctx.gh("auth", "status")
    if code:
        return None, res(cid, "skip", f"gh 인증 없음·없음(종료 {code})", "gh auth status",
                         ask="`gh auth login`(S5) 뒤 다시 점검한다")
    return str(repo), None


def s4a_protection(ctx: Ctx) -> dict:
    repo, early = _gh_ready(ctx, "ops_db_repo", "s4a.protection")
    if early:
        return early
    cmd = f"gh api repos/{repo}/branches/main/protection"
    code, out, err = ctx.gh("api", f"repos/{repo}/branches/main/protection")
    if code:     # 403(권한)·404(보호 없음 또는 레포 없음)는 도구로 고칠 수 없다 — 사람에게 묻는다
        http = re.search(r"HTTP (\d{3})", err + out)
        return res("s4a.protection", "skip", f"브랜치 보호 조회 종료 {code}" + (f" (HTTP {http.group(1)})" if http else ""), cmd,
                   ask="main 브랜치 보호(PR 필수·CODEOWNERS 리뷰)를 켰는지, 조회 권한(관리자)이 있는지 확인해 주세요")
    try:
        data = json.loads(out)
    except ValueError:
        return res("s4a.protection", "skip", "응답이 JSON 아님", cmd, ask="gh api 응답을 확인해 주세요")
    reviews = data.get("required_pull_request_reviews") or {}
    owners = bool(reviews.get("require_code_owner_reviews"))
    return res("s4a.protection", "pass" if reviews and owners else "fail",
               f"PR 리뷰 필수 {bool(reviews)} · CODEOWNERS 리뷰 {owners} · 필수 승인 수 "
               f"{reviews.get('required_approving_review_count', '?')}(0이면 본인 병합 가능, issue_db.merge)", cmd)


def _golden_tests(root: Path) -> list[Path]:
    g = root / "tests" / "golden"
    return sorted(g.rglob("test_*.py")) if g.is_dir() else []


def s4a_golden(ctx: Ctx) -> dict:
    g = ctx.root / "tests" / "golden"
    data = [p for p in g.rglob("*") if p.is_file() and p.suffix in (".json", ".yaml", ".yml")] if g.is_dir() else []
    cmd = "python3 -m pytest --collect-only -q tests/golden"
    if not data:
        return res("s4a.golden", "fail", "tests/golden/ 골든 파일 0", cmd)
    marks = []
    for p in sorted(data):
        if p.suffix == ".json":
            try:
                marks += golden_synthetic_errors(str(p.relative_to(ctx.root)), json.loads(p.read_text(encoding="utf-8")))
            except ValueError:
                pass        # 깨진 JSON은 골든 테스트가 잡는다
    if marks:
        return res("s4a.golden", "fail", "; ".join(marks), cmd,
                   ask="합성 줄을 보충한 골든에 사유를 적는다(16-existing-assets.md §16.3 골든 1)")
    if not _golden_tests(ctx.root):
        return res("s4a.golden", "needs-user", f"골든 {len(data)}개, 수집할 test_*.py 없음", cmd,
                   ask="사내 골든 테스트(tests/golden/test_*.py)를 어떻게 돌리는지 정해 주세요")
    code, out, _ = ctx.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                            "tests/golden"], timeout=300)
    m = re.search(r"(\d+) tests? collected", out)
    n = int(m.group(1)) if m else len(re.findall(r"(?m)^\S+::\S+", out))
    return res("s4a.golden", "pass" if code == 0 and n else "fail", f"골든 {len(data)}개, 수집 {n}건(종료 {code})", cmd)


IGNORE_COPY = shutil.ignore_patterns(".git", "workspace", "__pycache__", ".pytest_cache", "build", "*.egg-info", ".venv")


def _leaves(value, path=""):
    """JSON 스칼라 잎의 (경로, 값). 경로는 `a.b[0].c` 형식."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _leaves(v, f"{path}[{i}]")
    elif isinstance(value, (bool, int, float, str)):
        yield path, value


def _mutate(value, path: str):
    """`path` 잎 하나만 바꾼 사본."""
    data = json.loads(json.dumps(value))
    keys = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    cur = data
    for k in keys[:-1]:
        cur = cur[int(k[1:-1])] if k.startswith("[") else cur[k]
    last = keys[-1]
    idx = int(last[1:-1]) if last.startswith("[") else last
    v = cur[idx]
    cur[idx] = (not v) if isinstance(v, bool) else (v + 1 if isinstance(v, (int, float)) else f"{v}~mutated")
    return data


MUTATIONS = 3
# 골든 JSON 최상위 메타데이터(기대값이 아님): 합성 줄 보충 표식·사유(16-existing-assets.md §16.3 골든 1). 변조 대상에서 뺀다.
GOLDEN_META_KEYS = ("synthetic",)


def golden_synthetic_errors(name: str, data) -> list[str]:
    """골든 JSON 최상위 `synthetic` 표식 검사: 있으면 `{reason: "<왜 실제 로그에 없는지>"}`이고 사유가 비지 않아야 한다.
    표식이 없으면 실제 로그 기준 케이스다. 사내는 `s4a.golden`, 모의는 `tests/test_golden.py`가 쓴다."""
    if not isinstance(data, dict) or "synthetic" not in data:
        return []
    mark = data["synthetic"]
    if not isinstance(mark, dict) or not str(mark.get("reason") or "").strip():
        return [f"{name}: synthetic 표식에 사유(reason)가 없습니다"]
    return []


def s4a_golden_mutation(ctx: Ctx) -> dict:
    """C5: 임시 복사본에서 (1) 바꾸지 않은 골든 테스트가 통과하는지(종료 0) 보고, (2) 골든 기대값을 하나씩 바꿀 때마다(처음·가운데·끝
    최대 3곳) 테스트가 실패(종료 1)하는지 본다. 못 잡은 값은 필드 경로와 함께 사용자 필요다. 원본은 건드리지 않는다."""
    cmd = "(임시 복사본) python3 -m pytest -q tests/golden → 골든 JSON 값 1개씩 변경 → 다시"
    goldens = sorted((ctx.root / "tests" / "golden").rglob("*.json")) if (ctx.root / "tests" / "golden").is_dir() else []
    if not goldens or not _golden_tests(ctx.root):
        return res("s4a.golden_mutation", "skip", "골든 JSON 또는 tests/golden/test_*.py 없음", cmd,
                   ask="골든과 골든 테스트가 생긴 뒤 다시 점검한다")
    copy = ctx.tmpdir() / "repo"
    shutil.copytree(ctx.root, copy, ignore=IGNORE_COPY, symlinks=True)
    pytest = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests/golden"]
    code, _, _ = ctx.run(pytest, cwd=copy, timeout=600)
    if code != 0:
        return res("s4a.golden_mutation", "skip", f"바꾸지 않은 골든 테스트가 종료 {code} — 변조 시험 전제가 안 됨", cmd,
                   ask="골든 테스트를 먼저 통과시킨 뒤 다시 점검한다(s4a.golden)")
    rel = goldens[0].relative_to(ctx.root)
    target = copy / rel
    original = target.read_text(encoding="utf-8")
    leaves = [p for p, _ in _leaves(json.loads(original))
              if re.match(r"[^.\[]+", p).group() not in GOLDEN_META_KEYS]   # 최상위 메타 키만 뺀다(이벤트 필드 이름은 기대값)
    if not leaves:
        return res("s4a.golden_mutation", "skip", f"{rel}: 바꿀 값 없음", cmd, ask="값이 있는 골든 JSON을 둔다")
    picks = sorted({0, len(leaves) // 2, len(leaves) - 1})[:MUTATIONS]
    caught, missed, odd = [], [], []
    for i in picks:
        path = leaves[i]
        target.write_text(json.dumps(_mutate(json.loads(original), path), ensure_ascii=False, indent=2), encoding="utf-8")
        code, _, _ = ctx.run(pytest, cwd=copy, timeout=600)
        (caught if code == 1 else missed if code == 0 else odd).append(f"{path}" + (f"(종료 {code})" if code not in (0, 1) else ""))
        target.write_text(original, encoding="utf-8")
    ev = f"{rel} 값 {len(picks)}곳 변경: 잡음 {len(caught)}, 못 잡음 {len(missed)}, 기타 종료 {len(odd)} · 원본 그대로"
    if odd:
        return res("s4a.golden_mutation", "skip", ev + " — " + ", ".join(odd), cmd,
                   ask="골든 테스트가 실패(1)가 아닌 종료 코드를 냈다 — 테스트 수집·오류를 확인해 주세요")
    if missed:
        return res("s4a.golden_mutation", "needs-user", ev + " — 못 잡은 필드: " + ", ".join(missed), cmd,
                   ask=f"골든 테스트가 {', '.join(missed)} 값을 비교하지 않는다 — 의도인지(비교 제외 필드) 확인해 주세요")
    return res("s4a.golden_mutation", "pass", ev, cmd)


def s4a_analyzers(ctx: Ctx) -> dict:
    d = _site_defaults(ctx)
    if d is None:
        return _need_defaults("s4a.analyzers")
    data = (d.get("analyzers") or {}).get("data")
    return res("s4a.analyzers", "pass" if data else "fail", f"analyzers.data {'설정됨' if data else '비어 있음'}",
               "grep -n -A3 analyzers plugin/site-defaults.yaml")


def s4a_import_pr(ctx: Ctx) -> dict:
    repo, early = _gh_ready(ctx, "ops_db_repo", "s4a.import_pr")
    if early:
        return early
    cmd = f"gh pr list --repo {repo} --state merged --search import --json number,title"
    code, out, _ = ctx.gh("pr", "list", "--repo", repo, "--state", "merged", "--search", "import", "--json",
                          "number,title", "--limit", "20")
    if code:
        return res("s4a.import_pr", "skip", f"gh pr list 종료 {code}", cmd, ask="gh 권한을 확인해 주세요")
    prs = json.loads(out or "[]")
    if not prs:
        return res("s4a.import_pr", "needs-user", "머지된 import PR 0건", cmd, ask="기존 data 분류 import PR을 머지했는지 알려 주세요")
    return res("s4a.import_pr", "pass", f"머지된 import PR {len(prs)}건 (#{', #'.join(str(p.get('number')) for p in prs[:5])})", cmd)


# --- S-4 ----------------------------------------------------------------------------------------------------

def _need_clone(ctx: Ctx, cid: str) -> tuple[Path | None, dict | None]:
    try:
        clone = ctx.ops_clone()
    except CloneUnavailable as exc:
        return None, res(cid, "skip", str(exc), "git -C <임시 clone> checkout --detach origin/main",
                         ask="운영 DB clone의 main(origin/main)을 확인해 주세요(점검은 원본을 바꾸지 않는다)")
    except RuntimeError as exc:
        return None, res(cid, "fail", str(exc), "git clone --no-local <ops_db> <임시>")
    if clone is None:
        return None, res(cid, "skip", "steps.yaml `ops_db`(운영 이슈 DB clone) 없음", None,
                         ask="운영 이슈 DB clone 경로를 알려 주세요 → `propose --set ops_db=<경로>`(점검은 임시 clone에서만)")
    return clone, None


def s4_regress(ctx: Ctx) -> dict:
    clone, early = _need_clone(ctx, "s4.regress")
    if early:
        return early
    code, out, err = ctx.py("plugin/scripts/db_regress.py", "--db", str(clone), "--all", "--json",
                            "--plugin-root", str(ctx.root / "plugin"))
    return res("s4.regress", "pass" if code == 0 else "fail", f"(임시 clone) 종료 {code}" +
               (f" — {_first_line(err)}" if code else ""), "python3 plugin/scripts/db_regress.py --db <임시 clone> --all")


def s4_verify_rules(ctx: Ctx) -> dict:
    clone, early = _need_clone(ctx, "s4.verify_rules")
    if early:
        return early
    _, first, _ = ctx.run(["git", "-C", str(clone), "rev-list", "--max-parents=0", "HEAD"], timeout=30)
    first = (first.split() or [""])[0]
    code, _, err = ctx.py("plugin/scripts/db_verify.py", "rules", "--changed", first, "--db", str(clone), "--json",
                          "--plugin-root", str(ctx.root / "plugin"))
    return res("s4.verify_rules", "pass" if code == 0 else "fail",
               f"(임시 clone, 첫 커밋 이후 전체) 종료 {code}" + (f" — {_first_line(err)}" if code else ""),
               "python3 plugin/scripts/db_verify.py rules --changed <첫 커밋> --db <임시 clone>")


def _types(db: Path) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for t in sorted(db.glob("*/*/type.md")):
        out.setdefault(t.parent.parent.name, []).append(t.parent)
    return out


def _real_fixture(type_dir: Path) -> bool:
    for e in (type_dir / "fixtures").glob("*.expect.yaml") if (type_dir / "fixtures").is_dir() else []:
        if not SYNTHETIC_RE.search(e.read_text(encoding="utf-8", errors="replace")):
            return True
    return False


def s4_seed(ctx: Ctx) -> dict:
    clone, early = _need_clone(ctx, "s4.seed")
    if early:
        return early
    counts = {cat: sum(_real_fixture(t) for t in types) for cat, types in _types(clone).items()}
    low = {c: n for c, n in counts.items() if c != "data" and n < 5}
    ev = "실제 fixture 있는 유형: " + (", ".join(f"{c} {n}" for c, n in counts.items()) or "없음")
    if not counts or low:
        return res("s4.seed", "fail", ev + (f" — 5 미만: {', '.join(low)}" if low else ""), "find <db> -name '*.expect.yaml'")
    return res("s4.seed", "pass", ev, "find <db> -name '*.expect.yaml'")


def placeholder_rules(db: Path) -> list[str]:
    out = []
    for p in sorted((db / "parser-rules").rglob("*.y*ml")) if (db / "parser-rules").is_dir() else []:
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if PLACEHOLDER_RE.match(line):
                out.append(f"{p.relative_to(db).as_posix()}:{n}")
    return out


def s4_placeholder(ctx: Ctx) -> dict:
    clone, early = _need_clone(ctx, "s4.placeholder")
    if early:
        return early
    found = placeholder_rules(clone)
    return res("s4.placeholder", "info", f"`reason: placeholder` 규칙 {len(found)}건", "grep -rn 'reason: placeholder' parser-rules")


# --- S-5 ----------------------------------------------------------------------------------------------------

def gate_verdict(summary: dict, g: tuple[float, float, str]) -> tuple[str, str]:
    """offline_eval `summary`와 게이트. null 지표·평가 0건은 미충족(fail)."""
    top1, err, ev_n = summary.get("top1_accuracy"), summary.get("error_rate"), summary.get("evaluated")
    ev = f"top1 {top1} (≥ {g[0]}) · error_rate {err} (≤ {g[1]}) · 평가 {ev_n}/{summary.get('total')}"
    if not ev_n:
        return "fail", ev + " — 평가 0건"
    if top1 is None or err is None:
        return "fail", ev + " — 지표 null"
    if top1 < g[0] or err > g[1]:
        return "fail", ev + " — 기준 미달"
    return "pass", ev


def s5_offline_eval(ctx: Ctx) -> dict:
    g = gate(ctx.profile)
    if g is None:
        return res("s5.offline_eval", "needs-user", "S-5 게이트 줄 없음(S-1에서 합의)", None,
                   ask="게이트 기준치 → `propose --set gate.top1=<값> --set gate.error_rate=<값>`")
    labelset = ctx.root / str(ctx.inputs.get("labelset") or "tests/site/offline-eval.yaml")
    cmd = f"python3 tools/offline_eval.py {labelset.relative_to(ctx.root) if labelset.is_relative_to(ctx.root) else labelset} --db <임시 clone> --json"
    if not labelset.is_file():
        return res("s5.offline_eval", "needs-user", "라벨셋 없음", cmd, ask="최종 확인용 라벨셋 경로 → `propose --set labelset=<경로>`")
    clone, early = _need_clone(ctx, "s5.offline_eval")
    if early:
        return early
    code, out, err = ctx.py("tools/offline_eval.py", str(labelset), "--db", str(clone), "--json",
                            "--plugin-root", str(ctx.root / "plugin"))
    try:
        summary = json.loads(out)["summary"]
    except (ValueError, KeyError, TypeError):
        return res("s5.offline_eval", "fail", f"종료 {code}, JSON 아님 — {_first_line(err)}", cmd)
    status, ev = gate_verdict(summary, g)
    return res("s5.offline_eval", status, ev, cmd)


def s5_sandbox_pr(ctx: Ctx) -> dict:
    repo, early = _gh_ready(ctx, "sandbox_repo", "s5.sandbox_pr")
    if early:
        return early
    cmd = f"gh pr list --repo {repo} --state all --limit 5 --json number"
    code, out, _ = ctx.gh("pr", "list", "--repo", repo, "--state", "all", "--limit", "5", "--json", "number")
    prs = json.loads(out or "[]") if code == 0 else []
    if not prs:
        return res("s5.sandbox_pr", "needs-user", f"샌드박스 PR 0건(종료 {code})", cmd, ask="샌드박스 PR 1건을 만든 뒤 다시 점검한다")
    return res("s5.sandbox_pr", "pass", f"샌드박스 PR {len(prs)}건", cmd)


def s5_smoke(ctx: Ctx) -> dict:
    return res("s5.smoke", "needs-user", "실제 Jira·로그 analyze/record --dry-run과 C2·C4 확인은 세션에서 사람이 본다", None,
               ask="스모크(analyze·record --dry-run, 듀얼 SIM·재부팅·시계 차·마스킹, C4 복구) 결과를 확인해 주세요 "
                   "→ `--done S-5 --waive s5.smoke=\"<확인 내용>\"`")


# --- S-6 ----------------------------------------------------------------------------------------------------

def s6_review_open(ctx: Ctx) -> dict:
    return _review_open(ctx, "s6.review_open")


def s6_synthetic(ctx: Ctx) -> dict:
    clone, early = _need_clone(ctx, "s6.synthetic")
    if early:
        return early
    hits = [p.relative_to(clone).as_posix() for p in sorted(clone.rglob("*.expect.yaml"))
            if SYNTHETIC_RE.search(p.read_text(encoding="utf-8", errors="replace"))]
    return res("s6.synthetic", "fail" if hits else "pass", f"`origin: synthetic` {len(hits)}건"
               + (": " + ", ".join(hits[:5]) + (" …" if len(hits) > 5 else "") if hits else ""),
               "grep -rl 'origin: synthetic' --include='*.expect.yaml' <임시 clone>")


PLACEHOLDER_LINE = re.compile(r"(?m)^- placeholder 규칙: ")


def s6_placeholder(ctx: Ctx) -> dict:
    clone, early = _need_clone(ctx, "s6.placeholder")
    if early:
        return early
    found = placeholder_rules(clone)
    cmd = "grep -rn 'reason: placeholder' <임시 clone>/parser-rules"
    if PLACEHOLDER_LINE.search(ctx.profile):
        return res("s6.placeholder", "pass", f"SITE_PROFILE.md에 보고됨 (지금 {len(found)}건)", cmd)
    return res("s6.placeholder", "needs-user", f"`reason: placeholder` {len(found)}건, SITE_PROFILE.md 보고 줄 없음", cmd,
               ask="placeholder 목록 보고 줄을 승인해 주세요 → `propose --apply placeholder-line`",
               propose=[{"id": "placeholder-line", "kind": "progress-line",
                         "line": f"- placeholder 규칙: {len(found)}건 (목록 {EVIDENCE_FILE})", "pattern": PLACEHOLDER_LINE.pattern,
                         "basis": "; ".join(found) or "없음"}])


# --- S-7 ----------------------------------------------------------------------------------------------------

def s7_marketplace(ctx: Ctx) -> dict:
    p = ctx.root / ".claude-plugin" / "marketplace.json"
    if not p.is_file():
        return res("s7.marketplace", "fail", ".claude-plugin/marketplace.json 없음", "ls .claude-plugin/")
    try:
        plugins = json.loads(p.read_text(encoding="utf-8")).get("plugins") or []
    except ValueError:
        return res("s7.marketplace", "fail", "marketplace.json JSON 오류", "python3 -m json.tool .claude-plugin/marketplace.json")
    return res("s7.marketplace", "pass" if plugins else "fail", f"plugins {len(plugins)}개", "cat .claude-plugin/marketplace.json")


def s7_usage(ctx: Ctx) -> dict:
    platforms = ctx.inputs.get("platforms") or [None]
    parts = []
    for p in platforms:
        args = ["--platform", str(p)] if p else []
        code, out, _ = ctx.py("plugin/scripts/usage_stats.py", *args, timeout=120)
        parts.append(f"{p or '기본'}: 종료 {code}")
    return res("s7.usage", "info", " · ".join(parts), "python3 plugin/scripts/usage_stats.py [--platform <이름>]")


def s7_pilot(ctx: Ctx) -> dict:
    """파일럿 보고: '파일럿'이 든 한 줄에 항목이 모두 있어야 한다(여러 줄에 흩어진 낱말은 보고가 아니다)."""
    text = ctx.profile + "\n" + ((ctx.root / EVIDENCE_FILE).read_text(encoding="utf-8") if (ctx.root / EVIDENCE_FILE).is_file() else "")
    lines = [ln for ln in text.splitlines() if "파일럿" in ln]
    best = min(([f for f in PILOT_FIELDS if f not in ln] for ln in lines), key=len, default=list(PILOT_FIELDS))
    if best:
        return res("s7.pilot", "needs-user", f"파일럿 보고 줄({len(lines)}줄 중)에 없는 항목: {', '.join(best)}", None,
                   ask="파일럿 결과를 한 줄로(" + ", ".join(PILOT_FIELDS) + ") SITE_PROFILE.md 또는 evidence.md에 기록한다")
    return res("s7.pilot", "pass", "파일럿 보고 줄에 항목 모두 있음", None)


def s7_expansion(ctx: Ctx) -> dict:
    return res("s7.expansion", "needs-user", "전체 확대 여부는 사용자가 정한다", None,
               ask="전체 확대 여부를 결정해 주세요 → `--done S-7 --waive s7.expansion=\"<결정>\"`")


CHECKS = {
    "S-1": [s1_profile, s1_review_open, s1_gate, s1_samples, s1_python, s1_env, s1_ghe, s1_claude, s1_todos],
    "S-2": [s2_pending, s2_graded, s2_offsite, s2_safety, s2_manual, s2_summary, s2_probe, s2_s1_rows, s2_baseline],
    "S-3": [s3_site_defaults, s3_tracker_kind, s3_config_check, s3_doctor, s3_parse_logcat, s3_tracker_candidates,
            s3_jira_fields],
    "S-4a": [s4a_protection, s4a_golden, s4a_golden_mutation, s4a_analyzers, s4a_import_pr],
    "S-4": [s4_regress, s4_verify_rules, s4_seed, s4_placeholder],
    "S-5": [s5_offline_eval, s5_sandbox_pr, s5_smoke],
    "S-6": [s6_review_open, s6_synthetic, s6_placeholder],
    "S-7": [s7_marketplace, s7_usage, s7_pilot, s7_expansion],
}


def check_id(fn) -> str:
    return fn.__name__.replace("_", ".", 1)


def run_checks(step: str, root: Path, allow_api: bool = False) -> list[dict]:
    ctx = Ctx(Path(root), allow_api=allow_api)
    out = []
    try:
        for fn in CHECKS[step]:
            ctx.used_clone = False
            try:
                r = fn(ctx)
            except Exception as exc:  # noqa: BLE001 — 한 점검의 오류가 나머지를 막지 않는다
                r = res(check_id(fn), "fail", f"점검 오류: {type(exc).__name__}: {str(exc)[:160]}", None)
            if ctx.used_clone and ctx.clone_ref:      # 운영 DB를 본 근거에는 어느 브랜치·커밋인지 붙인다
                r["evidence"] = f"[운영 DB {ctx.clone_ref}] {r['evidence']}"
            out.append(r)
    finally:
        ctx.cleanup()
    return out


def exit_code(results: list[dict], waived: set[str] = frozenset()) -> int:
    for r in results:
        if r["status"] == "fail" or (r["status"] in ("skip", "needs-user") and r["id"] not in waived):
            return 1
    return 0


MARK = {"pass": "통과", "fail": "실패", "skip": "건너뜀", "needs-user": "사용자 필요", "info": "정보"}


def report(step: str, results: list[dict]) -> str:
    lines = [f"자동 점검 {step} (읽기 전용)", "| 점검 | 결과 | 근거 |", "|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {MARK[r['status']]} | {str(r['evidence']).replace('|', '/')} |")
    counts = {s: sum(r["status"] == s for r in results) for s in STATUSES}
    lines.append(" · ".join(f"{MARK[s]} {counts[s]}" for s in STATUSES))
    if counts["skip"] or counts["needs-user"]:
        lines.append("건너뜀·사용자 필요는 통과가 아니다(`--done`은 `--waive <점검>=\"사유\"` 없이 거부).")
    return "\n".join(lines)
