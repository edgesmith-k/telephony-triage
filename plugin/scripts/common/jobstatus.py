"""작업 상태 한 화면의 수집기 (`job_status.py`, contracts.md §3.2). 로컬 기록만 읽는다.

하지 않는 것: fetch·gh, lock 획득·갱신, git 쓰기(write-tree·승인 해시 재계산·worktree prune), 파일 쓰기·mkdir,
손상 파일 수리. git은 `<JOB>/wt` 안의 읽기(`rev-parse`, `log -1 --format=%P`, `--no-optional-locks status`)만 한다.
읽지 않는 것: `issue_raw.json`, `steps-pasted.txt` 내용(있는지만), 로그, `events.json`, `trace.jsonl` 내용(크기만),
needs_input 질문 문구(상태 파일에 없다: `pending {kind, asked_at}`만).

단계는 위에서부터 처음 맞는 것이다(`STAGES`). 줄마다 확신도: `now`(지금 확인) · `recorded`(기록, 시각) · `unknown`(확인 불가).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from common import issuepost, session_lock, userconfig

PLAN, STATE, STAGE, PR_FILE, PASTED_STEPS = "plan.json", "state.json", "stage.json", "pr.json", "steps-pasted.txt"
TRIAGE_STATE = "triage-state.json"
TRACE = "trace.jsonl"
REMOTE_NOTE = "원격 최신성: 확인하지 않음(로컬 기록만)"
CANDIDATES_MAX = 5
LABEL_MAX = 160
GIT_TIMEOUT = 20
MD_MAX = 3072                   # markdown 바이트 상한
STAGES = ("none", "pr-created", "pushed-no-pr", "committed", "needs-input", "summary-shown", "staged", "plan-saved",
          "needs-input-past", "analyzed", "started", "unknown")
# 파일별로 쓰는 중첩 값의 형식. 값이 null이면 통과, 형식이 다르면 그 파일을 손상으로 본다(고치지 않는다)
SHAPES = {
    PLAN: ((("issue",), dict), (("pr",), dict), (("feedback",), dict), (("pr", "number"), int), (("pr", "head_sha"), str),
           (("pr", "branch"), str), (("request_hash",), str), (("source",), str)),
    STATE: ((("approved_hash",), str), (("base_sha",), str), (("staged_at",), str), (("pr_digest",), str)),
    STAGE: ((("checks",), dict), (("drift",), list), (("result",), str), (("stopped",), str)),
    TRIAGE_STATE: ((("job",), dict), (("job", "runs"), list), (("pending",), dict), (("pending", "kind"), str),
                   (("pending", "asked_at"), str), (("snapshot",), dict), (("owner",), str), (("cleanup_targets",), int),
                   (("platform",), str)),
    "analysis.json": ((("issue",), dict), (("read_only_reasons",), list), (("must_show",), list), (("platform",), str),
                      (("status",), str), (("request_hash",), str), (("read_only_hint",), str)),
}


def _notes():
    """문구는 원본에서 가져온다(dbpr.worktree·issue_post: 읽기 전용 import)."""
    import issue_post
    from dbpr.worktree import RETAINED_NOTES
    return RETAINED_NOTES["unpublished"], RETAINED_NOTES["pushed-no-pr"], issue_post.STALE_REASON, issue_post.PLAN_OTHER_ANALYSIS


def _shape_problem(name: str, doc: dict) -> str | None:
    for path, kind in SHAPES.get(name, ()):
        node = doc
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None and not isinstance(node, kind):
            return ".".join(path)
    if name == TRIAGE_STATE:
        runs = (doc.get("job") or {}).get("runs") or []
        last = runs[-1] if runs else {}
        if not isinstance(last, dict) or not isinstance(last.get("top") or {}, dict):
            return "job.runs[-1]"
    return None


class StatusUsage(Exception):
    """종료 코드 2(플랫폼 불일치 등)."""


def _clip(text, n: int = LABEL_MAX) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _mtime(path: Path) -> str | None:
    try:
        return session_lock.iso(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))
    except OSError:
        return None


class _Files:
    """작업 디렉토리 JSON 읽기. 손상은 경고로 남기고 None(고치지 않는다)."""

    def __init__(self, job: Path, warnings: list):
        self.job, self.warnings, self.corrupt, self._cache = job, warnings, set(), {}

    def json(self, name: str) -> dict | None:
        if name not in self._cache:
            try:
                doc = issuepost.read_json(self.job / name)
                bad = _shape_problem(name, doc) if doc is not None else None
            except (OSError, ValueError, UnicodeDecodeError):
                doc, bad = None, "읽지 못함"
            if bad:
                self.corrupt.add(name)
                self.warnings.append(f"{name} 손상({bad}) — 고치지 않았다. 그 파일에 기대는 판단은 확인 불가")
                doc = None
            self._cache[name] = doc
        return self._cache[name]


def _git(wt: Path, *args: str) -> str | None:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        proc = subprocess.run(["git", "--no-optional-locks", "-C", str(wt), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _row(code: str, label: str, confidence: str, next_: str | None = None, at: str | None = None,
         evidence: list | None = None) -> dict:
    row = {"code": code, "label": _clip(label), "confidence": confidence}
    if at:
        row["at"] = at
    if evidence:
        row["evidence"] = [_clip(e, 120) for e in evidence]
    if next_:
        row["next"] = _clip(next_, 240)
    return row


def read_lock(work_dir: Path, key: str, owner: str | None) -> tuple[dict, dict | None]:
    """(화면용 lock 요약, 막힌 것 1건 또는 None). owner 토큰은 내지 않는다."""
    try:
        held = session_lock.describe(session_lock.read(work_dir))
    except session_lock.LockError:
        return ({"held": None, "corrupt": True},
                _row("lock-corrupt", "session.lock을 읽을 수 없다(손상) — 고치지 않았다", "now",
                     "그 세션이 끝났는지 확인하고, 사용자 확인 후에만 `db_pr lock release <작업 키> --force`"
                     "(.corrupt-<ts>로 백업 후 제거)"))
    if held is None:
        return {"held": False}, None
    mine = held.get("job") == key
    info = {"held": True, "mine": mine, "job": held.get("job"), "command": held.get("command"),
            "age_sec": held.get("age_sec"), "expired": held.get("expired")}
    info["same_session"] = bool(owner) and held.get("owner") == owner
    if not mine and not held.get("expired"):
        return info, _row("lock-other", f"다른 작업 {held.get('job')}({held.get('command')}, {held.get('age_sec')}초 전 갱신)이 "
                                        "세션 lock을 갖고 있다", "now",
                          f"그 세션이 진행 중인지 먼저 확인한다. 끝났다고 사용자가 확인한 뒤에만 "
                          f"`db_pr lock release {held.get('job')} --force`")
    if mine and held.get("expired"):
        return info, _row("lock-stale", f"이 작업의 lock이 {held.get('age_sec')}초 동안 갱신되지 않았다(만료) — 이전 세션이 "
                                        "끝났을 수 있다", "now", "같은 작업을 다시 시작하면 이어받는다(analyze 재실행)")
    return info, None


def quick_stage(job: Path) -> str:
    """후보 목록용 얕은 단계(파일만, git·lock 없음). 손상 파일은 `unknown`."""
    files = _Files(job, [])
    plan, state, tstate, analysis = (files.json(n) for n in (PLAN, STATE, TRIAGE_STATE, "analysis.json"))
    if files.corrupt:
        return "unknown"
    pr = (plan or {}).get("pr") or {}
    if pr.get("number"):
        return "pr-created"
    if pr.get("head_sha"):
        return "pushed-no-pr"
    if state and state.get("approved_hash") and (job / PR_FILE).is_file():
        return "summary-shown"
    if state is not None:
        return "staged"
    if plan is not None:
        return "plan-saved"
    if (tstate or {}).get("pending"):
        return "needs-input-past"
    if (analysis or {}).get("status") == "ok":
        return "analyzed"
    return "started"


def trace_rows(job: Path, tail: int | None = None) -> list[dict]:
    """`JOB/trace.jsonl`의 행(깨진 줄·객체 아닌 줄은 건너뛴다). `tail`이면 끝 `tail`바이트만 읽고 잘린 첫 줄은 버린다.
    없거나 못 읽으면 []. 읽는 곳: `usage_stats`(전체), `job_status`의 last-run-error(끝 일부)."""
    try:
        with (job / TRACE).open("rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - tail) if tail else 0)
            data = fh.read()
    except OSError:
        return []
    if tail and size > tail:
        data = data.partition(b"\n")[2]
    rows = []
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def candidates(work_dir: Path, safe_key_re) -> list[dict]:
    """작업 디렉토리 후보(최근 기록 순, `_`·`.` 폴더 제외)."""
    out = []
    try:
        entries = list(work_dir.iterdir())
    except OSError:
        return []
    for d in entries:
        if d.name.startswith(("_", ".")) or (safe_key_re is not None and not safe_key_re.fullmatch(d.name)):
            continue
        try:        # 훑는 도중 사라진 폴더·파일은 건너뛴다
            if not d.is_dir():
                continue
            stamps = [(d / n).stat().st_mtime for n in (PLAN, TRIAGE_STATE) if (d / n).is_file()]
            when = max(stamps) if stamps else d.stat().st_mtime
        except OSError:
            continue
        out.append((when, d.name))
    out.sort(reverse=True)
    return [{"key": name, "stage": quick_stage(work_dir / name),
             "at": session_lock.iso(datetime.fromtimestamp(when, timezone.utc))} for when, name in out]


def _post(key: str, platform: str | None, defaults: dict) -> dict:
    """Jira 코멘트 게시 상태(`issue_post status`와 같은 판정). 실패는 확인 불가와 사유."""
    try:
        import issue_post
        job = issue_post.Job(SimpleNamespace(key=key, platform=platform), defaults)
        out, _ = issue_post.cmd_status(None, job)
        return {k: out.get(k) for k in ("state", "postable", "reason", "posted_at")}
    except Exception as exc:  # noqa: BLE001 — 게시 칸 하나가 화면 전체를 막지 않는다
        return {"state": "확인 불가", "reason": _clip(str(exc) or type(exc).__name__, 120)}


def _next_for_question(kind: str) -> str:
    """질문 종류별 다음 할 일(triage.py needs_input 안내와 같은 말)."""
    if kind == "issue":
        return "Jira MCP 도구를 호출한 뒤 같은 analyze 명령을 다시 실행한다"
    if kind == "logs":
        return "로그를 `--logs`로 주고 같은 analyze 명령을 다시 실행한다"
    return f"질문({kind})에 답하고 같은 명령에 `--answer {kind}=<값>`을 붙여 다시 실행한다"


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def collect(work_dir: Path, key: str, cfg: dict, defaults: dict, platform: str | None = None,
            tracker: str | None = None) -> dict:
    """한 작업의 상태. 플랫폼 불일치는 `StatusUsage`."""
    unpublished, pushed_no_pr, stale_note, plan_other = _notes()
    work_dir = Path(work_dir)
    platform = platform or userconfig.TOP_PROFILE
    job = work_dir / key
    has_job = job.is_dir()
    warnings: list[str] = []
    files = _Files(job, warnings)
    blockers: list[dict] = []
    out: dict = {"key": key, "platform": platform}

    tstate = files.json(TRIAGE_STATE) if has_job else None
    analysis = files.json("analysis.json") if has_job else None
    done = (analysis or {}).get("platform") or userconfig.TOP_PROFILE
    if analysis and done != platform:
        raise StatusUsage(f"이 분석은 {done} 플랫폼이다(선택한 플랫폼: {platform}) — --platform {done}으로 다시 실행한다")
    recorded = (tstate or {}).get("platform")
    if recorded and recorded != platform:
        raise StatusUsage(f"이 작업은 {recorded} 플랫폼이다 — --platform {recorded}로 다시 실행한다")
    plan = files.json(PLAN) if has_job else None
    state = files.json(STATE) if has_job else None
    stage_doc = files.json(STAGE) if has_job else None

    # 대상 --------------------------------------------------------------------------------------------
    snap_meta = None
    try:
        snap_meta = issuepost.read_json(work_dir / session_lock.SNAPSHOT_META)
    except (OSError, ValueError, UnicodeDecodeError):
        warnings.append(f"{session_lock.SNAPSHOT_META} 손상(읽지 못함)")
    if snap_meta:
        snapshot = {"sha": str(snap_meta.get("sha") or "")[:12] or None, "base": snap_meta.get("base"),
                    "at": snap_meta.get("at"), "source": session_lock.SNAPSHOT_META}
    elif (tstate or {}).get("snapshot"):
        snapshot = {"sha": str(tstate["snapshot"].get("sha") or "")[:12] or None, "base": None, "at": None,
                    "source": TRIAGE_STATE}
    else:
        snapshot = None
    issue = (plan or {}).get("issue") or (analysis or {}).get("issue") or {}
    out["target"] = {"platform": platform, "tracker": tracker, "key": key,
                     "issue": {"key": issue.get("key") or key, "origin": issue.get("origin")},
                     "issue_db": str(userconfig.get(cfg, "issue_db.path") or "") or None, "work_dir": str(work_dir),
                     "snapshot": snapshot, "remote": REMOTE_NOTE}

    # lock -----------------------------------------------------------------------------------------------
    lock, lock_block = read_lock(work_dir, key, (tstate or {}).get("owner"))
    out["lock"] = lock
    if lock_block:
        blockers.append(lock_block)

    pending = (tstate or {}).get("pending") or None
    runs = ((tstate or {}).get("job") or {}).get("runs") or []
    last = runs[-1] if runs else {}
    wt = job / "wt"
    wt_exists = (wt / ".git").exists()
    pr = (plan or {}).get("pr") or {}
    approved = (state or {}).get("approved_hash")
    live_question = bool(pending) and TRIAGE_STATE not in files.corrupt and lock.get("mine") \
        and lock.get("same_session") and not lock.get("expired")

    def stage(id_: str, label: str, confidence: str, at: str | None = None, evidence: list | None = None) -> dict:
        row = {"id": id_, "label": _clip(label), "confidence": confidence}
        if at:
            row["at"] = at
        if evidence:
            row["evidence"] = [_clip(e, 120) for e in evidence]
        return row

    def unknown(name: str) -> dict:
        return stage("unknown", f"{name} 손상 — 단계 판단 불가(고치지 않았다)", "unknown")

    commit_info = None
    if wt_exists:
        heads = _git(wt, "rev-parse", "HEAD", "HEAD^{tree}")
        parents = _git(wt, "log", "-1", "--format=%P")
        dirty = _git(wt, "status", "--porcelain")
        if heads is None or parents is None:
            warnings.append("wt git 읽기 실패 — 커밋 여부 확인 불가")
        else:
            head, _, tree = heads.partition("\n")
            commit_info = {"head": head, "tree": tree.strip(), "parents": parents.split(),
                           "dirty": None if dirty is None else len([x for x in dirty.splitlines() if x.strip()])}
    at_pr_head = bool(commit_info and pr.get("head_sha") and commit_info["head"] == pr.get("head_sha"))
    # sync-pr 재적용: PR이 있는 계획을 같은 JOB에서 다시 stage한다(wt HEAD가 PR head가 아니다)
    resync = bool(pr.get("number")) and wt_exists and state is not None and not at_pr_head
    git_failed = wt_exists and commit_info is None
    if resync and git_failed:      # wt HEAD를 못 읽었다 — sync-pr 재적용으로 단정하지 않는다
        prefix = f"PR #{pr.get('number')} 확인 불가(git 읽기 실패) — "
    else:
        prefix = f"PR #{pr.get('number')} 재동기화 중(sync-pr) — " if resync else ""
    committed = bool(commit_info and state and commit_info["head"] != state.get("base_sha")
                     and commit_info["parents"] == [state.get("base_sha")])

    nxt = None
    if not has_job:
        st = stage("none", "작업 디렉토리 없음 — 이 키로 시작한 작업이 없다", "now")
        nxt = f"/telephony-triage:analyze {key} <로그 경로>"
    elif PLAN in files.corrupt:
        st = unknown(PLAN)
    elif pr.get("number") and not resync:
        st = stage("pr-created", f"PR #{pr['number']} 생성됨(브랜치 {pr.get('branch')}) — PR의 지금 상태는 확인하지 않았다",
                   "recorded", _mtime(job / PLAN), [f"plan.json pr.number {pr['number']}"])
        nxt = f"PR 리뷰·머지 대기. main이 바뀌었으면 /telephony-triage:sync-pr {pr.get('branch')}"
        if at_pr_head:
            nxt = f"PR은 만들어졌다. publish를 다시 하지 말고 db_pr discard {wt}만 다시 한다"
            blockers.append(_row("wt-after-pr", f"PR #{pr['number']} 생성 뒤 worktree가 남아 있다", "now", nxt))
        elif wt_exists:
            warnings.append("wt가 남아 있지만 HEAD가 PR head와 다르다(state.json 없음) — 용도 확인 불가")
    elif pr.get("head_sha") and not pr.get("number"):
        st = stage("pushed-no-pr", "push 기록 있음, PR 연결 미확인", "recorded", _mtime(job / PLAN),
                   [f"plan.json pr.head_sha {str(pr['head_sha'])[:12]}, pr.number 없음"])
        nxt = pushed_no_pr
        blockers.append(_row("pushed-no-pr", "push 기록 있음, PR 연결 미확인(PR 생성 실패로 단정하지 않는다)", "recorded",
                             pushed_no_pr, _mtime(job / PLAN)))
    elif STATE in files.corrupt:
        st = unknown(STATE)
    elif committed:
        ev = [f"wt HEAD {commit_info['head'][:12]}, 부모 = state.json base_sha"]
        if commit_info.get("dirty"):
            ev.append(f"커밋 뒤 wt 변경 {commit_info['dirty']}개")
        if not approved:
            st = stage("committed", prefix + "커밋됨 — 확인 화면 없음(approved_hash 없음)", "now", None, ev)
            nxt = f"db_pr summary {wt} --format markdown으로 확인 화면을 만들고 승인받는다"
        elif commit_info["tree"] == approved:
            st = stage("committed", prefix + "승인 트리 커밋됨(미push)", "now", None, ev)
            nxt = "확인 화면을 다시 보이고 사용자 승인을 받은 뒤에만 publish 한다(승인 여부는 기록되지 않는다)"
        else:
            st = stage("committed", prefix + "커밋됨 — 트리가 승인 해시와 다르다", "now", None, ev)
            nxt = f"승인 뒤 파일이 바뀌었다 — db_pr summary {wt} --format markdown을 다시 해 확인 화면을 새로 보이고 승인받는다"
            blockers.append(_row("approved-tree-mismatch", "커밋 트리가 승인 해시와 다르다(승인 뒤 파일이 바뀌었다)", "now", nxt))
    elif live_question:
        kind = str(pending.get("kind"))
        st = stage("needs-input", f"질문 대기: {kind}", "now", pending.get("asked_at"),
                   [f"lock 이 작업·같은 세션({lock.get('age_sec')}초 전 갱신)"])
        nxt = _next_for_question(kind)
    elif approved and (job / PR_FILE).is_file():
        st = stage("summary-shown", prefix + f"확인 화면 생성됨({str(approved)[:8]}) — 사용자 승인 여부는 기록되지 않는다",
                   "recorded", _mtime(job / PR_FILE),
                   ["state.json approved_hash", "pr.json 있음", "승인 뒤 파일 변경 여부: 확인 불가(승인 해시를 다시 계산하지 않는다)"])
        nxt = "확인 화면을 사용자에게 다시 보이고 승인받은 뒤에만 `publish --commit --and-discard`"
    elif state is not None:
        ev = [f"wt {'있음' if wt_exists else '없음'}(지금 확인)"]
        if commit_info and commit_info.get("dirty") is not None:
            ev.append(f"wt 변경 {commit_info['dirty']}개")
        fb = (stage_doc or {}).get("feedback_check")
        if fb:
            ev.append(f"feedback_check {fb if isinstance(fb, str) else json.dumps(fb, ensure_ascii=False)}")
        st = stage("staged", prefix + "계획을 worktree에 적용함(stage)", "recorded", state.get("staged_at"), ev)
        nxt = f"db_pr summary {wt} --format markdown으로 확인 화면을 만든다" if wt_exists else \
            "worktree가 없다 — 계획을 확인하고 `stage --then-summary`부터 다시 한다"
    elif plan is not None:
        fb = (plan.get("feedback") or {}).get("decision")
        st = stage("plan-saved", f"작업 계획 저장됨(source: {plan.get('source')}, 결정: {fb or '없음'}) — 미게시", "recorded",
                   _mtime(job / PLAN), [f"started_at {plan.get('started_at')}" if plan.get("started_at") else "plan.json"])
        nxt = unpublished + " — 이어서 하려면 같은 키로 analyze를 다시 실행해 이어서(resume)를 고른다"
        if plan.get("request_hash") and (analysis or {}).get("request_hash") \
                and plan["request_hash"] != analysis["request_hash"]:
            blockers.append(_row("plan-stale", f"{plan_other} — 계획이 지금 analysis.json과 다른 분석에서 나왔다", "recorded",
                                 "같은 키로 analyze를 다시 실행해 계획을 새로 저장할지 사용자에게 묻는다", _mtime(job / PLAN)))
    elif TRIAGE_STATE in files.corrupt:
        st = unknown(TRIAGE_STATE)
    elif pending:
        kind = str(pending.get("kind"))
        tail = "세션 상태 확인 불가" if kind == "lock" else "세션 끝남"
        st = stage("needs-input-past", f"마지막 질문 {kind} ({pending.get('asked_at')}) — {tail}", "recorded",
                   pending.get("asked_at"))
        nxt = f"같은 analyze 명령을 다시 실행하면 질문({kind})을 다시 받는다"
    elif "analysis.json" in files.corrupt:
        st = unknown("analysis.json")
    elif (analysis or {}).get("status") == "ok":
        top = last.get("top") or {}
        ev = [f"mode {last.get('mode') or analysis.get('mode')}, dry_run {last.get('dry_run')}",
              f"1위 {top.get('cause') or top.get('type') or '없음'}"]
        st = stage("analyzed", "분석 완료(analysis.json ok)", "recorded", last.get("at") or _mtime(job / "analysis.json"), ev)
        if last.get("request_hash") != analysis.get("request_hash"):
            blockers.append(_row("analysis-stale", stale_note, "recorded", "같은 키로 analyze를 다시 실행한다"))
            nxt = stale_note
        else:
            nxt = f"결과를 확인하고 기록(계획 저장)으로 잇거나, 기록하지 않으면 `triage.py release {key}`로 lock을 푼다"
    else:
        ev = [n for n in (TRIAGE_STATE, "trace.jsonl") if (job / n).is_file()]
        st = stage("started", "작업 디렉토리만 있다(분석 결과 없음)", "now", None, [f"{', '.join(ev)} 있음"] if ev else None)
        nxt = f"/telephony-triage:analyze {key} <로그 경로>로 다시 시작한다"
    if resync:
        st.setdefault("evidence", []).insert(0, f"plan.json pr.number {pr.get('number')}, "
                                                + ("wt git 읽기 실패 — 재동기화 여부 확인 불가" if git_failed else "wt HEAD ≠ pr.head_sha"))
    if pending and TRIAGE_STATE not in files.corrupt and st["id"] not in ("needs-input", "needs-input-past"):
        out["last_question"] = {"kind": pending.get("kind"), "asked_at": pending.get("asked_at"), "live": bool(live_question)}
        if live_question:
            blockers.append(_row("needs-input", f"analyze가 질문({pending.get('kind')})을 기다린다", "now",
                                 _next_for_question(str(pending.get("kind"))), pending.get("asked_at")))
    out["stage"] = st

    # stage.json·pr.json --------------------------------------------------------------------------------------
    # 지금 기다리는 질문(needs-input)이 단계를 앞서도 state.json이 있으면 stage 결과는 그대로 막힌 것이다
    staged_like = st["id"] in ("staged", "summary-shown", "committed") or (st["id"] == "needs-input" and state is not None)
    if stage_doc and state is not None and staged_like:
        checks = stage_doc.get("checks") or {}
        failed = [n for n, v in checks.items() if isinstance(v, dict) and v.get("code") not in (0, 3, None)]
        if stage_doc.get("stopped") in ("apply", "draft-verify"):
            failed.insert(0, stage_doc["stopped"])
        if stage_doc.get("result") == "check-failed" or failed:
            blockers.append(_row("stage-failed", f"stage 실패: {', '.join(map(str, failed)) or 'check-failed'}", "recorded",
                                 "계획을 고쳐 `stage --then-summary`부터 다시 한다", _mtime(job / STAGE)))
        if stage_doc.get("result") == "needs-approval" or any(isinstance(v, dict) and v.get("code") == 3
                                                               for v in checks.values()):
            blockers.append(_row("needs-approval", "승인 필요 항목 있음(stage 종료 3) — 확인 화면과 PR에 \"승인 필요\"로 보인다",
                                 "recorded", "확인 화면의 승인 필요 항목을 사용자에게 보인다(메인테이너 승인이 리뷰 조건)",
                                 _mtime(job / STAGE)))
        drift = stage_doc.get("drift") or []
        if drift or stage_doc.get("stopped") == "drift":
            blockers.append(_row("drift", f"drift {len(drift)}건 — 계획 대상이 main에서 바뀌었다", "recorded",
                                 "drift 항목마다 계획 값 유지 / main 값 유지 / 직접 입력을 사용자가 고른 뒤 다시 stage한다",
                                 _mtime(job / STAGE)))
    if approved and state.get("pr_digest") and (st["id"] in ("summary-shown", "committed") or staged_like) \
            and _sha256(job / PR_FILE) != state["pr_digest"]:
        blockers.append(_row("pr-json-changed", "pr.json이 확인 화면 뒤에 바뀌었다(없어졌다) — publish가 거부한다", "now",
                             f"db_pr summary {wt} --format markdown을 다시 해 확인 화면을 새로 보이고 승인받는다"))
    if has_job and (job / PASTED_STEPS).is_file():
        blockers.append(_row("pasted-steps-remains", "붙여넣은 스텝 원문(steps-pasted.txt)이 남아 있다", "now",
                             f"작업을 끝낼 때 db_pr discard 또는 `triage.py release {key}`가 지운다"))
    if (tstate or {}).get("cleanup_targets"):
        blockers.append(_row("cleanup-targets", f"잔여 worktree·도구 브랜치 {tstate['cleanup_targets']}개(마지막 analyze 기록)",
                             "recorded", "/telephony-triage:sync에서 정리"))
    if (analysis or {}).get("read_only_reasons"):
        blockers.append(_row("read-only", "읽기 전용 모드: " + ", ".join(map(str, analysis["read_only_reasons"])), "recorded",
                             analysis.get("read_only_hint") or "config.py check 사유를 확인한다"))
    out["blockers"] = blockers
    # 분석 리포트의 꼭 볼 줄(앞 2줄)은 막힌 것이 아니라 참고다
    out["must_show"] = [_clip(line) for line in ((analysis or {}).get("must_show") or [])[:2]]
    out["next"] = nxt

    out["approval"] = {"approved_hash_prefix": str(approved)[:8] if approved else None,
                       "staged_at": (state or {}).get("staged_at"), "user_approval": "unknown"}
    out["post"] = _post(key, platform, defaults) if has_job else {"state": "none"}
    names = {"plan": PLAN, "state": STATE, "stage": STAGE, "pr": PR_FILE, "analysis": "analysis.json",
             "report": "report.md", "post": issuepost.POST_FILE}
    found = {k: str(job / n) for k, n in names.items() if (job / n).is_file()}
    if wt_exists:
        found["wt"] = str(wt)
    trace = job / "trace.jsonl"
    try:
        found["trace"] = {"path": str(trace), "bytes": trace.stat().st_size}
    except OSError:
        pass
    out["files"] = found
    out["warnings"] = warnings
    return out


# -- markdown --------------------------------------------------------------------------------------------


def _tag(row: dict) -> str:
    c = row.get("confidence")
    if c == "now":
        return "[현재]"
    if c == "recorded":
        return f"[기록 {row['at']}]" if row.get("at") else "[기록]"
    return "[확인 불가]"


def _fit(lines: list, limit: int = MD_MAX) -> str:
    """`lines` = [(텍스트, 버림 순위 또는 None)]. 바이트 상한을 넘으면 순위가 큰 줄부터(같으면 뒤에서부터) 버리고
    마지막에 `- … 생략 N줄(근거·경고·파일 등, JSON 출력)`을 붙인다. 그래도 넘으면 줄마다 자르고, 끝으로 뒤에서부터 줄을 뺀다(생략 줄은 남는다)."""
    def size(rows, dropped):
        text = "\n".join(r[0] for r in rows) + "\n"
        if dropped:
            text += f"- … 생략 {dropped}줄(근거·경고·파일 등, JSON 출력)\n"
        return len(text.encode("utf-8")), text

    rows, dropped = list(lines), 0
    n, text = size(rows, dropped)
    while n > limit:
        cands = [i for i, r in enumerate(rows) if r[1] is not None]
        if not cands:     # 버릴 줄이 없다: 줄마다 자른다(마지막 수단)
            rows = [(_clip(r[0], 120), None) for r in rows]
            n, text = size(rows, dropped)
            while n > limit and rows:     # 그래도 넘으면 뒤에서부터 줄을 빼 생략 줄 자리를 남긴다(≤ limit 보장, 생략 표시 유지)
                rows.pop()
                dropped += 1
                n, text = size(rows, dropped)
            break
        top = max(rows[i][1] for i in cands)
        i = max(i for i in cands if rows[i][1] == top)
        rows.pop(i)
        dropped += 1
        n, text = size(rows, dropped)
    return text


def markdown(doc: dict) -> str:
    if "candidates" in doc:
        lines = [(f"## 작업 상태 후보 ({doc.get('platform')})", None), ("", None)]
        if not doc["candidates"]:
            lines.append(("- 작업 없음 — `/telephony-triage:analyze <JIRA-KEY> <로그 경로>`로 시작한다", None))
        for c in doc["candidates"]:
            lines.append((f"- {_clip(c['key'], 80)}: {c['stage']} [기록 {c['at']}]", 1))
        if doc["candidates"]:
            lines += [("", None), ("작업 키를 골라 `job_status.py <KEY>`로 다시 본다.", None)]
        return _fit(lines)
    t = doc["target"]
    issue = t["issue"]
    key = _clip(doc["key"], 80)
    L: list = [(f"## {key} 작업 상태 ({doc['platform']})", None), ("", None), ("### 대상", None),
               (f"- [현재] 트래커 {t.get('tracker')} · 이슈 {_clip(issue.get('key'), 80)}"
                + (f"(origin {issue['origin']})" if issue.get("origin") else ""), None)]
    snap = t.get("snapshot")
    if snap:
        L.append((f"- {_tag({'confidence': 'recorded', 'at': snap.get('at')})} 스냅샷 {snap.get('sha')}"
                  + (f" ({_clip(snap['base'], 40)})" if snap.get("base") else "") + f" — {snap.get('source')}", 3))
    L += [(f"- [확인 불가] {t['remote']}", None), ("", None), ("### 단계", None)]
    st = doc["stage"]
    L.append((f"- {_tag(st)} {st['id']}: {st['label']}", None))
    L += [(f"  - {e}", 4) for e in st.get("evidence") or []]
    lock = doc["lock"]
    if lock.get("corrupt"):
        L.append(("- [현재] lock: 손상", None))
    elif lock.get("held"):
        cmd = f"{_clip(lock['command'], 30)}, " if lock.get("command") else ""
        L.append((f"- [현재] lock: {_clip(lock.get('job'), 80)}({cmd}{lock.get('age_sec')}초 전"
                  + (", 만료" if lock.get("expired") else "") + ")", None))
    else:
        L.append(("- [현재] lock: 없음", None))
    q = doc.get("last_question")
    if q:
        L.append((f"- {_tag({'confidence': 'now' if q.get('live') else 'recorded', 'at': q.get('asked_at')})} "
                  f"마지막 analyze 실행이 질문({q.get('kind')})에서 멈췄다", None))
    post = doc.get("post") or {}
    if post.get("state") not in (None, "none"):
        tag = "[확인 불가]" if post.get("state") == "확인 불가" else "[기록]"
        L.append((f"- {tag} Jira 코멘트: {post.get('state')}" + (f" — {_clip(post['reason'], 120)}" if post.get("reason") else ""), 3))
    ap = doc.get("approval") or {}
    if ap.get("approved_hash_prefix"):
        L.append((f"- [확인 불가] 사용자 승인: 기록되지 않는다(확인 화면 {ap['approved_hash_prefix']})", None))
    for line in doc.get("must_show") or []:
        at = st.get("at") if st["id"] == "analyzed" else None
        L.append((f"- {_tag({'confidence': 'recorded', 'at': at})} 꼭 볼 것: {line}", 3))
    for w in doc.get("warnings") or []:
        L.append((f"- [확인 불가] {_clip(w, 120)}", 5))
    L += [("", None), ("### 막힌 것", None)]
    blockers = doc.get("blockers") or []
    for i, b in enumerate(blockers):
        L.append((f"- {_tag(b)} {b['code']}: {b['label']}", None if i == 0 else 2))
    if not blockers:
        L.append(("- 없음", None))
    L += [("", None), ("### 다음 할 일", None)]
    todo = [doc["next"]] if doc.get("next") else []
    for b in blockers:
        if b.get("next") and b["next"] not in todo:
            todo.append(b["next"])
    for i, x in enumerate(todo[:4]):
        L.append((f"- {_clip(x, 240)}", None if i == 0 else 2))
    if not todo:
        L.append(("- 없음", None))
    L += [("", None), ("### 관련 파일", None)]
    files = doc.get("files") or {}
    if files:
        names = []
        for k, v in files.items():
            if isinstance(v, dict):
                names.append(f"{Path(v['path']).name}({v['bytes']}B)")
            else:
                names.append(Path(v).name + ("/" if k == "wt" else ""))
        L.append((f"- `<work_dir>/{key}` ({_clip(t['work_dir'], 120)}): " + " · ".join(names), 6))
    else:
        L.append(("- 없음", None))
    return _fit(L)
