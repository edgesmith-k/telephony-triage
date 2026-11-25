"""`triage.py check-output <KEY> --for deep|explore [--skipped <사유>] [--out <dir>]` — 5-1·5-2 출력 검사(B2 §6).

Claude가 쓴 `JOB/deep-output.md`·`JOB/explore-output.md`를 받아:
1. `mask_pii`와 같은 마스킹을 하고 마스킹한 글을 그 파일에 다시 쓴다(뒤 Step 7은 마스킹된 글만 본다).
2. 고정 칸과 UTF-8 바이트 한도를 본다(한 칸 768바이트 = 한글 약 250자).
3. 근거 원문 검사: 인용이 준 타임라인(모듈 뷰·`JOB/timeline.md`, 설치 스킬이면 events.json 전체 행)이나 `triage.py window` 구간
   (`JOB/windows.json` 기록과 sha256이 같은 `window-<n>.md`만 — 바뀌었거나 없으면 빼고 경고·`windows_excluded`)에 있는지.
4. report.md의 5-1·5-2 줄(과 `  - ` 아래 줄)을 쓴다 — `TODO(LLM)`이 남은 줄만 고친다. 모델은 그 줄을 고치지 않는다.
   탐색 가설 줄에는 그 가설의 원문에 없는 인용 수 `[근거 불일치 N]`(N>0일 때만).
   정상 가설(`가설 N: 정상(설계상 정상 동작) — <이유>`)은 `로그로 확인` 인용 하나 이상이 원문 검사 `ok`일 때만 정상으로 본다(약함은
   아니다) — 아니면 그 가설 줄에 `[정상 근거 없음]`. 적합성 확인에서 고른 가설(`가장 유력: N`, 없으면 1)이 정상이면 1위 채택을
   보류한다(아래 5와 같은 보류, 기록 `fit_hold_reason: normal` — 부적합 보류는 `unfit`).
   `규칙 제안:`(deep 칸·탐색 꼬리)은 `  - 규칙 제안 (심층|탐색): <줄>` 하위 줄로 쓴다(SKILL Step 7이 묻는다). `— 근거: <문구>`가 있으면
   그 문구가 원문 검사 `ok`일 때만, 없으면 근거 원문 검사를 실제로 했고 원문에 없는 인용이 하나도 없을 때만 싣는다. 뺀 것은 수만
   한 줄로 적는다(그 줄에는 Step 7이 고르지 않게 `규칙 제안` 낱말을 쓰지 않는다).
   적합성 확인(`fit_check`)이 가설 없이 끝나거나 `1위 판단: 부적합`이면(가설이 있어도, sim1122 F2) 1위 부적합 보류 — 결론·해결책 줄도
   보류로 고치고 기록에 `fit_hold: <원인 ID>`(줄을 못 고쳐도 기록은 남기고 `fit_hold_unwritten`·stderr 경고. 뒤 검사·생략·실패 기록도
   fit_hold를 이어받는다). 적합성 확인·채택·가설 있음인데 `1위 판단` 칸이 없으면 채택은 그대로 두고 경고 하위 줄(`WARN_NO_FIT`).
5. 확인할 내용(사용자 질문) 줄 꼬리를 탐색 결과를 가리키게 고친다(통과면 답 자리, 생략·실패면 답 안 함, F7).
6. 같은 실행에서 다시 검사하면 앞 검사의 원문에 없는 인용 수를 `fabricated_before`로 이어받는다(F9 — 고쳐 다시 검사해도 지우지 않는다).

`--skipped "<사유>"`: 실행하지 않았거나 실패 — 줄을 "생략: <사유>"로(이미 스크립트가 쓴 생략·해당 없음·받기 실패 줄이면 그대로).
기록 `JOB/check-output.json[purpose]`(스크립트만 쓴다, guard 규칙 12)와 trace `checked` 행(`core.trace_event`). 표시 의무: 작업 디렉토리 JOB이면 검사마다 `evidence` 기록
(`.shown/log.jsonl`, 원문에 없는 인용이 있을 때만 줄이 있다 — 빈 줄은 앞 의무를 닫는다).

출력은 JSON 한 줄(≤ 4KB). 종료 0 = 썼음(또는 `kept`), 1 = 형식·마스킹 실패(줄은 생략으로 고쳤다, `next`),
2 = 사용 오류·설정 오류·작업 없음·작업 디렉토리 이상(`next`가 있으면 따른다, 없으면 멈춘다).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from common import evidence, masking, provenance, shown
from common.fixtures import CAUSE_ID
from common.exitcodes import CHECK_FAILED, OK, USAGE

from . import report as rep
from .core import (
    DEEP_MAX_BYTES,
    DEEP_PREFIX,
    DEEP_SKIPPED,
    EVIDENCE_SUB,
    EXPLORE_INPUT_FILE,
    EXPLORE_MAX_BYTES,
    EXPLORE_PREFIX,
    EXPLORE_SKIPPED,
    FIELD_MAX_BYTES,
    HYPS_MAX,
    NEXT_CHECK_FAILED,
    NEXT_CHECK_NA,
    OUTPUT_MAX_BYTES,
    QUOTES_MAX,
    TIMELINE_FILE,
    WINDOW_NAME_RE,
    WINDOW_RECORD,
    _now,
    trace_event,
)

RECORD = "check-output.json"
MODULE_RECORD = "module-skill.json"
OUTPUT_FILE = {"deep": "deep-output.md", "explore": "explore-output.md"}
PREFIX = {"deep": DEEP_PREFIX, "explore": EXPLORE_PREFIX}
SKIPPED = {"deep": DEEP_SKIPPED, "explore": EXPLORE_SKIPPED}
KEEP_SUB = ("  - 모듈 타임라인:",)
DEEP_TIMELINE = "module-skill/deep/timeline.md"      # `module --for deep`가 쓰는 심층 타임라인(모듈·설치 스킬 공통)
INPUT_NAMES = {"analysis.json", "events.json", "match.json", TIMELINE_FILE, EXPLORE_INPUT_FILE}
EVENTS_MAX = 64 << 20
SKILL_LABEL = "근거 원문 검사(events.json 기준)"
WARN_REWRITE = "경고: report.md 줄을 고치지 못했다"
WARN_HOLD = "경고: 1위 보류를 report.md {what}에 쓰지 못했다 — check-output 기록(fit_hold)·Jira 본문은 보류로 남긴다"
HOLD_KEEP = ("fit_hold", "fit_hold_reason", "fit_hold_unwritten")     # 탐색 기록을 새로 써도 이어받는다(보류로 고친 줄은 다음 run까지 남는다)
WARN_DECISION = "경고: analysis.json 판단(decision)을 고치지 못했다({why})"
TOP_FIT_SUB = "  - 1위 판단(모델): {fit}{why}"
TOP_FIT_HELD = " → 1위 {cause} 채택을 보류로 바꿨다"
TOP_FIT_NONE_HELD = " → 가설 없음이라 1위 {cause} 보류(1위 판단 '{fit}'과 맞지 않음 — 탐색 출력 확인)"
WARN_NO_FIT = "  - 경고: 1위 판단 칸 없음 — 1위 {cause} 채택은 그대로다(탐색 가설이 1위와 맞는지 확인)"
WARN_FIT_UNREAD = ("  - 경고: 1위 판단 칸을 읽지 못함 — `1위 판단: <원인 ID> 적합|부적합|모름 — <이유>` 형식이 아니다(1위 {cause} 판단은 "
                   "그대로)")
WARN_FIT_OTHER = ("  - 경고: 1위 판단의 부적합 원인({got})이 채택 원인 {cause}와 맞지 않아 보류하지 않았다(`1위 판단: {cause} …`로 "
                  "다시 확인)")
WARN_FIT_RELEASE = ("  - 경고: 1위 판단 적합 — 앞 실행 부적합 원인 {cause}의 보류(prior.unfit)는 이번 결과에 그대로다(같은 인자로 run을 "
                    "다시 하면 보류가 풀린다)")
# 확인할 내용 줄(report.py) 꼬리: 탐색 검사 뒤 답 자리를 가리킨다(F7)
QUESTION_PREFIX = "- 확인할 내용(사용자 질문): "
QUESTION_PENDING = " — 탐색 분석(동의 뒤)에서 답한다"
QUESTION_DONE = " — 답: 아래 탐색 분석 줄(가설 1의 로그로 확인·반대 근거)과 `- 원인:`·다음 확인 줄"
QUESTION_DONE_NONE = " — 답: 아래 탐색 분석 줄(가설 없음 이유·다음 확인)과 `- 원인:` 줄"
QUESTION_SKIPPED = " — 탐색 분석 생략이라 답하지 않음(근거 로그로 직접 확인)"
QUESTION_TAILS = (QUESTION_PENDING, QUESTION_DONE, QUESTION_DONE_NONE, QUESTION_SKIPPED)
FAB_BEFORE = " · 앞 검사 원문에 없음 {n}(다시 검사해도 지우지 않음)"
# 정상 가설(설계상 정상 동작, explore.md 종합 판단 0): 머리가 `정상`으로 시작한다. 근거 인용이 원문에 없으면 정상으로 보지 않는다
NORMAL_RX = re.compile(r"^[`*\s]*정상(?:\s*\(|\s*[—–:-]|\s*$)")
NORMAL_BAD = " [정상 근거 없음]"
TOP_FIT_NORMAL_HELD = " → {n}번 가설이 정상(설계상 정상 동작)이라 1위 {cause} 보류"
NORMAL_HELD_SUB = "  - {n}번 가설이 정상(설계상 정상 동작, 근거 줄 원문 확인)이라 1위 {cause} 채택을 보류로 바꿨다"
WARN_TOP_NUM = "  - 경고: `가장 유력: {top}`을 가설 번호로 읽지 못해(없는 번호) 1번 가설로 적합성 확인을 봤다"
TOP_NUM_RX = re.compile(r"^[`*\s]*(?:가설\s*)?#?(\d+)(?!\d)")      # `가장 유력: 2`·`가설 2` (module_eval.TOP_NUM_RX와 같은 읽기)
# 규칙 제안 하위 줄(SKILL Step 7 `규칙 제안` 질문이 report.md에서 읽는다). 근거 원문 확인이 안 된 제안은 싣지 않는다
RULE_SUB = "  - 규칙 제안 ({kind}): {text}"
RULE_DROPPED = "  - {kind} 출력의 제안 {n}개는 근거가 원문에서 확인되지 않아 뺐다"
RULE_KIND = {"deep": "심층", "explore": "탐색"}
RULE_BASIS_RX = re.compile(r"\s[—–]\s*근거\s*[:：]\s*(.+)$")
RULES_MAX, RULE_CLIP = 5, 300
# 11/25 기대 체인 형식 경고(explore.md 쓰는 것): 판정이 아니라 모델에게 고쳐 쓰기를 한 번 청한다(사내 모델이 형식을 놓칠 수 있어 실패로 두지 않는다)
FORMAT_SUB = "  - 형식 경고(탐색, 판정 아님): {text}"
FORMAT_NEXT = ("explore-output.md에서 형식 경고가 가리킨 칸만 고쳐 쓰고 같은 check-output을 한 번만 다시 실행한다(두 번째 결과는 경고가 "
               "남아도 그대로 쓴다)")
FORMAT_CLIP = 600
TIMER_RX = re.compile(r"타이머|timer|throttl|스로틀|재시도|retry|backoff|임계|threshold|카운터|counter|횟수", re.IGNORECASE)
BOUNDARIES = ("AP 내부", "AP-CP 경계", "CP 내부", "CP-망 경계", "환경", "모름")
CLAIM_STEP_RX = re.compile(r"단계\s*#?(\d+)|^\D*?(\d+)")
FLIP_RX = re.compile(r"(아니오|아니요|예)[\s`*.)\]]*$")
# 분석 스킬 의견 `<원인 ID> — <근거>`의 앞 ID. 백틱·굵게로 감싸거나 조사(`ID와`)가 붙어도 잡고, 숫자가 더 붙은 것은 아니다
OPINION_ID = re.compile(rf"\s*[`*]*({CAUSE_ID})(?!\d)")


class _Stop(Exception):
    """실패 출력 하나: 종료 코드, reason, next(없으면 멈춤), stderr 한 줄."""

    def __init__(self, code: int, reason: str, nxt: str | None = None, err: str | None = None, **extra):
        super().__init__(reason)
        self.code, self.reason, self.next, self.err, self.extra = code, reason, nxt, err, extra


def _emit(data: dict) -> None:
    print(rep.dumps(data))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _kind(path: Path) -> str | None:
    """'file' | 'link' | 'other' | None(없음)."""
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return None
    return "link" if stat.S_ISLNK(mode) else "file" if stat.S_ISREG(mode) else "other"


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if _kind(path) == "file" else None
    except (OSError, ValueError):
        return None


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
        try:
            if os.write(fd, data) != len(data):
                raise OSError("short write")
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _record(job: Path, purpose: str, entry: dict) -> None:
    path = job / RECORD
    data = _load(path)
    data = data if isinstance(data, dict) else {}
    old = data.get(purpose)
    if isinstance(old, dict) and old.get("fit_hold") and "fit_hold" not in entry:   # 다시 검사·생략·실패해도 보류는 이어 간다
        entry = {**entry, **{k: old[k] for k in HOLD_KEEP if k in old}}
    before = _fab_before(old)
    if before and "fabricated_before" not in entry:      # F9: 앞 검사의 원문에 없는 인용 수는 다시 검사·생략·실패해도 남긴다
        entry = {**entry, "fabricated_before": before}
    data[purpose] = entry
    try:
        _write_atomic(path, (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    except OSError:
        print(f"경고: {RECORD}를 쓰지 못했다", file=sys.stderr)


def _fab_before(old) -> int:
    """앞 기록까지의 원문에 없는 인용 수(가장 큰 값). 기록이 없거나 숫자가 아니면 0."""
    if not isinstance(old, dict):
        return 0
    vals = [v for v in (old.get("fabricated"), old.get("fabricated_before")) if isinstance(v, int) and not isinstance(v, bool)]
    return max(vals, default=0)


def _obligation(args, job: Path, purpose: str, lines: list[str]) -> None:
    """check-output 표시 의무(B2-6: 심층은 결과 첫 줄 + 지어낸 인용이 있으면 근거 원문 검사 줄, 탐색은 그 검사 줄만,
    `_skipped`·`_fail`은 빈 줄 = 닫기만). --out JOB은 작업 디렉토리 밖이라 기록하지 않는다."""
    if args.out:
        return
    shown.record(job.parent, "triage", "evidence", job.name, key=f"evidence:{job.name}/{purpose}", lines=lines,
                 path=str(job / "report.md"))


def _resolve_job(args, defaults: dict) -> Path:
    """`module`과 같은 JOB 정하기(B1 §4.3 1·3·4): 키 → (--out 아니면) 다른 켠 플랫폼의 작업 찾기 → JOB 디렉토리."""
    from common import userconfig
    from triage import (  # triage.py의 explore·release와 같은 함수(지연 import: triage가 이 모듈을 부른다)
        _find_job,
        _work_key,
    )
    cfg = args.platform_cfg
    key = (args.key if re.fullmatch(r"[A-Za-z0-9._-]+", args.key) else None) if args.out else _work_key(cfg, args.key)
    if key is None:
        raise _Stop(USAGE, "사용 오류", err=f"Jira 키 형식이 아니다: {masking.mask_brief(args.key, 60)} — 키를 확인한 뒤 다시 실행한다")
    args.key = key
    if not args.out:
        _find_job(args, defaults, key)
        cfg = args.platform_cfg
    job = Path(args.out).expanduser().resolve() if args.out else Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / key
    if not job.is_dir():
        raise _Stop(USAGE, "작업 없음", err=f"작업 디렉토리가 없다: {job} — 이 키로 /telephony-triage:analyze를 먼저 실행한다")
    kind = _kind(job / "report.md")
    if kind == "link":
        raise _Stop(USAGE, "작업 디렉토리 이상", NEXT_CHECK_NA, "report.md가 링크다 — 따라가지 않는다")
    if kind != "file":
        raise _Stop(USAGE, "작업 없음", err="report.md가 없다 — 이 키로 /telephony-triage:analyze를 먼저 실행한다")
    for name in (RECORD, MODULE_RECORD):
        if _kind(job / name) in ("link", "other"):
            raise _Stop(USAGE, "작업 디렉토리 이상", NEXT_CHECK_NA, f"{name}가 일반 파일이 아니다")
    return job


# --- 근거 원문 -------------------------------------------------------------------------------------------

def _inputs_match(job: Path, inputs) -> bool:
    if not isinstance(inputs, dict) or not inputs:
        return False
    for name, digest in inputs.items():
        if name not in INPUT_NAMES:
            return False
        path = job / name
        cur = _sha(path.read_bytes()) if _kind(path) == "file" else None
        if cur != digest:
            return False
    return True


def _recorded_timeline(job: Path, rec) -> tuple[str | None, str | None, str | None]:
    """기록의 타임라인 → (JOB 기준 경로, 본문, 건너뛴 사유). inputs와 타임라인 sha256이 지금 파일과 같아야 쓴다."""
    tl = rec.get("timeline") if isinstance(rec, dict) else None
    if not isinstance(tl, dict) or not isinstance(tl.get("path"), str):
        return None, None, "타임라인 기록 없음"
    path = Path(tl["path"])
    path = path if path.is_absolute() else job / path
    try:
        rel = path.resolve().relative_to(job.resolve()).as_posix()
    except (OSError, ValueError):
        return None, None, "기록이 이전 분석 것"
    if not _inputs_match(job, rec.get("inputs")) or _kind(path) != "file":
        return None, None, "기록이 이전 분석 것"
    data = path.read_bytes()
    if tl.get("sha256") != _sha(data):
        return None, None, "기록이 이전 분석 것"
    return rel, data.decode("utf-8", "replace"), None


def _source(job: Path, purpose: str, mode: str, rec, events: dict | None) -> tuple[object, str | None, str | None]:
    """검사 원문 → (기록에 남길 JOB 기준 경로(들) | None, 원문 글 | None, 건너뛴 사유 | None)."""
    if purpose == "explore":
        rel, text, _why = _recorded_timeline(job, rec) if isinstance(rec, dict) else (None, None, None)
        if text is not None:
            return rel, text, None
        if _kind(job / TIMELINE_FILE) == "file":
            return TIMELINE_FILE, (job / TIMELINE_FILE).read_text(encoding="utf-8", errors="replace"), None
        return None, None, "타임라인 없음"
    if mode == "module":
        rel, text, why = _recorded_timeline(job, rec)
        return (rel, text, None) if text is not None else (None, None, why)
    # 설치 스킬: 심층 타임라인(있고 맞으면) + events.json 합친 행 전부
    parts, srcs = [], []
    if isinstance(rec, dict) and isinstance(rec.get("timeline"), dict):
        rel, text, _why = _recorded_timeline(job, rec)
    elif _kind(job / DEEP_TIMELINE) == "file":
        rel, text = DEEP_TIMELINE, (job / DEEP_TIMELINE).read_text(encoding="utf-8", errors="replace")
    else:
        rel, text = None, None
    if text is not None:
        parts.append(text)
        srcs.append(rel)
    ev = job / "events.json"
    if _kind(ev) != "file":
        return None, None, "events.json 없음"
    try:
        if os.stat(ev).st_size > EVENTS_MAX:
            return None, None, "events.json 큼"
    except OSError:
        return None, None, "events.json 없음"
    if events is None:
        return None, None, "events.json 못 읽음"
    parts.append(evidence.event_rows_text(events))
    srcs.append("events.json")
    return srcs, "\n".join(parts), None


def _windows(job: Path) -> tuple[list[str], list[str], list[str]]:
    """`triage.py window` 기록의 구간 중 지금 파일 sha256이 기록과 같은 것 → (JOB 기준 이름들, 본문들, 뺀 이름들(바뀜·없음))."""
    data = _load(job / WINDOW_RECORD)
    names, texts, bad = [], [], []
    for w in (data.get("windows") if isinstance(data, dict) else None) or []:
        name = w.get("path") if isinstance(w, dict) else None
        if not isinstance(name, str) or not WINDOW_NAME_RE.fullmatch(name):
            continue
        path = job / name
        raw = path.read_bytes() if _kind(path) == "file" else None
        if raw is None or _sha(raw) != w.get("sha256"):
            bad.append(name)
            continue
        names.append(name)
        texts.append(raw.decode("utf-8", "replace"))
    return names, texts, bad


# --- 칸 검사 ---------------------------------------------------------------------------------------------

def _b(text) -> int:
    return len(str(text or "").encode("utf-8"))


def _caps(purpose: str, mode: str, fields: dict, text: str) -> str | None:
    """첫 위반의 칸 이름(없으면 None)."""
    if purpose == "explore":
        if _b(text) > EXPLORE_MAX_BYTES:
            return "전체"
        if not fields["hyps"]:
            for name, value in (("가설 없음", fields["none"]), ("다음 확인", fields["next"])):
                if _b(value) > FIELD_MAX_BYTES:
                    return name
            return None
        if len(fields["hyps"]) > HYPS_MAX:
            return "가설"
        for hyp in fields["hyps"]:
            quotes = hyp["로그로 확인"]
            if not 1 <= len(quotes) <= QUOTES_MAX or any(_b(q) > FIELD_MAX_BYTES for q in quotes):
                return "로그로 확인"
            for name in ("가설", "코드로 추정", "반대 근거", "다음 확인"):
                if _b(hyp[name]) > FIELD_MAX_BYTES:
                    return name
        return None
    if _b(text) > DEEP_MAX_BYTES:
        return "전체"
    items = fields["근거"]
    low = 1 if mode == "module" else 0
    if not low <= len(items) <= QUOTES_MAX or any(_b(q) > FIELD_MAX_BYTES for q in items):
        return "근거"
    single = ("원인 층", "원인 데몬", "반대 근거", "분석 스킬 의견") if mode == "module" else ("요약", "분석 스킬 의견")
    for name in single:
        if _b(fields[name]) > FIELD_MAX_BYTES:
            return name
    return None


def _quotes(purpose: str, fields: dict | None) -> list[str]:
    """인용 목록. 탐색은 가설 순서대로 `로그로 확인` 전부 뒤에 가설 순서대로 `기대 체인` 관측 줄(`evidence.chain_quotes`)."""
    if not fields:
        return []
    if purpose == "explore":
        return ([q for hyp in fields["hyps"] for q in hyp["로그로 확인"]]
                + [q for hyp in fields["hyps"] for q in evidence.chain_quotes(hyp)])
    return list(fields.get("근거") or [])


def _parse(purpose: str, mode: str, text: str) -> dict | None:
    if purpose == "explore":
        return evidence.parse_explore(text)
    return evidence.parse_fields(text, evidence.FIELDS_DEEP if mode == "module" else evidence.FIELDS_SKILL)


def _chain_warnings(fields: dict) -> list[str]:
    """기대 체인 형식 경고(기계로 볼 수 있는 것만): 가장 유력(없으면 가설 1)에 표 없음, `첫 갈라짐` 단계가 표의 가장 이른 false가
    아님(없음·false 없는데 적음), false가 있는데 `원인 층` 없음, `책임 경계` 값이 목록 밖, 타이머·재시도·임계값·횟수 낱말이 든 가설
    (정상 가설 아님)에 `메커니즘 재계산` 없음, 가장 유력의 메커니즘 재계산이 `아니오`."""
    out = []
    picked = _picked(fields)
    for k, h in enumerate(fields.get("hyps") or []):
        n, rows = k + 1, h.get("기대 체인") or []
        if k == picked and not rows:
            out.append(f"가설 {n}(가장 유력)에 `기대 체인:` 표 없음 — 실패 줄 다음에 일어나야 할 일을 단계 표로")
        first = next((r["단계"] for r in rows if r["일치"] == "false"), None)
        m = CLAIM_STEP_RX.search(h.get("첫 갈라짐") or "")
        claim = int(m.group(1) or m.group(2)) if m else None
        if first is not None and claim is None:
            out.append(f"가설 {n}: 표의 첫 false가 단계 {first}인데 `첫 갈라짐: 단계 {first} — …` 칸이 없음")
        elif first is not None and claim != first:
            out.append(f"가설 {n}: 첫 갈라짐 단계 {claim} ≠ 표의 가장 이른 false 단계 {first} — 가장 잘 설명하는 단계가 아니라 가장 이른 false")
        elif first is None and claim is not None and rows:
            out.append(f"가설 {n}: 첫 갈라짐 단계 {claim}인데 표에 false 행이 없음")
        if first is not None and not h.get("원인 층"):
            out.append(f"가설 {n}: 첫 갈라짐이 있는데 `원인 층:` 없음 — 단계 {first}에서 해야 했는데 안 한 주체")
        if h.get("책임 경계") is not None and not h["책임 경계"].lstrip("`* ").startswith(BOUNDARIES):
            out.append(f"가설 {n}: `책임 경계`는 {' | '.join(BOUNDARIES)} 중 하나")
        mech = h.get("메커니즘 재계산")
        if not mech and TIMER_RX.search(h["가설"] or "") and not NORMAL_RX.match(h["가설"] or ""):
            out.append(f"가설 {n}: 타이머·재시도·임계값·횟수 원인인데 `메커니즘 재계산:` 없음 — 로그 값으로 다시 계산하고 고치면 뒤집히나")
        flip = FLIP_RX.search(mech or "")
        if k == picked and flip and flip.group(1) != "예":
            out.append(f"가설 {n}: 메커니즘 재계산이 '아니오'(고쳐도 결과가 안 뒤집힘)인데 가장 유력 — 원인이 아니다")
    return out


def _recheck_open(job: Path) -> bool:
    """앞 탐색 검사가 형식 경고를 냈고 아직 다시 검사하지 않았나(경고 뒤 한 번만 — `TODO(LLM)`이 없어도 줄을 다시 쓴다)."""
    data = _load(job / RECORD)
    rec = data.get("explore") if isinstance(data, dict) else None
    return isinstance(rec, dict) and bool(rec.get("format_warnings")) and not rec.get("format_recheck")


# --- 그리기 ----------------------------------------------------------------------------------------------

def _head(current: str | None, prefix: str, default: str) -> str:
    if current and current.startswith(prefix) and "): " in current:
        return current[: current.index("): ") + 3]
    return default


def _one(text) -> str:
    return " ".join(str(text or "").split())


def _render(purpose: str, mode: str, head: str, fields: dict, sub: str, fab_by_hyp: list[int] | None = None,
            normal_bad: list[bool] | None = None) -> list[str]:
    """report 줄. `fab_by_hyp`(탐색, 가설별 원문에 없는 인용 수)가 0보다 크면 그 가설 줄에 `[근거 불일치 N]`, `normal_bad`(정상이라고
    적었는데 원문에 있는 인용이 없음)면 `[정상 근거 없음]`."""
    if purpose == "explore":
        if not fields["hyps"]:
            return [f"{head}가설 없음: {_one(fields['none'])} / 다음 확인: {_one(fields['next'])}", sub]
        out = [f"{head}가설 {len(fields['hyps'])}개 — 점수·분류·검증에 쓰지 않는다"]
        for i, h in enumerate(fields["hyps"], 1):
            k = fab_by_hyp[i - 1] if fab_by_hyp else 0
            mark = (f" [근거 불일치 {k}]" if k else "") + (NORMAL_BAD if normal_bad and normal_bad[i - 1] else "")
            out.append(f"  - 가설 {i}{mark}: {_one(h['가설'])} / 로그로 확인: {' | '.join(_one(q) for q in h['로그로 확인'])} / "
                       f"코드로 추정: {_one(h['코드로 추정'])} / 반대 근거: {_one(h['반대 근거'])} / 다음 확인: {_one(h['다음 확인'])}"
                       + (f" / 첫 갈라짐: {_one(h['첫 갈라짐'])}" if h.get("첫 갈라짐") else ""))
        return out + [sub]
    quotes = " | ".join(_one(q) for q in fields["근거"])
    if mode == "module":
        first = (f"{head}원인 층 {_one(fields['원인 층'])} · 원인 데몬 {_one(fields['원인 데몬'])} / 분석 스킬 의견: "
                 f"{_one(fields['분석 스킬 의견'])}")
        return [first, f"  - 근거: {quotes}", f"  - 반대 근거: {_one(fields['반대 근거'])}", sub]
    return ([f"{head}{_one(fields['요약'])} / 분석 스킬 의견: {_one(fields['분석 스킬 의견'])}"]
            + ([f"  - 근거: {quotes}"] if fields["근거"] else []) + [sub])


def _evidence_sub(mode: str, res: dict | None, skipped: str | None, before: int = 0) -> str:
    if mode == "skill":
        lead = "  - " + SKILL_LABEL + ": "
    else:
        lead = EVIDENCE_SUB.format(text="")
    tail = FAB_BEFORE.format(n=before) if before else ""
    if skipped:
        return f"{lead}건너뜀({skipped}){tail}"
    text = f"인용 {res['n']}개 중 원문에 없음 {res['fabricated']}"
    if res["weak"]:
        text += f" · 약함 {res['weak']}"
    if mode == "skill" and res["raw"]:
        text += f" · 원문 로그 인용 {res['raw']}개(검사 밖)"
    if res["fabricated"]:
        text += f" ({res['first']}…)"
    return lead + text + tail


# --- 본체 ------------------------------------------------------------------------------------------------

def _rewrite(report: Path, prefix: str, lines: list[str], keep_sub: tuple[str, ...] = (), pending: bool = True) -> bool:
    ok = rep.rewrite_line(report, prefix, lines, keep_sub=keep_sub, only_pending=pending)
    if not ok:
        print(WARN_REWRITE, file=sys.stderr)
    return ok


def _top_cause(analysis: dict) -> str | None:
    top = (rep.lead_first(analysis.get("decision"), analysis.get("candidates") or []) or [None])[0]   # 채택 원인(없으면 1위)
    return top.get("cause") if isinstance(top, dict) else None


def _unfit_applies(analysis: dict, tf: dict | None) -> bool:
    """`1위 판단`의 부적합이 채택 원인(없으면 순위 1위)에 해당하나(RP-1·RP-7): 적은 ID가 그 원인과 같을 때, ID 없이 쓴 옛 형식은
    그 원인이 순위 1위일 때만(모델이 보는 "1위"는 `분류 후보:` 줄의 순위 1위다)."""
    if not tf or tf.get("fit") != "부적합":
        return False
    cause = _top_cause(analysis)
    rank1 = ((analysis.get("candidates") or [{}])[0] or {}).get("cause")
    return bool(cause) and (tf.get("cause") == cause if tf.get("cause") else cause == rank1)


def _normal_flags(fields: dict, per_hyp: list[list[str]] | None) -> tuple[list[bool], list[bool]]:
    """가설마다 (정상으로 봄, 정상이라 적었지만 근거 없음). 정상으로 봄 = 머리가 정상이고 `로그로 확인` 중 하나 이상이 원문 검사
    `ok`다(약함 `weak`은 아니다 — 원문에 없는 짧은 낱말도 weak가 된다). `per_hyp` = 가설별 인용 판정, 원문 검사를 못 했으면 None."""
    ok, bad = [], []
    for k, h in enumerate(fields.get("hyps") or []):
        claim = bool(NORMAL_RX.match(h["가설"] or ""))
        found = bool(per_hyp) and "ok" in per_hyp[k]
        ok.append(claim and found)
        bad.append(claim and not found)
    return ok, bad


def _top_index(fields: dict) -> int | None:
    """`가장 유력: N`이 있는 가설 번호면 0부터의 순번, 칸이 없으면 0, 있는데 못 읽거나 없는 번호면 None."""
    if not str(fields.get("top") or "").strip():
        return 0
    m = TOP_NUM_RX.match(str(fields["top"]))
    k = int(m.group(1)) - 1 if m else -1
    return k if 0 <= k < len(fields.get("hyps") or []) else None


def _picked(fields: dict) -> int:
    """적합성 확인에서 본 가설 번호(0부터): `가장 유력: N`이 있는 가설 번호면 그것, 아니면 0(가설 1 — 못 읽으면 경고 하위 줄)."""
    return _top_index(fields) or 0


def _hold_reason(analysis: dict, fields: dict) -> str:
    """보류 사유: 가설 없음·`1위 판단: 부적합`이면 unfit, 그 밖(고른 가설이 정상)은 normal."""
    return "unfit" if not fields["hyps"] or _unfit_applies(analysis, fields.get("top_fit")) else "normal"


def _fit_hold(analysis: dict, fields: dict, normal1: bool = False) -> str | None:
    """FR-02: 적합성 확인(`explore.reason: fit_check`)이 가설 없이 끝났거나 모델이 채택 원인에 `1위 판단: <ID> 부적합`을 적었으면
    (가설이 있어도, sim1122 F2) 보류한 원인 ID, 아니면 None. 감지는 구조(사유·빈 가설·판단 칸)만 보고 판정(C·순위)은 바꾸지 않는다.
    report.md 재작성 성패와 무관하다(기록·Jira는 이것으로 정한다)."""
    cause = _top_cause(analysis)
    if (analysis.get("explore") or {}).get("reason") != "fit_check" or not cause:
        return None
    return cause if not fields["hyps"] or normal1 or _unfit_applies(analysis, fields.get("top_fit")) else None


def _fit_subs(analysis: dict, fields: dict, hold: str | None, normal1: bool = False) -> list[str]:
    """탐색 줄 아래 1위 판단 하위 줄(읽었을 때)과 경고 하위 줄: 칸을 못 읽음, 부적합으로 적은 원인이 채택 원인이 아님,
    적합성 확인·채택·가설 있음인데 칸이 없음."""
    tf = fields.get("top_fit")
    cause = _top_cause(analysis)
    fit_check = (analysis.get("explore") or {}).get("reason") == "fit_check"
    warn_top = ([WARN_TOP_NUM.format(top=_one(fields.get("top"))[:40])]
                if fit_check and fields["hyps"] and _top_index(fields) is None else [])
    return warn_top + _fit_subs_main(analysis, fields, hold, normal1, tf, cause, fit_check)


def _fit_subs_main(analysis, fields, hold, normal1, tf, cause, fit_check) -> list[str]:
    if tf and tf["fit"] is None:
        return [WARN_FIT_UNREAD.format(cause=cause or "-")] if fit_check else []
    if tf:
        why = f" — {_one(tf['why'])}" if tf["why"] else ""
        line = TOP_FIT_SUB.format(fit=(f"{tf['cause']} " if tf.get("cause") else "") + tf["fit"], why=why)
        if hold:
            n = _picked(fields) + 1
            line += (TOP_FIT_HELD.format(cause=hold) if tf["fit"] == "부적합" else TOP_FIT_NORMAL_HELD.format(n=n, cause=hold)
                     if normal1 and fields["hyps"] else TOP_FIT_NONE_HELD.format(cause=hold, fit=tf["fit"]))
        out = [line]
        if fit_check and tf["fit"] == "부적합" and not hold and cause:
            out.append(WARN_FIT_OTHER.format(got=tf.get("cause") or "ID 없음", cause=cause))
        unfit = str((analysis.get("prior") or {}).get("unfit") or "").split(" — ", 1)[0].strip()
        dec = analysis.get("decision") or {}
        if (unfit and tf["fit"] == "적합" and tf.get("cause") in (None, unfit) and dec.get("state") == "held"
                and dec.get("reason") == "fit_check"):      # CP-3: 이번 run을 막은 앞 부적합 — 다음 run(driver.read_prior)이 푼다
            out.append(WARN_FIT_RELEASE.format(cause=unfit))
        return out
    if hold and normal1:
        return [NORMAL_HELD_SUB.format(n=_picked(fields) + 1, cause=hold)]
    if (fields["hyps"] and cause and fit_check and (analysis.get("decision") or {}).get("state") == "accepted"):
        return [WARN_NO_FIT.format(cause=cause)]
    return []


def _rule_subs(purpose: str, items, source: str | None, tags, res: dict | None) -> tuple[list[str], int, int]:
    """`규칙 제안` 항목 → (report 하위 줄, 실은 수, 뺀 수). `없음`은 건너뛴다. `— 근거: <문구>`가 있으면 그 문구가 원문(`source`)
    검사 `ok`일 때만, 없으면 근거 원문 검사(`res`)를 실제로 했고 원문에 없는 인용이 없을 때만 싣는다 — 근거 불일치 가설에서 나온
    제안·검사를 건너뛴 출력의 제안을 막는다."""
    kind, kept, dropped = RULE_KIND[purpose], [], 0
    for item in [_one(x) for x in items or []][:RULES_MAX]:
        if not item or evidence.RULE_NONE_RX.match(item):     # `없음`·`해당 없음`(뒤 설명 무엇이든)은 제안이 아니다
            continue
        m = RULE_BASIS_RX.search(item)
        if m:
            ok = source is not None and evidence.check_quotes([m.group(1)], source, tags)["verdicts"] == ["ok"]
        else:
            ok = res is not None and not res.get("fabricated")
        if ok:
            kept.append(RULE_SUB.format(kind=kind, text=item if len(item) <= RULE_CLIP else item[:RULE_CLIP - 1] + "…"))
        else:
            dropped += 1
    return kept + ([RULE_DROPPED.format(kind=kind, n=dropped)] if dropped else []), len(kept), dropped


def _question_tail(report: Path, tail: str) -> None:
    """확인할 내용 줄의 꼬리를 이번 탐색 결과로 바꾼다(F7·RP-8 — 다시 검사해도 갱신). 꼬리가 탐색 안내(`QUESTION_TAILS`)가 아니면
    (never·--no-explore) 그대로."""
    line = rep.current_line(report, QUESTION_PREFIX)
    old = next((t for t in QUESTION_TAILS if line and line.endswith(t)), None)
    if old and old != tail and not rep.rewrite_line(
            report, QUESTION_PREFIX, [line[: -len(old)] + tail], keep_sub=("  - ",)):
        print(WARN_REWRITE, file=sys.stderr)


def _hold_lines(report: Path, cause: str, held: bool = False, normal: bool = False) -> list[str]:
    """결론·해결책 줄을 보류로 고친다(탐색 줄과 달리 1위 확정·`검증됨`을 권하지 않게). 다시 불러도 같다(이미 고친 해결책 줄은 그대로).
    판단이 이미 보류(`held`)면 리포트에 해결책 줄이 없다(report.py가 싣지 않는다) — 없어도 실패가 아니다.
    못 고친 줄 이름 목록(줄 없음·쓰기 실패)."""
    failed = []
    conclusion = rep.FIT_HOLD_NORMAL_CONCLUSION if normal else rep.FIT_HOLD_CONCLUSION
    if not rep.rewrite_line(report, rep.CONCLUSION_PREFIX, [rep.CONCLUSION_PREFIX + conclusion.format(cause=cause)]):
        failed.append("결론 줄")
    line = rep.current_line(report, rep.RESOLUTION_PREFIX)
    if line:
        body = line[len(rep.RESOLUTION_PREFIX):]
        body = body.rpartition(rep.RESOLUTION_CHECK)[0] or body
        if not rep.rewrite_line(report, rep.RESOLUTION_PREFIX,
                                [f"{rep.FIT_HOLD_RESOLUTION}{body}{rep.RESOLUTION_CHECK}"
                                 f"{rep.FIT_HOLD_NORMAL_CHECK if normal else rep.FIT_HOLD_CHECK}"]):
            failed.append("해결책 줄")
    elif not held and rep.current_line(report, rep.FIT_HOLD_RESOLUTION) is None:      # 이미 보류로 고친 줄이면 실패가 아니다
        failed.append("해결책 줄")
    return failed


def _read_analysis(job: Path) -> tuple[dict | None, str | None]:
    """analysis.json(일반 파일만) → (내용, 읽은 바이트의 sha256). 없거나 못 읽으면 (None, None)."""
    path = job / "analysis.json"
    try:
        raw = path.read_bytes() if _kind(path) == "file" else None
        return (json.loads(raw), _sha(raw)) if raw is not None else (None, None)
    except (OSError, ValueError):
        return None, None


def _rebase_module_inputs(job: Path, old: str, new: str) -> bool:
    """module-skill.json 기록 중 `inputs["analysis.json"]`이 고치기 전 해시인 것을 새 해시로 바꾼다 — 판단만 고친 analysis.json
    때문에 뒤 검사가 그 기록을 "이전 분석 것"으로 보고 근거 원문 검사를 건너뛰지 않게. 고칠 것을 못 썼으면 False."""
    path = job / MODULE_RECORD
    msj = _load(path)
    if not isinstance(msj, dict):
        return True
    hit = [rec["inputs"] for rec in msj.values() if isinstance(rec, dict) and isinstance(rec.get("inputs"), dict)
           and rec["inputs"].get("analysis.json") == old]
    for inputs in hit:
        inputs["analysis.json"] = new
    if hit:
        try:
            _write_atomic(path, (json.dumps(msj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        except OSError:
            print(f"경고: {MODULE_RECORD}의 analysis.json 해시를 고치지 못했다", file=sys.stderr)
            return False
    return True


def _decision_update(args, job: Path, analysis: dict, read_sha: str | None, *, hold: bool = False,
                     opinion: str | None = None, normal: bool = False) -> dict:
    """analysis.json `decision`을 고친다(단계 4): 탐색 적합성 확인 보류(`hold`)면 채택 → held/fit_check(counter 없앰), 심층 분석
    의견의 원인 ID가 채택 원인과 다르면 `counter`만 붙인다(상태·사유 그대로). 상태·사유·selected·counter와 (보류면) 사건의
    `result: adopted → held`만 바꾸고 나머지 자격 검사 칸(`check`·`events_total`)은 그대로 둔다. 이미 보류면 사유를 바꾸지 않는다(앞 사유가 우선).
    decision 없는 옛 JOB은 그대로. 4KB 압축 → 스키마 검사(TT_SCHEMA_CHECK) → 처음 읽은 뒤 바뀌지 않았는지 해시 대조 → 원자 쓰기 →
    module-skill.json 입력 해시 갱신 → report.md `- 판단:` 줄 재작성 → (작업 디렉토리 JOB이면) 리포트 표시 기록을 새 줄로 다시 남긴다.
    check-output 기록에 더할 칸: 판단을 못 고쳤으면 `decision_unwritten: <사유>`, module-skill.json 해시를 못 고쳤으면
    `module_inputs_unwritten: true`(판단은 썼다). 고칠 것이 없거나 다 썼으면 {}."""
    dec = analysis.get("decision")
    if not isinstance(dec, dict) or dec.get("state") != "accepted":
        return {}
    if hold:
        new = {**{k: v for k, v in dec.items() if k != "counter"}, "state": "held", "reason": "fit_check", "selected": None,
               "events": [{**e, "result": "held"} if isinstance(e, dict) and e.get("result") == "adopted" else e
                          for e in dec.get("events") or []]}     # 붙은 사건도 채택 → 보류(observed는 그대로)
    else:
        m = OPINION_ID.match(opinion or "")
        selected = (dec.get("selected") or {}).get("cause")
        if not m or m.group(1) == selected or (dec.get("counter") or {}).get("cause") == m.group(1):
            return {}
        new = {**dec, "counter": {"cause": m.group(1)}}
    result = rep.fit({**analysis, "decision": new})     # 4KB를 넘으면 판단의 사건(events)부터 준다 — 상태·사유·counter는 그대로
    why = None
    violation = rep.schema_violation(result)
    if violation:
        why, detail = "스키마 위반", violation
    elif _read_analysis(job)[1] != read_sha:
        why = detail = "검사 중 analysis.json이 바뀌었다"
    if why:
        print(WARN_DECISION.format(why=detail), file=sys.stderr)
        return {"decision_unwritten": why}
    data = (rep.dumps(result) + "\n").encode("utf-8")
    try:
        _write_atomic(job / "analysis.json", data)
    except OSError:
        print(WARN_DECISION.format(why="쓰기 실패"), file=sys.stderr)
        return {"decision_unwritten": "쓰기 실패"}
    extra = {} if not read_sha or _rebase_module_inputs(job, read_sha, _sha(data)) else {"module_inputs_unwritten": True}
    report = job / "report.md"
    if not rep.rewrite_line(report, rep.DECISION_PREFIX, [rep.decision_line(new, analysis.get("candidates") or [], normal)]):
        print(WARN_REWRITE, file=sys.stderr)
        return {**extra, "decision_unwritten": "report.md 판단 줄"}
    if not args.out:    # run이 남긴 리포트 표시 의무(같은 key)를 고친 줄로 바꾼다 — 옛 "원인 채택" 줄을 보이라고 하지 않게
        shown.record(job.parent, "triage", "report", job.name, key=f"report:{job.name}#{analysis.get('run')}",
                     lines=shown.report_core(report.read_text(encoding="utf-8")), must_show=result.get("must_show") or [],
                     path=str(job.absolute() / "report.md"))
    return extra


def _skipped(args, job: Path, purpose: str, env: dict) -> int:
    report, prefix = job / "report.md", PREFIX[purpose]
    reason = masking.mask_brief(args.skipped, 120)
    current = rep.current_line(report, prefix)
    if current is None or "TODO(LLM)" not in current:
        _emit({"kept": masking.mask_brief(current or "", 300)})     # 스크립트가 쓴 생략·해당 없음·받기 실패 줄은 그대로
        return OK
    line = SKIPPED[purpose].format(reason=reason)
    if not rep.rewrite_line(report, prefix, [line], only_pending=True):
        print(WARN_REWRITE, file=sys.stderr)
        _emit({"kept": masking.mask_brief(current, 300)})
        return OK
    _record(job, purpose, {"skipped": reason, "at": _now(), "env": env})
    if purpose == "explore":
        _question_tail(report, QUESTION_SKIPPED)
    _obligation(args, job, purpose, [])
    _emit({"line": masking.mask_brief(line, 300), "skipped": reason})
    return OK


def _mode(job: Path, purpose: str, analysis: dict) -> tuple[str, object]:
    """deep: module | skill(설치 스킬, 기록 없음 = Skill 도구 대안), explore: explore. 두 번째 값 = 그 purpose의 기록."""
    msj = _load(job / MODULE_RECORD)
    rec = msj.get(purpose) if isinstance(msj, dict) else None
    rec = rec if isinstance(rec, dict) else None
    if purpose == "explore":
        return "explore", rec
    if rec and rec.get("module"):
        return "module", rec
    if rec and "skill" in rec:
        return "skill", rec
    if (analysis.get("analyzer") or {}).get("category"):
        raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, "모듈 스킬 기록 없음 — module --for deep 먼저")
    return "skill", None


def _preconditions(job: Path, purpose: str) -> tuple[dict, str | None, bool]:
    """(analysis.json 내용, 그 바이트의 sha256 — 판단을 고쳐 쓰기 직전 대조용, 형식 경고 뒤 다시 검사인가)."""
    report = job / "report.md"
    current = rep.current_line(report, PREFIX[purpose])
    analysis, read_sha = _read_analysis(job)
    if not isinstance(analysis, dict):
        raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, "analysis.json이 없다")
    recheck = bool(current) and "TODO(LLM)" not in current and purpose == "explore" and _recheck_open(job)
    if not current or ("TODO(LLM)" not in current and not recheck):
        raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, "고칠 줄이 없다(이미 쓴 줄은 그대로 둔다)")
    if purpose == "deep":
        ana = analysis.get("analyzer")
        if not isinstance(ana, dict) or ana.get("error") or ana.get("when") == "never":
            raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, "심층 분석 해당 없음")
    elif _kind(job / EXPLORE_INPUT_FILE) != "file" or (analysis.get("explore") or {}).get("when") == "never":
        raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, "탐색 분석 해당 없음")
    return analysis, read_sha, recheck


def _fail(job: Path, purpose: str, env: dict, reason: str, label: str, sha: str | None, args) -> int:
    report = job / "report.md"
    if (_rewrite(report, PREFIX[purpose], [SKIPPED[purpose].format(reason=label)], pending=not getattr(args, "recheck", False))
            and purpose == "explore"):
        _question_tail(report, QUESTION_SKIPPED)
    _record(job, purpose, {"error": label, "at": _now(), "env": env, "output_sha256": sha})
    _obligation(args, job, purpose, [])
    print(label, file=sys.stderr)
    _emit({"reason": reason, "detail": label, "next": NEXT_CHECK_FAILED})
    return CHECK_FAILED


def _check(args, job: Path, purpose: str, env: dict) -> int:
    analysis, read_sha, args.recheck = _preconditions(job, purpose)
    out_path = job / OUTPUT_FILE[purpose]
    kind = _kind(out_path)
    if kind == "link":
        raise _Stop(USAGE, "작업 디렉토리 이상", NEXT_CHECK_NA, f"{OUTPUT_FILE[purpose]}가 링크다 — 따라가지 않는다")
    if kind != "file":
        raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, f"{OUTPUT_FILE[purpose]}가 없다 — 쓰지 못했으면 --skipped \"<사유>\"")
    mode, rec = _mode(job, purpose, analysis)
    events = _load(job / "events.json")
    events = events if isinstance(events, dict) else None
    allow = [p for p in (events or {}).get("mask_allow") or [] if isinstance(p, str)]
    off = bool((events or {}).get("mask_off"))      # 마스킹 끔 DB의 events면 출력을 바꾸지 않는다(08-safety §8)
    src_rel, src_text, src_skip = _source(job, purpose, mode, rec, events)
    win_names, win_texts, win_bad = _windows(job)       # `triage.py window` 구간도 근거 원문(sha가 맞는 것만)
    if win_bad:
        print(f"경고: 구간 파일이 기록과 달라(바뀜·없음) 근거 원문에서 뺐다: {', '.join(win_bad)}", file=sys.stderr)
    if src_text is not None and win_texts:
        src_text = "\n".join([src_text, *win_texts])
        src_rel = ([src_rel] if isinstance(src_rel, str) else list(src_rel or [])) + win_names

    # 1~3. 마스킹 → 다시 쓰기 → residual
    raw_bytes = out_path.read_bytes()
    raw = raw_bytes.decode("utf-8", "replace")
    masker = masking.new_masker(existing_text=src_text or "", allow_patterns=allow, log_lines=True, off=off)
    text = "\n".join(masker.mask(line) for line in raw.split("\n"))
    data = text.encode("utf-8")
    if data != raw_bytes:
        try:
            _write_atomic(out_path, data)
        except OSError:
            raise _Stop(USAGE, "작업 디렉토리 이상", NEXT_CHECK_NA, f"{OUTPUT_FILE[purpose]}를 다시 쓰지 못했다") from None
    sha = _sha(data)
    if len(raw_bytes) > OUTPUT_MAX_BYTES:
        return _fail(job, purpose, env, "출력 형식 불일치", "출력 형식 불일치(파일 한도)", sha, args)
    left = {} if off else masking.residual(text, allow)
    if left:
        what = ", ".join(f"{k} {n}건" for k, n in sorted(left.items()))
        return _fail(job, purpose, env, "마스킹 점검 실패", f"마스킹 점검 실패({what})", sha, args)

    # 4~5. 칸·한도
    fields = _parse(purpose, mode, text)
    if fields is None:
        return _fail(job, purpose, env, "출력 형식 불일치", "출력 형식 불일치(칸)", sha, args)
    bad = _caps(purpose, mode, fields, text)
    if bad:
        return _fail(job, purpose, env, "출력 형식 불일치", f"출력 형식 불일치({bad} 한도)", sha, args)

    # 근거 원문 검사(설치 스킬만 raw_items: 마스킹이 바꾼 인용 = 준 파일 밖 원문 값)
    quotes = _quotes(purpose, fields)
    raw_items: frozenset[int] = frozenset()
    if mode == "skill":
        before = _quotes(purpose, _parse(purpose, mode, raw))
        if len(before) == len(quotes):
            raw_items = frozenset(i for i, (a, b) in enumerate(zip(before, quotes)) if a != b)
    res = fab_by_hyp = per_hyp = None
    source, tags = evidence.source_text(src_text) if src_skip is None and src_text is not None else (None, None)
    if not quotes:
        src_skip = "인용 없음"
    elif src_skip is None:
        res = evidence.check_quotes(quotes, source, tags, raw_items=raw_items)
        if purpose == "explore":        # verdicts는 `_quotes` 순서 = 가설 순서대로 `로그로 확인`을 이어 붙인 것
            it = iter(res["verdicts"])
            per_hyp = [[next(it) for _ in h["로그로 확인"]] for h in fields["hyps"]]
            chain_v = [[next(it) for _ in evidence.chain_quotes(h)] for h in fields["hyps"]]     # 기대 체인 관측 줄(뒤에 붙였다)
            fab_by_hyp = [(a + b).count("fabricated") for a, b in zip(per_hyp, chain_v)]
    normal_ok, normal_bad = _normal_flags(fields, per_hyp) if purpose == "explore" else ([], [])
    normal1 = bool(normal_ok) and normal_ok[_picked(fields)]       # `가장 유력: N`이 있으면 그 가설, 없으면 가설 1
    old = _load(job / RECORD)
    before = _fab_before(old.get(purpose) if isinstance(old, dict) else None)
    sub = _evidence_sub(mode, res, src_skip, before)

    report, prefix = job / "report.md", PREFIX[purpose]
    current = rep.current_line(report, prefix)
    if purpose == "explore":
        default = f"{EXPLORE_PREFIX} (추정, {TIMELINE_FILE}): "
    elif mode == "module":
        default = f"{DEEP_PREFIX} (모듈 스킬 {rec.get('module')} @{str(rec.get('sha') or '')[:7]}): "
    else:
        name = (rec or {}).get("skill") or (analysis.get("analyzer") or {}).get("skill") or "-"
        default = f"{DEEP_PREFIX} ({name}): "
    hold = _fit_hold(analysis, fields, normal1) if purpose == "explore" else None
    subs = _fit_subs(analysis, fields, hold, normal1) if purpose == "explore" else []
    rule_lines, rules_kept, rules_dropped = _rule_subs(purpose, fields.get("rules" if purpose == "explore" else "규칙 제안"),
                                                       source, tags, res)
    reason = _hold_reason(analysis, fields) if hold else None
    fmt = _chain_warnings(fields) if purpose == "explore" else []
    fmt_text = "; ".join(fmt)
    fmt_lines = [FORMAT_SUB.format(text=fmt_text if len(fmt_text) <= FORMAT_CLIP else fmt_text[:FORMAT_CLIP - 1] + "…")] if fmt else []
    lines = (_render(purpose, mode, _head(current, prefix, default), fields, sub, fab_by_hyp, normal_bad) + subs + rule_lines
             + fmt_lines)
    if _rewrite(report, prefix, lines, KEEP_SUB, pending=not args.recheck) and purpose == "explore":
        _question_tail(report, QUESTION_DONE if fields["hyps"] else QUESTION_DONE_NONE)
    unwritten = (_hold_lines(report, hold, (analysis.get("decision") or {}).get("state") == "held", reason == "normal")
                 if hold else [])
    if unwritten:
        print(WARN_HOLD.format(what="·".join(unwritten)), file=sys.stderr)
    if hold:
        dec_extra = _decision_update(args, job, analysis, read_sha, hold=True, normal=reason == "normal")
    elif purpose == "deep":
        dec_extra = _decision_update(args, job, analysis, read_sha, opinion=fields.get("분석 스킬 의견"))
    else:
        dec_extra = {}

    counts = {k: (res or {}).get(k, 0) for k in ("fabricated", "weak", "raw")}
    n = (res or {}).get("n", 0)
    _record(job, purpose, {"mode": mode, "at": _now(), "env": env, "output_sha256": sha, "source": src_rel if res else None,
                           "quotes": n, **counts, **({"fit_hold": hold, "fit_hold_reason": reason} if hold else {}),
                           **({"top_fit": fields["top_fit"]["fit"] or "읽지 못함"} if fields.get("top_fit") else {}),
                           **({"top_fit_cause": fields["top_fit"]["cause"]} if (fields.get("top_fit") or {}).get("cause") else {}),
                           **({"fit_hold_unwritten": unwritten} if unwritten else {}), **dec_extra,
                           **({"normal": [i + 1 for i, v in enumerate(normal_ok) if v]} if any(normal_ok) else {}),
                           **({"rules": rules_kept} if rules_kept else {}), **({"rules_dropped": rules_dropped} if rules_dropped else {}),
                           **({"format_warnings": fmt} if fmt else {}), **({"format_recheck": True} if args.recheck else {})})
    head = masking.mask_brief(lines[0], 300, off=off)     # 끔 DB: report.md 줄과 같은 글자(꼭 보일 줄 대조가 어긋나지 않게)
    fab = [sub.lstrip()] if counts["fabricated"] or before else []     # 앞 검사의 불일치도 보일 의무(RP-14)
    # 심층 분석은 결과 줄(첫 줄)을 늘 보인다 — 탐색은 지어낸 인용이 있을 때만(B2-6)
    _obligation(args, job, purpose, [head.removesuffix("…")] + fab if purpose == "deep" else fab)
    args.trace_extra = {"fabricated": counts["fabricated"]} if res else {}     # F9: 다시 검사해도 trace에 검사마다 수가 남는다
    warn = next((s.strip() for s in subs if s.startswith("  - 경고: 1위 판단")), None)
    _emit({"line": head, "evidence": sub.lstrip(), "quotes": n, **counts, **({"warning": warn} if warn else {}),
           **({"windows_excluded": win_bad} if win_bad else {}), **({"format_warnings": fmt} if fmt else {}),
           **({"next": FORMAT_NEXT} if fmt and not args.recheck else {})})
    return OK


def cmd_check_output(args, defaults: dict) -> int:
    purpose = args.purpose
    skipped = getattr(args, "skipped", None) is not None
    job = None
    try:
        job = _resolve_job(args, defaults)
        env = provenance.env_info(cfg=defaults)
        code = _skipped(args, job, purpose, env) if skipped else _check(args, job, purpose, env)
    except _Stop as stop:
        if stop.err:
            print(stop.err, file=sys.stderr)
        _emit({"reason": stop.reason, **stop.extra, **({"next": stop.next} if stop.next else {})})
        code = stop.code
    if job is not None:     # 사유 글은 싣지 않는다(있는지만)
        trace_event(job, "checked", purpose=purpose, skipped=skipped, exit=code, **getattr(args, "trace_extra", {}))
    return code
