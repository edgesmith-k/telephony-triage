#!/usr/bin/env python3
"""스킬 eval 한 건의 모의 환경을 만든다 (11-phases.md Phase 13, 10-skill-eval.md).

`tests/skill_evals/evals.json`의 항목 하나(`setup`)를 읽어 다음을 만든다.
- 테스트 헬퍼 플러그인 루트(`site-defaults.example.yaml` → `site-defaults.yaml`, 스킬 포함) = `CLAUDE_PLUGIN_ROOT`
- 임시 사용자 홈(`TELEPHONY_TRIAGE_HOME`)과 config, 모의 원격(bare) + 사용자 clone(`core.hooksPath .githooks`), gh 스텁 상태
- eval용 Jira 티켓 디렉토리(`MOCK_JIRA_DIR`), 로그 파일(`<out>/logs/`), 필요하면 main에 미리 넣은 변경·이미 올린 PR
- `<out>/env.sh`(export 목록)와 `<out>/env.json`(경로·상태), 채점용 `<out>/before.json`(사용자 clone 상태)

    python3 tests/helpers/skill_eval_env.py <eval id> --out <dir> [--evals tests/skill_evals/evals.json]

setup 필드 (모두 선택):
    db: tests/fixtures 아래 이슈 DB 이름 (기본 issue-db-sample)
    jira: [티켓 키]  — tests/skill_evals/jira, 없으면 tests/mocks/jira에서 찾는다
    logs: [{src: <레포 기준 경로> | scenario: <tests/skill_evals/scenarios 파일>, as: <파일명>, bugreport: zip|txt}]
        split_buffers: true — 버퍼별 파일 <as>.main.log·<as>.radio.log
    inject_main: [{scenario: <파일>, dest: <이슈 DB 안 디렉토리>, message: <커밋 메시지>}]
    published_pr: {job, branch, plan: <tests/skill_evals/plans 파일>, files: {<작업 디렉토리 기준 경로>: <레포 기준 원본>}}
    main_after_pr: [<이름>]  — 아래 MAIN_EDITS의 이름. 이미 올린 PR 뒤에 main을 바꾼다
    remote_after_pr: {branch, files: {<상대 경로>: <내용>}, message} — 제3자의 원격 PR 변경
    seed_plan: {job, plan, files} — 게시 전 계획을 작업 디렉토리에 보관
    user_config: {...}, site_defaults: {...}, clone_state: {branch, local_branches, dirty}
    analyzer_fail: true — 모의 분석 스킬 실패
    gh_unauth: true  — gh 스텁 인증 실패
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVALS = REPO / "tests" / "skill_evals"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_env  # noqa: E402
from runner import fixture_db, fixture_path, plugin_root  # noqa: E402
from workspace import Workspace, git  # noqa: E402

GEN = REPO / "tests" / "mocks" / "logcat_gen.py"
CALL = REPO / "tests" / "mocks" / "jira_mcp" / "call.py"
ANALYZER = REPO / "tests" / "mocks" / "skills" / "data-analyzer" / "run.py"


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
    android_versions: []
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
           "        android_versions: [\"16\"]\n"
           "      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/data/fail/DataFailCause.java\n"
           "        symbol: DataFailCause#toString\n"
           "        android_versions: [\"17\"]\n")
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


def _clone_state(clone: Path) -> dict:
    return {
        "branch": git(clone, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": git(clone, "rev-parse", "HEAD"),
        "status": git(clone, "status", "--porcelain"),
        "branches": sorted(git(clone, "branch", "--format=%(refname:short)").splitlines()),
        "branch_shas": dict(line.split(" ", 1)[::-1] for line in
                            git(clone, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads").splitlines()),
    }


def build(entry: dict, out: Path) -> dict:
    setup = entry.get("setup") or {}
    out = out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    # site_defaults: site-defaults.yaml 최상위 키 덮어쓰기 (예: eval 39의 빈 jira.tools)
    root = plugin_root("eval", **setup["site_defaults"]) if setup.get("site_defaults") else plugin_root()
    db_src = fixture_db(setup.get("db", "issue-db-sample"))
    ws = Workspace(src=db_src, root=root)

    jira_dir = out / "jira"
    jira_dir.mkdir()
    for key in setup.get("jira") or []:
        shutil.copyfile(_find_jira(key), jira_dir / f"{key}.yaml")

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

    pr = setup.get("published_pr")
    if pr:
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
        ws.push_main(lambda other, n=name: holder.setdefault("msg", MAIN_EDITS[n](other, ws)), f"eval {name}")

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
    if setup.get("gh_unauth"):
        env["MOCK_GH_UNAUTH"] = "1"
    path_dirs = [str(p) for p in mock_env.gh_path_dirs()]
    lines = ["# 스킬 eval 환경 — `source`로 불러온다"]
    lines += [f"export {k}='{v}'" for k, v in env.items()]
    # env.sh는 bash(Ubuntu, 또는 Windows 개발 PC의 Git Bash)가 읽으므로 PATH는 POSIX 형식으로 쓴다.
    posix = [_bash_path(p) for p in path_dirs]
    lines.append("export PATH='" + ":".join(posix) + "':\"$PATH\"")
    (out / "env.sh").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    info = {
        "eval_id": entry["id"], "env": env, "path_prefix": path_dirs,
        "plugin_root": str(root), "skill": str(root / "skills" / "telephony-triage"),
        "issue_db_clone": str(ws.clone), "remote": str(ws.remote), "work_dir": str(ws.work),
        "logs": sorted(str(p) for p in logs.iterdir()), "jira_dir": str(jira_dir),
        "jira_call": f"python3 \"{CALL.as_posix()}\" <tool> '<arguments JSON>'",
        "jira_tools_list": f"python3 \"{CALL.as_posix()}\" --list",
        "analyzer_run": (f"python3 -c \"import sys; sys.exit('mock-data-analyzer: internal error (timeout)')\" --input <입력 JSON 경로>"
                         if setup.get("analyzer_fail") else f"python3 \"{ANALYZER.as_posix()}\" --input <입력 JSON 경로>"),
        "gh_state": str(ws.gh_state),
    }
    (out / "env.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "before.json").write_text(json.dumps(_clone_state(ws.clone), ensure_ascii=False, indent=2),
                                     encoding="utf-8")
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
