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
from common.fixtures import CAUSE_ID_RE, TYPE_ID_RE
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
    recorded = (plan.get("pr") or {}).get("ids")    # publish가 기록한 이전 적용 ID(`{temp_id: id}`). 없으면 previous_id 키를 만들지 않는다
    if isinstance(recorded, dict):
        for row in ids:
            if recorded.get(row.get("temp_id")) not in (None, row["id"]):
                row["previous_id"] = recorded[row["temp_id"]]
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


# -- 마크다운 렌더 (`db_pr summary --format markdown`) --------------------------------------------
# `write-flow.md §4`가 정한 확인 화면 절 순서·문구를 코드로 옮긴 것이다. 표 밖의 계산은 거기 적힌 규칙만 쓴다.
# 규칙이 정하지 않은 경우는 추측하지 않고 원값을 "(규칙 없음 …)"으로 보인다.

TARGET_RE = re.compile(r"^\[([^\]]+)\]")                     # 계획 형식: "[<원인 또는 유형 ID>] add <KEY>: …"
NO_RULE = "규칙 없음"


def _md_cell(value) -> str:
    return str("" if value is None else value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _md_line(value) -> str:
    """한 줄로 보여야 하는 값(notes·제목·push_note 등): 개행·연속 공백을 공백 하나로. 줄 머리에 가짜 항목을 심지 못하게 한다."""
    return " ".join(str("" if value is None else value).split())


def _fence(text: str, info: str = "") -> str:
    """내용에 든 가장 긴 백틱 줄보다 한 칸 긴 펜스로 감싼다(내용이 펜스를 닫지 못하게)."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{info}\n{text}\n{fence}"


def target_id(commit_message: str | None) -> str | None:
    """대상 원인·유형 ID: 커밋 메시지 머리 `[<원인 또는 유형 ID>]`(write-flow 계획 형식)."""
    m = TARGET_RE.match(commit_message or "")
    if m and (CAUSE_ID_RE.fullmatch(m.group(1)) or TYPE_ID_RE.fullmatch(m.group(1))):
        return m.group(1)
    return None


def target_title(wt: Path, target: str | None) -> str | None:
    """대상 ID의 제목: 원인이면 소속 유형 type.md의 그 원인 `title`, 유형이면 유형 `title`. 못 찾으면 None."""
    if not target or not (CAUSE_ID_RE.fullmatch(target) or TYPE_ID_RE.fullmatch(target)):
        return None
    type_id = target.rsplit("-", 1)[0] if CAUSE_ID_RE.fullmatch(target) else target
    for path in sorted(wt.glob(f"*/{type_id}-*/type.md")):
        try:
            data = parse_frontmatter_text(path.read_text(encoding="utf-8"), str(path))
        except (IssueDbError, OSError):
            continue
        if target == type_id:
            return str(data["title"]) if data.get("title") else None
        for cause in data.get("causes") or []:
            if isinstance(cause, dict) and cause.get("id") == target and cause.get("title"):
                return str(cause["title"])
    return None


def id_assignment(row: dict) -> str:
    """ID 할당 한 줄(write-flow §4 ID 할당 문구). `expected_at_base`(계획 `base_sha` 당시 번호)가 다르면
    '계획 당시 X → Y (main에 먼저 머지된 원인)', `previous_id`(이전 적용 번호, 계획 `pr.ids` 기록)가 다르면 'X → Y 재할당'."""
    line = f"{row['temp_id']} → {row['id']}"
    notes = []
    base = row.get("expected_at_base")
    if base not in (None, row["id"]):
        notes.append(f"계획 당시 {base} → {row['id']} (main에 먼저 머지된 원인)")
    if row.get("previous_id") not in (None, row["id"]):
        notes.append(f"{row['previous_id']} → {row['id']} 재할당")
    return line + (": " + "; ".join(notes) if notes else "")


USER_STATEMENT = "근거: 사용자 진술"      # db-authoring.md: 사용자 진술만 있으면 method에 이 문구, status는 unverified


def resolution_states(operations: list[dict]) -> list[dict]:
    """해결책 검증 상태 `[{cause, state, reason}]` — 계획 op만 보고 정한다(type.md 현재 상태는 읽지 않는다).

    write-flow §4: 새 원인이거나 `set-resolution`이 있으면 unverified, 같은 계획의 `verify-resolution`이 적용된 경우만 verified.
    `state`는 원값(verified/unverified), `reason`은 고정 어휘: "신규 원인 (new-cause)", "해결책 변경 (set-resolution)",
    새 원인 본문 `resolution_verification.method`가 "근거: 사용자 진술"이면 그 문구를 덧붙인다. `new-type`은 "신규 유형 (new-type)". 어휘가 정해지지 않은 op
    (verify-resolution)는 op 이름만 보인다(렌더가 괄호로 감싼다). 해결책을 바꾸는 op가 없으면 빈 목록(해당 없음).
    """
    reasons: dict[str, list[str]] = {}
    verified: set[str] = set()
    for op in operations:
        kind = op.get("op")
        body = None
        if kind == "new-cause" and isinstance(op.get("temp_id"), str):
            cause, label, body = op["temp_id"], "신규 원인 (new-cause)", op.get("cause")
        elif kind == "new-type" and isinstance((op.get("first_cause") or {}).get("temp_id"), str):
            cause, label, body = op["first_cause"]["temp_id"], "신규 유형 (new-type)", op["first_cause"].get("cause")
        elif kind == "set-resolution" and isinstance(op.get("cause"), str):
            cause, label = op["cause"], "해결책 변경 (set-resolution)"
        elif kind == "verify-resolution" and isinstance(op.get("cause"), str):
            verified.add(op["cause"])
            reasons.setdefault(op["cause"], [])
            continue
        else:
            continue
        found = reasons.setdefault(cause, [])
        found.append(label)
        if isinstance(body, dict) and USER_STATEMENT in str((body.get("resolution_verification") or {}).get("method") or ""):
            found.append(USER_STATEMENT)
    return [{"cause": c, "state": "verified", "reason": "verify-resolution"} if c in verified else
            {"cause": c, "state": "unverified", "reason": ", ".join(dict.fromkeys(found))} for c, found in reasons.items()]


def screen_extras(wt: Path, scr: dict, operations: list[dict], digest: str) -> dict:
    target = target_id(scr.get("commit_message"))
    return {"target_id": target, "target_title": target_title(wt, target),
            "resolution": resolution_states(operations), "approved_hash": digest}


def _result_cell(row: dict) -> str:
    status = row.get("status")
    if status == "pass":
        return f"✅ {row['label']}"       # ✅는 status == "pass"일 때만
    if status == "fail":
        return f"❌ {row['label']}"
    return str(row.get("label"))          # skipped·review_required·needs-approval·알 수 없는 status는 원문 그대로


def _check_lines(checks: dict) -> list[str]:
    if "skipped" in checks:
        return [f"자동 검사: 건너뜀 — {_md_line(checks['skipped'])}"]
    ok = lambda v: "✅" if v else "❌"  # noqa: E731
    lint, ids, mask, regress, build = (checks[k] for k in ("lint", "ids", "mask", "regress", "build"))
    lines = [f"- 스키마·lint {ok(lint['ok'])} (오류 {lint['errors']}건, 경고 {lint['warnings']}건)"]
    lines += [f"  - lint 오류: {_md_line(f)}" for f in lint["findings"]]
    if lint["errors"] > len(lint["findings"]):
        lines.append(f"  - lint 오류 {lint['errors']}건 중 {len(lint['findings'])}건만 표시")
    lines.append(f"- ID·Jira 중복 {ok(ids['ok'])}")
    lines += [f"  - 중복: {_md_line(d)}" for d in ids["duplicates"]]
    lines.append(f"- 마스킹 {ok(mask['ok'])}")
    if mask["detections"]:
        lines.append(f"  - 마스킹 검출 {mask['detections']}건")
    lines.append(f"- fixture 회귀 {ok(regress['ok'])} ({regress['passed']}/{regress['total']})")
    lines += [f"  - 회귀 실패 fixture: {_md_line(f)}" for f in regress["failed"]]
    lines.append(f"- 생성 파일 {ok(build['ok'])}")
    return lines


def render_markdown(scr: dict, plan: dict, extra: dict) -> str:
    """`screen()` 결과를 write-flow §4 확인 화면 마크다운으로. 순수 함수(파일·git을 읽지 않는다)."""
    jira = scr.get("jira") or {}
    ids = scr["ids"]
    target, title = extra.get("target_id"), extra.get("target_title")
    key = jira.get("key") or target or (ids[0]["id"] if ids else None)
    head = f"## push 전 확인: {_md_line(key) or '(대상 없음)'}"
    if target:
        head += f" → {target} {_md_line(title) if title else '(제목 없음)'}"
    else:       # 대상 ID(`[<원인 또는 유형 ID>]`)를 못 정하면 조용히 생략하지 않고 원값을 보인다
        head += f" → ({NO_RULE} — 원값: {_md_line((scr.get('commit_message') or '').splitlines()[0] if scr.get('commit_message') else '') or '없음'})"
    branch = scr["branch"]
    prs = scr["open_prs"]
    open_prs = ("확인 못 함" if prs is None else
                ", ".join(_md_line(f"#{p.get('number')} {p.get('title')} ({p.get('url')})") for p in prs) or "없음")
    out = [head, f"구분: {_md_line(scr['source_label'])}",
           f"브랜치: {branch['name']} ({branch['remote']}) → PR 대상: {branch['base']}",
           f"리뷰어: {_md_line(', '.join(scr['reviewers'])) or '없음'}", f"열린 PR: {open_prs}", "",
           "### 변경 파일", "", "| 구분 | 파일 | 변경 |", "|---|---|---|"]
    out += [f"| {_md_cell(f['kind'])} | {_md_cell(f['path'])} | {_md_cell(f['change'])} |" for f in scr["files"]] \
        or ["| 없음 | | |"]
    out += ["", "### ID 할당", ""]
    rows = [f"- {id_assignment(i)}" for i in ids]
    pr = plan.get("pr") or {}
    if ids and (pr.get("number") or pr.get("head_sha")) and not isinstance(pr.get("ids"), dict):
        rows.append("- 재할당 내역: 확인 불가 (이전 적용 ID 기록 없음)")     # 이 기록 도입 전에 올린 PR
    rows += [_md_line(f"- fixture: {fx.get('path')} ({fx.get('kind')}, {fx.get('for')})") for fx in scr["fixtures"]]
    rows += [f"- pending 피드백 포함: {json.dumps(p, ensure_ascii=False)}" for p in scr["pending_included"]]
    out += rows or ["없음"]
    if scr.get("fix_changes"):
        out += ["", "### 수정 상태 변경", ""] + [f"- {_md_line(c['line'])}" for c in scr["fix_changes"]]
    notes = [_md_line(n) for n in scr["notes"]]
    drift_notes = [n for n in notes if n.startswith("drift:")]
    drift = [f"- {n}" for n in drift_notes] + [f"- {json.dumps(d, ensure_ascii=False)}" for d in scr["drift_decisions"]]
    if drift:
        out += ["", "### drift 결정 내역", ""] + drift
    others = [n for n in notes if not n.startswith("drift:")]
    out += ["", "### 추가 설명", ""] + ([f"- {n}" for n in others] or ["없음"])
    out += ["", "### README 반영 미리보기", ""]
    out += [_fence("\n".join(scr["readme_preview"]))] if scr["readme_preview"] else ["없음"]
    out += ["", "### 주요 diff", ""]
    if scr["diff"]:
        out.append(_fence("\n".join(scr["diff"]), "diff"))
        if scr["diff_truncated"]:
            out.append(f"전체 {scr['diff_total_lines']}줄 중 {len(scr['diff'])}줄 — '전체 diff 보기'를 고르면 전체를 본다.")
    else:
        out.append("없음")
    out += ["", "### 자동 검사 결과", ""] + _check_lines(scr["checks"])
    out += ["", "### 검증 결과", ""]
    if scr["verification"]:
        out += ["| 규칙 | 결과 | 사유 |", "|---|---|---|"]
        out += [f"| {_md_cell(r['id'])} | {_md_cell(_result_cell(r))} | "
                f"{_md_cell(r.get('reason') if r.get('status') != 'skipped' else '')} |" for r in scr["verification"]]
    elif "skipped" in scr["checks"]:      # 검사를 건너뛰었으면 검증도 못 돌았다 — "없음"으로 두지 않는다
        out.append(f"검증: 건너뜀 — {_md_line(scr['checks']['skipped'])}")
    else:
        out.append("없음")
    approval = scr["approval_needed"]
    out += ["", "승인 필요: " + (", ".join(str(r["id"]) for r in approval) + " — 메인테이너 승인 필수"
                                if approval else "없음")]
    states = extra.get("resolution") or []
    if states:
        for st in states:
            out.append(f"해결책 검증 상태: {st['cause']} — {st['state']}({st['reason']})")
    else:       # 해결책을 바꾸는 op(new-cause·new-type·set-resolution·verify-resolution)가 없다 — type.md 현재 상태는 읽지 않는다
        out.append("해결책 검증 상태: 해당 없음 (이번 계획은 해결책을 바꾸지 않음)")
    out += ["", "### 커밋 메시지 / PR 제목", "", _fence(scr["commit_message"]), f"PR 제목: {_md_line(scr['pr_title'])}"]
    if scr.get("push_note"):
        out.append(_md_line(scr["push_note"]))
    elif not scr["push_allowed"]:
        out.append(f"({NO_RULE} — 원값: push_allowed=false)")
    out += ["", f"approved_hash: {extra['approved_hash']}"]
    return "\n".join(out) + "\n"
