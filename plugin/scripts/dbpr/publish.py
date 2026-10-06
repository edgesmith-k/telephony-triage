"""my-prs·preflight·stage·summary·승인 해시·publish·find-plan."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml
from common import userconfig, yamlio
from common import checks as checks_mod
from common import ghcli
import db_summary
from common.exitcodes import CHECK_FAILED, OK, USAGE

from .lock import PLAN, PR_FILE, REGRESS, STAGE, STATE, TOOL_PREFIX, UsageError, _iso, _read_json, _write_json, now
from . import worktree as _wt
from .worktree import (Ctx, _check_branch, _err_brief, _gh, _git, _job_of, _out, _owned_worktree,
                       _pending_files, _prepare_worktree, _ref_sha, _same_path, _worktrees, run_script)


PLAN_KEY_ALIASES = {"ops": "operations", "op": "operations", "operation": "operations", "steps": "operations",
                    "base": "base_sha", "sha": "base_sha", "schema": "schema_version"}
PLAN_KEY_HELP = {"base_sha": "base_sha = db_pr snapshot의 snapshot_sha",
                 "schema_version": "schema_version = SNAP issue-db.config.yaml"}


def _load_plan_checked(plan_path: Path, repo: Path, base_sha: str) -> dict:
    """계획 JSON을 읽고 최상위 키를 검사한다 (db_add apply와 같은 `schema/plan.schema.json`, 없으면 최소 검사).
    잘못되면 `계획 형식 오류:` UsageError — 하위 스크립트의 Traceback까지 가지 않게 한다."""
    try:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"계획 형식 오류: JSON을 읽을 수 없습니다 ({plan_path}): {str(exc)[:200]}") from exc
    if not isinstance(plan, dict):
        raise UsageError(f"계획 형식 오류: 계획은 JSON 객체여야 합니다 ({plan_path})")
    schema = None
    proc = _git(repo, "show", f"{base_sha}:schema/plan.schema.json", check=False)
    if proc.returncode == 0:
        try:
            schema = json.loads(proc.stdout)
        except ValueError:
            schema = None
    required = list((schema or {}).get("required") or []) if isinstance(schema, dict) else []
    props = list(((schema or {}).get("properties") or {}).keys()) if isinstance(schema, dict) else []
    problems = []
    if props:
        unknown = [k for k in plan if k not in props]
        if unknown:
            hints = []
            for key in unknown:
                near = PLAN_KEY_ALIASES.get(key) or next(iter(difflib.get_close_matches(key, props, 1, 0.6)), None)
                hints.append(f"{key} (→ {near}?)" if near else key)
            problems.append("알 수 없는 최상위 키 " + ", ".join(hints))
    else:
        required = ["operations", "base_sha"]
    missing = [k for k in required if k not in plan]
    if not props:
        if "operations" in plan and not isinstance(plan["operations"], list):
            missing.append("operations(목록)")
        if "base_sha" in plan and not isinstance(plan["base_sha"], str):
            missing.append("base_sha(문자열)")
    if missing:
        problems.append("필수 키 없음: " + ", ".join(missing))
    if problems:
        helps = [PLAN_KEY_HELP[k] for k in missing if k in PLAN_KEY_HELP]
        tail = " — write-flow.md §계획 형식" + (f" ({', '.join(helps)})" if helps else "")
        raise UsageError("계획 형식 오류: " + "; ".join(problems) + tail,
                         {"unknown_keys": [k for k in plan if props and k not in props], "missing_keys": missing})
    return plan


# -- preflight -----------------------------------------------------------------------------


def _open_prs(ctx: Ctx, extra: list[str], runner, fields: str = "number,title,url,headRefName") -> tuple[list | None, str | None]:
    """`gh pr list <extra> --state open` → (PR 목록 또는 None, 경고 또는 None). preflight·my-prs 공유."""
    proc = runner(ctx, ["pr", "list", *extra, "--state", "open", "--json", fields], ctx.repo)
    if proc.returncode == 0:
        try:
            found = json.loads(proc.stdout or "[]")
        except ValueError:
            return None, f"열린 PR을 확인하지 못했다 (gh): JSON 아님 {(proc.stdout or '').strip()[:100]}"
        if not isinstance(found, list):
            return None, f"열린 PR을 확인하지 못했다 (gh): 목록이 아님 {(proc.stdout or '').strip()[:100]}"
        return found, None
    return None, f"열린 PR을 확인하지 못했다 (gh): {(proc.stderr or '').strip()[:200]}"


def my_prs(ctx: Ctx) -> dict:
    """내 열린 PR과 base 이동 여부 (읽기 전용: fetch·lock·쓰기 없음)."""
    if not userconfig.get(ctx.cfg, "issue_db.path"):
        raise UsageError("config가 없거나 issue_db.path가 비어 있다. /telephony-triage:setup을 먼저 한다.")
    ctx.require_repo()
    note = "base_moved는 fetch 없이 로컬 원격 ref(origin/*) 기준이다. null이면 그 ref가 없다(미fetch)."
    try:
        found, warning = _open_prs(ctx, ["--author", "@me"], _gh, "number,title,url,headRefName,baseRefName")
    except UsageError as exc:    # gh 시간 초과도 경고로 돌린다 (sync는 계속한다)
        found, warning = None, f"열린 PR을 확인하지 못했다 (gh): {str(exc)[:200]}"
    if found is None:
        return {"base": ctx.base, "prs": None, "warnings": [warning], "note": note}
    prs = []
    for pr in found:
        head = f"refs/remotes/origin/{pr.get('headRefName')}"
        base = f"refs/remotes/origin/{pr.get('baseRefName') or ctx.base}"   # PR의 base, 없으면 config base
        moved = None
        if _ref_sha(ctx.repo, head) and _ref_sha(ctx.repo, base):
            code = _git(ctx.repo, "merge-base", "--is-ancestor", base, head, check=False).returncode
            moved = {0: False, 1: True}.get(code)
        prs.append({"number": pr.get("number"), "title": pr.get("title"), "url": pr.get("url"),
                    "head": pr.get("headRefName"), "base_moved": moved})
    return {"base": ctx.base, "prs": prs, "warnings": [], "note": note}


def preflight(ctx: Ctx, branch: str, search: str | None, jira: str | None) -> dict:
    ctx.require_repo()
    _check_branch(ctx, branch)
    _git(ctx.repo, "fetch", "--prune", "origin")
    tool = TOOL_PREFIX + branch
    tool_sha = _ref_sha(ctx.repo, f"refs/heads/{tool}")
    tool_wt = next((w["path"] for w in _worktrees(ctx.repo) if w.get("branch") == f"refs/heads/{tool}"), None)
    user_sha = _ref_sha(ctx.repo, f"refs/heads/{branch}")
    remote_sha = _ref_sha(ctx.repo, f"refs/remotes/origin/{branch}")
    ahead = 0
    if user_sha:
        against = f"refs/remotes/origin/{branch}" if remote_sha else f"refs/remotes/origin/{ctx.base}"
        ahead = int(_out(_git(ctx.repo, "rev-list", "--count", f"{against}..refs/heads/{branch}", check=False)) or 0)
    open_prs, warnings = None, []
    if search:
        open_prs, warning = _open_prs(ctx, ["--search", search], _gh)
        if warning:
            warnings.append(warning)
    jira_in_main = None
    if jira:
        names = _out(_git(ctx.repo, "ls-tree", "-r", "--name-only", f"origin/{ctx.base}", check=False)).splitlines()
        hit = next((n for n in names if re.fullmatch(rf"[^/]+/[^/]+/jira/{re.escape(jira)}\.yaml", n)), None)
        if hit:
            record = yamlio.loads(_out(_git(ctx.repo, "show", f"origin/{ctx.base}:{hit}", check=False))) or {}
            jira_in_main = {"path": hit, "cause": record.get("cause")}
    return {
        "branch": branch,
        "tool_branch": {"name": tool, "exists": bool(tool_sha), "sha": tool_sha, "worktree": tool_wt,
                        "residual": bool(tool_sha) and tool_wt is None},
        "user_branch": {"exists": bool(user_sha), "sha": user_sha, "ahead_of_remote": ahead},
        "remote_sha": remote_sha,
        "open_prs": open_prs,
        "jira_in_main": jira_in_main,
        "warnings": warnings,
    }


def stage(ctx: Ctx, plan_path: Path, wt: Path, branch: str, dry_run: bool) -> tuple[dict, int]:
    ctx.require_repo()
    job_dir, job = _job_of(wt, ctx)
    wt = Path(wt).expanduser().resolve()
    ctx.lock.touch(job)
    _check_branch(ctx, branch)
    tool = TOOL_PREFIX + branch
    _git(ctx.repo, "worktree", "prune")
    for w in _worktrees(ctx.repo):
        if w.get("branch") == f"refs/heads/{tool}" and not _same_path(w["path"], wt):
            raise UsageError(f"도구 브랜치 {tool}가 다른 worktree({w['path']})에 checkout돼 있습니다. 그 작업을 "
                             "끝내거나 db_pr cleanup으로 정리한다.", {"worktree": w["path"]})
    _git(ctx.repo, "fetch", "origin")
    base_sha = _ref_sha(ctx.repo, f"refs/remotes/origin/{ctx.base}")
    if not base_sha:
        raise UsageError(f"origin/{ctx.base}가 없습니다.")
    plan = _load_plan_checked(plan_path, ctx.repo, base_sha)
    try:
        old_state = _read_json(job_dir / STATE)
    except ValueError:
        old_state = None
    for name in (STAGE, PR_FILE, REGRESS):
        (job_dir / name).unlink(missing_ok=True)
    state = {"base_sha": base_sha, "branch": branch, "approved_hash": None, "commit_message": None,
             "staged_at": _iso(now())}
    ids_at_base = None   # 계획 당시(plan.base_sha) 트리 기준 임시 ID 할당 — drift가 계산한다
    if old_state and old_state.get("ids_at_base") and old_state.get("base_sha") == base_sha == plan.get("base_sha"):
        ids_at_base = old_state["ids_at_base"]
    state["ids_at_base"] = ids_at_base
    _write_json(job_dir / STATE, state)
    result: dict = {"job": job, "wt": str(wt), "branch": branch, "tool_branch": tool, "base_sha": base_sha,
                    "plan": str(Path(plan_path).resolve()), "dry_run": dry_run, "source": plan.get("source")}

    if plan.get("base_sha") != base_sha:
        code, data, err = run_script("db_add.py", ["drift", str(plan_path), "--onto", base_sha, "--db", str(ctx.repo)])
        if code == USAGE or data is None:
            raise UsageError(f"drift 검사 실패: {_err_brief(err)}")
        result["drift"] = data.get("drift") or []
        ids_at_base = data.get("ids_at_base")
        state["ids_at_base"] = ids_at_base
        _write_json(job_dir / STATE, state)
        if code == CHECK_FAILED:
            result["stopped"] = "drift"
            result["ids_at_base"] = ids_at_base
            result["next"] = ("drift 항목마다 계획 값(plan_value) 유지 / main 값(current_value) 유지(op 삭제) / 직접 입력을 "
                              "골라 계획에 반영한다. plan_base_value는 계획 당시 main 값이다. 반영하고 "
                              f"base_sha를 {base_sha}로 바꾼 뒤 다시 stage한다 (contracts.md §작업 계획 drift).")
            _write_json(job_dir / STAGE, result)
            return result, CHECK_FAILED
    else:
        result["drift"] = []

    result["ids_at_base"] = ids_at_base
    result["worktree"] = _prepare_worktree(ctx, wt, tool, base_sha)
    code, check, err = run_script("config.py", ["check", "--db", str(wt), "--for", "dry-run" if dry_run else "write"])
    result["config_check"] = check
    if code != OK:
        reasons = "; ".join(r.get("message", "") for r in (check or {}).get("reasons") or []) or err.strip()
        raise UsageError(f"쓰기 불가: {reasons}", result)

    pending = _pending_files(ctx, job_dir) if plan.get("source") == "analyze" else []
    args = ["apply", str(plan_path), "--db", str(wt)]
    for path in pending:
        args += ["--pending", str(path)]
    code, applied, err = run_script("db_add.py", args)
    result["apply"] = applied
    result["pending_sources"] = [str(p) for p in pending]
    if code != OK:
        _write_json(job_dir / STAGE, result)
        if code == USAGE:
            raise UsageError(f"계획을 적용할 수 없습니다: {_err_brief(err, 500)}", result)
        result["stopped"] = "apply"
        return result, code

    db_cfg = yamlio.load(wt / "issue-db.config.yaml") or {}
    ci_mode = db_cfg.get("ci_mode", "local")
    cctx = checks_mod.Ctx(db=wt, scope="worktree", ref=f"origin/{ctx.base}", ci_mode=ci_mode, db_cfg=db_cfg,
                          plan=plan_path, regress_json=job_dir / REGRESS, plugin_root=_wt._PLUGIN_ROOT)

    def save_regress(res: checks_mod.StepResult) -> None:
        if res.name == "regress":
            _write_json(job_dir / REGRESS, res.data or {})

    run = checks_mod.run_checks(checks_mod.PROFILES["stage"], cctx, on_step=save_regress)
    if run.aborted is not None:
        bad = run.aborted
        if bad.name == "verify":
            # 주의: verify의 실행 불가는 checks 없이 result만 싣고 STAGE도 쓰지 않는다 (기존 동작 유지).
            raise UsageError(f"db_verify 실행 불가: {_err_brief(bad.stderr)}", result)
        checks_so_far = _stage_checks(run)
        _write_json(job_dir / STAGE, {**result, "checks": checks_so_far})
        raise UsageError(f"{bad.script} 실행 불가: {_err_brief(bad.stderr)}", {**result, "checks": checks_so_far})
    if ci_mode != "actions-build":
        checks_out = _stage_checks(run)
    else:
        checks_out = {"skipped": "ci_mode: actions-build — 생성·검사는 CI가 한다 (13-actions.md)"}
    result["checks"] = checks_out
    final = run.overall   # 1 > 3 > 0 (2는 위에서 중단했다)
    result["result"] = {0: "ok", 1: "check-failed", 3: "needs-approval"}[final]
    _write_json(job_dir / STAGE, result)
    return result, final


def _stage_checks(run: checks_mod.Run) -> dict:
    """`Run`을 stage 결과의 `checks` 모양 `{이름: {code, result, stderr}}`으로 (verify는 stderr 없음)."""
    out: dict = {}
    for res in run.steps:
        out[res.name] = {"code": res.code, "result": res.data}
        if res.name != "verify":
            out[res.name]["stderr"] = res.stderr[-500:] if res.code else ""
    return out


def _brief_checks(checks: dict) -> dict:
    """통과(code 0)한 단계만 접는다. 비0 단계·skipped는 그대로(실패 세부는 숨기지 않는다)."""
    from db_verify import brief_rules
    out: dict = {}
    for name, step in checks.items():
        res = step.get("result") if isinstance(step, dict) else None
        if not isinstance(step, dict) or step.get("code") != OK or not isinstance(res, dict):
            out[name] = step
        elif name == "lint":
            out[name] = {"code": OK, "errors": len(res.get("errors") or []), "warnings": len(res.get("warnings") or [])}
        elif name == "mask":
            out[name] = {"code": OK, "checked": res.get("checked")}
        elif name == "regress":
            out[name] = {"code": OK, "summary": res.get("summary")}
        elif name == "verify":
            out[name] = {"code": OK, "result": brief_rules(res)}
        else:
            out[name] = {"code": OK}
    return out


def _brief_stage(result: dict, job_dir: Path) -> dict:
    """stage의 stdout 요약본. `stage.json`(`result` 그대로)에는 전체가 남는다. 통과한 부분만 접고 비성공은 그대로 둔다."""
    out = dict(result)
    if "config_check" in out and isinstance(out["config_check"], dict):
        cc = out["config_check"]
        out["config_check"] = {k: cc.get(k) for k in ("for", "writable", "push_allowed", "reasons") if k in cc}
    applied = out.get("apply")
    if isinstance(applied, dict) and not out.get("stopped"):
        out["apply"] = {k: applied[k] for k in ("ids", "changed", "fixtures", "feedback", "pending_included", "rejected")
                        if k in applied}
    if isinstance(out.get("checks"), dict):
        out["checks"] = _brief_checks(out["checks"])
    out["detail"] = str(job_dir / STAGE)
    if out != {**result, "detail": out["detail"]}:      # 실제로 접은 것이 있을 때만
        out["folded"] = f"통과 항목 상세는 접힘 — 전체: 같은 명령에 --verbose 또는 {job_dir / STAGE}"
    return out


# -- summary -------------------------------------------------------------------------------


def approved_hash(wt: Path) -> str:
    """워킹 트리 전체(.gitignore 적용)를 임시 index로 올린 트리 해시. 기존 파일의 모드를 유지하려고
    HEAD에서 시작한다(`read-tree HEAD` → `add -A` → `write-tree`)."""
    fd, idx = tempfile.mkstemp(prefix="tt-approve-index-")
    os.close(fd)
    os.unlink(idx)
    env = {**os.environ, "GIT_INDEX_FILE": idx}
    try:
        for args in (("read-tree", "HEAD"), ("add", "-A")):
            proc = _git(wt, *args, env=env)
            if proc.returncode != 0:
                raise UsageError(f"승인 해시 계산 실패 (git {' '.join(args)}): {proc.stderr.strip()}")
        proc = _git(wt, "write-tree", env=env)
        if proc.returncode != 0:
            raise UsageError(f"승인 해시 계산 실패: {proc.stderr.strip()}")
        return proc.stdout.strip()
    finally:
        if os.path.exists(idx):
            os.unlink(idx)


def summary(ctx: Ctx, wt: Path, markdown: bool = False) -> dict:
    job_dir, job = _job_of(wt, ctx)
    _owned_worktree(ctx, wt)
    wt = job_dir / wt.name
    ctx.lock.touch(job)
    state = _read_json(job_dir / STATE)
    stage_result = _read_json(job_dir / STAGE)
    if not state or not stage_result or not stage_result.get("apply"):
        raise UsageError("stage 결과가 없습니다. 먼저 db_pr stage를 한다.")
    plan = json.loads(Path(stage_result["plan"]).read_text(encoding="utf-8"))
    db_cfg = yamlio.load(wt / "issue-db.config.yaml") or {}
    push_note = None
    if stage_result.get("dry_run"):
        push_note = "push 안 함: --dry-run"
        gh_ok, _ = ghcli.auth_status(ctx.host)
        if not gh_ok:
            push_note = "push 불가: gh 인증 없음 (--dry-run)"
    remote_sha = _ref_sha(ctx.repo, f"refs/remotes/origin/{state['branch']}")
    open_prs = None
    search = db_summary.search_key(plan, stage_result["apply"])
    if search:
        proc = _gh(ctx, ["pr", "list", "--search", search, "--state", "open", "--json", "number,title,url"], wt)
        if proc.returncode == 0:
            open_prs = json.loads(proc.stdout or "[]")
    scr = db_summary.screen(wt, plan, stage_result, state, db_cfg, job=job, base=ctx.base, git=_git,
                            remote_sha=remote_sha, open_prs=open_prs, push_note=push_note)
    body = db_summary.pr_body(scr, plan)
    digest = approved_hash(wt)
    state.update(approved_hash=digest, commit_message=scr["commit_message"])
    _write_json(job_dir / STATE, state)
    _write_json(job_dir / PR_FILE, {"title": scr["pr_title"], "body": body, "reviewers": scr["reviewers"]})
    result = {**scr, "pr_body": body, "approved_hash": digest}
    if markdown:    # opt-in: 확인 화면 마크다운(JSON 키·상태 파일은 그대로, main이 `_markdown`을 꺼내 출력한다)
        extras = db_summary.screen_extras(wt, scr, stage_result["apply"].get("operations") or [], digest)
        result["_markdown"] = db_summary.render_markdown(scr, plan, extras)
    return result


# -- publish -------------------------------------------------------------------------------


def _schema_allows_pr_ids(repo: Path, base_sha: str) -> bool:
    """`base_sha` 커밋의 `schema/plan.schema.json`이 `pr.ids`를 아는가(옛 스키마는 `pr`의 알 수 없는 키를 거부해 재적용이 깨진다)."""
    proc = _git(repo, "show", f"{base_sha}:schema/plan.schema.json", check=False)
    try:
        return "ids" in json.loads(proc.stdout)["properties"]["pr"]["properties"] if proc.returncode == 0 else False
    except (ValueError, KeyError, TypeError):
        return False


_GUARD_FIX_TAIL = "계획을 고쳐 3번(stage --then-summary)부터 다시 한다."


def _guard_problems(plugin_root: str | None, wt: Path) -> list[str]:
    """guard.py 규칙 3·4(`check_commit`)와 같은 검사·같은 문구. staged 범위로 `PROFILES["guard"]`를 돌린다."""
    staged = [p for p in _git(wt, "diff", "--cached", "--name-only", "-z").stdout.split("\0") if p]
    if not staged:
        return []
    try:
        db_cfg = yamlio.load(wt / "issue-db.config.yaml") or {}
    except (OSError, ValueError):
        db_cfg = {}
    except yaml.YAMLError as exc:
        raise UsageError(f"issue-db.config.yaml을 읽을 수 없다 (YAML 오류): {str(exc)[-300:]}") from exc
    if not isinstance(db_cfg, dict):
        raise UsageError("issue-db.config.yaml이 매핑(dict)이 아니다. 이슈 DB 설정 문제다 — 보고하고 멈춘다.")
    ci_mode = db_cfg.get("ci_mode", "local")
    branch = _out(_git(wt, "rev-parse", "--abbrev-ref", "HEAD", check=False)) if ci_mode != "actions-build" else ""
    cctx = checks_mod.Ctx(db=wt, scope="staged", files=staged, branch=branch, ci_mode=ci_mode, db_cfg=db_cfg,
                          plugin_root=plugin_root)
    return checks_mod.guard_deny_messages(checks_mod.run_checks(checks_mod.PROFILES["guard"], cctx).steps,
                                          fix_tail=_GUARD_FIX_TAIL)


def _commit_approved(wt: Path, job_dir: Path, state: dict, approved: str) -> tuple[dict, list[str] | None]:
    """`publish --commit`의 커밋 단계. (commit 정보, 실패 problems 또는 None). 이미 커밋이 있으면 건너뛴다(멱등)."""
    if _out(_git(wt, "rev-parse", "HEAD", check=False)) != state.get("base_sha"):
        return {"skipped": "이미 커밋됨"}, None
    fail = {"committed": False}
    digest = approved_hash(wt)
    if digest != approved or digest != state["approved_hash"]:
        return fail, ["승인 뒤 파일이 바뀌었다 (현재 트리가 승인 해시와 다르다). 확인 화면을 다시 받는다."]
    hooks = _out(_git(wt, "config", "--get", "core.hooksPath", check=False))
    if hooks != ".githooks":
        raise UsageError(f"이 레포의 core.hooksPath가 '{hooks or '(없음)'}'다. 정확히 .githooks여야 커밋할 수 있다 "
                         "(규칙 5). /telephony-triage:setup 을 다시 실행한다.")
    _git(wt, "add", "-A")
    deny = _guard_problems(_wt._PLUGIN_ROOT, wt)
    if deny:
        return fail, deny
    msg_file = job_dir / "commit-msg.txt"      # worktree 밖. 메시지는 셸을 거치지 않는 데이터다
    msg_file.write_text(state.get("commit_message") or "", encoding="utf-8", newline="\n")
    try:
        proc = _git(wt, "commit", "-q", "-F", str(msg_file), check=False)
    finally:
        msg_file.unlink(missing_ok=True)
    if proc.returncode != 0:
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return fail, [f"git commit 실패 (pre-commit hook 등): {output[-800:]}"]
    return {"committed": True, "sha": _out(_git(wt, "rev-parse", "HEAD"))}, None


def publish(ctx: Ctx, wt: Path, branch: str, lease: str, approved: str, commit: bool = False) -> tuple[dict, int]:
    job_dir, job = _job_of(wt, ctx)
    _owned_worktree(ctx, wt)
    wt = job_dir / wt.name
    ctx.lock.touch(job)
    state = _read_json(job_dir / STATE)
    stage_result = _read_json(job_dir / STAGE) or {}
    pr_info = _read_json(job_dir / PR_FILE)
    if not state or not state.get("approved_hash") or not pr_info:
        raise UsageError("승인 정보가 없습니다. stage --then-summary(확인) 뒤 publish --commit한다.")
    commit_info = None
    if commit:
        commit_info, early = _commit_approved(wt, job_dir, state, approved)
        if early is not None:
            return {"published": False, "commit": commit_info, "problems": early}, CHECK_FAILED
    extra = {"commit": commit_info} if commit_info is not None else {}
    problems = []
    tree = _out(_git(wt, "rev-parse", "HEAD^{tree}", check=False))
    if tree != approved or tree != state["approved_hash"]:
        problems.append("커밋 트리가 승인 해시와 다르다 (승인 뒤 파일이 바뀌었다). 확인 화면을 다시 받는다.")
    parent = _out(_git(wt, "rev-parse", "HEAD^", check=False))
    merge = _out(_git(wt, "rev-parse", "--verify", "--quiet", "HEAD^2", check=False))
    if parent != state["base_sha"] or merge:
        problems.append("커밋이 기준 SHA 위의 커밋 하나가 아니다 (커밋이 둘 이상이거나 머지 커밋이거나 기준이 다르다).")
    message = _git(wt, "log", "-1", "--format=%B", "HEAD", check=False).stdout.strip()
    if message != (state.get("commit_message") or "").strip():
        problems.append("커밋 메시지가 확인받은 메시지와 다르다. trailer(Co-Authored-By 등)나 서명 줄을 덧붙이지 않는다 — "
                        "summary의 commit_message 그대로 커밋한다.")
    if branch != state["branch"] or branch == ctx.base:
        problems.append(f"브랜치 {branch}가 stage한 브랜치 {state['branch']}와 다르거나 base 브랜치다.")
    if problems:
        return {"published": False, **extra, "problems": problems}, CHECK_FAILED
    lease_arg = (f"--force-with-lease=refs/heads/{branch}:" if lease == "new"
                 else f"--force-with-lease=refs/heads/{branch}:{lease}")
    env = {**os.environ, "TT_PUBLISH_TOKEN": approved}
    push = _git(wt, "push", lease_arg, "origin", f"HEAD:refs/heads/{branch}", check=False, env=env)
    if push.returncode != 0:
        return {"published": False, "pushed": False, **extra,
                "problems": ["push가 거부됐다 (원격 브랜치가 그 사이 바뀌었거나 lease가 다르다). 원격 상태를 다시 "
                             "확인하고(preflight) 처음부터 다시 한다."],
                "stderr": push.stderr.strip()[-800:]}, CHECK_FAILED
    head = _out(_git(wt, "rev-parse", "HEAD"))
    _git(ctx.repo, "fetch", "origin", check=False)
    body_file = job_dir / "pr-body.md"
    body_file.write_text(pr_info["body"], encoding="utf-8", newline="\n")
    number, url, action, gh_error = None, None, None, None
    try:
        proc = _gh(ctx, ["pr", "list", "--head", branch, "--state", "open", "--json", "number,url"], wt)
        existing = json.loads(proc.stdout or "[]") if proc.returncode == 0 else []
        if existing:
            number, url = existing[0]["number"], existing[0].get("url")
            proc = _gh(ctx, ["pr", "edit", str(number), "--title", pr_info["title"], "--body-file", str(body_file)],
                       wt)
            action = "edited"
        else:
            args = ["pr", "create", "--base", ctx.base, "--head", branch, "--title", pr_info["title"],
                    "--body-file", str(body_file)]
            for r in pr_info.get("reviewers") or []:
                args += ["--reviewer", r]
            proc = _gh(ctx, args, wt)
            action = "created"
            if proc.returncode == 0:
                url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None
                m = re.search(r"/pull/(\d+)", url or "")
                number = int(m.group(1)) if m else None
        if proc.returncode != 0:
            gh_error = (proc.stderr or proc.stdout).strip()[:300]
    finally:
        body_file.unlink(missing_ok=True)
    # 계획 갱신 (pr, base_sha, included_pending)
    plan_path = Path(stage_result.get("plan") or job_dir / PLAN)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["pr"] = {"number": number, "branch": branch, "head_sha": head}
    applied_ids = {i["temp_id"]: i["id"] for i in (stage_result.get("apply") or {}).get("ids") or [] if i.get("temp_id")}
    ids_recorded = bool(applied_ids) and _schema_allows_pr_ids(ctx.repo, state["base_sha"])
    if ids_recorded:    # summary가 재할당(이전 적용 대비)을 보이는 데 쓴다. 검증에 쓴 base_sha의 스키마가 pr.ids를 알 때만
        plan["pr"]["ids"] = applied_ids
    plan["base_sha"] = state["base_sha"]
    included = {i["file"]: i for i in plan.get("included_pending") or []}
    inc_dir = job_dir / "included_pending"
    for src in stage_result.get("pending_sources") or []:
        src = Path(src)
        if src.parent != inc_dir and src.is_file():
            inc_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(inc_dir / src.name))
        included[src.name] = {"file": src.name, "pr": number}
    plan["included_pending"] = sorted(included.values(), key=lambda i: i["file"])
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    result = {"published": True, "pushed": True, **extra, "branch": branch, "head_sha": head, "lease": lease,
              "pr": {"number": number, "url": url, "action": action}, "plan": str(plan_path),
              "pr_ids_recorded": ids_recorded}
    if gh_error:
        result["gh_error"] = f"push는 됐지만 PR {action}에 실패했다: {gh_error}"
        return result, USAGE
    return result, OK


# -- find-plan (sync-pr) -------------------------------------------------------------------

MANUAL_RESYNC = [
    "자기 로컬 브랜치에서 git fetch origin 후 git rebase origin/<base>",
    "충돌이 생성 파일(README, 카테고리 README, STATS, CHANGELOG)뿐이면 main 쪽을 받고 db_build --write로 다시 만든다. "
    "다른 파일 충돌은 직접 해결한다",
    "새 ID가 main과 겹치면(db_add check-ids --base origin/<base>) db_add renumber <옛 ID>로 옮기고 "
    "db_lint --residual <옛 ID>=<새 ID>로 확인한다",
    "/telephony-triage:validate 통과 후 커밋하고 git push --force-with-lease로 올린다",
]


def find_plan(ctx: Ctx, branch: str) -> dict:
    ctx.require_repo()
    found = []
    for path in sorted(ctx.work_dir.glob(f"*/{PLAN}")) if ctx.work_dir.is_dir() else []:
        plan = _read_json(path) or {}
        if (plan.get("pr") or {}).get("branch") == branch:
            found.append((path, plan))
    if not found:
        return {"found": False, "branch": branch,
                "message": "이 브랜치의 작업 계획이 없다(직접 편집한 브랜치이거나 다른 PC에서 만든 PR). 도구는 이 브랜치를 "
                           "바꾸지 않는다. 아래 수동 재동기화 절차를 따른다 (06-collaboration.md §6.3).",
                "manual_steps": [s.replace("<base>", ctx.base) for s in MANUAL_RESYNC]}
    path, plan = found[0]
    _git(ctx.repo, "fetch", "--prune", "origin")
    remote_sha = _ref_sha(ctx.repo, f"refs/remotes/origin/{branch}")
    head_sha = (plan.get("pr") or {}).get("head_sha")
    changed = bool(remote_sha) and remote_sha != head_sha
    stat = None
    if changed and head_sha and _ref_sha(ctx.repo, head_sha):
        stat = _out(_git(ctx.repo, "diff", "--stat", head_sha, remote_sha, check=False))
    return {"found": True, "branch": branch, "job": path.parent.name, "plan": str(path), "pr": plan.get("pr"),
            "source": plan.get("source"), "schema_version": plan.get("schema_version"),
            "remote_sha": remote_sha, "remote_exists": bool(remote_sha), "remote_changed": changed,
            "remote_diff_stat": stat,
            "multiple": [str(p) for p, _ in found[1:]]}
