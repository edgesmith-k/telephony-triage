#!/usr/bin/env python3
"""issue_post.py — 분석 결과를 Jira 코멘트 1건(PROBLEM / CAUSE / NEXT ACTION / ANALYSIS)으로 만들고 승인을 기록한다
(07-workflow.md §Step 9, 08-safety.md §9 규칙 2).

    issue_post.py status  <KEY> [--json]
    issue_post.py render  <KEY> [--fill <json>] [--format jira-wiki|markdown] [--omit a,b] [--again] [--json]
    issue_post.py approve <KEY> --sha <post_sha256> [--json]

`JOB` = `<work_dir>/<KEY>`. 입력은 모두 이미 마스킹된 파일이다: `JOB/analysis.json`, `JOB/jira.json`(원문 인용 검사용 텍스트는
본문에 넣지 않는다), `JOB/plan.json`(있으면), `JOB/triage-state.json`, 스냅샷 `issue-db.config.yaml`(`mask.allow_patterns`,
`jira_key_regex`).

- `render`: 스크립트가 결정적인 칸을 채우고 LLM 칸(`problem`·`cause`·`next`·`code_location`)은 `--fill`의 JSON에서 받는다.
  `--fill`이 없으면 LLM 칸을 `TODO(LLM)`로 둔 초안 화면만 낸다(해시 줄 없음). `--fill`이 있으면 검사(형식·basis·길이·TODO·
  로그 원문 줄·Jira 원문 40자 이상 인용·code.skipped인데 코드 위치) → 마스킹(결정적 본문의 토큰 다음 번호부터, 전체 본문에
  다시 적용, 남은 식별자 0) → 렌더 후 `JOB/post.md`(올라갈 본문 그대로)와 확인 화면을 낸다. 화면 마지막 줄은
  `post_sha256: <hex>`이고 게시 가능할 때만 낸다. 실행할 때마다 기존 `post.approved.json`을 지운다(승인 무효화).
  `--omit failed_step|fields|evidence|must_show|others`(쉼표 구분)로 스크립트 칸 항목을 뺄 수 있다(문구는 못 바꾼다).
  `--again`은 사용자가 "다시 올려줘"라고 명시했을 때만 쓴다(게시 이력이 있어도 게시 가능, 승인 기록에 `again: true`).
  `JOB/plan.json`은 analyze 계획이고 이번 analysis.json 뒤에 저장된 것만 분류 출처로 쓴다(낡은 계획은 "계획 없음").
  `--json`의 `post_sha256`은 게시 가능할 때만 낸다.
- `approve`: 사용자가 확인 화면을 승인한 뒤에만 부른다. `--sha` == `post.render.json` == `post.md` 해시, 분석
  `request_hash` 불변, 형식이 지금 설정과 같음(`--format`으로 고른 경우 제외), 게시 이력 없음을 확인하고 `post.approved.json`(30분 유효, 1회용)을 쓴 뒤 MCP 도구 이름과 인자
  `{tool, arguments, body_sha256, expires_at}`를 낸다. 스킬은 이 값으로 도구를 한 번만 부른다. guard가 승인 기록과 대조해 ask를 낸다.
- `status`: `{key, postable, reason, state: none|draft|rendered|approved|posted|error, tool, format, post_sha256,
  approved_at, expires_at, posted_at, comment_id}`.

게시 가능(postable) 조건(첫 실패가 `reason`): 코멘트 도구 설정 유효 → analysis.json `status: ok` → `mode` write·read-only →
`triage-state.json` 마지막 실행의 `request_hash`가 같고 `dry_run`이 거짓 → `jira.origin: mcp` → 게시 이력 없음(또는 `--again`).
게시 가능하지 않아도 render는 본문 파일을 만든다(직접 붙여넣기 대안). lock은 잡지 않는다: `JOB/post*` 파일만 쓰고
git·clone·스냅샷·worktree를 건드리지 않는다.

종료 코드: 0 = 완료(postable이 거짓이어도 render는 0), 1 = 검사 실패(fill 형식·basis·길이·TODO·로그 원문 줄·Jira 원문 인용·
마스킹 잔여, approve의 sha 불일치·render 뒤 post.md 편집·분석 변경·이미 게시함), 2 = 사용·환경 오류(site-defaults·사용자
config 없음, 키 형식 불일치, analysis.json 없음·status≠ok, approve인데 postable 거짓, plan.json 손상).
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import compat, issuepost, masking, session_lock, site_defaults, userconfig  # noqa: E402
from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402
import platforms  # noqa: E402

DEFAULT_KEY_RE = r"[A-Z][A-Z0-9]+-\d+"     # jira_fields.DEFAULT_KEY_RE와 같다
OMIT_KEYS = ("failed_step", "fields", "evidence", "must_show", "others")
FILL_KEYS = {"problem", "cause", "next", "code_location"}
BASIS = {"log": "[로그로 확인]", "code": "[코드로 추정]", "placeholder": "[placeholder 규칙 결과]", "explore": "[탐색 분석 가설]"}
PROBLEM_MAX, CAUSE_TEXT_MAX, NEXT_MAX, CODE_MAX = 200, 300, 200, 200
CAUSE_ITEMS, NEXT_ITEMS = (1, 4), (0, 3)
FIELD_MAX = 60                              # Jira 구조화 필드 값 하나 (작성자가 정하는 값: 한 줄로 접고 자른다)
FAILED_STEP_MAX, EVIDENCE_LINES, EVIDENCE_CHARS, OTHERS_MAX = 120, 6, 160, 3
QUOTE_MIN = 40                              # Jira 원문과 이만큼 같은 연속 부분이 있으면 인용으로 본다
TODO = "TODO(LLM)"
CONFIRMED = {"accepted", "chose-other", "new-cause", "new-type"}


class Usage(Exception):
    pass


# -- 입력 --------------------------------------------------------------------------------------


def _read(path: Path, what: str) -> dict | None:
    try:
        return issuepost.read_json(path)
    except (OSError, ValueError) as exc:
        raise Usage(f"{what} 손상: {path} ({type(exc).__name__})") from exc


class Job:
    def __init__(self, args, defaults: dict):
        user = userconfig.load_user()
        if user is None:
            raise Usage("사용자 config가 없다 — /telephony-triage:setup 을 먼저 한다")
        self.cfg = userconfig.merged(defaults, user)
        work = Path(str(userconfig.get(self.cfg, "work_dir"))).expanduser()
        self.snap = work / session_lock.SNAPSHOT_DIR
        db_cfg = compat.load_db_config(self.snap) if (self.snap / "issue-db.config.yaml").is_file() else {}
        key_re = re.compile(str(db_cfg.get("jira_key_regex") or DEFAULT_KEY_RE))
        self.key = args.key
        if not issuepost.KEY_SAFE_RE.fullmatch(self.key) or not key_re.fullmatch(self.key):
            raise Usage(f"Jira 키 형식이 아니다: {self.key}")
        self.allow = list((db_cfg.get("mask") or {}).get("allow_patterns") or [])
        self.dir = work / self.key
        self.spec, self.spec_err = issuepost.write_spec(self.cfg)
        self.analysis = _read(self.dir / "analysis.json", "analysis.json")
        self.render_doc = _read(self.dir / issuepost.RENDER_FILE, issuepost.RENDER_FILE)
        self.approved = _read(self.dir / issuepost.APPROVED_FILE, issuepost.APPROVED_FILE)
        self.result = _read(self.dir / issuepost.RESULT_FILE, issuepost.RESULT_FILE)

    def path(self, name: str) -> Path:
        return self.dir / name

    def require_analysis(self) -> dict:
        if not self.analysis or self.analysis.get("status") != "ok":
            raise Usage(f"{self.dir / 'analysis.json'}이(가) 없거나 status가 ok가 아니다 — analyze를 먼저 끝낸다")
        return self.analysis

    def plan(self) -> dict | None:
        """이번 분석의 작업 계획(사용자 확정 결과)만. 다른 키·결정 없는 계획·analyze가 아닌 계획·이번 분석보다 먼저
        저장된 계획(낡은 plan.json)은 쓰지 않는다(`plan_skipped`에 사유). plan에는 분석과 잇는 값이 없다(`started_at`은
        lock 획득 시각이라 실행보다 앞선다): Step 7이 이번 analysis.json 뒤에 저장했는지를 파일 수정 시각으로 본다."""
        self.plan_skipped = None
        path = self.dir / "plan.json"
        plan = _read(path, "plan.json")
        if not plan or (plan.get("jira") or {}).get("key") != self.key:
            return None
        if not (isinstance(plan.get("feedback"), dict) and plan["feedback"].get("decision")):
            return None
        if plan.get("request_hash") and self.analysis and plan["request_hash"] != self.analysis.get("request_hash"):
            self.plan_skipped = "다른 분석의 계획(request_hash)"
            return None
        if plan.get("source") != "analyze":
            self.plan_skipped = f"analyze 계획이 아님(source: {plan.get('source')})"
            return None
        if not plan.get("request_hash") and path.stat().st_mtime_ns < (self.dir / "analysis.json").stat().st_mtime_ns:
            self.plan_skipped = "이번 분석 전에 저장된 계획"
            return None
        return plan

    def tool_format(self, override: str | None) -> str:
        if override:
            return override
        fmt = (self.spec or {}).get("format") or userconfig.get(self.cfg, "jira.write_tools.add_comment.format")
        return fmt if fmt in issuepost.FORMATS else issuepost.DEFAULT_FORMAT

    def posted(self) -> bool:
        return bool(self.result and self.result.get("status") == "posted")

    def postable(self, again: bool, history: bool = True) -> tuple[bool, str | None]:
        """(게시 가능, 첫 실패 사유). `history=False`면 게시 이력(6번)은 보지 않는다(approve가 따로 종료 1로 본다)."""
        if self.spec is None:
            return False, (f"코멘트 도구 설정 오류: {self.spec_err}" if self.spec_err
                           else "쓰기 도구 미설정(jira.write_tools.add_comment)")
        a = self.analysis
        if not a or a.get("status") != "ok":
            return False, "분석 결과(analysis.json status: ok)가 없다"
        if a.get("mode") not in ("write", "read-only"):
            return False, f"{a.get('mode')} 실행 결과는 게시하지 않는다"
        try:
            state = issuepost.read_json(self.dir / "triage-state.json") or {}
        except (OSError, ValueError):
            state = {}
        runs = (state.get("job") or {}).get("runs") or []
        last = runs[-1] if runs and isinstance(runs[-1], dict) else {}
        if last.get("request_hash") != a.get("request_hash"):
            return False, "분석 상태(triage-state.json)가 analysis.json과 다르다 — 다시 분석한다"
        if last.get("dry_run") is not False:
            return False, "--dry-run 실행 결과는 게시하지 않는다" if last.get("dry_run") else "실행 기록에 dry-run 여부가 없다 — 다시 분석한다"
        if (a.get("jira") or {}).get("origin") != "mcp":
            return False, f"Jira가 MCP에서 오지 않았다(origin: {(a.get('jira') or {}).get('origin')})"
        if history and self.posted() and not again:
            r = self.result
            return False, (f"이미 게시함(comment {r.get('comment_id') or '?'}, {r.get('posted_at')}) — "
                           "다시 올리려면 사용자가 명시한 뒤 --again")
        return True, None


# -- 분류·칸 -------------------------------------------------------------------------------------


def _clip(text, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _cand_name(c: dict) -> str:
    return c.get("cause") or c.get("type") or "?"


def _score(c: dict) -> str:
    return f"규칙 일치 점수 {c.get('score')} (S={c.get('S')}, C={c.get('C')}) — 진단 확신도 아님"


def _find_op(plan: dict, kind: str, pred) -> dict | None:
    return next((op for op in plan.get("operations") or [] if isinstance(op, dict) and op.get("op") == kind and pred(op)),
                None)


def classify(a: dict, plan: dict | None) -> dict:
    """CAUSE·NEXT ACTION의 결정적 내용. `cand`는 본문이 가리키는 후보(근거 로그·해결책 출처)."""
    cands = [c for c in a.get("candidates") or [] if isinstance(c, dict)]
    top = cands[0] if cands else None
    by_type = lambda t: next((c for c in cands if c.get("type") == t), None)  # noqa: E731
    out = {"cand": None, "lines": [], "next": [], "resolved": False}
    pr = ((plan or {}).get("pr") or {}).get("number")
    pr_text = f"이슈 DB PR #{pr} 리뷰 중" if pr else "이슈 DB 미반영"
    if plan:
        fb = plan["feedback"]
        decision, final = fb.get("decision"), fb.get("final")
        out["decision"] = decision
        if decision in ("accepted", "chose-other"):
            cand = next((c for c in cands if c.get("cause") == final), None)
            out["cand"] = cand
            if cand:
                cls = f"{cand.get('category')} > {cand.get('type')} > {final} {cand.get('title') or ''}".rstrip()
            else:
                cls = f"{str(final).rsplit('-', 1)[0]} > {final}"
            out["cls"], out["confirm"] = cls, f"사용자 확정({decision})"
            out["lines"].append(_score(cand) if cand else
                                (f"자동 후보 밖의 원인 — 자동 분석 1위 {_cand_name(top)} {_score(top)}" if top else "자동 후보 없음"))
            if cand and cand.get("resolution"):
                out["resolved"] = True
                out["next"].append(f"해결책: {cand['resolution']} (해결책 검증: "
                                   f"{'검증됨' if cand.get('resolution_verification') == 'verified' else '미검증'})")
                if cand.get("fix_status"):
                    msg = cand.get("fix_message")
                    out["next"].append(f"수정 상태: {cand['fix_status']}" + (f" — {msg}" if msg else ""))
            elif not cand:
                out["resolved"] = True
                out["next"].append(f"해결책: 이슈 DB {final} 참조(자동 후보 밖)")
        elif decision in ("new-cause", "new-type"):
            if decision == "new-cause":
                op = _find_op(plan, "new-cause", lambda o: o.get("temp_id") == final) or {}
                cause = op.get("cause") or {}
                cat = (by_type(op.get("type")) or {}).get("category")
                type_text = op.get("type") or "?"
            else:
                op = _find_op(plan, "new-type", lambda o: (o.get("first_cause") or {}).get("temp_id") == final) or {}
                cause = (op.get("first_cause") or {}).get("cause") or {}
                cat = op.get("category")
                type_text = f"새 유형 {(op.get('type') or {}).get('title') or ''} ({op.get('temp_id')})"
            out["cls"] = (f"{cat or '?'} > {type_text} > 새 원인 {cause.get('title') or ''} "
                          f"(임시 ID {final}, {pr_text})")
            out["confirm"] = f"사용자 확정({decision})"
            if top:
                out["lines"].append(f"자동 분석 1위 {_cand_name(top)} {_score(top)}")
            if cause.get("resolution"):
                out["resolved"] = True
                out["next"].append(f"해결책(새 원인 제안, 미검증): {cause['resolution']}")
        elif decision == "unresolved":
            op = _find_op(plan, "unresolved", lambda o: True) or {}
            type_id = op.get("type") or (top or {}).get("type") or "?"
            cat = (by_type(type_id) or {}).get("category")
            out["cls"], out["confirm"] = f"{cat or '?'} > {type_id} > 원인 미확정", "원인 미확정(사용자 판단)"
            if top:
                out["lines"].append(f"자동 분석 1위 {_cand_name(top)} {_score(top)}")
        else:
            plan = None     # 모르는 결정: 계획 없음으로 보고 자동 후보만 쓴다
    if not plan:
        out["decision"] = None
        out["confirm"] = "자동 분석 1위 후보 — 사람이 확정하지 않음"
        if top:
            out["cand"] = top
            if top.get("cause") and top.get("C"):
                out["cls"] = f"{top.get('category')} > {top.get('type')} > {top['cause']} {top.get('title') or ''}".rstrip()
                out["lines"].append(_score(top))
                if top.get("resolution"):
                    out["resolved"] = True
                    out["next"].append(f"해결책: {top['resolution']} (해결책 검증: "
                                       f"{'검증됨' if top.get('resolution_verification') == 'verified' else '미검증'})")
                    if top.get("fix_status"):
                        msg = top.get("fix_message")
                        out["next"].append(f"수정 상태: {top['fix_status']}" + (f" — {msg}" if msg else ""))
            else:
                out["cls"] = f"{top.get('category')} > {top.get('type')} > 원인 미확인"
                out["lines"] += [_score(top), "유형만 일치, 원인 미확인"]
        else:
            count = (a.get("unjudged") or {}).get("count") or 0
            out["cls"] = f"판정 불완전 — 판정 불가 유형 {count}개" if count else "후보 없음"
            out["confirm"] = "자동 분석(사람 미확정)"
    if not out["resolved"]:
        out["next"].insert(0, "원인 미확정 — 추가 로그·재현 정보 필요")
    if plan:
        out["db"] = f"이슈 DB: PR #{pr} 리뷰 중" if pr else "이슈 DB: 계획만 저장(이슈 DB 미반영)"
    else:
        out["db"] = "이슈 DB: 기록 안 함"
    return out


def _line(text: str) -> dict:
    return {"kind": "line", "text": text}


IN_RANGE = {True: "발생 시각 포함", "partial": "발생 시각 일부", False: "발생 시각 밖"}


def build(job: Job, a: dict, plan: dict | None, fill: dict | None, omit: set[str]) -> tuple[dict, str, dict]:
    """(sections, tail, info). fill이 None이면 LLM 칸은 TODO(LLM)."""
    jira_doc = _read(job.path("jira.json"), "jira.json") or {}
    fields = jira_doc.get("jira") or {}
    note = ((plan or {}).get("jira") or {}).get("note")
    cl = classify(a, plan)
    s = {name: [] for name in issuepost.SECTIONS}
    # PROBLEM
    s["PROBLEM"].append(_line(f"Jira: {job.key}"))
    if "fields" not in omit:
        parts = [f"{label}: {_clip(fields[k], FIELD_MAX)}" for k, label in (("model", "단말"), ("sw", "SW"), ("android_version", _platform_label(a)),
                                                          ("carrier", "캐리어"), ("occurred_on", "발생일")) if fields.get(k)]
        if parts:
            s["PROBLEM"].append(_line(" · ".join(parts)))
    step = (a.get("jira") or {}).get("failed_step")
    if "failed_step" not in omit and isinstance(step, dict) and step.get("text"):
        s["PROBLEM"].append(_line(f"실패 스텝(보조 정보): {_clip(step['text'], FAILED_STEP_MAX)}"))
    if note:
        s["PROBLEM"].append(_line(f"요약: {_clip(note, PROBLEM_MAX)}"))
    else:
        s["PROBLEM"].append(_line(f"증상: {fill['problem'] if fill else TODO + ' 증상 한 줄'}"))
    # CAUSE
    s["CAUSE"].append(_line(f"분류: {cl['cls']} — {cl['confirm']}"))
    s["CAUSE"] += [_line(t) for t in cl["lines"]]
    if fill:
        s["CAUSE"] += [_line(f"{BASIS[c['basis']]} {c['text']}") for c in fill["cause"]]
    else:
        s["CAUSE"].append(_line(f"{TODO} 원인 설명 1~4줄(각 줄 basis: log|code|placeholder|explore)"))
    # NEXT ACTION
    s["NEXT ACTION"] += [_line(t) for t in cl["next"]] + [_line(cl["db"])]
    if fill:
        s["NEXT ACTION"] += [_line(f"다음 확인: {t}") for t in fill["next"]]
    else:
        s["NEXT ACTION"].append(_line(f"다음 확인: {TODO} (선택, 0~3개)"))
    # ANALYSIS
    cand = cl["cand"]
    ev = [e for e in (cand or {}).get("evidence") or [] if isinstance(e, dict)][:EVIDENCE_LINES]
    if "evidence" not in omit and ev:
        s["ANALYSIS"].append(_line(f"근거 로그 (마스킹, {_cand_name(cand)} 후보 {len(ev)}줄):"))
        s["ANALYSIS"].append({"kind": "code", "text": [_clip(f"{e.get('ts')} {e.get('tag')} {e.get('msg')}", EVIDENCE_CHARS)
                                                       for e in ev]})
    must = [str(m) for m in a.get("must_show") or []]
    logs = a.get("logs") or {}
    rng = logs.get("range")
    if isinstance(rng, list) and len(rng) == 2 and not any(m.startswith("로그 범위") for m in must):
        s["ANALYSIS"].append(_line(f"로그 범위: {rng[0]} ~ {rng[1]} ({IN_RANGE.get(logs.get('in_range'), '불명')})"))
    if "must_show" not in omit:
        s["ANALYSIS"] += [_line(f"주의: {m}") for m in must]
    if (a.get("code") or {}).get("skipped", True):
        s["ANALYSIS"].append(_line("코드 위치: 코드 미확인"))
    elif fill is None:
        s["ANALYSIS"].append(_line(f"코드 위치: {TODO} 파일:라인 — 분기 조건 (선택)"))
    elif fill.get("code_location"):
        s["ANALYSIS"].append(_line(f"코드 위치: {fill['code_location']}"))
    others = [c for c in a.get("candidates") or [] if isinstance(c, dict) and c is not cand][:OTHERS_MAX]
    if "others" not in omit and others:
        s["ANALYSIS"].append(_line("기타 후보: " + "; ".join(
            f"{_cand_name(c)} {c.get('title') or ''} ({c.get('score')})".replace("  ", " ") for c in others)))
    tail = f"telephony-triage 자동 분석(실행 {a.get('run')}, {a.get('generated_at')}). Jira·로그 원문은 싣지 않는다."
    texts = jira_doc.get("text") or {}
    quote_src = [str(texts.get("summary") or ""), str(texts.get("description") or "")] + \
        [str(c) for c in texts.get("comments") or []]
    info = {"cl": cl, "note": bool(note), "quote_src": [q for q in quote_src if q.strip()]}
    return s, tail, info


# -- fill 검사 -----------------------------------------------------------------------------------


def _platform_label(a: dict) -> str:
    """Jira 플랫폼 버전 칸 라벨 (`analysis.json`의 `platform`, 없으면 기본 플랫폼)."""
    try:
        return platforms.label(a.get("platform") or platforms.DEFAULT_NAME)
    except platforms.PlatformConfigError as exc:
        raise Usage(f"analysis.json platform: {exc}") from exc


def raw_finders() -> tuple[list, list[str]]:
    """`(find_raw 목록, 경고)`. 설치된 플랫폼 **전부**(`platforms.known()`, 설정과 무관)의 합집합으로 본다 — 게시 본문의
    원문 줄 검사는 넓을수록 안전하다. 불러오지 못한 플랫폼은 빼고 경고한다(나머지로 계속)."""
    finders, errors = platforms.known_raw_line_finders()
    warnings = [f"플랫폼 {name}을(를) 불러오지 못해 그 형식의 원문 줄 검사는 건너뛰었다 ({type(exc).__name__}: {exc})"
                for name, exc in errors]
    return [find for _, _, find, _ in finders], warnings


def _raw_log_line(text: str, finders: list) -> bool:
    """판별 함수가 예외를 내면 원문으로 본다(fail-closed)."""
    for find in finders:
        try:
            if find(text):
                return True
        except Exception:  # noqa: BLE001
            return True
    return False


def _quoted(text: str, sources: list[str]) -> bool:
    t = " ".join(text.split())
    for src in sources:
        s = " ".join(src.split())
        if len(t) >= QUOTE_MIN and len(s) >= QUOTE_MIN:
            m = difflib.SequenceMatcher(None, t, s, autojunk=False).find_longest_match(0, len(t), 0, len(s))
            if m.size >= QUOTE_MIN:
                return True
    return False


def check_fill(raw, need_problem: bool, code_skipped: bool, masker, quote_src: list[str],
               finders: list | None = None) -> tuple[dict | None, list[str], list[str]]:
    """(마스킹된 fill 또는 None, problems, warnings). `finders`가 없으면 `raw_finders()`."""
    problems: list[str] = []
    warnings: list[str] = []
    if finders is None:
        finders, finder_warnings = raw_finders()
        warnings += finder_warnings
    if not isinstance(raw, dict):
        return None, ["fill이 JSON 객체가 아니다"], warnings
    unknown = sorted(set(raw) - FILL_KEYS)
    if unknown:
        problems.append(f"모르는 키: {', '.join(map(str, unknown))}")
    texts: list[tuple[str, str, int]] = []       # (이름, 값, 상한)
    problem = raw.get("problem")
    if problem is not None and not isinstance(problem, str):
        problems.append("problem은 문자열 또는 null이다")
    elif need_problem:
        if not (problem or "").strip():
            problems.append("problem(증상 한 줄)이 필요하다(plan의 jira.note가 없다)")
        else:
            texts.append(("problem", problem, PROBLEM_MAX))
    elif problem:
        warnings.append("plan의 jira.note가 있어 problem은 무시했다")
    cause = raw.get("cause")
    if not isinstance(cause, list) or not CAUSE_ITEMS[0] <= len(cause) <= CAUSE_ITEMS[1]:
        problems.append(f"cause는 {CAUSE_ITEMS[0]}~{CAUSE_ITEMS[1]}개 목록이다")
        cause = []
    for i, c in enumerate(cause):
        if not isinstance(c, dict) or set(c) - {"basis", "text"}:
            problems.append(f"cause[{i}]는 {{basis, text}} 객체다")
        elif c.get("basis") not in BASIS:
            problems.append(f"cause[{i}].basis가 없거나 다른 값이다(log|code|placeholder|explore)")
        elif not isinstance(c.get("text"), str) or not c["text"].strip():
            problems.append(f"cause[{i}].text가 비어 있다")
        else:
            texts.append((f"cause[{i}]", c["text"], CAUSE_TEXT_MAX))
    nxt = raw.get("next") if raw.get("next") is not None else []
    if not isinstance(nxt, list) or not NEXT_ITEMS[0] <= len(nxt) <= NEXT_ITEMS[1]:
        problems.append(f"next는 {NEXT_ITEMS[0]}~{NEXT_ITEMS[1]}개 목록이다")
        nxt = []
    for i, t in enumerate(nxt):
        if not isinstance(t, str) or not t.strip():
            problems.append(f"next[{i}]가 비어 있거나 문자열이 아니다")
        else:
            texts.append((f"next[{i}]", t, NEXT_MAX))
    code = raw.get("code_location")
    if code is not None and not isinstance(code, str):
        problems.append("code_location은 문자열 또는 null이다")
    elif code and code_skipped:
        problems.append("코드 분석을 건너뛰어(code.skipped) code_location을 넣을 수 없다")
    elif code:
        texts.append(("code_location", code, CODE_MAX))
    masked: dict[str, str] = {}
    for name, value, limit in texts:
        if "\n" in value or "\r" in value:
            problems.append(f"{name}: 칸당 한 줄이다(줄바꿈 금지)")
        if len(value) > limit:
            problems.append(f"{name}: {len(value)}자 > 상한 {limit}자")
        if "TODO" in value:
            problems.append(f"{name}: TODO가 남았다")
        if _raw_log_line(value, finders):
            problems.append(f"{name}: 로그 원문 줄 모양이다(근거 로그는 스크립트 칸에만)")
        m = masker.mask(value.strip())
        if _quoted(m, quote_src):
            problems.append(f"{name}: Jira 원문과 {QUOTE_MIN}자 이상 같다(원문 인용 금지)")
        masked[name] = m
    if problems:
        return None, problems, warnings
    return {"problem": masked.get("problem"),
            "cause": [{"basis": c["basis"], "text": masked[f"cause[{i}]"]} for i, c in enumerate(cause)],
            "next": [masked[f"next[{i}]"] for i in range(len(nxt))],
            "code_location": masked.get("code_location")}, problems, warnings


# -- 화면 ----------------------------------------------------------------------------------------


def screen(job: Job, a: dict, plan: dict | None, info: dict, fmt: str, body: str | None, omit: list[str],
           ok: bool, reason: str | None, problems: list[str], warnings: list[str], missing: list[str],
           new_tokens: int, sha: str | None) -> str:
    cl = info["cl"]
    tool = (job.spec or {}).get("tool") or "미설정"
    lines = [f"## Jira 게시 전 확인: {job.key} → 코멘트 1건 ({tool})"]
    length = f"{len(body):,}자" if body is not None else "-"
    lines.append(f"- 형식: {fmt} · 길이: {length} / 상한 {issuepost.BODY_MAX:,}자")
    lines.append(f"- 분류: {cl['cls']} — {cl['confirm']} · 분석 실행 {a.get('run')} ({a.get('generated_at')})")
    skipped = getattr(job, "plan_skipped", None)
    lines.append(f"- 분류 출처: JOB/plan.json ({plan.get('started_at')})" if plan else
                 "- 분류 출처: 계획 없음" + (f" (JOB/plan.json은 쓰지 않음: {skipped})" if skipped else ""))
    if body is not None:
        lines.append(f"- 마스킹: 적용(LLM 칸 새 토큰 {new_tokens}개), 남은 식별자 0")
    problem_src = "스크립트(plan note)" if info["note"] else "스크립트+LLM(problem)"
    lines.append(f"- 칸 출처: PROBLEM {problem_src} · CAUSE 스크립트+LLM(cause) · NEXT ACTION 스크립트+LLM(next) · "
                 "ANALYSIS 스크립트(+LLM code_location)")
    lines.append(f"- 빠진 항목(--omit): {', '.join(omit) if omit else '없음'}")
    lines.append("- 게시 가능: 예" if ok else f"- 게시 가능: 아니오 — {reason} (본문은 JOB/post.md에만 남는다)")
    lines += [f"- 경고: {w}" for w in warnings]
    if missing:
        lines.append(f"- LLM 칸 미작성: {', '.join(missing)} — JOB/{issuepost.FILL_FILE}을 쓰고 render --fill로 다시 한다")
    if problems:
        lines.append("- 검사 실패(fill을 고쳐 render --fill을 다시 한다):")
        lines += [f"  - {p}" for p in problems]
    if body is not None:
        title = "본문 (이대로 올라간다)" if not missing else "본문 초안 (TODO(LLM) 칸을 채워야 올릴 수 있다)"
        lines += [f"--- {title} ---", body, "--- 끝 ---"]
    if sha and ok and not missing and not problems:
        lines += ["선택: 승인 / 수정 요청 / 취소", f"post_sha256: {sha}"]
    return "\n".join(lines) + "\n"


# -- 커맨드 --------------------------------------------------------------------------------------


def _omit(value: str | None) -> list[str]:
    items = [v.strip() for v in (value or "").split(",") if v.strip()]
    bad = [v for v in items if v not in OMIT_KEYS]
    if bad:
        raise Usage(f"--omit 값은 {'|'.join(OMIT_KEYS)} 중에서 고른다: {', '.join(bad)}")
    return list(dict.fromkeys(items))


def cmd_render(args, job: Job) -> tuple[dict, int]:
    a = job.require_analysis()
    omit = _omit(args.omit)
    plan = job.plan()
    fmt = job.tool_format(args.format)
    job.dir.mkdir(parents=True, exist_ok=True)
    userconfig.ensure_private_dir(job.dir)
    (job.path(issuepost.APPROVED_FILE)).unlink(missing_ok=True)     # 다시 그리면 이전 승인은 무효다
    problems: list[str] = []
    warnings: list[str] = []
    fill = None
    raw = None
    if args.fill:
        try:
            raw = json.loads(Path(args.fill).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"fill을 읽지 못했다: {type(exc).__name__}")
    sections, tail, info = build(job, a, plan, None, set(omit))       # 결정적 본문(TODO 칸 포함)
    det_text = "\n".join(issuepost.section_text(sections[n]) for n in issuepost.SECTIONS) + "\n" + tail
    try:
        masker = masking.new_masker(existing_text=det_text, allow_patterns=job.allow)
    except masking.AllowPatternError as exc:
        raise Usage(str(exc)) from exc
    code_skipped = (a.get("code") or {}).get("skipped", True)
    missing: list[str] = []
    if args.fill and not problems:
        fill, p, warnings = check_fill(raw, not info["note"], code_skipped, masker, info["quote_src"])
        problems += p
    if not args.fill:
        missing = (["problem"] if not info["note"] else []) + ["cause"]
    if fill is not None:
        sections, tail, info = build(job, a, plan, fill, set(omit))
    body = None
    if not problems:
        for name in issuepost.SECTIONS:
            n = len(issuepost.section_text(sections[name]))
            if fill is not None and n > issuepost.SECTION_MAX[name]:
                problems.append(f"{name} {n:,}자 > 상한 {issuepost.SECTION_MAX[name]:,}자 — LLM 칸을 줄이거나 --omit")
        body = issuepost.RENDERERS[fmt](sections, tail)
        body = issuepost.normalize_body(masker.mask(body))
        if fill is not None and len(body) > issuepost.BODY_MAX:
            problems.append(f"본문 {len(body):,}자 > 상한 {issuepost.BODY_MAX:,}자")
        if masker.find(body):
            problems.append(f"마스킹되지 않은 식별자 {len(masker.find(body))}개가 남았다")
        if problems:
            body = None
    valid = body is not None and fill is not None
    sha = issuepost.body_sha256(body) if valid else None
    ok, reason = job.postable(args.again)
    post_path = job.path(issuepost.POST_FILE)
    if valid:
        post_path.write_text(issuepost.normalize_body(body) + "\n", encoding="utf-8", newline="\n")
        try:
            post_path.chmod(0o600)
        except OSError:
            pass
    else:
        post_path.unlink(missing_ok=True)
    fb = (plan or {}).get("feedback") or {}
    issuepost.write_private_json(job.path(issuepost.RENDER_FILE), {
        "schema": 1, "key": job.key, "format": fmt, "format_source": "option" if args.format else "config",
        "request_hash": a.get("request_hash"), "run": a.get("run"),
        "plan": {"decision": fb.get("decision"), "final": fb.get("final"),
                 "pr_number": ((plan or {}).get("pr") or {}).get("number")} if plan else None,
        "omit": omit, "again": bool(args.again), "postable": ok, "reason": reason, "post_sha256": sha,
        "created_at": issuepost.iso(issuepost.now())})
    new_tokens = sum(masker.counts.values())
    text = screen(job, a, plan, info, fmt, body, omit, ok, reason, problems, warnings, missing, new_tokens, sha)
    out = {"screen": text, "post_sha256": sha if ok else None, "postable": ok, "reason": reason, "slots_missing": missing,
           "problems": problems, "files": {"post": str(post_path) if valid else None,
                                           "render": str(job.path(issuepost.RENDER_FILE))}}
    return out, (CHECK_FAILED if problems else OK)


def spec_format(job: Job) -> str:
    return (job.spec or {}).get("format") or issuepost.DEFAULT_FORMAT


def cmd_approve(args, job: Job) -> tuple[dict, int]:
    a = job.require_analysis()
    doc = job.render_doc
    if not doc or doc.get("key") != job.key:
        return {"error": "render 기록이 없다 — render --fill부터 한다"}, CHECK_FAILED
    ok, reason = job.postable(bool(doc.get("again")), history=False)
    if not ok:
        raise Usage(f"게시할 수 없다: {reason}")
    post_path = job.path(issuepost.POST_FILE)
    body = post_path.read_text(encoding="utf-8") if post_path.is_file() else None
    if not doc.get("post_sha256") or args.sha != doc["post_sha256"]:
        return {"error": "--sha가 마지막 render의 post_sha256과 다르다 — 확인 화면을 다시 보이고 승인받는다"}, CHECK_FAILED
    if body is None or issuepost.body_sha256(body) != doc["post_sha256"]:
        return {"error": "render 뒤 post.md가 바뀌었다(또는 없다) — render --fill부터 다시"}, CHECK_FAILED
    if a.get("request_hash") != doc.get("request_hash"):
        return {"error": "render 뒤 분석이 다시 돌았다(request_hash) — render --fill부터 다시"}, CHECK_FAILED
    if doc.get("format_source") != "option" and doc.get("format") != spec_format(job):
        return {"error": f"render 뒤 코멘트 도구 형식이 바뀌었다({doc.get('format')} → {spec_format(job)}) — render --fill부터 다시"}, \
            CHECK_FAILED
    if job.posted() and not doc.get("again"):
        return {"error": "이미 게시함 — 다시 올리려면 사용자가 명시한 뒤 render --again"}, CHECK_FAILED
    at = issuepost.now()
    spec = job.spec
    record = {"schema": 1, "key": job.key, "tool": spec["tool"], "key_arg": spec["key_arg"],
              "body_sha256": doc["post_sha256"], "format": doc.get("format"), "request_hash": a.get("request_hash"),
              "approved_at": issuepost.iso(at), "expires_at": issuepost.iso(issuepost.expires(at)), "used_at": None,
              "again": bool(doc.get("again"))}
    issuepost.write_private_json(job.path(issuepost.APPROVED_FILE), record)
    return {"key": job.key, "tool": spec["tool"], "arguments": issuepost.call_arguments(spec, job.key, body),
            "body_sha256": record["body_sha256"], "expires_at": record["expires_at"]}, OK


def cmd_status(args, job: Job) -> tuple[dict, int]:
    doc, appr, res = job.render_doc, job.approved, job.result
    ok, reason = job.postable(bool((doc or {}).get("again")))
    if res and res.get("status") == "posted" and (doc is None or (
            res.get("body_sha256") == doc.get("post_sha256") and not doc.get("again"))):
        state = "posted"
    elif appr and not appr.get("used_at"):
        state = "error" if res and res.get("status") == "error" and res.get("approved_at") == appr.get("approved_at") \
            else "approved"
    elif doc:
        state = "rendered" if doc.get("post_sha256") else "draft"
    elif res:
        state = "posted" if res.get("status") == "posted" else "error"
    else:
        state = "none"
    return {"key": job.key, "postable": ok, "reason": reason, "state": state,
            "tool": (job.spec or {}).get("tool"), "format": job.tool_format(None),
            "post_sha256": (doc or {}).get("post_sha256"), "approved_at": (appr or {}).get("approved_at"),
            "expires_at": (appr or {}).get("expires_at"), "posted_at": (res or {}).get("posted_at"),
            "comment_id": (res or {}).get("comment_id")}, OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="issue_post.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--plugin-root", default=None)
    common.add_argument("--json", action="store_true", help="JSON 출력")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status", parents=[common])
    p.add_argument("key", metavar="KEY")
    p = sub.add_parser("render", parents=[common])
    p.add_argument("key", metavar="KEY")
    p.add_argument("--fill", metavar="json", help="LLM 칸 JSON {problem, cause[{basis, text}], next[], code_location}")
    p.add_argument("--format", choices=issuepost.FORMATS, help="본문 형식(기본: 코멘트 도구 설정, 없으면 jira-wiki)")
    p.add_argument("--omit", metavar="a,b", help="뺄 스크립트 칸 항목: " + "|".join(OMIT_KEYS))
    p.add_argument("--again", action="store_true", help="게시 이력이 있어도 다시 올린다(사용자가 명시했을 때만)")
    p = sub.add_parser("approve", parents=[common])
    p.add_argument("key", metavar="KEY")
    p.add_argument("--sha", required=True, metavar="post_sha256", help="확인 화면 마지막 줄의 post_sha256")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(Path(args.plugin_root) if args.plugin_root else None)
    try:
        job = Job(args, defaults)
        out, code = {"render": cmd_render, "approve": cmd_approve, "status": cmd_status}[args.cmd](args, job)
    except Usage as exc:
        print(f"issue_post.py: {exc}", file=sys.stderr)
        return USAGE
    if args.cmd == "render" and not args.json:
        sys.stdout.write(out["screen"])
    elif args.cmd == "status" and not args.json:
        print(f"{out['key']}: {out['state']} · 게시 가능 {'예' if out['postable'] else '아니오 — ' + str(out['reason'])}")
    else:
        if "error" in out:
            print(f"issue_post.py: {out['error']}", file=sys.stderr)
        print(json.dumps(out, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
