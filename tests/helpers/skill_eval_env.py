#!/usr/bin/env python3
"""스킬 eval 한 건의 모의 환경을 만든다 (11-phases.md Phase 13, 10-skill-eval.md).

`tests/skill_evals/evals.json`의 항목 하나(`setup`)를 읽어 다음을 만든다.
- 테스트 헬퍼 플러그인 루트(`site-defaults.example.yaml` → `site-defaults.yaml`, 스킬 포함) = `CLAUDE_PLUGIN_ROOT`
- 임시 사용자 홈(`TELEPHONY_TRIAGE_HOME`)과 config, 모의 원격(bare) + 사용자 clone(`core.hooksPath .githooks`), gh 스텁 상태
- eval용 Jira 티켓 디렉토리(`MOCK_JIRA_DIR`), 로그 파일(`<out>/logs/`), 필요하면 main에 미리 넣은 변경·이미 올린 PR
- `<out>/env.sh`(export 목록)와 `<out>/env.json`(경로·상태), 채점용 `<out>/before.json`(사용자 clone 상태)
- Bash용 격리 홈 `<out>/user-home`(env.sh의 `HOME`, Windows는 `USERPROFILE`도): `.claude.json`의 사용자 범위 `mcpServers`에
  모의 트래커 서버(`tracker_servers`, run.py `--mcp-config`와 같은 정의)만 있다 — setup 0번 `config.py tracker-candidates`가
  실제 `~/.claude.json` 대신 이것을 읽는다(eval 58). 자식 claude 프로세스·hook·MCP 서버의 홈은 그대로다(env.json `env`에 없다).
  Python 사용자 site는 `PYTHONUSERBASE`로 원래 위치에 묶는다

    python3 tests/helpers/skill_eval_env.py <eval id> --out <dir> [--evals tests/skill_evals/evals.json]

setup 필드 (모두 선택):
    db: tests/fixtures 아래 이슈 DB 이름 (기본 issue-db-sample)
    jira: [티켓 키]  — tests/skill_evals/jira, 없으면 tests/mocks/jira에서 찾는다
    tracker: github — 두 번째 트래커(트래커 범용화 §6-3): site-defaults `tracker` 블록을 `runner.GITHUB_TRACKER`로(site_defaults의
        tracker가 있으면 그 키가 우선), db 기본값을 `issue-db-github`로, 모의 GitHub Issues MCP 환경(`MOCK_GH_ISSUES_DIR`·
        `MOCK_GH_ISSUES_WRITE_LOG`)을 export한다. direct 모드의 `jira_call`·`jira_tools_list`는 모의 GitHub 서버 call.py를 가리킨다
    gh_issues: [작업 키] — tests/skill_evals/github_issues, 없으면 tests/mocks/github_issues에서 찾는다(`<owner>.<repo>-<n>.yaml`)
    logs: [{src: <레포 기준 경로> | scenario: <tests/skill_evals/scenarios 파일>, as: <파일명>, bugreport: zip|txt}]
        split_buffers: true — 버퍼별 파일 <as>.main.log·<as>.radio.log
    inject_main: [{scenario: <파일>, dest: <이슈 DB 안 디렉토리>, message: <커밋 메시지>}]
    published_pr: {job, branch, plan: <tests/skill_evals/plans 파일>, files: {<작업 디렉토리 기준 경로>: <레포 기준 원본>}}
        또는 그 목록 — 순서대로 올린다(PR 번호 1, 2…, eval 75)
    main_after_pr: [<이름>]  — 아래 MAIN_EDITS의 이름. 이미 올린 PR 뒤에 main을 바꾼다
    remote_after_pr: {branch, files: {<상대 경로>: <내용>}, message} — 제3자의 원격 PR 변경
    seed_plan: {job, plan, files} — 게시 전 계획을 작업 디렉토리에 보관
    user_config: {...}, site_defaults: {...}, clone_state: {branch, local_branches, dirty}
    leftovers: [{job, branch?}] — 다른 작업 키가 비정상 종료로 남긴 도구 worktree(`<work_dir>/<job>/wt`)와 도구 브랜치(기본 `tt/<job>`).
        사용자 clone에 만들고 before.json은 그 뒤에 찍으므로 "그대로 남았나"는 clone_same·존재 확인으로 본다
    analyzer_fail: true — 모의 분석 스킬 실패
    analyzer_proposal: true — 모의 분석 스킬이 `규칙 제안:`([이슈 DB]·[스킬])을 내고 patch 대상 references/DATA-001.md를 둔다(plugin 모드, `run.py`가
        tests/mocks/skills/data-analyzer-proposal을 덧씌우고 채점용 analyzer-manifest.json을 쓴다, eval 71)
    gh_unauth: true  — gh 스텁 인증 실패
    gh_merge: {checks: none|pass|pending|fail, merge_state: <mergeStateStatus>, methods: "merge,squash,rebase",
               reviews: "[<PR 번호|브랜치>=]<종류>:<login>@<head|old|none|sha>,…"} — gh 스텁의 PR 검사·병합 가능 상태·
        허용 병합 방식·모의 리뷰(`MOCK_GH_CHECKS`·`MOCK_GH_MERGE_STATE`·`MOCK_GH_MERGE_METHODS`·`MOCK_GH_REVIEWS`, 병합 eval 72·75).
        reviews는 스텁 파서(`parse_reviews`)로 검사한다. 없는 키는 스텁 기본값(검사 없음·CLEAN·세 방식 모두·리뷰 없음)이고,
        gh_merge가 없으면 env에 아무것도 더하지 않는다(다른 eval은 예전과 같다)
    approver_deny: true — 권한 확인 응답 서버(eval-approver)가 모든 ask를 거부한다(`run.py`가 `EVAL_APPROVER_DENY=1`로 붙인다, eval 62)
    module_skills: {source: mock|template|missing} — 모듈 스킬 레포(B2 §13.1). `<out>/module-remote/`에 file:// bare 레포를 만들고
        (`tests/helpers/module_remote.build`: mock = `tests/mocks/module-skills`, template = `templates/module-skills`) site-defaults
        `module_skills.remote`로 넣는다. missing = 없는 `file://<out>/missing.git`(git이 레포가 아니라고 해 `인증`, 오프라인 인증 실패).
        env.json에 `module_source`·`module_remote_sha`(missing이면 null)
    fresh_user: true — 플러그인을 방금 설치한 첫 사용자(setup-first-time): 환경을 다 만든 뒤(before.json 뒤) 사용자 config.yaml과
        이슈 DB clone을 지운다(모의 원격·gh 스텁은 그대로). 격리 홈 `.gitconfig`에 모의 GHE URL(`issue_db.remote`) → 로컬 bare 원격
        `insteadOf`를 써서 setup 3번이 제안하는 `git clone <URL> <경로>`가 Bash에서 실제로 된다(`config.py init`은 로컬 경로
        원격을 거부한다). env.json `work_dir`는 새 config의 기본값 `<TELEPHONY_TRIAGE_HOME>/work`(setup은 작업 디렉토리를 묻지
        않는다), `issue_db_clone`은 지운 자리(사용자가 답할 경로)다. `run.py`는 이 eval의 config에 `skill_dir`를 합치지 않는다
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import site
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVALS = REPO / "tests" / "skill_evals"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_env  # noqa: E402
from runner import GH_SERVER, fixture_db, fixture_path, github_defaults, plugin_root  # noqa: E402
from workspace import Workspace, git  # noqa: E402

GEN = REPO / "tests" / "mocks" / "logcat_gen.py"
CALL = REPO / "tests" / "mocks" / "jira_mcp" / "call.py"
GH_CALL = REPO / "tests" / "mocks" / "github_issues_mcp" / "call.py"
JIRA_MCP_PY = REPO / "tests" / "mocks" / "jira_mcp" / "server.py"
GH_MCP_PY = REPO / "tests" / "mocks" / "github_issues_mcp" / "server.py"
ANALYZER = REPO / "tests" / "mocks" / "skills" / "data-analyzer" / "run.py"
MODULE_SOURCES = ("mock", "template", "missing")
MODULE_TEMPLATES = REPO / "templates" / "module-skills"


def module_remote(spec, out: Path) -> tuple[str | None, str | None]:
    """setup.module_skills → (remote URL, HEAD sha). 없으면 (None, None). 틀리면 SystemExit."""
    if not spec:
        return None, None
    if not isinstance(spec, dict) or set(spec) != {"source"} or spec["source"] not in MODULE_SOURCES:
        raise SystemExit(f"setup.module_skills는 {{source: {'|'.join(MODULE_SOURCES)}}}: {spec}")
    if spec["source"] == "missing":
        return (out / "missing.git").as_uri(), None
    import module_remote as mr  # 작업 묶음 2의 도우미(B2 §5.8, R30 build(out, src=MOCK, extra=None) -> file URL)
    kwargs = {"src": MODULE_TEMPLATES} if spec["source"] == "template" else {}
    url = mr.build(out / "module-remote", **kwargs)
    from urllib.parse import unquote, urlparse
    bare = Path(unquote(urlparse(url).path))
    sha = subprocess.run(["git", "--git-dir", str(bare), "rev-parse", "HEAD"], capture_output=True, text=True,
                         check=True).stdout.strip()
    return url, sha


def _gen(scenario: Path, out: Path, name: str | None = None, bugreport: str | None = None,
         split: bool = False) -> list[Path]:
    args = [sys.executable, str(GEN), str(scenario), "--out", str(out), "--json"]
    if split:
        args += ["--split-buffers"]
    if name:
        args += ["--name", name]
    if bugreport:
        args += ["--bugreport", bugreport]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}   # 경로에 한글이 있으면 Windows 기본 인코딩으로 깨진다
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", check=True, env=env)
    info = json.loads(proc.stdout)
    files = [Path(f) for f in info["files"]]
    if info.get("expect"):
        files.append(Path(info["expect"]))
    return files


def _type_dir(root: Path, type_id: str) -> Path:
    hits = sorted(root.glob(f"*/{type_id}-*/type.md"))
    assert hits, f"유형 디렉토리 없음: {type_id}"
    return hits[0].parent


def _edit_type(root: Path, type_id: str, old: str, new: str) -> None:
    path = _type_dir(root, type_id) / "type.md"
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{path}: {old!r} 없음"
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


NEW_DATA_CAUSE = """  - id: DATA-001-03
    status: active
    title: 데이터 한도 초과
    description: 요금제 데이터 한도를 넘어 망이 데이터 연결을 제한함
    signatures:
      - id: data-throttled
        must_event:
          - {event: data_evaluation_rejected, fields: {reasons: '.*DATA_THROTTLED.*'}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 요금제 데이터 한도를 확인하고 한도를 늘리거나 다음 주기까지 기다린다
    resolution_type: network
    resolution_verification: {status: unverified}
    fix: {status: not-a-bug, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    platform_versions: []
    code_refs: []
"""


def main_e016(root: Path, ws: Workspace) -> str:
    """eval 16: 같은 유형(DATA-001)에 새 원인 DATA-001-03이 먼저 머지되고, 계획이 바꾸는 DATA-001-02 해결책도 main에서 바뀜."""
    _edit_type(root, "DATA-001", "tags:", NEW_DATA_CAUSE + "tags:")
    _edit_type(root, "DATA-001", "### DATA-001-02", "### DATA-001-03 데이터 한도 초과\n- **재현 시나리오**: 한도 초과 요금제로 데이터 사용\n\n### DATA-001-02")
    _edit_type(root, "DATA-001", "    resolution: 데이터 로밍 설정을 켠다",
               "    resolution: 설정 > 모바일 네트워크에서 데이터 로밍을 켠다")
    subprocess.run([sys.executable, str(ws.root / "scripts" / "db_build.py"), "--write", "--db", str(root)],
                   check=True, capture_output=True, env=mock_env.env_with_mocks(plugin_root=ws.root))
    return "다른 PR: DATA-001-03 데이터 한도 초과 추가, DATA-001-02 해결책 문구 변경"


def main_schema99(root: Path, ws: Workspace) -> str:
    """eval 13: 이슈 DB 스키마가 플러그인 지원 범위보다 새 버전(99)이 된 main."""
    cfg = root / "issue-db.config.yaml"
    text = cfg.read_text(encoding="utf-8")
    old, new = "schema_version: 1\n", "schema_version: 99\n"
    assert old in text
    cfg.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    return "스키마 v99 (플러그인 범위 밖)"


def main_e015(root: Path, ws: Workspace) -> str:
    """eval 15: DATA-001-01의 DataFailCause code_ref를 버전 구분 없는 Android 16 경로 하나로 만든다.
    Android 17 트리에서는 그 파일이 fail/ 아래로 옮겨져 있어 "경로 변경"을 찾아야 한다."""
    old = ("      - ref: aosp:frameworks/base/telephony/java/android/telephony/DataFailCause.java\n"
           "        symbol: DataFailCause#toString\n"
           "        platform_versions: [\"16\"]\n"
           "      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/data/fail/DataFailCause.java\n"
           "        symbol: DataFailCause#toString\n"
           "        platform_versions: [\"17\"]\n")
    new = ("      - ref: aosp:frameworks/base/telephony/java/android/telephony/DataFailCause.java\n"
           "        symbol: DataFailCause#toString\n")
    _edit_type(root, "DATA-001", old, new)
    return "DATA-001-01 DataFailCause code_ref를 16 경로 하나로 (17 경로 항목 제거)"


def _update_call_cause(root: Path, ws: Workspace, **changes) -> None:
    import yaml

    path = _type_dir(root, "CALL-001") / "type.md"
    _, front, body = path.read_text(encoding="utf-8").split("---", 2)
    data = yaml.safe_load(front)
    cause = next(c for c in data["causes"] if c["id"] == "CALL-001-01")
    cause.update(changes)
    path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---" + body,
                    encoding="utf-8", newline="\n")
    subprocess.run([sys.executable, str(ws.root / "scripts" / "db_build.py"), "--write", "--db", str(root)],
                   check=True, capture_output=True, env=mock_env.env_with_mocks(plugin_root=ws.root))


def main_e025(root: Path, ws: Workspace) -> str:
    _update_call_cause(root, ws, scenario_signatures=[], recovery_signatures=[])
    return "CALL-001-01 시나리오·회복 흔적 시그니처 없음"


def main_e026(root: Path, ws: Workspace) -> str:
    _update_call_cause(root, ws, fix={"status": "open", "ref": None, "fixed_in": [],
                                    "verification": None, "verification_history": []})
    return "CALL-001-01 수정 제출 전 open 상태"


MAIN_EDITS = {"e016": main_e016, "schema99": main_schema99, "e015": main_e015,
              "e025": main_e025, "e026": main_e026}


def _bash_path(p: str) -> str:
    """Windows 경로(`C:\\a\\b`)를 Git Bash 경로(`/c/a/b`)로. 그 밖에는 그대로."""
    if os.name != "nt" or len(p) < 2 or p[1] != ":":
        return p
    return "/" + p[0].lower() + p[2:].replace("\\", "/")


def _find_jira(key: str) -> Path:
    for d in (EVALS / "jira", REPO / "tests" / "mocks" / "jira"):
        if (d / f"{key}.yaml").is_file():
            return d / f"{key}.yaml"
    raise SystemExit(f"Jira 티켓 없음: {key}")


def _find_gh_issue(key: str) -> Path:
    for d in (EVALS / "github_issues", REPO / "tests" / "mocks" / "github_issues"):
        if (d / f"{key}.yaml").is_file():
            return d / f"{key}.yaml"
    raise SystemExit(f"GitHub 이슈 없음: {key}")


def _clone_state(clone: Path) -> dict:
    return {
        "branch": git(clone, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": git(clone, "rev-parse", "HEAD"),
        "status": git(clone, "status", "--porcelain"),
        "branches": sorted(git(clone, "branch", "--format=%(refname:short)").splitlines()),
        "branch_shas": dict(line.split(" ", 1)[::-1] for line in
                            git(clone, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads").splitlines()),
    }


GH_MERGE_KEYS = {"checks": "MOCK_GH_CHECKS", "merge_state": "MOCK_GH_MERGE_STATE", "methods": "MOCK_GH_MERGE_METHODS",
                 "reviews": "MOCK_GH_REVIEWS"}
GH_CHECKS = ("none", "pass", "pending", "fail")
GH_METHODS = ("merge", "squash", "rebase")
GH_STUB = REPO / "tests" / "mocks" / "bin" / "gh_stub.py"


def _check_reviews(spec) -> None:
    """setup.gh_merge.reviews를 gh 스텁과 같은 파서(`parse_reviews`)로 검사한다. 틀리면 SystemExit."""
    import importlib.util
    if not isinstance(spec, str) or not spec.strip():
        raise SystemExit(f"setup.gh_merge.reviews는 글(`[<PR|브랜치>=]<종류>:<login>@<커밋>`, 쉼표 목록): {spec!r}")
    loader = importlib.util.spec_from_file_location("tt_gh_stub", GH_STUB)
    stub = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(stub)
    try:
        stub.parse_reviews(spec)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — 스텁은 형식 오류를 예외나 종료로 알린다
        raise SystemExit(f"setup.gh_merge.reviews 형식 오류: {spec!r} ({exc})") from None


def gh_merge_env(spec) -> dict[str, str]:
    """setup.gh_merge → gh 스텁 환경 변수(`tests/mocks/bin/gh_stub.py` 머리말). 없으면 {} — 스텁 기본값 그대로."""
    if not spec:
        return {}
    if not isinstance(spec, dict) or set(spec) - set(GH_MERGE_KEYS):
        raise SystemExit(f"setup.gh_merge 키는 {sorted(GH_MERGE_KEYS)}: {spec}")
    if spec.get("checks") not in (None, *GH_CHECKS):
        raise SystemExit(f"setup.gh_merge.checks는 {'|'.join(GH_CHECKS)}: {spec['checks']}")
    methods = [m for m in str(spec.get("methods") or ",".join(GH_METHODS)).split(",") if m]
    if not methods or set(methods) - set(GH_METHODS):
        raise SystemExit(f"setup.gh_merge.methods는 {','.join(GH_METHODS)} 중 쉼표로: {spec.get('methods')}")
    if "reviews" in spec:
        _check_reviews(spec["reviews"])
    return {GH_MERGE_KEYS[k]: str(v) for k, v in spec.items() if v not in (None, "")}


def _tilde_keys(value, at: str = "") -> list[str]:
    """`~`로 시작하는 문자열 값의 키 경로. eval config는 절대 경로만 쓴다 — guard hook은 실제 HOME, Bash는 격리 홈으로 `~`를 푼다."""
    if isinstance(value, dict):
        return [k for key, v in value.items() for k in _tilde_keys(v, f"{at}{key}.")]
    if isinstance(value, list):
        return [k for v in value for k in _tilde_keys(v, at)]
    return [at.rstrip(".")] if isinstance(value, str) and value.startswith("~") else []


def tracker_servers(env: dict) -> dict:
    """eval의 모의 트래커 MCP 서버(`mcpServers` 항목): `mock-jira`, github eval이면 `mock-github-issues`도.
    run.py `--mcp-config`와 격리 홈의 `.claude.json`(사용자 범위)이 같은 정의를 쓴다."""
    out = {"mock-jira": {"command": sys.executable, "args": [JIRA_MCP_PY.as_posix()],
                         "env": {k: env[k] for k in ("MOCK_JIRA_DIR", "MOCK_JIRA_WRITE_LOG", "PYTHONIOENCODING")}}}
    if "MOCK_GH_ISSUES_DIR" in env:
        out[GH_SERVER] = {"command": sys.executable, "args": [GH_MCP_PY.as_posix()],
                          "env": {k: env[k] for k in ("MOCK_GH_ISSUES_DIR", "MOCK_GH_ISSUES_WRITE_LOG", "PYTHONIOENCODING")}}
    return out


def _fresh_user(ws: Workspace, user_home: Path) -> None:
    """setup.fresh_user: 사용자 config와 이슈 DB clone을 지우고, 격리 홈에서 모의 GHE URL이 로컬 bare 원격으로 clone되게 한다."""
    import yaml
    cfg = ws.home / "config.yaml"
    url = yaml.safe_load(cfg.read_text(encoding="utf-8"))["issue_db"]["remote"]
    cfg.unlink()
    for p in ws.clone.rglob("*"):       # Windows: git 객체 파일은 읽기 전용이라 그대로는 지워지지 않는다
        if not p.is_symlink():
            p.chmod(p.stat().st_mode | stat.S_IWUSR)
    shutil.rmtree(ws.clone)
    subprocess.run(["git", "config", "--file", str(user_home / ".gitconfig"), f"url.{ws.remote.as_posix()}.insteadOf", url],
                   check=True, capture_output=True)


def build(entry: dict, out: Path, direct_tools: bool = True) -> dict:
    """direct_tools=False(plugin 모드)면 env.json에 jira_call·jira_tools_list·analyzer_run을 쓰지 않는다 —
    실행자가 MCP·Skill 대신 그 명령을 직접 부르는 우회를 막는다."""
    setup = entry.get("setup") or {}
    out = out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    # site_defaults: site-defaults.yaml 최상위 키 덮어쓰기 (예: eval 39의 빈 tracker.tools)
    github = setup.get("tracker") == "github"
    if setup.get("tracker") not in (None, "jira", "github"):
        raise SystemExit(f"setup.tracker는 jira|github: {setup.get('tracker')}")
    overrides = dict(setup.get("site_defaults") or {})
    if github:   # 두 번째 트래커: tracker 블록은 github 예시, site_defaults.tracker의 키가 우선
        overrides["tracker"] = github_defaults(**(overrides.get("tracker") or {}))["tracker"]
    module_url, module_sha = module_remote(setup.get("module_skills"), out)
    if module_url:      # URL이 env 디렉토리마다 달라 plugin_root 캐시 키도 다르다
        overrides["module_skills"] = {"remote": module_url}
    root = plugin_root("eval", **overrides) if overrides else plugin_root()
    db_src = fixture_db(setup.get("db", "issue-db-github" if github else "issue-db-sample"))
    ws = Workspace(src=db_src, root=root)

    jira_dir = out / "jira"
    jira_dir.mkdir()
    for key in setup.get("jira") or []:
        shutil.copyfile(_find_jira(key), jira_dir / f"{key}.yaml")
    gh_dir = out / "gh_issues"
    if github or setup.get("gh_issues"):
        gh_dir.mkdir()
        for key in setup.get("gh_issues") or []:
            shutil.copyfile(_find_gh_issue(key), gh_dir / f"{key}.yaml")

    logs = out / "logs"
    logs.mkdir()
    for item in setup.get("logs") or []:
        if "src" in item:
            dest = logs / item.get("as", Path(item["src"]).name)
            shutil.copyfile(fixture_path(item["src"]), dest)
        elif item.get("split_buffers"):
            tmp = out / "_gen"
            for f in _gen(EVALS / "scenarios" / item["scenario"], tmp, name=item["as"], split=True):
                if not f.name.endswith(".expect.yaml"):
                    shutil.copyfile(f, logs / f.name)       # <as>.<buffer>.log
            shutil.rmtree(tmp)
        else:
            tmp = out / "_gen"
            files = _gen(EVALS / "scenarios" / item["scenario"], tmp, bugreport=item.get("bugreport"))
            main = [f for f in files if not f.name.endswith(".expect.yaml")]
            if item.get("bugreport"):
                main = [f for f in main if f.suffix in (".zip", ".txt") and "bugreport" in f.name] or main
            shutil.copyfile(main[0], logs / item.get("as", main[0].name))
            shutil.rmtree(tmp)

    for inj in setup.get("inject_main") or []:
        def edit(other: Path, inj=inj):
            for f in _gen(EVALS / "scenarios" / inj["scenario"], out / "_inj"):
                dest = other / inj["dest"] / f.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dest)
            subprocess.run([sys.executable, str(root / "scripts" / "db_build.py"), "--write", "--db", str(other)],
                           check=True, capture_output=True, env=mock_env.env_with_mocks(plugin_root=root))
        ws.push_main(edit, inj.get("message", "eval 사전 주입"))
        shutil.rmtree(out / "_inj", ignore_errors=True)
    if setup.get("inject_main"):
        git(ws.clone, "pull", "-q", "--ff-only")

    pubs = setup.get("published_pr") or []
    for pr in [pubs] if isinstance(pubs, dict) else pubs:     # 목록이면 순서대로 올린다(PR 번호 1, 2…)
        plan = json.loads((EVALS / "plans" / pr["plan"]).read_text(encoding="utf-8"))
        for rel, src in (pr.get("files") or {}).items():
            ws.put(pr["job"], rel, fixture_path(src))
        text = json.dumps(plan, ensure_ascii=False).replace("<JOB>", str(ws.job_dir(pr["job"])).replace("\\", "/"))
        ws.plan(pr["job"], json.loads(text))
        ws.ship(pr["job"], pr["branch"])
        git(ws.clone, "fetch", "-q", "origin")
    seed = setup.get("seed_plan")
    if seed:
        plan = json.loads((EVALS / "plans" / seed["plan"]).read_text(encoding="utf-8"))
        for rel, src in (seed.get("files") or {}).items():
            ws.put(seed["job"], rel, fixture_path(src))
        text = json.dumps(plan, ensure_ascii=False).replace("<JOB>", str(ws.job_dir(seed["job"])).replace("\\", "/"))
        ws.plan(seed["job"], json.loads(text))
    for name in setup.get("main_after_pr") or []:
        holder = {}
        ws.push_main(lambda other, n=name: holder.setdefault("msg", MAIN_EDITS[n](other, ws)), f"eval {name}")  # noqa: B023 — push_main이 바로 부른다

    remote_edit = setup.get("remote_after_pr")
    if remote_edit:
        def edit_remote(other: Path):
            for rel, text in remote_edit.get("files", {}).items():
                path = (other / rel).resolve()
                if not path.is_relative_to(other.resolve()):
                    raise ValueError(f"원격 편집 경로가 작업 트리 밖임: {rel}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
        ws.push_branch(remote_edit["branch"], edit_remote,
                       remote_edit.get("message", "eval: 제3자의 원격 브랜치 변경"))

    if setup.get("user_config"):
        import yaml
        cfg_path = ws.home / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        extra = json.loads(json.dumps(setup["user_config"]).replace("<MOCK_SRC>", (REPO / "tests" / "mocks" / "src").as_posix()))
        cfg.update(extra)
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")

    for lo in setup.get("leftovers") or []:   # 다른 작업이 남긴 worktree·도구 브랜치 (before.json 전에 만든다)
        wt = ws.wt(lo["job"])
        wt.parent.mkdir(parents=True, exist_ok=True)
        git(ws.clone, "worktree", "add", "--no-track", "-B", lo.get("branch") or f"tt/{lo['job']}", str(wt), "origin/main")

    cs = setup.get("clone_state") or {}
    for br in cs.get("local_branches") or []:   # 사용자의 로컬 브랜치 (도구가 건드리면 안 된다)
        git(ws.clone, "branch", br, "HEAD~0")
    if cs.get("branch"):
        git(ws.clone, "checkout", "-q", "-b", cs["branch"])
    for rel, text in (cs.get("dirty") or {}).items():   # 커밋하지 않은 사용자 변경
        path = ws.clone / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    env = {
        "CLAUDE_PLUGIN_ROOT": str(root),
        "TELEPHONY_TRIAGE_HOME": str(ws.home),
        "MOCK_GH_STATE_DIR": str(ws.gh_state),
        "MOCK_JIRA_DIR": str(jira_dir),
        "MOCK_JIRA_WRITE_LOG": str(out / "jira-writes.json"),
        "PYTHONIOENCODING": "utf-8",
    }
    if gh_dir.is_dir():     # 모의 GitHub Issues MCP(트래커 범용화 §6-3) — github eval에서만
        env["MOCK_GH_ISSUES_DIR"] = str(gh_dir)
        env["MOCK_GH_ISSUES_WRITE_LOG"] = str(out / "gh-issues-writes.json")
    if setup.get("gh_unauth"):
        env["MOCK_GH_UNAUTH"] = "1"
    env.update(gh_merge_env(setup.get("gh_merge")))
    import yaml
    tilde = _tilde_keys(yaml.safe_load((ws.home / "config.yaml").read_text(encoding="utf-8")) or {})
    if tilde:
        raise SystemExit(f"eval 사용자 config는 절대 경로만(`~` 금지 — guard와 Bash의 HOME이 다르다): {tilde}")
    # Bash 격리 홈: 사용자 범위 MCP 등록은 모의 트래커뿐(setup 0번 tracker-candidates가 읽는다). env(자식 claude 프로세스)에는 넣지 않는다
    user_home = out / "user-home"
    user_home.mkdir()
    (user_home / ".claude.json").write_text(json.dumps({"mcpServers": tracker_servers(env)}, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    homes = {"HOME": _bash_path(str(user_home)), "PYTHONUSERBASE": site.getuserbase()}
    if os.name == "nt":     # Windows Python의 Path.home()은 USERPROFILE을 본다
        homes["USERPROFILE"] = str(user_home)
    path_dirs = [str(p) for p in mock_env.gh_path_dirs()]
    lines = ["# 스킬 eval 환경 — `source`로 불러온다"]
    lines += [f"export {k}='{v}'" for k, v in {**env, **homes}.items()]
    # env.sh는 bash(Ubuntu, 또는 Windows 개발 PC의 Git Bash)가 읽으므로 PATH는 POSIX 형식으로 쓴다.
    posix = [_bash_path(p) for p in path_dirs]
    lines.append("export PATH='" + ":".join(posix) + "':\"$PATH\"")
    (out / "env.sh").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    info = {
        "eval_id": entry["id"], "env": env, "path_prefix": path_dirs,
        "plugin_root": str(root), "skill": str(root / "skills" / "telephony-triage"),
        "issue_db_clone": str(ws.clone), "remote": str(ws.remote), "work_dir": str(ws.work),
        "logs": sorted(str(p) for p in logs.iterdir()), "jira_dir": str(jira_dir),
        "gh_state": str(ws.gh_state), "user_home": str(user_home),
    }
    if setup.get("fresh_user"):     # 새 config는 work_dir를 저장하지 않는다 — 기본값(<홈>/work)에 lock·스냅샷이 생긴다
        info["work_dir"] = str(ws.home / "work")
    if gh_dir.is_dir():
        info["gh_issues_dir"] = str(gh_dir)
    if module_url:
        info.update(module_source=setup["module_skills"]["source"], module_remote_sha=module_sha)
    if direct_tools:
        call = GH_CALL if github else CALL      # 트래커 MCP 대신 부르는 명령(키 이름은 기존 그대로)
        info.update({
            "jira_call": f"python3 \"{call.as_posix()}\" <tool> '<arguments JSON>'",
            "jira_tools_list": f"python3 \"{call.as_posix()}\" --list",
            "analyzer_run": ("python3 -c \"import sys; sys.exit('mock-data-analyzer: internal error (timeout)')\" --input <입력 JSON 경로>"
                             if setup.get("analyzer_fail") else f"python3 \"{ANALYZER.as_posix()}\" --input <입력 JSON 경로>"),
        })
    (out / "env.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "before.json").write_text(json.dumps(_clone_state(ws.clone), ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    if setup.get("fresh_user"):
        _fresh_user(ws, user_home)
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("eval_id", type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--evals", default=str(EVALS / "evals.json"))
    args = parser.parse_args(argv)
    data = json.loads(Path(args.evals).read_text(encoding="utf-8"))
    entry = next((e for e in data["evals"] if e["id"] == args.eval_id), None)
    if entry is None:
        raise SystemExit(f"eval {args.eval_id} 없음")
    print(json.dumps(build(entry, Path(args.out)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
