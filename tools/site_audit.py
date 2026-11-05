"""사내 정기 점검(F, MODULE_SKILLS_DECISIONS 11/05 "사내 모델로 쌓이는 기록·모듈 문서의 품질" ③) — `site_step.py audit`가 부른다.

    python3 tools/site_step.py audit [--since YYYY-MM-DD | --since <레포>=<sha> ... | --last] [--repo ops_db|ofono_db|modules ...]
                                     [--cap-tokens 300000] [--inhouse-model <정규식> ...] [--jobs <work_dir>] [--json]
    python3 tools/site_step.py audit --record [--defer <id>[,<id>]]

지난 점검 뒤 이슈 DB(steps.yaml `ops_db`·`ofono_db`, 사용자 clone의 마지막 fetch 시점 origin/main — 임시 clone)와 모듈 스킬 레포
(`module_skills.remote`, 임시 clone)에 들어온 커밋 중 사내 모델이 만든 것(`Triage-Env` trailer, db_summary.env_trailer)과 출처를
모르는 것을 고른다. Claude 출처는 세기만 하고 뺀다. 그다음 **토큰 0 검사**를 먼저 돌린다: db_lint·db_regress·db_verify rules
(R3·R4 = 시그니처 겹침, 종료 3 = 승인 필요)·db_review(중복 후보)·mask_pii --check·근거 원문 검사 기록(JOB `check-output.json`)·
module_repo_check·module_eval `--dry-run`(case 형식·크기, 실행 수). 걸린 기록과 바뀐 모듈만 Claude가 볼 목록으로 남기고, 추정 토큰을
붙여 상한(`AUDIT_CAP_TOKENS`) 안만 "이번"으로, 나머지는 "미룸"(다음 점검으로 이월)으로 둔다. **Claude를 부르지 않는다** — 명령과
리뷰 지시문만 보인다.

쓰는 것: `docs/site/audit/plan.json`·`docs/site/audit/<날짜>-review.md`(점검마다), `docs/site/audit/state.json`(`--record`만). 그 밖은
쓰지 않는다(임시 clone은 지운다). `--record`는 계획의 끝 커밋(`to`)을 기준점으로 남긴다 — 점검 뒤에 들어온 커밋은 다음 점검에 든다.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import site_checks as sc

AUDIT_DIR = "docs/site/audit"
STATE_FILE = AUDIT_DIR + "/state.json"
PLAN_FILE = AUDIT_DIR + "/plan.json"
AUDIT_CAP_TOKENS = 300_000      # 점검 한 번의 Claude 토큰 상한(바뀐 모듈 ≈2개 + 걸린 기록 10~20건, 전체 흐름 eval 1회 ≈400k보다 작다)
AUDIT_EVERY_DAYS = 7            # 주기(매주): 창이 작아 리뷰가 한 세션에 끝난다
AUDIT_OVERDUE_DAYS = 14         # 이보다 오래되면 MS-2 ms2.audit가 사용자 필요
FIRST_WINDOW_DAYS = 14          # 기록이 없거나 기준점이 사라졌을 때 보는 기간
MODULE_RUN_TOKENS = 35_000      # 모듈 eval run 하나(C0 run 26–33k를 올림). 사외 실측(module_offsite_results.json)이 있으면 그 평균
MODULE_DOC_TOKENS = 30_000      # eval을 못 돌리는 모듈(case 없음·arm 자료 없음)의 문서 리뷰 세션 하나(explore·SKILL·analyzer + diff)
ARM_MATERIAL = "tests/fixtures/module-arms"   # = module_eval.ARM_MATERIAL(레포 루트 기준). 플랫폼 디렉토리가 없으면 eval 불가
RECORD_BASE = 20_000            # 기록 리뷰 세션 한 번(지시문·도구 설명)
RECORD_PER = 3_000              # 기록 하나 + diff 바이트/4(32 KiB까지)
RECORD_DIFF_CAP = 32 * 1024
MAX_COMMITS = 500
REPOS = ("ops_db", "ofono_db", "modules")
REPO_LABELS = {"ops_db": "운영 DB", "ofono_db": "oFono DB", "modules": "모듈 레포"}
DB_PLATFORM = {"ops_db": None, "ofono_db": "ofono"}
PRIORITY = {"P0": 0, "P1": 1, "M": 2, "P2": 3}
ENV_RE = re.compile(r"^Triage-Env: (.*)$", re.MULTILINE)          # = db_summary.ENV_TRAILER_RE
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
ISSUE_FILE_RE = re.compile(r"(?:^|/)issues/([A-Z][A-Z0-9]+-\d+)\.yaml$")       # <유형 디렉토리>/issues/<KEY>.yaml
TYPE_ID_RE = re.compile(r"^[A-Z]+-\d{3}")
RESULTS = "tests/skill_evals/module_offsite_results.json"
NO_CLAUDE = "<claude 부르지 않음>"


class AuditUsage(Exception):
    pass


def today() -> date:
    return date.today()


# -- 출처 -------------------------------------------------------------------------------------------------------------

def parse_env_trailer(body: str) -> dict | None:
    """커밋 본문의 마지막 `Triage-Env:` 줄 → {runtime, model, gateway, label} (없으면 None)."""
    found = ENV_RE.findall(body or "")
    if not found:
        return None
    out = {}
    for part in found[-1].split(";"):
        k, sep, v = part.strip().partition("=")
        if sep and k.strip():
            out[k.strip()] = v.strip()
    return out


def classify(env: dict | None, inhouse: list[str] | None = None) -> str:
    """inhouse | claude | unknown. 사내 모델 정규식(`--inhouse-model`)이 먼저, `claude-`로 시작하면 claude, OpenCode·
    Anthropic 밖 게이트웨이면 inhouse, 나머지(trailer 없음·모름)는 unknown."""
    if not env:
        return "unknown"
    model = env.get("model") or ""
    if any(re.search(p, model) for p in inhouse or ()):
        return "inhouse"
    if model.startswith("claude-"):
        return "claude"
    if env.get("runtime") == "opencode" or env.get("gateway") == "other":
        return "inhouse"
    return "unknown"


# -- 상태 -------------------------------------------------------------------------------------------------------------

def load_state(root: Path) -> dict:
    p = Path(root) / STATE_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    data.setdefault("version", 1)
    data.setdefault("points", {})
    data.setdefault("carry", [])
    data.setdefault("history", [])
    return data


def last_audit(state: dict) -> date | None:
    hist = state.get("history") or []
    try:
        return date.fromisoformat(str(hist[-1]["at"])[:10]) if hist else None
    except (KeyError, ValueError, TypeError):
        return None


def _write(root: Path, rel: str, text: str) -> None:
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


# -- git --------------------------------------------------------------------------------------------------------------

def _git(ctx, clone: Path, *args: str, timeout: int = 120) -> tuple[int, str]:
    code, out, _ = ctx.run(["git", "-C", str(clone), *args], timeout=timeout)
    return code, out


def _head(ctx, clone: Path) -> str:
    return _git(ctx, clone, "rev-parse", "HEAD")[1].strip()


def _first_commit(ctx, clone: Path) -> str:
    return (_git(ctx, clone, "rev-list", "--max-parents=0", "HEAD")[1].split() or [""])[0]


def _is_ancestor(ctx, clone: Path, sha: str) -> bool:
    return bool(sha) and _git(ctx, clone, "merge-base", "--is-ancestor", sha, "HEAD")[0] == 0


def commits(ctx, clone: Path, point: str | None, since: str | None, rev: str | None = None) -> list[dict]:
    """[{sha, at, subject, body, files}] 새것부터, 병합 커밋 제외, 생성 파일 제외. MAX_COMMITS+1개까지 읽는다.
    `rev`를 주면 그 커밋 하나만."""
    args = ["log", "--no-merges", "--name-only", f"-n{1 if rev else MAX_COMMITS + 1}", "--format=%x1e%H%x1f%cI%x1f%B%x1d"]
    if since:
        args.append(f"--since={since}")
    args.append(rev or (f"{point}..HEAD" if point else "HEAD"))
    code, out = _git(ctx, clone, *args, timeout=300)
    if code:
        return []
    found = []
    for rec in out.split("\x1e")[1:]:
        head, _, files = rec.partition("\x1d")
        sha, at, body = (head.split("\x1f", 2) + ["", ""])[:3]
        names = [f for f in files.splitlines() if f.strip() and not sc.GENERATED_RE.match(f.strip())]
        found.append({"sha": sha.strip(), "at": at.strip(), "subject": (body.strip().splitlines() or [""])[0][:120],
                      "body": body, "files": [f.strip() for f in names]})
    return found


# -- 계획 -------------------------------------------------------------------------------------------------------------

def _since_args(values: list[str]) -> tuple[str | None, dict[str, str]]:
    date_value, shas = None, {}
    for v in values or []:
        if "=" in v:
            repo, _, sha = v.partition("=")
            if repo not in REPOS or not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
                raise AuditUsage(f"--since {v}: <레포>=<sha> 꼴이다(레포: {', '.join(REPOS)})")
            shas[repo] = sha.lower()
        else:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise AuditUsage(f"--since {v}: YYYY-MM-DD 또는 <레포>=<sha>") from None
            if date_value:
                raise AuditUsage("--since 날짜는 한 번만 준다")
            date_value = v
    return date_value, shas


def _clone_for(ctx, repo: str) -> tuple[Path | None, str | None]:
    """(임시 clone, 건너뛴 이유)."""
    try:
        if repo == "modules":
            if not sc.module_settings(ctx)["ms"]:
                return None, "module_skills.remote 없음"
            return ctx.module_clone(), None
        clone = ctx.db_clone(repo)
        return (clone, None) if clone else (None, f"steps.yaml `{repo}` 없음")
    except (sc.CloneUnavailable, sc.ModuleCloneError, RuntimeError) as exc:
        return None, str(exc)[:160]


def _window(ctx, repo: str, clone: Path, state: dict, since_date: str | None, since_sha: dict) -> dict:
    head = _head(ctx, clone)
    first_days = (today() - timedelta(days=FIRST_WINDOW_DAYS)).isoformat()
    point = (state.get("points") or {}).get(repo) or {}
    w = {"from": None, "since": None, "to": head, "label": "", "recorded_from": point.get("sha")}
    if repo in since_sha:
        sha = since_sha[repo]
        full = _git(ctx, clone, "rev-parse", "--verify", "--quiet", sha + "^{commit}")[1].strip()
        if not _is_ancestor(ctx, clone, full):
            raise AuditUsage(f"--since {repo}={sha}: HEAD의 조상 커밋이 아니다")
        w.update({"from": full, "label": f"--since {sha[:7]}"})
    elif since_date:
        w.update({"since": since_date, "label": f"--since {since_date}"})
    elif point.get("sha"):
        if _is_ancestor(ctx, clone, point["sha"]):
            w.update({"from": point["sha"], "label": f"지난 점검 {str(point.get('at', ''))[:10]}"})
        else:
            w.update({"since": first_days, "label": f"기준점 없음(역사 바뀜) — 최근 {FIRST_WINDOW_DAYS}일"})
    else:
        w.update({"since": first_days, "label": f"첫 점검 — 최근 {FIRST_WINDOW_DAYS}일"})
    return w


def _owner(path: str, picked: list[dict]) -> dict | None:
    """그 파일을 건드린 가장 새 고른 커밋, 없으면 같은 유형 폴더(`카테고리/유형-…/`)를 건드린 가장 새 고른 커밋."""
    parts = path.split("/")
    prefix = "/".join(parts[:2]) + "/" if len(parts) >= 3 else None
    exact = next((c for c in picked if path in c["files"]), None)      # picked는 새것부터
    if exact or not prefix:
        return exact
    return next((c for c in picked if any(f.startswith(prefix) for f in c["files"])), None)


def _type_owner(target: str, picked: list[dict]) -> dict | None:
    m = TYPE_ID_RE.match(target or "")
    if not m:
        return None
    tid = m.group(0)
    for c in picked:
        if any(len(f.split("/")) >= 2 and (f.split("/")[1] == tid or f.split("/")[1].startswith(tid + "-")) for f in c["files"]):
            return c
    return None


def _json(out: str):
    try:
        return json.loads(out)
    except ValueError:
        return None


def _row(cid: str, status: str, evidence: str, cmd: str | None = None) -> dict:
    return {"id": cid, "status": status, "evidence": evidence, "cmd": cmd}


def db_checks(ctx, repo: str, clone: Path, base: str, picked: list[dict], jobs: Path | None) -> tuple[list[dict], list[dict]]:
    """(검사 행, 걸린 것 [{sha|None, flag, priority, file}]). 스크립트는 레포 플러그인으로 임시 clone에서 돈다."""
    rows, flags = [], []
    plug = ["--plugin-root", str(ctx.root / "plugin")]
    tag = f"audit.{repo}"
    changed = sorted({f for c in picked for f in c["files"]})

    def flag(path_or_target: str, what: str, prio: str, by_type: bool = False) -> None:
        c = _type_owner(path_or_target, picked) if by_type else _owner(path_or_target, picked)
        flags.append({"sha": c["sha"] if c else None, "flag": what, "priority": prio, "file": path_or_target})

    def call(name: str, script: str, *args: str) -> tuple[int, object, str]:
        code, out, err = ctx.py(f"plugin/scripts/{script}", *args, *plug)
        return code, _json(out), sc._first_line(err)

    # 1. db_lint
    code, data, err = call("lint", "db_lint.py", "--db", str(clone), "--changed", base, "--json")
    if code in (0, 1) and isinstance(data, dict):
        errs, warns = data.get("errors") or [], data.get("warnings") or []
        for e in errs:
            for f in e.get("files") or [e.get("file")]:
                f and flag(f, f"lint 오류 {e.get('code')}", "P1")
        for e in warns:
            for f in e.get("files") or [e.get("file")]:
                f and flag(f, f"lint 경고 {e.get('code')}", "P2")
        rows.append(_row(f"{tag}.lint", "fail" if errs else "pass", f"오류 {len(errs)} · 경고 {len(warns)}",
                         f"db_lint.py --db <임시 clone> --changed {base[:7]}"))
    else:
        rows.append(_row(f"{tag}.lint", "skip", f"실행 못 함(종료 {code}) {err}", "db_lint.py"))
    # 2. db_regress (전체)
    code, data, err = call("regress", "db_regress.py", "--db", str(clone), "--all", "--json")
    if code in (0, 1) and isinstance(data, dict):
        bad = [r for r in data.get("results") or [] if r.get("status") != "pass"]
        for r in bad:
            flag(str(r.get("fixture")), "회귀 실패", "P0")
        rows.append(_row(f"{tag}.regress", "fail" if bad else "pass",
                         f"fixture {len(data.get('results') or [])} · 실패 {len(bad)}", "db_regress.py --db <임시 clone> --all"))
    else:
        rows.append(_row(f"{tag}.regress", "skip", f"실행 못 함(종료 {code}) {err}", "db_regress.py --all"))
    # 3. db_verify rules (R3·R4 시그니처 겹침, 종료 3 승인 필요)
    code, data, err = call("verify", "db_verify.py", "rules", "--changed", base, "--db", str(clone), "--json")
    if code in (0, 1, 3) and isinstance(data, dict):
        hit = 0
        for r in data.get("rules") or []:
            if r.get("id") in ("R3", "R4") and r.get("status") == "fail":
                hit += 1
                for t in r.get("targets") or []:
                    flag(str(t), f"시그니처 겹침 {r['id']}", "P1", by_type=True)
            if r.get("status") == "needs-approval":
                hit += 1
                for c in picked[:1]:
                    flags.append({"sha": c["sha"], "flag": f"승인 필요 {r.get('id')}", "priority": "P1", "file": None})
        status = "fail" if code == 1 else ("needs-user" if code == 3 else "pass")
        rows.append(_row(f"{tag}.verify", status, f"종료 {code} · R3/R4·승인 필요 {hit}",
                         f"db_verify.py rules --changed {base[:7]} --db <임시 clone>"))
    else:
        rows.append(_row(f"{tag}.verify", "skip", f"실행 못 함(종료 {code}) {err}", "db_verify.py rules"))
    # 4. db_review 중복 후보(바뀐 유형만)
    code, data, err = call("review", "db_review.py", "--db", str(clone), "--json")
    if code == 0 and isinstance(data, dict):
        dup = next((i for i in data.get("items") or [] if i.get("key") == "duplicate-candidates"), {}) or {}
        n = 0
        for e in dup.get("entries") or []:
            for t in e.get("types") or []:
                c = _type_owner(str(t), picked)
                if c:
                    n += 1
                    flags.append({"sha": c["sha"], "flag": "중복 후보", "priority": "P1", "file": None})
                    break
        rows.append(_row(f"{tag}.review", "fail" if n else "pass", f"바뀐 유형의 중복 후보 {n}", "db_review.py --db <임시 clone>"))
    else:
        rows.append(_row(f"{tag}.review", "skip", f"실행 못 함(종료 {code}) {err}", "db_review.py"))
    # 5. mask_pii --check (바뀐 파일)
    exist = [str(clone / f) for f in changed if (clone / f).is_file()]
    if exist:
        code, data, err = call("mask", "mask_pii.py", "--check", "--db", str(clone), "--json", *exist)
        if code in (0, 1) and isinstance(data, dict):
            det = data.get("detections") or []
            for d in det:
                flag(str(d.get("path")), f"마스킹 안 됨 {d.get('kind')}", "P0")
            rows.append(_row(f"{tag}.mask", "fail" if det else "pass", f"파일 {len(exist)} · 검출 {len(det)}",
                             "mask_pii.py --check <바뀐 파일>"))
        else:
            rows.append(_row(f"{tag}.mask", "skip", f"실행 못 함(종료 {code}) {err}", "mask_pii.py --check"))
    else:
        rows.append(_row(f"{tag}.mask", "info", "바뀐 파일 없음(지워진 것만)", None))
    # 6. 근거 원문 검사 기록(JOB check-output.json)
    keys: dict[str, dict] = {}
    for c in picked:
        for f in c["files"]:
            m = ISSUE_FILE_RE.search(f)
            if m:
                keys.setdefault(m.group(1), c)
    subj = {k: c for c in picked for k in KEY_RE.findall(c["subject"]) if k not in keys}
    counts = {"ok": 0, "weak": 0, "fabricated": 0, "none": 0}
    for key, c in [*keys.items(), *subj.items()]:
        rec = (jobs / key / "check-output.json") if jobs else None
        data = _json(rec.read_text(encoding="utf-8")) if rec and rec.is_file() else None
        if not isinstance(data, dict):
            if key in keys:
                counts["none"] += 1
            continue
        fab = sum(int((v or {}).get("fabricated") or 0) for v in data.values() if isinstance(v, dict))
        weak = sum(int((v or {}).get("weak") or 0) for v in data.values() if isinstance(v, dict))
        verdict = "fabricated" if fab else ("weak" if weak else "ok")
        counts[verdict] += 1
        if verdict != "ok":
            flags.append({"sha": c["sha"], "flag": f"근거 {verdict} {key}", "priority": "P0" if fab else "P2", "file": None})
    ev = f"ok {counts['ok']} · weak {counts['weak']} · fabricated {counts['fabricated']} · 근거 기록 없음 {counts['none']}"
    status = "fail" if counts["fabricated"] else ("skip" if counts["none"] else "pass")
    if not keys and not any(counts.values()):
        status, ev = "info", "바뀐 이슈 기록 없음"
    rows.append(_row(f"{tag}.grounding", status, ev + ("" if jobs else " (JOB 폴더 모름 — --jobs)"),
                     "<work_dir>/<KEY>/check-output.json"))
    return rows, flags


def _measured(module: str, root: Path) -> float | None:
    p = Path(root) / RESULTS
    try:
        cases = ((json.loads(p.read_text(encoding="utf-8")).get("modules") or {}).get(module) or {}).get("cases") or {}
    except (OSError, ValueError):
        return None
    vals = [arm.get("tokens_total") for c in cases.values() for arm in (c.get("with") or {}, c.get("without") or {})
            if isinstance(arm.get("tokens_total"), (int, float))]
    return sum(vals) / len(vals) if vals else None


def _no_eval_reason(ctx, clone: Path, path: str) -> str | None:
    """module_eval을 돌릴 수 없는 모듈의 사유(없으면 None): 클론에 `<path>/evals/*/case.yaml`이 없거나, 이 레포에 그 플랫폼 arm
    자료(`tests/fixtures/module-arms/<p>`)가 없다(MS-2부터 Android eval 입력은 모듈 레포 밖). 그 밖의 module_eval 오류는 실패로 둔다."""
    if not any((clone / path / "evals").glob("*/case.yaml")):
        return "eval case 없음 — 문서 리뷰만"
    if not (Path(ctx.root) / ARM_MATERIAL / path.split("/", 1)[0]).is_dir():
        return "arm 자료 없음 — 문서 리뷰만"
    return None


def module_checks(ctx, clone: Path, picked: list[dict], carried: list[str] | None = None,
                  head: str = "") -> tuple[list[dict], list[dict], list[str]]:
    """(검사 행, 모듈 항목 후보, 고칠 것). 바뀐 `<p>/<m>`(`<p>/_common`이면 그 플랫폼 모듈 전부)과 이월된 모듈만."""
    import module_repo_check

    doc = sc.modules_doc(clone)
    mods = sc._module_paths(doc)
    changed: dict[str, dict] = {}
    size: dict[str, int] = {}
    for c in reversed(picked):                         # 오래된 것부터 → 마지막 커밋이 남는다
        for f in c["files"]:
            parts = f.split("/")
            if len(parts) < 2:
                continue
            hit = [path for p, _, path, _ in mods if parts[0] == p and (parts[1] == "_common" or f.startswith(path + "/"))]
            for path in hit:
                changed[path] = c
                size[path] = size.get(path, 0) + 1
    for path in carried or []:
        if path not in changed and any(p == path for _, _, p, _ in mods):
            changed[path] = {"sha": head, "at": ""}
    found = module_repo_check.findings(clone)
    rows = [_row("audit.modules.repo_check", "fail" if found else "pass", f"지적 {len(found)}" +
                 (f": {sc._cap_list(found, 5)}" if found else ""), "python3 tools/module_repo_check.py <임시 clone>")]
    fix = [f"모듈 레포: {f}" for f in found]
    bad_paths = {path for path in changed for f in found if f.startswith(path + "/")}
    items, dry_fail, runs_total = [], [], 0
    missing_claude = str(ctx.tmpdir() / "no-claude")
    for path, c in sorted(changed.items()):
        if path in bad_paths:
            continue
        no_eval = _no_eval_reason(ctx, clone, path)
        if no_eval:                                    # eval을 못 돌리는 것은 실패가 아니다 — 문서 리뷰 항목으로(이월도 된다)
            items.append({"path": path, "commit": c, "runs": 0, "est": MODULE_DOC_TOKENS, "changed": size.get(path, 0),
                          "per_run": 0, "measured": False, "doc_only": no_eval})
            continue
        code, out, err = ctx.py("plugin/scripts/module_eval.py", "--module", path, "--templates", str(clone), "--dry-run",
                                "--json", "--claude", missing_claude)
        data = _json(out) if code == 0 else None
        if not isinstance(data, dict):
            dry_fail.append(path)
            fix.append(f"모듈 {path}: module_eval --dry-run 종료 {code} — {sc._first_line(err) or '출력 없음'}")
            continue
        runs = int((data.get("estimate") or {}).get("runs") or len(data.get("plan") or []))
        runs_total += runs
        per = _measured(path, ctx.root) or MODULE_RUN_TOKENS
        items.append({"path": path, "commit": c, "runs": runs, "est": int(round(runs * per)), "changed": size.get(path, 0),
                      "per_run": int(round(per)), "measured": per != MODULE_RUN_TOKENS})
    docs = [i for i in items if i.get("doc_only")]
    rows.append(_row("audit.modules.dry_run", "fail" if dry_fail else ("pass" if len(items) > len(docs) else "info"),
                     f"바뀐 모듈 {len(changed)} · dry-run 통과 {len(items) - len(docs)} · 실행 수 {runs_total}" +
                     (f" · 문서 리뷰만 {len(docs)}({', '.join(sorted({i['doc_only'] for i in docs}))})" if docs else "") +
                     (f" · 실패 {', '.join(dry_fail)}" if dry_fail else ""),
                     "module_eval.py --module <p>/<m> --templates <임시 clone> --dry-run --json"))
    return rows, items, fix


def _diff_bytes(ctx, clone: Path, sha: str, files: list[str]) -> int:
    code, out = _git(ctx, clone, "show", "--format=", sha, "--", *files)
    return len(out.encode("utf-8")) if code == 0 else 0


def plan(ctx, since: list[str] | None = None, last: bool = False, repos: list[str] | None = None,
         cap: int = AUDIT_CAP_TOKENS, inhouse: list[str] | None = None, jobs: str | None = None) -> dict:
    root = Path(ctx.root)
    state = load_state(root)
    since_date, since_sha = _since_args(since or [])
    if last and (since_date or since_sha):
        raise AuditUsage("--last와 --since는 함께 쓰지 않는다")
    if last and not state["points"]:
        raise AuditUsage("기록된 점검이 없다 — 첫 점검은 --last 없이(최근 14일)")
    for r in repos or []:
        if r not in REPOS:
            raise AuditUsage(f"--repo {r}: {', '.join(REPOS)}")
    for p in inhouse or []:
        try:
            re.compile(p)
        except re.error as exc:
            raise AuditUsage(f"--inhouse-model {p!r}: 정규식 오류 {exc}") from None
    st = sc.module_settings(ctx)
    jobs_by = {}
    if jobs:
        jobs_by = {k: Path(jobs).expanduser() for k in ("ops_db", "ofono_db")}
    elif st["d"] is not None:
        uc = sc._plugin_common("userconfig")
        for k, plat in DB_PLATFORM.items():
            try:
                wd = uc.merged(st["d"], st["u"], platform=plat).get("work_dir")
            except Exception:  # noqa: BLE001 — 설정 오류는 근거 기록 없음(skip)으로
                wd = None
            jobs_by[k] = Path(str(wd)).expanduser() if wd else None
    windows, checks, fix, items, skipped = {}, [], [], [], {}
    carry = list(state.get("carry") or [])
    for repo in [r for r in REPOS if not repos or r in repos]:
        clone, why = _clone_for(ctx, repo)
        if clone is None:
            skipped[repo] = why
            continue
        w = _window(ctx, repo, clone, state, since_date, since_sha)
        found = commits(ctx, clone, w["from"], w["since"])
        if len(found) > MAX_COMMITS:
            checks.append(_row(f"audit.{repo}.window", "fail", f"커밋 {MAX_COMMITS}개 넘음 — --since로 줄인다", None))
            w.update({"commits": len(found), "provenance": {}})
            windows[repo] = w
            continue
        prov = {"inhouse": 0, "unknown": 0, "claude": 0}
        picked = []
        for c in found:
            c["provenance"] = classify(parse_env_trailer(c["body"]), inhouse)
            prov[c["provenance"]] += 1
            if c["provenance"] != "claude":
                picked.append(c)
        if not w["from"]:                                  # 날짜 창: 창 바로 앞 커밋(없으면 첫 커밋부터)
            oldest = found[-1]["sha"] if found else w["to"]
            parent = _git(ctx, clone, "rev-parse", "--verify", "--quiet", oldest + "^")[1].strip()
            w["base"] = parent or _first_commit(ctx, clone)
        else:
            w["base"] = w["from"]
        w.update({"commits": len(found), "provenance": prov})
        windows[repo] = w
        carried = [c for c in carry if (c.startswith("mod:") if repo == "modules" else c.startswith(f"rec:{repo}:"))]
        if not picked and not carried:
            checks.append(_row(f"audit.{repo}.window", "info", "고를 커밋 없음(사내·출처 모름 0)", None))
            continue
        for cid in carried:                                # 이월 기록: 커밋을 다시 읽는다
            if cid.startswith("rec:"):
                sha = cid.split(":", 2)[2]
                if not any(c["sha"].startswith(sha) for c in picked) and _is_ancestor(ctx, clone, sha):
                    for c in commits(ctx, clone, None, None, rev=sha):
                        c["provenance"], c["carried"] = "carried", True
                        picked.append(c)
        picked.sort(key=lambda c: c["at"], reverse=True)
        if repo == "modules":
            rows, mods, mfix = module_checks(ctx, clone, picked, [c[4:] for c in carried], w["to"])
            checks += rows
            fix += mfix
            remote = sc._plugin_common("userconfig").redact_remote(st["ms"]["remote"])
            base_branch = st["ms"]["base_branch"]
            model = ctx.inputs.get("eval_model")
            for m in mods:
                sha = m["commit"]["sha"]
                clone_cmd = f"git clone --branch {base_branch} {remote} <모듈 레포 clone>"
                if m.get("doc_only"):
                    cmds = [clone_cmd, f"git -C <모듈 레포 clone> show {sha} -- {m['path']}/"]
                    note = f"run 0 · {m['doc_only']} · 문서 리뷰 {MODULE_DOC_TOKENS:,} 토큰"
                else:
                    cmds = [clone_cmd, f"python3 plugin/scripts/module_eval.py --module {m['path']} --templates <모듈 레포 clone> "
                                       f"--sha {sha} --json" + (f" --model {model}" if model else "")]
                    note = f"run {m['runs']} × {m['per_run']:,} 토큰" + (" (사외 실측 평균)" if m["measured"] else "")
                items.append({"id": f"mod:{m['path']}", "repo": "modules", "kind": "module", "priority": "M",
                              "flags": ["바뀐 모듈"] + ([m["doc_only"]] if m.get("doc_only") else []) +
                                       (["이월"] if m.get("carried") or f"mod:{m['path']}" in carry else []),
                              "files": [m["path"] + "/"], "est_tokens": m["est"], "at": m["commit"].get("at", ""),
                              "changed": m["changed"], "sha": sha, "doc_only": bool(m.get("doc_only")),
                              "cmds": cmds, "note": note})
            continue
        rows, flags = db_checks(ctx, repo, clone, w["base"], picked, jobs_by.get(repo))
        checks += rows
        by_sha: dict[str, list[dict]] = {}
        for f in flags:
            if f["sha"] is None:
                fix.append(f"{REPO_LABELS[repo]}: {f['flag']} {f['file'] or ''} — 고른 커밋 밖(기존 상태)".rstrip())
                continue
            by_sha.setdefault(f["sha"], []).append(f)
        src = ctx.inputs.get(repo) or f"<{repo} clone>"
        for c in picked:
            fl = by_sha.get(c["sha"]) or []
            cid = f"rec:{repo}:{c['sha'][:12]}"
            if not fl and cid not in carry:
                continue
            prio = min((f["priority"] for f in fl), key=PRIORITY.get, default="P2")
            nbytes = min(_diff_bytes(ctx, clone, c["sha"], c["files"]), RECORD_DIFF_CAP)
            items.append({"id": cid, "repo": repo, "kind": "record", "priority": prio,
                          "flags": sorted({f["flag"] for f in fl}) + (["이월"] if cid in carry else []),
                          "files": c["files"][:20], "est_tokens": RECORD_PER + nbytes // 4, "at": c["at"], "changed": nbytes,
                          "sha": c["sha"], "provenance": c["provenance"],
                          "cmds": [f"git -C {src} show {c['sha'][:12]} -- " + " ".join(c["files"][:20])]})
    # 우선순위로 채운다: 이월 먼저, P0 → P1 → 모듈(바뀐 양 큰 것) → P2, 같으면 레포·커밋 시각
    items.sort(key=lambda i: ("이월" not in i["flags"], PRIORITY[i["priority"]], -i["changed"] if i["kind"] == "module" else 0,
                              REPOS.index(i["repo"]), i["at"]))
    used, base_added = 0, False
    for it in items:
        extra = RECORD_BASE if it["kind"] == "record" and not base_added else 0
        cost = it["est_tokens"] + extra
        if cost > cap:
            it["slot"], it["why"] = "미룸", "상한보다 큼"
        elif used + cost <= cap:
            it["slot"] = "이번"
            used += cost
            base_added = base_added or bool(extra)
        else:
            it["slot"], it["why"] = "미룸", "상한"
    now = [i for i in items if i["slot"] == "이번"]
    later = [i for i in items if i["slot"] == "미룸"]
    last_at = last_audit(state)
    bad = [c for c in checks if c["status"] in ("fail", "skip", "needs-user")]
    result = {"version": 1, "created": datetime.now().isoformat(timespec="seconds"), "window": windows, "skipped": skipped,
              "checks": checks, "fix": fix, "items": items, "cap": cap, "est_now": used,
              "est_deferred": sum(i["est_tokens"] for i in later), "every_days": AUDIT_EVERY_DAYS,
              "overdue_days": AUDIT_OVERDUE_DAYS, "last_audit": last_at.isoformat() if last_at else None,
              "next_due": (today() + timedelta(days=AUDIT_EVERY_DAYS)).isoformat(),
              "from_points": {r: (state["points"].get(r) or {}).get("sha") for r in windows},
              "constants": {"module_run_tokens": MODULE_RUN_TOKENS, "module_doc_tokens": MODULE_DOC_TOKENS, "record_base": RECORD_BASE, "record_per": RECORD_PER}}
    result["exit"] = 1 if (bad or fix or items) else 0
    if not windows and not skipped:
        result["exit"] = 1
    return result


# -- 출력·기록 --------------------------------------------------------------------------------------------------------

MARK = {"pass": "통과", "fail": "실패", "skip": "건너뜀", "needs-user": "사용자 필요", "info": "정보"}


def render(p: dict) -> str:
    cell = lambda t: str(t).replace("|", "/")  # noqa: E731
    out = [f"정기 점검(사내 전용) — 토큰 0 검사를 먼저 돌렸다. Claude는 부르지 않았다. 상한 {p['cap']:,} 토큰/점검 · 주기 {p['every_days']}일 "
           f"(넘으면 {p['overdue_days']}일에 MS-2 사용자 필요)", "", "| 레포 | 창 | 커밋 | 사내 | 출처 모름 | Claude(뺌) |", "|---|---|---|---|---|---|"]
    for repo, w in p["window"].items():
        pv = w.get("provenance") or {}
        span = f"{(w.get('from') or '')[:7] or w.get('since')} → {w['to'][:7]}"
        out.append(f"| {REPO_LABELS[repo]} | {cell(span)} ({cell(w['label'])}) | {w.get('commits', 0)} | {pv.get('inhouse', 0)} | "
                   f"{pv.get('unknown', 0)} | {pv.get('claude', 0)} |")
    for repo, why in p["skipped"].items():
        out.append(f"| {REPO_LABELS[repo]} | 건너뜀: {cell(why)} | | | | |")
    out += ["", "| 검사 | 결과 | 근거 |", "|---|---|---|"]
    out += [f"| {c['id']} | {MARK[c['status']]} | {cell(c['evidence'])} |" for c in p["checks"]]
    if p["fix"]:
        out += ["", "고칠 것(스크립트 판정 — Claude 리뷰 대상이 아니다):"] + [f"- {f}" for f in p["fix"]]
    out += ["", "| # | 항목 | 우선 | 근거 | 추정 토큰 | 이번/미룸 |", "|---|---|---|---|---|---|"]
    for n, it in enumerate(p["items"], 1):
        out.append(f"| {n} | {it['id']} | {it['priority']} | {cell(', '.join(it['flags']))} | {it['est_tokens']:,} | "
                   f"{it['slot']}{' (' + it['why'] + ')' if it.get('why') else ''} |")
    if not p["items"]:
        out.append("| - | Claude가 볼 것 없음 | | | 0 | |")
    later = sum(1 for i in p["items"] if i["slot"] == "미룸")
    out += ["", f"이번 {sum(1 for i in p['items'] if i['slot'] == '이번')} / 상한 {p['cap']:,} (추정 {p['est_now']:,}) · 미룸 {later} "
                f"(추정 {p['est_deferred']:,}, `--record` 때 다음 점검으로 이월) · 다음 점검 {p['next_due']}"]
    cmds = [c for i in p["items"] if i["slot"] == "이번" for c in i["cmds"]]
    if cmds:
        out += ["", "토큰을 쓰는 단계 — 사용자 승인 뒤 사내 Claude 세션에서만(이 도구는 실행하지 않는다):"]
        out += [f"  {c}" for c in dict.fromkeys(cmds)]
    out += ["", f"리뷰 지시문: {AUDIT_DIR}/{today().isoformat()}-review.md · 계획: {PLAN_FILE}",
            "리뷰를 마치면(또는 미루기로 하면) `python3 tools/site_step.py audit --record [--defer <id>,…]`로 기준점을 남긴다."]
    return "\n".join(out)


def review_md(p: dict) -> str:
    now = [i for i in p["items"] if i["slot"] == "이번"]
    lines = [f"# 정기 점검 리뷰 {today().isoformat()} (사내 전용, 반출 금지)", "",
             "사내 Claude 세션에 붙여 넣는 지시문이다. 기록이 근거·스크립트 판정과 맞는지 본다. 파일 쓰기·push·Jira 쓰기는 하지 않는다.",
             "고칠 것은 이슈 DB 계획 op PR(분류·시그니처·태그는 사용자 확인 뒤)이나 모듈 레포 PR로 따로 낸다. 판정 기준은 스크립트 출력이고 "
             "이 리뷰는 보조다.", "", f"상한 {p['cap']:,} 토큰 · 이번 추정 {p['est_now']:,}", ""]
    for it in now:
        lines.append(f"## {it['id']} ({it['priority']}, 추정 {it['est_tokens']:,})")
        lines.append(f"- 근거: {', '.join(it['flags'])}")
        lines.append(f"- 파일: {', '.join(it['files'])}")
        lines += [f"- 명령: `{c}`" for c in it["cmds"]]
        if it["kind"] == "module" and it.get("doc_only"):
            lines.append("- 볼 것: eval을 돌릴 수 없다 — 바뀐 문서(explore·SKILL·analyzer)가 플랫폼 공통 원칙·안전 규칙과 맞는지 diff로만 본다.")
        elif it["kind"] == "module":
            lines.append("- 볼 것: with ≥ without, 안전 위반 0. 결과 기록은 스크립트(module_eval)만 쓴다.")
        lines.append("")
    if not now:
        lines.append("이번에 볼 것 없음.")
    return "\n".join(lines) + "\n"


def write_plan(root: Path, p: dict) -> list[str]:
    _write(root, PLAN_FILE, json.dumps(p, ensure_ascii=False, indent=1) + "\n")
    rel = f"{AUDIT_DIR}/{today().isoformat()}-review.md"
    _write(root, rel, review_md(p))
    return [PLAN_FILE, rel]


def _carry_repo(cid: str) -> str | None:
    """이월 id의 레포: `mod:<p>/<m>` → modules, `rec:<레포>:<sha>` → <레포>."""
    if cid.startswith("mod:"):
        return "modules"
    if cid.startswith("rec:"):
        return cid.split(":", 2)[1]
    return None


def record(root: Path, defer: list[str] | None = None) -> str:
    root = Path(root)
    path = root / PLAN_FILE
    if not path.is_file():
        raise AuditUsage(f"{PLAN_FILE}가 없다 — 먼저 `site_step.py audit`")
    p = _json(path.read_text(encoding="utf-8"))
    if not isinstance(p, dict) or "window" not in p:
        raise AuditUsage(f"{PLAN_FILE}를 읽지 못함 — `site_step.py audit`를 다시 돌린다")
    state = load_state(root)
    now_points = {r: (state["points"].get(r) or {}).get("sha") for r in p["window"]}
    if p.get("recorded"):
        raise AuditUsage("이 계획은 이미 기록했다 — 새 점검은 `site_step.py audit`")
    if now_points != (p.get("from_points") or {}):
        raise AuditUsage("계획이 지금 기준점에서 시작하지 않는다(그 사이 기록이 있었다) — `site_step.py audit`를 다시 돌린다")
    ids = {i["id"] for i in p["items"]}
    extra = [d.strip() for x in defer or [] for d in x.split(",") if d.strip()]
    unknown = [d for d in extra if d not in ids]
    if unknown:
        raise AuditUsage(f"--defer: 계획에 없는 항목 {', '.join(unknown)} (항목: {', '.join(sorted(ids)) or '없음'})")
    at = datetime.now().isoformat(timespec="seconds")
    for repo, w in p["window"].items():
        if w.get("provenance"):                            # 커밋 수 초과(실패) 창은 기준점을 옮기지 않는다
            state["points"][repo] = {"sha": w["to"], "at": at}
    done = {r for r, w in p["window"].items() if w.get("provenance")}
    keep = [c for c in state["carry"] if _carry_repo(c) not in done]   # 이번에 처리하지 않은 레포(--repo·clone 건너뜀·커밋 수 초과)의 이월은 남긴다
    carry = keep + [i["id"] for i in p["items"] if i["slot"] == "미룸"] + extra
    state["carry"] = list(dict.fromkeys(carry))
    state["history"].append({"at": at, "window": {r: {"from": w.get("from") or w.get("since"), "to": w["to"]}
                                                  for r, w in p["window"].items()},
                             "counts": {"items": len(p["items"]), "now": sum(1 for i in p["items"] if i["slot"] == "이번"),
                                        "deferred": len(state["carry"])}, "est_now": p["est_now"], "cap": p["cap"]})
    state["history"] = state["history"][-52:]
    _write(root, STATE_FILE, json.dumps(state, ensure_ascii=False, indent=1) + "\n")
    p["recorded"] = at
    _write(root, PLAN_FILE, json.dumps(p, ensure_ascii=False, indent=1) + "\n")
    return (f"정기 점검 기록: 기준점 {', '.join(f'{REPO_LABELS[r]} {w['to'][:7]}' for r, w in p['window'].items())} · "
            f"이월 {len(state['carry'])} · 다음 점검 {(today() + timedelta(days=AUDIT_EVERY_DAYS)).isoformat()} ({STATE_FILE})")
