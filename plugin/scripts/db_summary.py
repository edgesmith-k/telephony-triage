"""db_summary.py — 라이브러리: `db_pr summary`가 확인 화면 데이터와 PR 본문을 만들 때 쓴다.

실행 파일이 아니다(shebang·main 없음). git 호출은 호출자(`db_pr`)가 `git(repo, *args, check=...)`로 넘긴다:
`db_pr`가 `__main__`으로 도는 동안 이 모듈이 `db_pr`를 import하면 두 번째 사본이 로드되므로 import하지 않는다.
lock·상태 파일·gh·승인 해시는 `db_pr`에 있다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from common import masking
from common.exitcodes import NEEDS_APPROVAL, OK
from common.issuedb import IssueDbError, parse_frontmatter_text

GENERATED_RE = re.compile(r"^(README\.md|STATS\.md|parser-rules/CHANGELOG\.md|[^/]+/README\.md)$")
SOURCE_LABELS = {"analyze": "분석 (analyze)", "record": "수동 기록 (record)", "import": "기존 분류 가져오기 (import)",
                 "fix-submitted": "수정 CL 반영 (fix-submitted)", "verify-fix": "코드 수정 검증 (verify-fix)",
                 "validate-cause": "해결책 검증 (validate --cause)", "review": "월간 리뷰 정리 (review)",
                 "move": "유형 이동·병합 (move)"}



def _status_entries(wt: Path, git) -> list[tuple[str, str]]:
    raw = git(wt, "status", "--porcelain=v1", "-z", "-uall").stdout
    out = []
    for entry in filter(None, raw.split("\0")):
        out.append((entry[:2], entry[3:]))
    return out


def _file_kind(path: str) -> str:
    if GENERATED_RE.match(path):
        return "생성 파일"
    if "/jira/" in path:
        return "Jira 기록"
    if path.startswith("feedback/"):
        return "피드백"
    if path.endswith("/type.md"):
        return "유형"
    if path.startswith("parser-rules/"):
        return "파서 규칙"
    if "/fixtures/" in path:
        return "fixture"
    return "기타"


def _codeowners(wt: Path) -> list[tuple[str, list[str]]]:
    path = wt / ".github" / "CODEOWNERS"
    rules = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            rules.append((parts[0], parts[1:]))
    return rules


def _owners_for(rules: list[tuple[str, list[str]]], rel: str) -> list[str]:
    owners: list[str] = []
    for pattern, who in rules:   # CODEOWNERS: 마지막으로 맞는 규칙이 이긴다
        p = pattern.lstrip("/")
        if (p.endswith("/") and rel.startswith(p)) or rel == p:
            owners = who
    return owners


def reviewers(wt: Path, paths: list[str], plan: dict, db_cfg: dict) -> list[str]:
    rules = _codeowners(wt)
    owners: list[str] = []
    for rel in paths:
        if GENERATED_RE.match(rel):   # 생성 파일은 원본 변경을 따라가므로 리뷰어 계산에서 뺀다
            continue
        owners += _owners_for(rules, rel)
        if rel.endswith("/type.md") and (wt / rel).is_file():
            from common.issuedb import read_frontmatter
            for sc in read_frontmatter(wt / rel).get("secondary_categories") or []:
                owners += _owners_for(rules, f"{sc}/")
    for op in plan.get("operations") or []:
        if op.get("op") == "allow-cause":
            name = str(op.get("fixture", "")).split("/")[-1]
            m = re.match(r"([A-Z][A-Z0-9]*)-\d{3}", name)
            cat = next((c["key"] for c in db_cfg.get("categories") or [] if m and c.get("id_prefix") == m.group(1)),
                       None)
            if cat:
                owners += _owners_for(rules, f"{cat}/")
    fmt = str((db_cfg.get("reviewers") or {}).get("format") or "{org}/{team}")
    out = []
    for owner in owners:
        org, _, team = owner.lstrip("@").partition("/")
        value = fmt.format(org=org, team=team) if team else owner.lstrip("@")
        if value not in out:
            out.append(value)
    return out


def _verification_rows(stage_result: dict) -> list[dict]:
    verify = ((stage_result.get("checks") or {}).get("verify") or {}).get("result") or {}
    rows = []
    for item in verify.get("rules") or []:
        shown = {"pass": "통과", "fail": "실패", "needs-approval": "승인 필요", "not-implemented": "미구현(뼈대)"}
        status = item.get("status")
        label = shown.get(status) or (f"건너뜀: {item.get('reason')}" if status == "skipped" else status)
        if status == "skipped" and item.get("review_required"):
            label = f"검증 못 함 — 리뷰 대상 ({item.get('reason')})"
        rows.append({"id": item.get("id"), "status": status, "label": label, "reason": item.get("reason"),
                     "review_required": item.get("review_required", False)})
    return rows


def _check_rows(stage_result: dict) -> dict:
    checks = stage_result.get("checks") or {}
    if "skipped" in checks:
        return {"skipped": checks["skipped"]}

    def res(name):
        return (checks.get(name) or {}).get("result") or {}

    lint, mask, ids, regress = res("lint"), res("mask"), res("ids"), res("regress")
    return {
        "lint": {"ok": (checks.get("lint") or {}).get("code") == OK, "errors": len(lint.get("errors") or []),
                 "warnings": len(lint.get("warnings") or []),
                 "findings": [f"{f.get('code')}: {f.get('file')}" for f in (lint.get("errors") or [])][:20]},
        "ids": {"ok": (checks.get("ids") or {}).get("code") == OK, "duplicates": ids.get("duplicates") or []},
        "mask": {"ok": (checks.get("mask") or {}).get("code") == OK, "detections": len(mask.get("detections") or [])},
        "regress": {"ok": (checks.get("regress") or {}).get("code") == OK,
                    "passed": (regress.get("summary") or {}).get("passed"),
                    "total": (regress.get("summary") or {}).get("total"),
                    "failed": [r.get("fixture") for r in regress.get("results") or [] if r.get("status") != "pass"]},
        "build": {"ok": (checks.get("build") or {}).get("code") == OK},
    }


def _readme_preview(wt: Path, keys: list[str]) -> list[str]:
    lines = []
    for path in [wt / "README.md", *sorted(wt.glob("*/README.md"))]:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if (line.startswith("|") or line.startswith("###")) and any(k in line for k in keys) and line not in lines:
                lines.append(line)
    return lines[:20]


def _main_diff(wt: Path, entries: list[tuple[str, str]], git) -> tuple[list[str], int]:
    tracked = [p for s, p in entries if s != "??" and not GENERATED_RE.match(p) and "/fixtures/" not in p]
    diff = git(wt, "diff", "--", *tracked, check=False).stdout.strip().splitlines() if tracked else []
    for status, path in entries:
        if status == "??" and not GENERATED_RE.match(path) and "/fixtures/" not in path:
            text = (wt / path).read_text(encoding="utf-8", errors="replace").splitlines()
            diff += [f"+++ {path} (신규)"] + ["+" + line for line in text]
    return diff[:50], len(diff)


def _builds(items) -> list[str]:
    """`fixed_in`·history의 `[{branch, build}]` → 표시용 빌드 목록(빌드가 없으면 브랜치)."""
    out = []
    for it in items or []:
        value = (it.get("build") or it.get("branch")) if isinstance(it, dict) else it
        if value and str(value) not in out:
            out.append(str(value))
    return out


def _cause_fix(data: dict | None, cause_id: str) -> dict | None:
    for cause in (data or {}).get("causes") or []:
        if isinstance(cause, dict) and cause.get("id") == cause_id:
            return cause.get("fix") or {}
    return None


def _detail(ref, builds: list[str]) -> str:
    return ", ".join(x for x in (f"ref {ref}" if ref else "", f"fixed_in {', '.join(builds)}" if builds else "") if x)


def fix_changes(wt: Path, entries: list[tuple[str, str]], operations: list[dict], base_sha: str | None, git) -> list[dict]:
    """적용된 `update-fix`·`verify-fix` op마다 원인의 수정 상태가 어떻게 바뀌었는지 → `[{cause, from, to, history, line}]`.

    "이전"은 `git show <base_sha>:<type.md>`의 frontmatter, "이후"는 작업 worktree의 파일이다. 이전 내용을 읽지 못하면 `from`은 None.
    `history`는 이번 변경으로 `verification_history`에 새로 들어간 항목 `{result, ref, fixed_in:[빌드]}`(없으면 None)다.
    """
    out, seen = [], set()
    for op in operations:
        cause = op.get("cause")
        if op.get("op") not in ("update-fix", "verify-fix") or not isinstance(cause, str) or cause in seen:
            continue
        seen.add(cause)
        type_id = cause.rsplit("-", 1)[0]
        pattern = re.compile(rf"^[^/]+/{re.escape(type_id)}-[^/]+/type\.md$")
        rel = next((p for _, p in entries if pattern.match(p)), None)
        if rel is None or not (wt / rel).is_file():
            continue
        try:
            after = _cause_fix(parse_frontmatter_text((wt / rel).read_text(encoding="utf-8"), rel), cause)
            proc = git(wt, "show", f"{base_sha}:{rel}", check=False) if base_sha else None
            before = (_cause_fix(parse_frontmatter_text(proc.stdout, rel), cause)
                      if proc is not None and proc.returncode == 0 else None)
        except IssueDbError:
            continue
        if after is None:
            continue
        old_hist = (before or {}).get("verification_history") or []
        new_hist = after.get("verification_history") or []
        added = new_hist[0] if len(new_hist) > len(old_hist) and isinstance(new_hist[0], dict) else None
        history = ({"result": added.get("result"), "ref": added.get("ref"), "fixed_in": _builds(added.get("fixed_in"))}
                   if added else None)
        src, dst = (before or {}).get("status"), after.get("status")
        detail = _detail(after.get("ref"), _builds(after.get("fixed_in")))
        if history and dst == "open" and src != "open":
            prev = "·".join(x for x in (f"이전 ref {history['ref']}" if history["ref"] else "",
                                        f"fixed_in {', '.join(history['fixed_in'])}" if history["fixed_in"] else "") if x)
            line = (f"{cause}: {src or '?'} → open ({prev + ' → ' if prev else ''}"
                    f"verification_history 보존, 결과 {history['result']})")
        elif history and src == dst:
            line = f"{cause}: verification_history에 {history['result']} 추가 (상태 {dst} 유지)"
        elif dst == "fixed" and src != "fixed":
            build = (after.get("verification") or {}).get("build")
            line = f"{cause}: {src or '?'} → fixed" + (f" (검증 빌드 {build})" if build else "")
        elif src != dst:
            line = f"{cause}: {src or '?'} → {dst}" + (f" ({detail})" if detail else "")
        else:
            line = f"{cause}: 수정 정보 갱신 ({dst})" + (f" — {detail}" if detail else "")
        out.append({"cause": cause, "from": src, "to": dst, "history": history, "line": line})
    return out


def search_key(plan: dict, applied: dict) -> str | None:
    """열린 PR을 찾는 gh 검색어: Jira 키, 없으면 첫 할당 ID."""
    ids = applied.get("ids") or []
    return (plan.get("jira") or {}).get("key") or (ids[0]["id"] if ids else None)


def screen(wt: Path, plan: dict, stage_result: dict, state: dict, db_cfg: dict, *, job: str, base: str, git,
           remote_sha: str | None, open_prs: list | None, push_note: str | None) -> dict:
    """확인 화면 데이터. `git(repo, *args, check=...)`은 호출자가 넘긴다(db_pr를 import하지 않는다)."""
    applied = stage_result["apply"]
    entries = _status_entries(wt, git)
    names = {"??": "신규", " M": "수정", "M ": "수정", " D": "삭제", "D ": "삭제", "A ": "신규"}
    deleted = {Path(p).name: p for s, p in entries if "D" in s}
    files = []
    for status, path in entries:
        change = names.get(status, status.strip() or "수정")
        if status == "??" and Path(path).name in deleted and "/jira/" in path:
            change = f"이동 (← {deleted[Path(path).name]})"
        elif "D" in status and any(s == "??" and Path(p).name == Path(path).name and "/jira/" in p for s, p in entries):
            continue
        files.append({"kind": _file_kind(path), "path": path, "change": change})
    paths = [p for _, p in entries]
    jira = plan.get("jira") or {}
    at_base = {i.get("temp_id"): i.get("id") for i in stage_result.get("ids_at_base") or []}
    ids = [({**i, "expected_at_base": at_base[i["temp_id"]]} if i.get("temp_id") in at_base else dict(i))
           for i in applied.get("ids") or []]
    keys = [i["id"] for i in ids] + [jira.get("key")] if jira else [i["id"] for i in ids]
    for op in applied.get("operations") or []:
        for field in ("cause", "type", "to", "id", "a", "b", "owner"):
            if isinstance(op.get(field), str):
                keys.append(op[field])
    keys = [k for k in keys if k]
    diff, diff_total = _main_diff(wt, entries, git)
    checks = _check_rows(stage_result)
    verification = _verification_rows(stage_result)
    approval = [r for r in verification if r["status"] == "needs-approval"]
    verify_code = ((stage_result.get("checks") or {}).get("verify") or {}).get("code")
    if verify_code == NEEDS_APPROVAL and not approval:
        approval = [{"id": "db_verify", "status": "needs-approval", "label": "승인 필요 (종료 코드 3)"}]
    source = plan.get("source")
    notes = []
    if source == "record":
        notes.append("로그·코드 분석: 하지 않음 (수동 기록)")
    if jira.get("origin") == "file":
        notes.append("Jira 메타데이터: 오프라인 파일")
    new_pending, user_statement = [], False
    for op in applied.get("operations") or []:
        body = op.get("cause") if op.get("op") == "new-cause" else (op.get("first_cause") or {}).get("cause") \
            if op.get("op") == "new-type" else None
        cid = op.get("temp_id") if op.get("op") == "new-cause" else (op.get("first_cause") or {}).get("temp_id")
        if isinstance(body, dict):
            if body.get("signatures_pending") and not body.get("signatures"):
                new_pending.append(cid)
            if "사용자 진술" in str((body.get("resolution_verification") or {}).get("method") or ""):
                user_statement = True
    if "사용자 진술" in str(jira.get("note") or ""):
        user_statement = True
    for cid in new_pending:
        notes.append(f"{cid}: 시그니처 없음 — 매칭 불가, 리뷰 대상")
    if user_statement:
        notes.append("해결책 근거: 사용자 진술 — 카테고리 오너 리뷰 필요")
    for row in verification:
        if row["status"] == "skipped" and row.get("review_required"):
            notes.append(f"{row['id']}: 검증 못 함 — 리뷰 대상 ({row['reason']})")
    # 계획의 pr_notes: 흐름별 설명(drift 결정, verify-fix 근거, allow-cause 사유 등). 한 번 더 마스킹한다.
    masker = masking.new_masker(allow_patterns=(db_cfg.get("mask") or {}).get("allow_patterns") or [])
    notes += [masker(str(n)) for n in plan.get("pr_notes") or [] if str(n).strip()]
    check = stage_result.get("config_check") or {}
    push_allowed = bool(check.get("push_allowed")) and not stage_result.get("dry_run")
    commit_message = applied.get("commit_message") or ""
    title = commit_message.splitlines()[0] if commit_message else f"[{job}] {source}"
    revs = reviewers(wt, paths, plan, db_cfg)
    result = {
        "source": source, "source_label": SOURCE_LABELS.get(source, source),
        "jira": {"key": jira.get("key"), "origin": jira.get("origin"),
                 "label": "Jira 메타데이터: 오프라인 파일" if jira.get("origin") == "file" else None},
        "branch": {"name": state["branch"], "remote": "갱신" if remote_sha else "신규", "remote_sha": remote_sha,
                   "base": base},
        "reviewers": revs, "open_prs": open_prs,
        "files": files, "ids": ids, "fixtures": applied.get("fixtures") or [],
        "drift_decisions": stage_result.get("drift") or [],
        "readme_preview": _readme_preview(wt, keys), "diff": diff, "diff_total_lines": diff_total,
        "diff_truncated": diff_total > 50, "checks": checks, "verification": verification,
        "approval_needed": approval, "notes": notes, "commit_message": commit_message, "pr_title": title,
        "push_allowed": push_allowed, "push_note": push_note, "pending_included": applied.get("pending_included") or [],
    }
    changes = fix_changes(wt, entries, applied.get("operations") or [], state.get("base_sha"), git)
    if changes:      # 수정 상태가 바뀌는 계획에만 나온다(없으면 출력이 이전과 같다)
        result["fix_changes"] = changes
    return result


def pr_body(screen: dict, plan: dict) -> str:
    jira = plan.get("jira") or {}
    lines = ["## 분석 요약", "", f"- 구분: {screen['source_label']}"]
    if jira:
        info = ", ".join(f"{k}: {jira[k]}" for k in ("model", "sw", "android_version", "carrier") if jira.get(k))
        lines.append(f"- Jira: {jira.get('key')}" + (f" ({info})" if info else ""))
        if jira.get("note"):
            lines.append(f"- 메모: {jira['note']}")
    for note in screen["notes"]:
        lines.append(f"- {note}")
    if screen["ids"]:
        lines.append("- ID 할당: " + ", ".join(
            f"{i['temp_id']} → {i['id']}"
            + (f" (계획 당시 {i['expected_at_base']})" if i.get("expected_at_base") not in (None, i["id"]) else "")
            for i in screen["ids"]))
    if screen.get("fix_changes"):
        lines += ["", "### 수정 상태 변경", ""] + [f"- {c['line']}" for c in screen["fix_changes"]]
    lines += ["", "### 변경 파일", "", "| 구분 | 파일 | 변경 |", "|---|---|---|"]
    lines += [f"| {f['kind']} | {f['path']} | {f['change']} |" for f in screen["files"]]
    checks = screen["checks"]
    lines += ["", "## 검증 결과", ""]
    if "skipped" in checks:
        lines.append(f"- 자동 검사: {checks['skipped']}")
    else:
        ok = lambda v: "✅" if v else "❌"  # noqa: E731
        lines.append(f"- 스키마·lint {ok(checks['lint']['ok'])} (경고 {checks['lint']['warnings']}건) / "
                     f"ID 중복 {ok(checks['ids']['ok'])} / 마스킹 {ok(checks['mask']['ok'])} / "
                     f"fixture 회귀 {ok(checks['regress']['ok'])} ({checks['regress']['passed']}/"
                     f"{checks['regress']['total']}) / 생성 파일 {ok(checks['build']['ok'])}")
    if screen["verification"]:
        lines += ["", "| 검증 | 결과 |", "|---|---|"]
        lines += [f"| {r['id']} | {r['label']} |" for r in screen["verification"]]
    lines.append("")
    lines.append("승인 필요: " + (", ".join(r["id"] for r in screen["approval_needed"]) + " — 메인테이너 승인 필수"
                                  if screen["approval_needed"] else "없음"))
    return "\n".join(lines) + "\n"
