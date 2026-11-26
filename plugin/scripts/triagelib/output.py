"""`triage.py check-output <KEY> --for deep|explore [--skipped <사유>] [--out <dir>]` — 5-1·5-2 출력 검사(B2 §6).

Claude가 쓴 `JOB/deep-output.md`·`JOB/explore-output.md`를 받아:
1. `mask_pii`와 같은 마스킹을 하고 마스킹한 글을 그 파일에 다시 쓴다(뒤 Step 7은 마스킹된 글만 본다).
2. 고정 칸과 UTF-8 바이트 한도를 본다(한 칸 768바이트 = 한글 약 250자).
3. 근거 원문 검사: 인용이 준 타임라인(모듈 뷰·`JOB/timeline.md`, 설치 스킬이면 events.json 전체 행)이나 `triage.py window` 구간
   (`JOB/windows.json` 기록과 sha256이 같은 `window-<n>.md`만 — 바뀌었거나 없으면 빼고 경고·`windows_excluded`), `triage.py summary`·5-1이 쓴
   `summary.md`(`summary.json` sha가 같을 때만)에 있는지.
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
7. 조사 모드(analysis.json `investigate.mode`, run이 판정)면 탐색 가장 유력 가설(없으면 1)에 검증 게이트 6개(`_investigation`)를 보고
   결과를 analysis.json·기록 `investigation`에, 조사 결론 줄을 report.md CAUSE 칸에 쓴다(통과 = 인용·형식 확인이면 맨 위, 근거 부족이면
   결론 줄 아래). 게이트는 인용이 원문에 있는지와 단계표 형식만 본다 — 원인이 맞는지는 사람이 본다(11/25 결정 1). 게이트 2는 가장
   이른 false 단계의 관측이 원문 확인 인용이거나, 로그·파서 규칙에 있는 낱말을 앞 단계 뒤 max(`explore.after_sec`, 기대 시간) 안에서
   사본으로만 0건 센 `찾았는데 없음`이어야 하고, 사본이 아래 끝 + 기대 시간(없으면 10초)까지 없으면(아래 끝이 없으면 사본 길이가 기대
   시간보다 짧으면) 미관측으로 실패한다. 행 모양 인용이 사본에서 다른 시각(다른 날) 줄만 가리키면 약함(`_quote_at`). 원문 모양
   인용은 날짜·시간대까지 사본 줄과 같아야 원문 확인이다(`evidence.stamp_matches`). 게이트 5는 숫자 기대면 계산 숫자와 명시적 `예`,
   명시적 `아니오`는 늘 실패(외부 리뷰 1125). 가장 유력이 정상(근거 줄 원문 확인)이면 `normal: true`. 점수·분류·decision은 바꾸지
   않는다. Jira 본문(`issue_post`)은 이 기록(analysis.json 아님)을 읽는다.
8. 인용 줄이 한 칸 한도(768바이트)를 넘으면 실패가 아니라 앞부분 + ` …`로 줄여 대조·표시한다(`_clip_quote`).

`--skipped "<사유>"`: 실행하지 않았거나 실패 — 줄을 "생략: <사유>"로(이미 스크립트가 쓴 생략·해당 없음·받기 실패 줄이면 그대로).
기록 `JOB/check-output.json[purpose]`(스크립트만 쓴다, guard 규칙 12)와 trace `checked` 행(`core.trace_event`). 표시 의무: 작업 디렉토리 JOB이면 검사마다 `evidence` 기록
(`.shown/log.jsonl`, 원문에 없는 인용이 있을 때만 줄이 있다 — 빈 줄은 앞 의무를 닫는다).

출력은 JSON 한 줄(≤ 4KB). 종료 0 = 썼음(또는 `kept`), 1 = 형식·마스킹 실패(줄은 생략으로 고쳤다, `next`)·`이미 검사함`(이 purpose
기록이 있고 고칠 줄이 없음 — 줄 그대로, `next`대로 계속, 가-6), 2 = 사용 오류·설정 오류·작업 없음·작업 디렉토리 이상(`next`가 있으면 따른다, 없으면 멈춘다).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from datetime import timedelta
from pathlib import Path

from common import evidence, issuepost, logtime, masking, modulelines, provenance, shown
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
    EXPLORE_PENDING_LINE,
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
NORMAL_RX = re.compile(r"^[`*\s]*정상(?:\s*동작)?(?:\s*\(|\s*[—–:-]|\s*$)")     # `정상 동작 — …`도(틀은 `정상(설계상 정상 동작)`)
NORMAL_BAD = " [정상 근거 없음]"
TOP_FIT_NORMAL_HELD = " → {n}번 가설이 정상(설계상 정상 동작)이라 1위 {cause} 보류"
NORMAL_HELD_SUB = "  - {n}번 가설이 정상(설계상 정상 동작, 근거 줄 원문 확인)이라 1위 {cause} 채택을 보류로 바꿨다"
WARN_TOP_NUM = "  - 경고: `가장 유력: {top}`을 가설 번호로 읽지 못해(없는 번호) 1번 가설로 적합성 확인을 봤다"
WARN_INV_TOP = "`가장 유력: {top}`을 가설 번호로 읽지 못해 가설 1을 조사 결론으로 검사했다 — `가장 유력: <번호>`"
TOP_NUM_RX = re.compile(r"^[`*\s]*(?:가설\s*)?#?(\d+)(?!\d)")      # `가장 유력: 2`·`가설 2` (module_eval.TOP_NUM_RX와 같은 읽기)
# 규칙 제안 하위 줄(SKILL Step 7 `규칙 제안` 질문이 report.md에서 읽는다). 근거 원문 확인이 안 된 제안은 싣지 않는다
RULE_SUB = "  - 규칙 제안 ({kind}): {text}"
RULE_DROPPED = "  - {kind} 출력의 제안 {n}개를 뺐다 — {why}"
# B1(반입 8): 원문 확인 인용 줄의 태그 중 tags.yaml에 없는 것 — 사람이 tags.yaml 추가를 판단한다(자동으로 더하지 않는다)
UNKNOWN_TAGS_SUB = "  - 파서 설정에 없는 태그가 근거 인용에 쓰임({kind}): {tags} — tags.yaml 추가 검토(사람이 판단, 자동으로 더하지 않음)"
UNKNOWN_TAGS_MAX = 10
# 뺀 이유(R-09 결정 2, 기록 `rules_dropped_why` 키 → 줄 문구). 원인 미확정 = 판단 채택도 조사 결론 identified도 아니라 첫 점검·함정을 안 받음
RULE_WHY = {"근거 불일치": "근거 불일치(원문에서 확인 안 됨)", "형식": "형식", "원인 미확정": "원인 미확정(첫 점검·함정)"}
RULE_KIND = {"deep": "심층", "explore": "탐색"}
RULE_BASIS_RX = re.compile(r"\s[—–]\s*근거\s*[:：]\s*(.+)$")
RULES_MAX, RULE_CLIP = 5, 300
# 11/25 기대 체인 형식 경고(explore.md 쓰는 것): 판정이 아니라 모델에게 고쳐 쓰기를 한 번 청한다(사내 모델이 형식을 놓칠 수 있어 실패로 두지 않는다)
FORMAT_SUB = "  - 형식 경고(탐색, 판정 아님): {text}"
FORMAT_NEXT = ("explore-output.md에서 형식 경고가 가리킨 칸만 고쳐 쓰고 같은 check-output을 한 번만 다시 실행한다(두 번째 결과는 경고가 "
               "남아도 그대로 쓴다)")
FORMAT_CLIP = 600
RECHECK_KEPT = "첫 검사 결과 유지(다시 검사가 형식·마스킹 검사에서 실패해 리포트 줄을 바꾸지 않았다)"
TIMER_RX = re.compile(r"타이머|timer|throttl|스로틀|재시도|retry|backoff|임계|threshold|카운터|counter|횟수", re.IGNORECASE)
# 가-1: 재계산 칸을 쓰는 조건 하나(explore.md 쓰는 것과 같은 말). 경고가 이 문장을 그대로 알려 준다
MECH_RULE = ("원인이 타이머·재시도 간격·임계값·횟수 같은 숫자 값이면 로그 값으로 다시 계산하고 `→ 고치면 결과가 뒤집히나: 예|아니오`, "
             "원인이 그 값이 아니면 `메커니즘 재계산: 해당 없음 — <이유>`")
NA_RX = re.compile(r"해당\s*없음")
BOUNDARIES = ("AP 내부", "AP-CP 경계", "CP 내부", "CP-망 경계", "망", "환경", "모름")
LAYER_ABBR = {"AP": "AP 내부", "CP": "CP 내부", "AP-CP": "AP-CP 경계", "CP-망": "CP-망 경계"}
LAYER_ABBR_RX = re.compile(r"^(AP-CP|CP-망|AP|CP)\s*(?:\([^()]*\))?$")
# `첫 갈라짐` 번호: 맨 앞 `단계 N`·`N단계`·선두 숫자만(`없음…`이나 문장 속 숫자는 None — 시각 `13:05`를 단계로 읽지 않게)
CLAIM_STEP_RX = re.compile(r"^[\s`*]*(?:단계\s*#?\s*(\d+)|#?(\d+)\s*단계|#?(\d+)(?!\d|:))")
# `→ 고치면 결과가 뒤집히나: 예|아니오` 답(뒤 설명 허용). 틀 그대로 `예|아니오`면 group(2)가 있다(값 없음)
# 답 `예` 뒤 한글은 `예입니다`·`예이다`·`예임`·`예요`(사이 공백 허용)만 — `예상`·`예외`·`예정`·`예시`는 답이 아니다(A3)
YES = r"예(?=(?:\s*(?:입니다|이다|임|요))?(?![가-힣]))"
FLIP_RX = re.compile(rf"뒤집히나\s*[?？]?\s*[:：]?\s*[`*]*\s*(아니오|아니요|{YES})(\s*[|/]\s*(?:아니오|아니요|예))?")
FLIP_TAIL_RX = re.compile(r"(아니오|아니요|(?<![가-힣])예)(?:\s*(?:입니다|이다|임|요))?[\s`*.)\]]*$")      # `뒤집히나`가 없는 옛 꼴: 끝의 답
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
    if isinstance(old, dict) and old.get("mech_no") and "investigation" not in entry and "mech_no" not in entry:
        entry = {**entry, "mech_no": old["mech_no"]}      # eval 46: 생략·실패한 검사 사이에도 이어 간다(다음 검사가 판단)
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


def _raw_ready() -> None:
    """`evidence.raw_row`가 쓸 원문 줄 정규식을 플랫폼 레지스트리에서 한 번 넣는다(common은 플랫폼을 import하지 않는다)."""
    if not evidence.raw_patterns_set():
        import platforms
        evidence.set_raw_patterns(platforms.raw_line_patterns())


def _copy_source(job: Path, analysis: dict, quotes: list[str]) -> tuple[list[str], str, list[str]]:
    """탐색 인용을 찾을 마스킹 사본 줄(`window.served_copies`, `evidence.copy_rows`) → (JOB 기준 사본 이름들, 행들, 사본 글들 — 게이트
    `찾았는데 없음` 세기가 다시 쓴다). 사본이 없으면 ([], "", [])."""
    from triagelib import window
    _raw_ready()
    served, _skipped = window.served_copies(job, analysis if isinstance(analysis, dict) else {})
    texts = []
    for path in served:
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    rows = evidence.copy_rows(texts, quotes) if texts else ""
    return ([f"{window.MASKED_DIR}/{p.name}" for p in served] if rows else []), rows, texts


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


def _summary_source(job: Path, names: list, texts: list, bad: list) -> tuple[list, list, list]:
    """`JOB/summary.md`(전체 로그 모양 요약)를 sha 기록 `summary.json`과 같을 때만 근거 원문에 더한다(window 구간과 같은 규칙)."""
    rec = _load(job / "summary.json")
    if not isinstance(rec, dict) or rec.get("path") != "summary.md":
        return names, texts, bad
    raw = (job / "summary.md").read_bytes() if _kind(job / "summary.md") == "file" else None
    events = (job / "events.json").read_bytes() if _kind(job / "events.json") == "file" else None
    if raw is None or _sha(raw) != rec.get("sha256") or events is None or _sha(events) != rec.get("events_sha256"):
        return names, texts, bad + ["summary.md"]       # 바뀌었거나 다른 run(events.json)의 요약
    return names + ["summary.md"], texts + [raw.decode("utf-8", "replace")], bad


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
            quotes = hyp["로그로 확인"]       # 긴 인용 줄은 `_parse`가 앞부분만 남겼다(R-05)
            if not 1 <= len(quotes) <= QUOTES_MAX:
                return "로그로 확인"
            for name in ("가설", "코드로 추정", "반대 근거", "다음 확인"):
                if _b(hyp[name]) > FIELD_MAX_BYTES:
                    return name
        return None
    if _b(text) > DEEP_MAX_BYTES:
        return "전체"
    items = fields["근거"]
    low = 1 if mode == "module" else 0
    if not low <= len(items) <= QUOTES_MAX:
        return "근거"
    single = ("원인 층", "원인 데몬", "반대 근거", "분석 스킬 의견") if mode == "module" else ("요약", "분석 스킬 의견")
    for name in single:
        if _b(fields[name]) > FIELD_MAX_BYTES:
            return name
    checks = fields.get(evidence.CHECK_FIELD) or []
    if len(checks) > QUOTES_MAX or any(_b(c["why"]) > FIELD_MAX_BYTES for c in checks):
        return evidence.CHECK_FIELD
    return None


def _quotes(purpose: str, fields: dict | None) -> list[str]:
    """근거 원문 검사할 인용: 탐색은 가설 순서대로 `로그로 확인` 전부 뒤에 가설 순서대로 `기대 체인` 관측 줄(`evidence.chain_quotes`),
    심층은 `근거` 뒤에. 둘 다 끝에 `후보 확인` 항목의 근거(`_check_quoted` 순서)."""
    if not fields:
        return []
    if purpose == "explore":
        return ([q for hyp in fields["hyps"] for q in hyp["로그로 확인"]]
                + [q for hyp in fields["hyps"] for q in evidence.chain_quotes(hyp)] + [why for _i, why in _check_quoted(fields)])
    return list(fields.get("근거") or []) + [why for _i, why in _check_quoted(fields)]


NOT_FOUND_RX = re.compile(r"^[`*\s]*찾았는데\s*없음")     # `후보 확인` 근거 `찾았는데 없음: …`은 인용이 아니다


def _check_quoted(fields: dict) -> list[tuple[int, str]]:
    """`후보 확인` 항목 중 근거를 인용으로 쓴 것 [(항목 번호, 근거)] — 빈 근거·`찾았는데 없음: …`은 뺀다(옛 한 줄 형식이면 [])."""
    return [(i, c["why"]) for i, c in enumerate(fields.get(evidence.CHECK_FIELD) or [])
            if c.get("why") and c.get("verdict") != "?" and not NOT_FOUND_RX.match(c["why"])]


def _clip_quote(q: str) -> str:
    """R-05: 한 칸 한도(768바이트)를 넘는 인용 줄은 앞부분만(UTF-8 경계, 낱말이 잘리지 않게 마지막 공백까지) + ` …` — 사본 원문 줄이
    길어 그대로 인용해도 출력 전체를 버리지 않는다. `…` 뒤는 원문 대조에서 생략으로 읽힌다(앞부분만 대조)."""
    if _b(q) <= FIELD_MAX_BYTES:
        return q
    s = q.encode("utf-8")[:FIELD_MAX_BYTES - 4].decode("utf-8", "ignore")
    return (s[:s.rfind(" ")] if " " in s else s) + " …"


def _parse(purpose: str, mode: str, text: str) -> dict | None:
    if purpose == "explore":
        fields = evidence.parse_explore(text)
        for h in (fields or {}).get("hyps") or []:
            h["로그로 확인"] = [_clip_quote(q) for q in h["로그로 확인"]]
        return fields
    fields = evidence.parse_fields(text, evidence.FIELDS_DEEP if mode == "module" else evidence.FIELDS_SKILL)
    if fields:
        fields["근거"] = [_clip_quote(q) for q in fields["근거"]]
    return fields


def _chain_warnings(fields: dict, investigating: bool = False) -> list[str]:
    """기대 체인 형식 경고(기계로 볼 수 있는 것만): 가장 유력(없으면 가설 1)에 표 없음, `일치` 칸을 못 읽음, `첫 갈라짐` 단계가 표의
    가장 이른 false가 아님(없음·false 없는데 적음), `책임 경계` 값이 목록 밖, 타이머·재시도·임계값·횟수 낱말이 든 가설(정상 가설
    아님)에 `메커니즘 재계산` 없음, 가장 유력의 메커니즘 재계산이 `아니오`. 조사 모드(`investigating`)면 게이트 3이 보는 칸도:
    가장 유력에 false가 있는데 `책임 경계` 없음, 그 단계 `기대 주체`를 못 읽음(열·머리 행 없음)·목록 밖(R-07).
    `원인 층`은 선택 칸이고 기대는 게이트가 없어 보지 않는다(R-03 — 경고가 다시 검사를 늘 열었다)."""
    out = []
    picked = _picked(fields)
    for k, h in enumerate(fields.get("hyps") or []):
        n, rows = k + 1, h.get("기대 체인") or []
        if k == picked and not rows:
            out.append(f"가설 {n}(가장 유력)에 `기대 체인:` 표 없음 — 실패 줄 다음에 일어나야 할 일을 단계 표로")
        unread = [str(r["단계"]) for r in rows if r["일치"] == "?"]
        if unread:
            out.append(f"가설 {n}: 단계 {', '.join(unread)}의 `일치` 칸을 못 읽음 — true, false, 모름 중 하나")
        first = next((r["단계"] for r in rows if r["일치"] == "false"), None)
        m = CLAIM_STEP_RX.match(h.get("첫 갈라짐") or "")
        claim = int(next(g for g in m.groups() if g)) if m else None
        if first is not None and claim is None:
            out.append(f"가설 {n}: 표의 첫 false가 단계 {first}인데 `첫 갈라짐: 단계 {first} — …` 칸이 없음")
        elif first is not None and claim != first:
            out.append(f"가설 {n}: 첫 갈라짐 단계 {claim} ≠ 표의 가장 이른 false 단계 {first} — 가장 잘 설명하는 단계가 아니라 가장 이른 false")
        elif first is None and claim is not None and rows:
            out.append(f"가설 {n}: 첫 갈라짐 단계 {claim}인데 표에 false 행이 없음 — 정상 가설이면 `첫 갈라짐: 없음 — <이유>`")
        if h.get("책임 경계") is not None and _layer(h["책임 경계"]) is None:
            out.append(f"가설 {n}: `책임 경계`는 {' | '.join(BOUNDARIES)} 중 하나")
        elif investigating and k == picked and first is not None and h.get("책임 경계") is None:
            out.append(f"가설 {n}(가장 유력): `책임 경계:` 칸 없음 — 가설 머리 다음 줄에 단계 {first} 기대 주체와 같은 값")
        row = next((r for r in rows if r["일치"] == "false"), None)
        if investigating and k == picked and row is not None and not row["주체"]:
            out.append(f"가설 {n}: 단계 {first}의 `기대 주체` 칸을 못 읽음 — 표 머리 행을 "
                       "`| 단계 | 기대 | 기대 주체 | 기대 근거 | 관측 줄 | 일치 |` 그대로 쓴다")
        elif investigating and k == picked and row is not None and _layer(row["주체"]) is None:
            out.append(f"가설 {n}: 단계 {first} 기대 주체 `{_one(row['주체'])[:20]}`는 목록 밖 — {' | '.join(BOUNDARIES)} 중 하나")
        mech = h.get("메커니즘 재계산")
        normal = NORMAL_RX.match(h["가설"] or "")
        if not mech and TIMER_RX.search(h["가설"] or "") and not normal:     # 낱말만 본다 — `해당 없음 — <이유>`도 답이다(가-1)
            out.append(f"가설 {n}: 머리에 타이머·재시도·횟수 낱말이 있는데 `메커니즘 재계산:` 없음 — {MECH_RULE}")
        flip = FLIP_RX.search(mech or "")
        if flip and flip.group(2):
            out.append(f"가설 {n}: 메커니즘 재계산의 답이 틀 그대로(`예|아니오`) — 예나 아니오 하나만")
        answer = (None if (flip and flip.group(2)) or (not flip and NA_RX.search(mech or ""))
                  else (flip or FLIP_TAIL_RX.search(mech or "")))
        if k == picked and answer and answer.group(1) != "예" and not normal:
            out.append(f"가설 {n}: 메커니즘 재계산이 '아니오'(고쳐도 결과가 안 뒤집힘)인데 가장 유력 — 재계산으로 보면 그 값은 원인이 "
                       "아니다. 값이 원인이면 가설을 고치고, 원인이 숫자 값이 아니면 처음부터 `해당 없음 — <이유>`가 맞다"
                       + (" — 조사 모드라 이 답은 다시 검사에서 지우거나 바꿔도 이어진다(`예`와 계산 숫자일 때만 새로 판정)"
                          if investigating else ""))
        big = [r["단계"] for r in rows if any(_b(r[c]) > FIELD_MAX_BYTES for c in ("기대", "근거", "관측", "일치"))]
        if big:
            out.append(f"가설 {n}: 기대 체인 단계 {', '.join(map(str, big))}의 칸이 {FIELD_MAX_BYTES}바이트를 넘음 — 줄여 쓴다")
    return out


CHECK_MISSING = ("`near_causes`(DB 원인 후보)가 있는데 `후보 확인:` 칸이 없음 — 끝에 후보마다 `- <ID>: 맞음|아님|모름 — <근거 줄 | "
                 "찾았는데 없음>`")
CHECK_TOP_MISSING = ("1위 규칙 {cause}가 맞았지만 스크립트가 원인으로 채택하지 않았는데 `후보 확인:`에 그 ID가 없음 — 끝에 "
                     "`- {cause}: 맞음|아님|모름 — <근거 줄 | 찾았는데 없음>`(이번 실패를 설명하나)")


def _check_warnings(analysis: dict, fields: dict) -> list[str]:
    """조사 모드 DB 원인 후보 대조(반입 7 B-2) 형식 경고: analysis.json `near_causes`가 있는데 판정을 읽은 `후보 확인` 항목이 없다
    (실패·게이트가 아니다 — 조사 결론 게이트는 가설 인용만 본다)."""
    read = [c for c in fields.get(evidence.CHECK_FIELD) or [] if c["verdict"] != "?"]
    if analysis.get("near_causes") and not read:
        return [CHECK_MISSING]
    top = (analysis.get("candidates") or [None])[0]
    if ((analysis.get("investigate") or {}).get("reason") == "채택 안 함" and isinstance(top, dict) and top.get("cause")
            and not any(c["cause"] == top["cause"] for c in read)):      # 5번: 맞았지만 채택 안 한 1위 규칙도 이번 실패와 대조한다
        return [CHECK_TOP_MISSING.format(cause=top["cause"])]
    return []


def _recheck_open(job: Path) -> bool:
    """앞 탐색 검사가 형식 경고를 냈고 아직 다시 검사하지 않았나(경고 뒤 한 번만 — `TODO(LLM)`이 없어도 줄을 다시 쓴다)."""
    data = _load(job / RECORD)
    rec = data.get("explore") if isinstance(data, dict) else None
    return isinstance(rec, dict) and bool(rec.get("format_warnings")) and not rec.get("format_recheck")


# --- 조사 결론 게이트(11/25 A635, 07-workflow §Step 5-2 조사 모드) ------------------------------------------------
# analysis.json `investigate.mode`(run이 판정)일 때만 가장 유력(없으면 가설 1)을 본다. 판정은 아래 칸·원문 대조 결과만 쓴다(LLM 판단 아님)

# 시간 단위(영어는 뒤에 영문자·숫자가 이어지면 단위가 아니다 — `10 s1`·`2h1`. `m` 한 글자는 미터와 섞여 넣지 않는다)
TIME_EN = r"milliseconds?|msec|ms|hours?|hrs?|h|seconds?|secs?|s|minutes?|mins?"
TIME_KO = r"밀리초|시간|초|분"
# 숫자+시간·횟수 단위. `번`은 뺀다(`2번 단계`·`1번 슬롯`처럼 순번에 흔하다)
NUM_UNIT_RX = re.compile(rf"\d+(?:\.\d+)?\s*(?:(?:{TIME_EN}|times?)(?![A-Za-z0-9])|{TIME_KO}|회)")
QUOTE_TS_RX = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:?\d{2})?|(?:\d{4}-)?\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3,9}"
                         r"|\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?")
MONTHS = "JanFebMarAprMayJunJulAugSepOctNovDec"     # syslog `Mon` → 월(`index // 3 + 1`)
OUTER_SIDES = {"CP 내부": ("cp",), "CP-망 경계": ("cp", "net"), "망": ("net",)}
# CP 쪽 = 플랫폼 백엔드의 벤더 IPC 태그(`is_vendor_ipc` — tags.yaml `ipc: vendor`가 있으면 그것, 없으면 백엔드 기본: Android
# `VENDOR_IPC_TAGS`, oFono 구성요소 `vendor_ipc`)와 아래 카테고리, 망 쪽 = 아래 카테고리. 카테고리 이름은 placeholder다
CP_CATEGORIES, NET_CATEGORIES = ("modem",), ("nas",)    # TODO(SITE:S9) 사내 tags.yaml의 모뎀·망 거절(NAS) 카테고리 이름
SIDE_LABEL = {"cp": "CP", "net": "망"}
INV_CAUSE_MAX, INV_WHY_MAX, INV_EXPECT_MAX = 120, 80, 80
# eval 46: 재계산 '아니오'를 받은 같은 가설이 그 줄만 지워 다시 오면(숫자 기대가 없으면 재계산은 필수가 아니라 통과하던 것) 실패를 이어받는다
MECH_NO_CARRIED = "앞 검사에서 이 가설의 재계산 답이 아니오 — 지우거나 예가 아닌 답으로 바꿈(가설을 고치거나 숫자와 예로 다시)"
NORMAL_UNSEEN = "정상 가설인데 정상 근거 줄 미확인 — `로그로 확인`에 회복·no-op 줄을 원문 그대로"     # 가-2


def _layer(value) -> str | None:
    """`책임 경계`·기대 주체 칸 → `BOUNDARIES` 값(앞부분 일치, `AP-CP 경계(변환·직렬화)`도), 목록 밖·없음이면 None.
    칸 전체가 뜻이 하나인 줄임(`AP`·`CP`·`AP-CP`·`CP-망`, 뒤 괄호 설명 허용)이면 그 값(R-07). `모뎀(CP)`·`CP 쪽`처럼 모호하면 읽지 않는다."""
    s = str(value or "").strip("`* ")
    m = LAYER_ABBR_RX.match(s)
    return next((b for b in BOUNDARIES if s.startswith(b)), None) or (LAYER_ABBR[m.group(1)] if m else None)


def _quote_ts(q: str, events: dict | None):
    """인용 앞 시각 → UTC datetime, 못 읽으면 None. 원문 모양(logcat·oFono ISO·BSD syslog·BusyBox, R-04)은 그 칸으로 — 연도가 없으면
    작업 `--year`(없으면 분석 범위 시작의 연도), 시간대가 없으면 작업 tz. 시간대 없는 ISO도 작업 tz. 타임라인 행 `HH:MM:SS.mmm`은 UTC
    (`window.parse_at`)."""
    from triagelib import window
    s = evidence.obs_quote(q) or ""
    inp = (events or {}).get("input") or {}
    g = evidence.raw_stamp(s)
    if g:
        def at(year):
            try:
                mon = int(g["mon"]) if g.get("mon") else MONTHS.index(g["bmon"]) // 3 + 1
                return logtime.normalize_ts(f"{int(year):04d}-{mon:02d}-{int(g['day']):02d}T{g['h']}:{g['mi']}:{g['s']}"
                                            + (f".{g['frac']}" if g.get("frac") else "") + (g.get("zone") or ""), inp.get("tz"), None)
            except (TypeError, ValueError):
                return None
        year = g.get("year") or inp.get("year") or str((inp.get("window") or {}).get("start") or "")[:4] or logtime.DEFAULT_YEAR
        t = at(year)
        if g.get("year") or t is None:
            return t
        # C-4: 연도 없는 줄은 분석 범위(없으면 로그 범위)에 가장 가까운 해로(±1년) — 해를 넘는 로그에서 12월·1월 줄을 같은 해로 읽지
        # 않게. ponytail: 6개월 넘게 이어진 로그면 가까운 해가 틀릴 수 있다(파서처럼 앞 줄을 따라가려면 줄 순서가 필요)
        win, cov = inp.get("window") or {}, (events or {}).get("coverage") or {}
        lo, hi = (logtime.normalize_ts(win.get("start") or cov.get("first_ts"), None, None),
                  logtime.normalize_ts(win.get("end") or cov.get("last_ts"), None, None))
        if lo is None or hi is None:
            return t
        cands = [t] + [c for d in (-1, 1) if (c := at(int(year) + d)) is not None]
        return min(cands, key=lambda c: 0 if lo <= c <= hi else min(abs(c - lo), abs(c - hi)).total_seconds())
    m = QUOTE_TS_RX.match(s)
    if m and "T" in m.group(0):
        return logtime.normalize_ts(m.group(0), inp.get("tz"), inp.get("year"))
    return window.parse_at(m.group(0), events or {})[0] if m else None


ROW_TS_MATCH_MAX = 1000   # C-4: 행 모양 인용과 메시지가 같은 사본 줄을 이만큼 보고도 같은 초를 못 찾으면 판단하지 않는다(시각 그대로)


def _quote_at(q: str, events: dict | None, copies: list[str]) -> tuple:
    """A5: 인용이 가리키는 사본 줄 → (UTC 시각 | None, 그 줄이 든 사본 순번 | None). 게이트가 쓰는 인용 시각·사본은 여기서 정한다.
    원문 모양 인용: 시각은 `_quote_ts`(ok면 `evidence.stamp_matches`가 날짜·시간대까지 사본 줄과 맞췄다), 사본은 시각 칸까지 맞는 첫 사본.
    행 모양 인용(`HH:MM:SS … 슬롯 레벨 태그 메시지`, C-4): 날짜가 없어 다른 날 사본 줄도 실패 당일 시각으로 읽힌다 — 태그와 메시지의
    가장 긴 조각(`…`로 나눔, 4자 이상)이 맞는 사본 줄을 찾아(행 시각은 UTC라 사본 줄의 시계 글자와 다를 수 있어 메시지로 찾는다, 레벨은 syslog에 없어
    보지 않는다) 그 줄 시각(`_quote_ts`)이 읽은 시각과 1초 안이면 그 사본, 맞는 줄은 있는데 1초 안인 줄이 하나도 없으면 (None, None)
    (다른 날 줄 — `_check`가 그 인용을 약함으로 낮춘다). 맞는 줄을 못 찾거나 상한에 닿으면 (읽은 시각, None)(맞는 결론을 잘못
    떨어뜨리지 않는 쪽)."""
    t = _quote_ts(q, events)
    s = evidence.obs_quote(q) or ""
    if t is None or not copies:
        return t, None
    if evidence.raw_stamp(s) is not None:
        return t, next((k for k, text in enumerate(copies) if evidence.stamp_matches(s, [text])), None)
    if not evidence.ROW_RX.match(s):
        return t, None
    _clock, _slot, _level, tag, msg = (s.split(" ", 4) + [""] * 5)[:5]
    msg = evidence.EVENT_SUFFIX_RX.sub("", evidence.ws(evidence.SCRIPT_NOTE_RX.sub("", msg)))
    # G-1·N-1·N-3: 첫 조각이 아니라 가장 긴 조각(앞뒤 괄호 뗌 — `[…]`, 8자 이상이 없으면 4자 이상)과 태그가 맞는 줄을 센다. 다른
    # 조각의 순서·있음은 세는 조건에 두지 않는다(두면 조각을 뒤섞거나 이웃 줄을 이어 맞는 줄 0개 → 날짜 대조를 피한다)
    parts = [p.strip(" []()") for p in evidence.ELLIPSIS_RX.split(msg)]
    seg = max(parts, key=len, default="")
    if len(seg) < 4:
        return t, None
    seen = 0
    for k, text in enumerate(copies):
        at = text.find(seg)
        while at >= 0 and seen < ROW_TS_MATCH_MAX:
            a, b = text.rfind("\n", 0, at) + 1, text.find("\n", at)
            b = len(text) if b < 0 else b
            if (lt := _quote_ts(text[a:b], events)) is not None:     # C-3: 태그는 보지 않는다(태그만 바꿔 대조를 피하지 않게)
                if any(abs((c - t).total_seconds()) < 1 for c in _year_variants(lt, text[a:b])):
                    return t, k
                seen += 1
            at = text.find(seg, b)
    return (None, None) if 0 < seen < ROW_TS_MATCH_MAX else (t, None)


def _year_variants(lt, line: str) -> list:
    """G-5: 사본 줄 시각과, 그 줄에 연도가 없으면(logcat·syslog — 범위 시작의 연도로 읽었다) ±1년도(해를 넘는 로그)."""
    if (evidence.raw_stamp(line) or {}).get("year"):
        return [lt]
    out = [lt]
    for d in (-1, 1):
        try:
            out.append(lt.replace(year=lt.year + d))
        except ValueError:      # 2월 29일
            pass
    return out


def _other_day(q: str, events: dict | None, copies: list[str]) -> bool:
    """A5: 행 모양 인용인데 같은 메시지의 사본 줄은 다른 시각(다른 날)에만 있다(`_quote_at` 시각 None, 읽은 시각은 있음). 원문 모양
    인용은 `stamp_matches`가 이미 날짜까지 맞춰 늘 False(G-8 — 사본을 다시 훑지 않는다)."""
    if not copies or evidence.raw_stamp(evidence.obs_quote(q) or "") is not None:
        return False
    return _quote_ts(q, events) is not None and _quote_at(q, events, copies)[0] is None


def _quote_tag(q: str) -> str | None:
    """인용의 태그(행 문법 넷째 칸 — 타임라인 줄 그대로, 원문 모양은 `raw_row`로 바꿔서). 못 읽으면 None."""
    s = evidence.obs_quote(q) or ""
    row = s if evidence.ROW_RX.match(s) else evidence.raw_row(s)
    parts = (row or "").split(" ", 4)
    return parts[3] if len(parts) >= 4 and parts[3] != "-" else None


def _ref(job: Path, events: dict | None):
    """확정 기준 시각(`summary.ref_of` — 실패 스텝·기준 줄·단서 시각·발생 시각, 추정 기준은 아니다) → UTC datetime, 없으면 None."""
    from triagelib import summary
    inp = (events or {}).get("input") or {}
    return logtime.normalize_ts(summary.ref_of(_load(job / EXPLORE_INPUT_FILE)), inp.get("tz"), inp.get("year"))


def _after_ref(job: Path, ok_quotes: list[str], events: dict | None, ref) -> tuple[bool, str]:
    """게이트 4: 기준 시각(`_ref`) 뒤 줄을 ok로 인용했거나, sha가 맞는 window 구간의 마지막 줄 시각이 기준보다 뒤다(그 뒤 줄이 실제로
    있을 때만 — 같은 시각은 아니다, `--span` 유무와 무관). 확정 기준이 없으면 통과가 아니라 가장 유력 가설의 ok 인용 중 가장 이른
    시각을 기준으로 본다(R-15). 구간 파일 줄의 끝 시각은 그 파일 머리의 날짜 포함 시각(`window.LINE_TS_RE`, G-2)만 쓰고, 없으면(옛 파일) 세지 않는다. 인용 시각은 `_quote_ts` — 사본에서 다른 날 줄만 가리키는 행 모양 인용은 `_check`가 이미 약함으로
    낮춰 ok 인용에 없다(A5, `_quote_at`)."""
    note = ""
    times = [t for q in ok_quotes if (t := _quote_ts(q, events)) is not None]
    if ref is None:
        ref = min(times, default=None)
        if ref is None:
            return False, "기준 시각 없음 — 원문 확인된 인용에도 시각이 없음"
        note = "(기준 시각 없음 — 가장 이른 인용 뒤)"
    if any(t > ref for t in times):
        return True, note
    from triagelib import window
    unknown = 0
    for text in _windows(job)[1]:
        m = window.LINE_TS_RE.search(text)      # G-2: window가 구간 파일 머리에 적은 날짜 포함 끝 시각(추측하지 않는다)
        if m is None:
            unknown += 1
        elif (t := logtime.normalize_ts(m.group(2), None, None)) is not None and t > ref:
            return True, note
    inp = (events or {}).get("input") or {}
    end = logtime.normalize_ts(((events or {}).get("coverage") or {}).get("last_ts"), inp.get("tz"), inp.get("year"))
    if end is not None and end <= ref:      # 가-3(2): 기준 뒤 줄이 로그에 없다 — 안 본 것이 아니다(통과는 아님)
        return False, "로그가 기준 시각에서 끝남 — 실패 뒤 로그가 필요함(`다음 확인`에 뒤 로그 요청)" + note
    return False, ("기준 시각 뒤 줄 인용·구간 없음(실패 뒤를 보지 않음)" + note
                   + (f" — 구간 {unknown}개는 날짜 모름(옛 구간 파일 — window를 다시 받으면 됨)" if unknown else ""))


def _absent_span(events: dict | None, low, span_sec: float):
    """`찾았는데 없음`을 세는 구간 (lo, hi, lo 포함 여부): 아래 끝(`low`)이 있으면 (low, low + `span_sec`] — 그 시각의 줄 자체는
    세지 않는다(C-1), 없으면 분석 범위(`input.window`, 없으면 전체 = None) [시작, 끝]."""
    if low is not None:
        return low, low + timedelta(seconds=span_sec), False
    win = ((events or {}).get("input") or {}).get("window") or {}
    lo, hi = (logtime.normalize_ts(win.get(k), None, None) for k in ("start", "end"))
    return lo, hi, True


def _span_text(span) -> str:
    """센 구간 글(타임라인과 같은 UTC 시각): `15:10:02.000~15:20:02.000`, 분석 범위면 `분석 범위 …`, 범위도 없으면 `로그 전체`."""
    lo, hi, whole = span
    if lo is None and hi is None:
        return "로그 전체"
    clock = lambda t: logtime.format_ts(t)[11:23] if t is not None else "?"
    return ("분석 범위 " if whole else "") + f"{clock(lo)}~{clock(hi)}"


def _absent(word: list[str], texts: list[str], events: dict | None, span) -> int:
    """R-02: `찾았는데 없음` 낱말(`word` — 모두 든 줄)이 마스킹 사본(`texts`)의 구간(`_absent_span`) 안에 몇 줄 있나(`ABSENT_MAX`에서
    멈춘다). 시각을 못 읽는 줄(덤프 이어진 줄 등)은 세지 않는다."""
    lo, hi, closed = span
    n = 0
    for text in texts:
        at = text.find(word[0])
        while at >= 0:
            a, b = text.rfind("\n", 0, at) + 1, text.find("\n", at)
            b = len(text) if b < 0 else b
            line = text[a:b]
            if all(w in line for w in word[1:]) and (t := _quote_ts(line, events)) is not None and (
                    lo is None or t > lo or (closed and t == lo)) and (hi is None or t <= hi):
                n += 1
                if n >= ABSENT_MAX:
                    return n
            at = text.find(word[0], b)
    return n


ABSENT_MAX = 1000         # 흔한 낱말이면 큰 사본에서 줄마다 시각을 읽지 않게 여기서 세기를 멈춘다(이유 글은 `1000건 이상`)
# ponytail: 경험값, 사내 로그로 조정 — 기대 칸에 시간 숫자가 없을 때 '없음'을 믿으려면 아래 끝 뒤 이만큼(초)은 로그가 있어야 한다
ABSENT_MIN_SEC = 10
# ponytail: 경험값 — 첫 어긋남 관측이 앞 단계 관측보다 이만큼 넘게 앞서면 다른 날·다른 시험의 줄로 본다(G-4). 원인이 앞서는 정상 경우를 남기려 넉넉히
OBS_BEFORE_MAX = timedelta(hours=1)
TIME_UNIT_RX = re.compile(rf"(\d+(?:\.\d+)?)\s*(?:({TIME_EN})(?![A-Za-z0-9])|({TIME_KO}))")   # NUM_UNIT_RX의 시간 단위
END_SCAN_LINES = 2000     # 사본 끝에서 시각을 읽을 수 있는 줄을 찾아 거슬러 올라가는 줄 수 상한
ABSENT_WORD_RX = re.compile(r"`([^`]+)`")
ASCII_WORD_RX = re.compile(r"[A-Za-z_][\w.:/-]{3,}")


def _absent_words(item: str) -> list[str]:
    """`찾았는데 없음` 항목 `<무엇> — <어디서>`의 셀 낱말: `<무엇>`의 백틱 글, 없으면 영문 낱말(4자 이상). 한글 설명뿐이면 []."""
    what = evidence.QUOTE_CUT_RX.split(item, maxsplit=1)[0]
    return ABSENT_WORD_RX.findall(what) or ASCII_WORD_RX.findall(what)


def _rules_text(events: dict | None) -> str:
    """이슈 DB 스냅샷의 파서 규칙 파일 글(`events.json rules.path`의 `*.yaml` — tags·extractors·ril 등). 못 읽으면 ""."""
    path = str(((events or {}).get("rules") or {}).get("path") or "")
    if not path:
        return ""
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(Path(path).glob("*.yaml")) if p.is_file())
    except OSError:
        return ""


def _need_sec(expect: str) -> float:
    """`찾았는데 없음`을 믿는 데 필요한 관측 시간(초): 기대 칸의 시간 숫자(`TIME_EN`·`TIME_KO` — 여럿이면 가장 큰 것), 없으면
    `ABSENT_MIN_SEC`."""
    def unit(u: str) -> float:
        if u in ("ms", "msec", "밀리초") or u.startswith("milli"):
            return 0.001
        return 3600 if u == "시간" or u[0] == "h" else 60 if u == "분" or u.startswith("min") else 1
    vals = [float(m.group(1)) * unit(m.group(2) or m.group(3)) for m in TIME_UNIT_RX.finditer(expect or "")]
    return max(vals, default=ABSENT_MIN_SEC)


def _copy_span(texts: list[str], events):
    """사본이 담는 시간 (처음, 끝)(UTC): 사본마다 머리에서 내려가며·끝에서 거슬러 올라가며 시각을 읽을 수 있는 첫 줄(`END_SCAN_LINES`줄
    까지, 파일 끝 개행은 한 줄로 세지 않는다)의 시각 — 처음은 가장 이른 것, 끝은 가장 늦은 것, 못 읽으면 None. events.json
    `coverage`는 사본 없이 건너뛴 파일(상한 초과)까지 담아 세는 글과 다를 수 있어 쓰지 않는다."""
    # ponytail: 파일 머리·끝 줄이 그 파일의 처음·마지막 시각이라고 본다 — 시각순이 아닌 묶음 파일이면 범위를 짧게 잡는다(미관측 쪽, 보수적)
    starts, ends = [], []
    for text in texts:
        text = text.rstrip("\n")
        for lines, out in ((text.split("\n", END_SCAN_LINES)[:END_SCAN_LINES], starts),
                           (text.rsplit("\n", END_SCAN_LINES)[-END_SCAN_LINES:][::-1], ends)):
            t = next((t for line in lines if (t := _quote_ts(line, events)) is not None), None)
            if t is not None:
                out.append(t)
    return min(starts, default=None), max(ends, default=None)


def _word_lines(text: str, word: list[str]) -> tuple[bool, set]:
    """`word` 낱말이 모두 든 사본 줄이 있나, 그 줄들의 태그(`raw_row` 넷째 칸, `ROW_TS_MATCH_MAX`줄까지)."""
    found, out, at, n = False, set(), text.find(word[0]), 0
    while at >= 0 and n < ROW_TS_MATCH_MAX:
        a, b = text.rfind("\n", 0, at) + 1, text.find("\n", at)
        b = len(text) if b < 0 else b
        if all(w in text[a:b] for w in word[1:]):
            found = True
            out.update((evidence.raw_row(text[a:b]) or "").split(" ", 4)[3:4])
            n += 1
        at = text.find(word[0], b)
    return found, out


def _span_copies(per: list, texts: list[str], low_copy: int | None) -> tuple[list[str], str]:
    """A4: `찾았는데 없음`의 끝을 잴 사본 → (사본 글들, 이유 메모). `per` = 항목마다 사본마다 `_word_lines`. 그 항목 낱말이 모두 든
    줄이 있는 사본(G-3)과, 그 줄들의 태그가 줄 태그로 나오는 사본(회전된 같은 버퍼 파일) — 다른 버퍼(main 등)가 길다고 '없음'을 믿지
    않는다. 낱말이 어느 사본에도 없으면(파서 규칙에만) 아래 끝을 준 인용 줄의 사본, 그것도 없으면 모든 사본 + 메모. 한 사본 안에 여러
    버퍼가 이어 붙은 파일(bugreport)은 가르지 않고, 같은 태그 한 줄이 다른 버퍼 사본 전체를 끌어들일 수 있다(G-6, 한계)."""
    hit = {k for res in per for k, (found, _t) in enumerate(res) if found}
    if not hit:
        return ([texts[low_copy]], "") if low_copy is not None else (texts, "낱말이 사본에 없어 전체 사본 끝으로 잼")
    tags = {tag for res in per for _f, ts in res for tag in ts}
    return [t for k, t in enumerate(texts) if k in hit or any(tag in _word_lines(t, [tag])[1] for tag in tags)], ""


def _first_obs(h: dict, first: dict, verdict: str | None, texts: list[str], events, low, after_sec: int,
               low_copy: int | None = None) -> tuple[str, str]:
    """R-02(결정 1): 가장 이른 false 단계의 관측 칸이 근거로 서나 — 원문 확인(ok) 인용이거나, 그 가설의 `찾았는데 없음` 항목 낱말이
    마스킹 사본(`texts`만 — 없으면 셀 수 없어 실패, 외부 리뷰 1125 지적 2)의 구간(`_absent_span(low)`, C-1)에서 0건. 그 단계 기대·
    관측 칸에 낱말이 든 항목만 보고, 없으면 모든 항목. 낱말은 사본이나 파서 규칙 글에 한 번이라도 나오는 실제 낱말이어야 한다(C-2 —
    없는 낱말은 늘 0건이다). 한 항목의 낱말이 여럿이면 낱말마다 따로 본다(N-2 — 있음·0건 세기·끝 재는 사본 모두 낱말 하나씩). 아래 끝이 있으면 구간 길이는 max(`after_sec`, 필요 시간 `_need_sec`)이고, 사본 끝(`_copy_span`)이
    아래 끝 + 필요 시간보다 앞이면 미관측으로 실패한다(지적 2 — 3초 로그로 "300초 뒤 없음"을 믿지 않는다). 아래 끝이 없으면
    분석 범위 전체를 세되 사본이 담는 길이(처음~끝)가 필요 시간보다 짧으면 미관측(C-3). 처음·끝은 그 낱말을 관측할 수 있는 사본
    (`_span_copies`, A4 — `low_copy` = 아래 끝을 준 인용 줄의 사본)으로만 잰다. 관측 인용이 사본에서 다른 날에만 있으면 그 이유(A5).
    → (실패 이유 | "", 통과 메모 = 센 구간, 로그 끝에서 잘렸으면 그 끝까지)."""
    if evidence.obs_quote(first["관측"]) is not None:
        if verdict == "ok":
            return "", ""
        if verdict == "weak" and _other_day(first["관측"], events, texts):
            return "관측 줄이 사본에서는 다른 시각(다른 날)에만 있음", ""
        return f"관측 인용이 원문에서 확인되지 않음({verdict or '검사 못 함'})", ""
    items = [(i, w) for i in h.get("찾았는데 없음") or [] if (w := _absent_words(i))]
    near = f"{first['기대']} {first['관측']}".lower()
    items = [x for x in items if any(w.lower() in near for w in x[1])] or items
    # N-2: 한 항목의 낱말 여럿은 낱말마다 따로 센다 — 모두 든 줄만 세면 실패 줄에 함께 든 두 낱말로 재요청 줄을 피한다
    items = [(i, [w]) for i, word in items for w in word]
    if not items:
        return "관측이 원문 확인 인용도, 셀 낱말이 있는 `찾았는데 없음` 항목도 아님", ""
    if not texts:
        return "사본이 없어 '없음'을 셀 수 없음", ""      # 고른 타임라인 행으로 대신 세지 않는다(건너뛴 검사를 통과로 두지 않음)
    rules = None
    for _i, word in items:
        for w in word:
            if not any(w in t for t in texts) and w not in (rules := _rules_text(events) if rules is None else rules):
                return f"`{w[:30]}`은 로그·파서 규칙 어디에도 없는 낱말", ""
    per = [[_word_lines(t, word) for t in texts] for _i, word in items]
    need = _need_sec(first["기대"])
    span = _absent_span(events, low, max(after_sec, need))
    # C-2: 낱말마다 그 낱말의 사본으로 처음·끝을 재고 가장 좁은 범위(처음은 가장 늦게, 끝은 가장 이르게, 하나라도 못 읽으면 None)
    # — 사본을 합치면 다른 사본에만 있는 낱말 하나를 덧붙여 '없음'의 끝을 늘릴 수 있다
    spans, notes = [], []
    for res in per:
        span_texts, span_note = _span_copies([res], texts, low_copy)
        spans.append(_copy_span(span_texts, events))
        notes.append(span_note)
    span_note = next((n for n in notes if n), "")
    first_t = None if any(a is None for a, _b in spans) else max(a for a, _b in spans)
    end = None if any(b is None for _a, b in spans) else min(b for _a, b in spans)
    where = _span_text((span[0], end, False) if low is not None and end is not None and end < span[1] else span)
    for _i, word in items:
        n = _absent(word, texts, events, span)
        if n:
            return f"`찾았는데 없음` `{' '.join(word)[:30]}` 줄이 {where}에 " + (f"{n}건 이상" if n >= ABSENT_MAX else f"{n}건"), ""
    if low is not None and (end is None or end < low + timedelta(seconds=need)):
        got = f"{max(0.0, round((end - low).total_seconds(), 1)):g}초까지만 있어" if end is not None else "끝 시각을 읽지 못해"
        return (f"로그가 {logtime.format_ts(low)[11:23]} 뒤 {got} '없음'을 확인할 수 없음(미관측, 필요 {need:g}초)", "")
    if low is None and (first_t is None or end is None or (end - first_t).total_seconds() < need):    # C-3: 분석 범위 전체를 세도
        got = f"{round((end - first_t).total_seconds(), 1):g}초 분량뿐이라" if first_t and end else "시각을 읽지 못해"
        return f"로그가 {got} '없음'을 확인할 수 없음(미관측, 필요 {need:g}초)", ""
    return "", f"`찾았는데 없음` {where}에 0건" + (f"({span_note})" if span_note else "")


def _unknown_tags(events: dict | None, quotes: list[str], res: dict | None) -> dict:
    """B1: 원문 확인(ok) 인용 줄의 태그(`_quote_tag`) 가운데 이슈 DB 스냅샷 tags.yaml(`events.json rules.path`)에 없는 것(파서가 버리는
    태그인데 근거로 쓰였다) → check-output 기록 칸 `parser_unknown_tags`(인용 순서, 40자·`UNKNOWN_TAGS_MAX`개까지). 규칙을 못 읽으면
    `parser_unknown_tags_skipped`(없음으로 적지 않는다). 인용 검사를 안 했거나 태그 있는 ok 인용이 없으면 {}. events.json에 그 태그의
    레코드가 있으면 파서가 이미 읽는 태그라 뺀다(백엔드 기본 벤더 IPC `RIL`·builtin 판별처럼 tags.yaml 밖에서 읽는 태그)."""
    if not res:
        return {}
    _raw_ready()
    tags = list(dict.fromkeys(t for q, v in zip(quotes, res["verdicts"]) if v == "ok" and (t := _quote_tag(q))))
    path = str(((events or {}).get("rules") or {}).get("path") or "")
    if not tags:
        return {}
    from common import parser_rules
    try:
        rules = parser_rules.load(path) if path else None
    except Exception:       # noqa: BLE001 — 규칙을 못 읽으면 건너뜀으로 남긴다
        rules = None
    if rules is None:
        return {"parser_unknown_tags_skipped": "tags.yaml을 읽지 못함"}
    read = {e.get("tag") for e in (events or {}).get("events") or [] if isinstance(e, dict)}
    out = [t[:40] for t in tags if rules.tag_category(t) is None and t not in read][:UNKNOWN_TAGS_MAX]
    return {"parser_unknown_tags": out} if out else {}


def _vendor_ipc(defaults: dict | None, platform: str | None, rules):
    """플랫폼 백엔드의 벤더 IPC 태그 판단(`is_vendor_ipc`, tags.yaml 속성 반영)과 백엔드 기본 벤더 IPC 태그가 있나 → (판단 | None,
    기본 있음). 백엔드를 못 불러오면 (None, False)(tags.yaml만 본다)."""
    import parser_backends
    import platforms
    try:
        name = platform or platforms.DEFAULT_NAME
        profile = platforms.load(defaults or {}, name, require_enabled=False)
        backend = parser_backends.load(platforms.backend_name(defaults or {}, name)).configure(profile).apply_rules(rules)
    except Exception:       # noqa: BLE001 — 설정·백엔드 문제면 tags.yaml 표시만으로 판정한다
        return None, False
    # ponytail: reference 백엔드(Android·oFono)의 기본 태그 집합(`TagAttrSet._default`)을 본다 — site 백엔드는 없으면 표시 없음으로
    return backend.is_vendor_ipc, bool(getattr(getattr(backend, "_vendor_ipc", None), "_default", None))


def _outer(events: dict | None, ok_quotes: list[str], layer: str | None, defaults: dict | None = None,
           platform: str | None = None) -> tuple[bool, str]:
    """게이트 6: CP·망 쪽 결론이면 ok 인용 중 그쪽 태그 줄이 하나 이상(`CP-망 경계`는 어느 쪽이든). CP 쪽 = 벤더 IPC 태그
    (`_vendor_ipc`)·`CP_CATEGORIES`, 망 쪽 = `NET_CATEGORIES`. 실패 이유(R-08): 판정할 표시(tags.yaml `ipc` 선언·카테고리, 백엔드 기본
    벤더 IPC 태그)가 있으면 "결론 쪽(CP) 태그 줄 인용 없음", 표시 자체가 없으면 "사내 태그 설정에 CP/망 표시 없음(설정 전)".
    표시가 백엔드 기본뿐(tags.yaml에 없음)이고 태그 있는 인용이 있으면 "인용한 줄의 태그가 CP 쪽으로 표시돼 있지 않음 — 사내 태그
    설정 확인"(C-7 — 판정은 같다)."""
    from common import parser_rules
    sides = OUTER_SIDES.get(layer or "")
    if not sides:
        return True, "해당 없음(AP·환경 쪽 결론)"
    try:
        rules = parser_rules.load(str(((events or {}).get("rules") or {}).get("path") or ""))
    except Exception:       # noqa: BLE001 — 규칙을 못 읽으면 실패로 둔다(통과로 표시하지 않는다)
        return False, "tags.yaml을 읽지 못함"
    cats = set(rules.tag_exact.values()) | {c for _p, c in rules.tag_regexes}
    vipc, backend_cp = _vendor_ipc(defaults, platform, rules)
    site = {"cp": rules.declares("ipc") or bool(cats & set(CP_CATEGORIES)), "net": bool(cats & set(NET_CATEGORIES))}
    marked = {"cp": site["cp"] or backend_cp, "net": site["net"]}
    side = {"cp": lambda t: (bool(vipc(t)) if vipc else rules.tag_attr(t, "ipc") == "vendor") or rules.tag_category(t) in CP_CATEGORIES,
            "net": lambda t: rules.tag_category(t) in NET_CATEGORIES}
    tags = [t for t in map(_quote_tag, ok_quotes) if t]
    if any(side[s](t) for t in tags for s in sides):
        return True, ""
    if not any(marked[s] for s in sides):
        return False, "사내 태그 설정에 CP/망 표시 없음(설정 전)"
    label = '·'.join(SIDE_LABEL[s] for s in sides)
    if tags and not any(site[s] for s in sides):     # C-7: 표시가 백엔드 기본(placeholder)뿐 — 인용한 CP 줄의 태그가 빠졌을 수 있다
        return False, f"인용한 줄의 태그가 {label} 쪽으로 표시돼 있지 않음 — 사내 태그 설정 확인"
    return False, f"결론 쪽({label}) 태그 줄 인용 없음"


def _investigation(job: Path, fields: dict, per_hyp, chain_v, sha: str, events: dict | None, defaults: dict | None = None,
                   platform: str | None = None, before: int = 0, texts: list[str] | None = None,
                   after_sec: int = 600, mech_no: str | None = None, normal: bool = False) -> tuple[dict, list[str]]:
    """조사 결론 게이트 6개 → (analysis.json·check-output 기록 `investigation`, 형식 경고). 하나라도 실패면 insufficient_evidence.
    `mech_no` = 앞 검사에서 재계산 답이 '아니오'였던 가설 머리(같은 머리인데 이번에 재계산 줄이 없으면 그 실패를 이어받는다, eval 46).
    `before` = 앞 검사의 원문에 없는 인용 수(있으면 게이트 1 실패, R-03), `texts` = 마스킹 사본 글(`찾았는데 없음` 세기 — 없으면
    셀 수 없어 게이트 2 실패), `after_sec` = `explore.after_sec`(`찾았는데 없음` 세는 구간 최소 길이, C-1), `normal` = 고른 가설이 정상이고
    정상 근거 줄이 원문 확인(`_normal_flags`)."""
    hyps = fields.get("hyps") or []
    if not hyps:
        return {"status": "insufficient_evidence", "hyp": None, "cause": None, "layer": None, "first_divergence": None,
                "gate": [{"name": "가설", "ok": False, "why": "가설 없음"}], "explore_sha": sha}, []
    _raw_ready()
    k = _picked(fields)
    h = hyps[k]
    rows = h.get("기대 체인") or []
    quotes = h["로그로 확인"] + evidence.chain_quotes(h)
    verdicts = None if per_hyp is None else per_hyp[k] + chain_v[k]
    first = next((r for r in rows if r["일치"] == "false"), None)
    m = CLAIM_STEP_RX.match(h.get("첫 갈라짐") or "")
    claim = int(next(g for g in m.groups() if g)) if m else None
    layer = _layer(h.get("책임 경계"))
    ref = _ref(job, events)
    gate: list[dict] = []
    warns: list[str] = []

    def add(name: str, ok, why: str = "") -> None:
        gate.append({"name": name, "ok": bool(ok), "why": why[:INV_WHY_MAX]})

    if verdicts is None:
        add("인용 원문", False, "근거 원문 검사 건너뜀")
    else:
        fab, n_ok = verdicts.count("fabricated"), verdicts.count("ok")
        add("인용 원문", not fab and n_ok and not before, f"앞 검사에 원문에 없는 인용 {before}(다시 검사해도 지우지 않음)"
            if before and not fab and n_ok else "" if not fab and n_ok else f"원문에 없음 {fab}, 원문 확인 {n_ok}")
    obs = note = ""
    far = None
    if first is not None and claim == first["단계"]:
        quoted = [r for r in rows if evidence.obs_quote(r["관측"]) is not None]
        by_row = dict(zip(map(id, quoted), chain_v[k])) if chain_v else {}
        # C-1: `찾았는데 없음` 아래 끝 = 기준 시각과 그 단계 앞 단계들의 원문 확인 관측 줄 중 가장 늦은 시각 중 늦은 쪽
        prior = [at for r in quoted if r["단계"] < first["단계"] and by_row.get(id(r)) == "ok"
                 and (at := _quote_at(r["관측"], events, texts or []))[0] is not None]
        last = max(prior, key=lambda at: at[0], default=(None, None))
        low = max([t for t in (ref, last[0]) if t is not None], default=None)
        obs, note = _first_obs(h, first, by_row.get(id(first)), texts or [], events, low, after_sec,
                               last[1] if last[0] is not None and low == last[0] else None)
        # G-4: 원문 확인된 관측 줄의 시각이 앞 단계 관측보다 `OBS_BEFORE_MAX` 넘게 앞서면(다른 날 줄) 첫 어긋남이 아니다. 앞 단계
        # 관측이 없으면 실패시키지 않고 기준 시각과 그만큼 떨어졌는지만 리포트에 드러낸다(`far`)
        obs_t = _quote_at(first["관측"], events, texts or [])[0] if not obs and by_row.get(id(first)) == "ok" else None
        if obs_t is not None and last[0] is not None and obs_t < last[0] - OBS_BEFORE_MAX:
            obs = f"관측이 앞 단계 관측보다 {_hours(last[0] - obs_t):g}시간 앞섬"
        elif obs_t is not None and last[0] is None and ref is not None and abs(obs_t - ref) > OBS_BEFORE_MAX:
            far = _hours(abs(obs_t - ref))
        if obs:
            obs = f"단계 {first['단계']}: {obs}"
            warns.append(f"가설 {k + 1}: 가장 이른 false {obs} — 관측 줄을 시각부터 원문 그대로 쓰거나, 없음이면 `찾았는데 없음:`에 "
                         "찾은 낱말을 백틱으로(예: - `SETUP_DATA_CALL` 재요청 — logs-masked 15:10:02 뒤 grep)")
    subject = _layer(first["주체"]) if first else None
    if first is None and NORMAL_RX.match(h["가설"] or ""):
        # 가-2: false 단계가 없는 정상 가설 — 첫 어긋남·책임 층은 해당 없음이고 정상 근거 줄(원문 확인)이 대신한다(R-16, 상태는
        # 호출부가 근거 부족 그대로 둔다)
        why = "해당 없음(정상 가설)" if normal else NORMAL_UNSEEN
        add("첫 어긋남", normal, why)
        add("책임 층", normal, why)
    else:
        add("첫 어긋남", first is not None and claim == first["단계"] and not obs,
            "기대 체인 표 없음" if not rows else "표에 false 단계 없음" if first is None
            else obs or note if claim == first["단계"] else f"첫 갈라짐 {claim or '없음'} ≠ 가장 이른 false 단계 {first['단계']}")
        add("책임 층", layer not in (None, "모름") and first is not None and subject == layer,
            "책임 경계 칸 없음·목록 밖" if layer is None else "책임 경계 모름" if layer == "모름" else "첫 갈라짐 단계 없음"
            if first is None else "기대 주체 칸 없음(옛 형식 표)" if not first["주체"] else ""
            if subject == layer else f"책임 경계 {layer} ≠ 단계 {first['단계']} 기대 주체 {subject or _one(first['주체'])[:20]}")
    ok_quotes = [q for q, v in zip(quotes, verdicts or []) if v == "ok"]
    add("실패 뒤 흔적", *_after_ref(job, ok_quotes, events, ref))
    mech = h.get("메커니즘 재계산") or ""
    flip = FLIP_RX.search(mech)
    na = not flip and bool(NA_RX.search(mech))      # 가-1: `해당 없음 — <이유>`는 답(예/아니오)이 아니라 정식 답 "해당 없음"
    answer = None if (flip and flip.group(2)) or na else (flip or FLIP_TAIL_RX.search(mech))
    reply = answer.group(1) if answer else None
    numeric = NUM_UNIT_RX.search((first or {}).get("기대") or "")     # R-17: 가장 이른 false 단계의 `기대` 칸만(가설 머리의 경과 시간은 아님)
    # 외부 리뷰 1125 지적 3: 명시적 `아니오`는 숫자 기대와 상관없이 실패, 숫자 기대면 계산 숫자와 명시적 `예`가 있어야 한다
    # eval 77: 지우지 않고 `해당 없음`·빈 답으로 바꿔 써도 이어받는다 — 같은 머리는 답 `예`와 계산 숫자일 때만 새로 판정
    carried = bool(mech_no) and mech_no == (_one(h["가설"])[:INV_CAUSE_MAX] or None) and not (
        reply == "예" and not (flip and flip.group(2)) and re.search(r"\d", mech))
    why = ("재계산 답이 아니오(고쳐도 안 뒤집힘)" if reply in ("아니오", "아니요")
           else MECH_NO_CARRIED if carried else "" if not numeric
           else "숫자 기대인데 메커니즘 재계산 없음" if not mech.strip() else "재계산 답이 틀 그대로" if flip and flip.group(2)
           else "숫자 기대인데 재계산이 해당 없음 — 기대의 숫자로 다시 계산(계산 숫자와 예)" if na
           else "재계산 답 없음(예/아니오)" if reply != "예" else "재계산에 계산 내용(숫자) 없음" if not re.search(r"\d", mech) else "")
    add("숫자 메커니즘", not why, why or ("" if numeric else "해당 없음(숫자 기대 없음)"))
    add("외부 근거", *_outer(events, ok_quotes, layer, defaults, platform))
    return ({"status": "identified" if all(g["ok"] for g in gate) else "insufficient_evidence", "hyp": k + 1,
             "cause": _one(h["가설"])[:INV_CAUSE_MAX] or None, "layer": layer,
             "first_divergence": {"step": first["단계"], "expect": _one(first["기대"])[:INV_EXPECT_MAX]} if first else None,
             "gate": gate, "explore_sha": sha, **({"obs_far_h": far} if far is not None else {})}, warns)


def _hours(d) -> float:
    return round(d.total_seconds() / 3600, 1)


# --- 그리기 ----------------------------------------------------------------------------------------------

def _head(current: str | None, prefix: str, default: str) -> str:
    if current and current.startswith(prefix) and "): " in current:
        return current[: current.index("): ") + 3]
    return default


def _one(text) -> str:
    return " ".join(str(text or "").split())


def _render(purpose: str, mode: str, head: str, fields: dict, sub: str, fab_by_hyp: list[int] | None = None,
            normal_bad: list[bool] | None = None, check_bad: set = frozenset()) -> list[str]:
    """report 줄. `fab_by_hyp`(탐색, 가설별 원문에 없는 인용 수)가 0보다 크면 그 가설 줄에 `[근거 불일치 N]`, `normal_bad`(정상이라고
    적었는데 원문에 있는 인용이 없음)면 `[정상 근거 없음]`, `check_bad`(심층·탐색 `후보 확인` 항목 번호 — 근거 인용이 원문에 없음)면 그
    항목에 `[근거 불일치]`. 탐색 `후보 확인`(조사 모드 near_causes 대조)은 가설 줄 뒤 하위 줄 하나."""
    checks = fields.get(evidence.CHECK_FIELD) or []
    check_line = [f"  - 후보 확인: {' | '.join(_check_one(c, i in check_bad) for i, c in enumerate(checks))}"] if checks else []
    if purpose == "explore":
        if not fields["hyps"]:
            return [f"{head}가설 없음: {_one(fields['none'])} / 다음 확인: {_one(fields['next'])}", *check_line, sub]
        out = [f"{head}가설 {len(fields['hyps'])}개 — 점수·분류·검증에 쓰지 않는다"]
        for i, h in enumerate(fields["hyps"], 1):
            k = fab_by_hyp[i - 1] if fab_by_hyp else 0
            mark = (f" [근거 불일치 {k}]" if k else "") + (NORMAL_BAD if normal_bad and normal_bad[i - 1] else "")
            out.append(f"  - 가설 {i}{mark}: {_one(h['가설'])} / 로그로 확인: {' | '.join(_one(q) for q in h['로그로 확인'])} / "
                       f"코드로 추정: {_one(h['코드로 추정'])} / 반대 근거: {_one(h['반대 근거'])} / 다음 확인: {_one(h['다음 확인'])}"
                       + (f" / 첫 갈라짐: {_one(h['첫 갈라짐'])}" if h.get("첫 갈라짐") else ""))
        return out + check_line + [sub]
    quotes = " | ".join(_one(q) for q in fields["근거"])
    if mode == "module":
        tail = (f"후보 확인: {' · '.join((c['cause'] or '?') + ' ' + c['verdict'] for c in checks)}" if checks
                else f"분석 스킬 의견: {_one(fields['분석 스킬 의견'])}")      # 옛 모듈 레포 형식(한 줄)
        first = f"{head}원인 층 {_one(fields['원인 층'])} · 원인 데몬 {_one(fields['원인 데몬'])} / {tail}"
        return [first, f"  - 근거: {quotes}", f"  - 반대 근거: {_one(fields['반대 근거'])}", *check_line, sub]
    return ([f"{head}{_one(fields['요약'])} / 분석 스킬 의견: {_one(fields['분석 스킬 의견'])}"]
            + ([f"  - 근거: {quotes}"] if fields["근거"] else []) + [sub])


def _check_one(c: dict, bad: bool = False) -> str:
    if c["verdict"] == "?":                 # 못 읽은 줄은 원문 그대로(check-output이 stderr에도 경고)
        return f"? (읽지 못함) {_one(c['why'])}"
    return f"{c['cause']} {c['verdict']}" + (" [근거 불일치]" if bad else "") + (f" — {_one(c['why'])}" if c["why"] else "")


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


def _rule_subs(purpose: str, items, source: str | None, tags, res: dict | None, text: str = "",
               confirmed: bool = True) -> tuple[list[str], int, dict, list[int] | None]:
    """`규칙 제안` 항목 → (report 하위 줄, 실은 수, 뺀 이유별 수 `{근거 불일치|형식|원인 미확정: n}`(0은 키 없음), 탐색 `[모듈]` 줄 중
    실은 번호 | None(그런 줄 없음)). `없음`은 건너뛴다.
    `— 근거: <문구>`가 있으면 그 문구가 원문(`source`) 검사 `ok`일 때만(원문 모양 줄이면 행 문법으로 바꾼 것도 대조), 없으면 근거 원문
    검사(`res`)를 실제로 했고 원문에 없는 인용이 없을 때만 싣는다 — 근거 불일치 가설에서 나온 제안·검사를 건너뛴 출력의 제안을 막는다.
    탐색 `[모듈]`(반입 7 A-1)은 목록 항목이 아니라 출력 글(`text`)의 `- [모듈]` 줄을 `modulelines.parse`로 읽는다(번호 N = 그 줄 순서,
    형식이 틀린 줄도 센다 — `skill_patch --module --line N`과 같은 번호). 형식 오류·모르는 칸(형식)·근거 원문 불일치를 빼고, 원인이
    확정되지 않았으면(`confirmed` 거짓) `HELD_SLOTS`(첫 점검·함정)도 뺀다(원인 미확정). 실은 줄은 `[모듈 N] …`으로 쓴다."""
    kind, kept, why = RULE_KIND[purpose], [], {}

    def drop(reason: str) -> None:
        why[reason] = why.get(reason, 0) + 1

    def grounded(basis: str) -> bool:
        return source is not None and evidence.check_quotes([basis], source, tags, alts=[evidence.raw_row(basis)])["verdicts"] == ["ok"]

    def add(line: str) -> None:
        kept.append(RULE_SUB.format(kind=kind, text=line if len(line) <= RULE_CLIP else line[:RULE_CLIP - 1] + "…"))

    module_items = 0
    for item in [_one(x) for x in items or []][:RULES_MAX]:
        if not item or evidence.RULE_NONE_RX.match(item):     # `없음`·`해당 없음`(뒤 설명 무엇이든)은 제안이 아니다
            continue
        if purpose == "explore" and item.startswith(modulelines.HEAD[2:]):
            module_items += 1           # 아래에서 줄 번호로 따로 본다
            continue
        m = RULE_BASIS_RX.search(item)
        if (grounded(m.group(1)) if m else res is not None and not res.get("fabricated")):
            add(item)
        else:
            drop("근거 불일치")
    rows = modulelines.parse(text) if purpose == "explore" else []
    lines = []
    for row in rows[:RULES_MAX]:
        if not row["ok"]:
            drop("형식")
        elif not grounded(row["basis"]):
            drop("근거 불일치")
        elif not confirmed and row["slot"] in modulelines.HELD_SLOTS:
            drop("원인 미확정")
        else:
            lines.append(row["n"])
            add(f"[모듈 {row['n']}]" + row["raw"][len(modulelines.HEAD):])
    for _ in range(module_items - len(rows)):       # `- ` 없이 쓴 [모듈] 항목(번호가 없어 고를 수 없다)
        drop("형식")
    n = sum(why.values())
    text_why = " · ".join(f"{RULE_WHY[r]} {why[r]}" for r in RULE_WHY if r in why)
    return (kept + ([RULE_DROPPED.format(kind=kind, n=n, why=text_why)] if n else []), len(kept), why,
            lines if rows or module_items else None)


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


def _save_analysis(job: Path, new: dict, read_sha: str | None, key: str, warn: str) -> tuple[dict | None, dict]:
    """analysis.json을 `new`로 바꿔 쓴다: 4KB 맞춤(`rep.fit` — 판단의 사건(events)부터 준다) → 스키마 검사(TT_SCHEMA_CHECK) → 처음
    읽은 뒤 바뀌지 않았는지 해시 대조 → 원자 쓰기 → module-skill.json 입력 해시 갱신. → (쓴 내용 | None, 기록에 더할 칸 — 못 썼으면
    `{key: 사유}`, 해시를 못 고쳤으면 `module_inputs_unwritten: true`)."""
    result = rep.fit(new)
    why = None
    violation = rep.schema_violation(result)
    if violation:
        why, detail = "스키마 위반", violation
    elif _read_analysis(job)[1] != read_sha:
        why = detail = "검사 중 analysis.json이 바뀌었다"
    if why:
        print(warn.format(why=detail), file=sys.stderr)
        return None, {key: why}
    data = (rep.dumps(result) + "\n").encode("utf-8")
    try:
        _write_atomic(job / "analysis.json", data)
    except OSError:
        print(warn.format(why="쓰기 실패"), file=sys.stderr)
        return None, {key: "쓰기 실패"}
    return result, ({} if not read_sha or _rebase_module_inputs(job, read_sha, _sha(data)) else {"module_inputs_unwritten": True})


WARN_INVESTIGATION = "경고: analysis.json 조사 결론(investigation)을 쓰지 못했다({why})"


def _without_investigation(rows: list[str]) -> list[str]:
    """report.md 줄에서 조사 결론 묶음(`- 조사 결론 (LLM, …`과 바로 뒤 `  - ` 줄)을 뺀다."""
    at = next((i for i, r in enumerate(rows) if r.startswith(issuepost.INVESTIGATION_PREFIX)), None)
    if at is None:
        return rows
    end = at + 1
    while end < len(rows) and rows[end].startswith("  - "):
        end += 1
    return rows[:at] + rows[end:]


def _clear_investigation(job: Path) -> None:
    """탐색 생략·실패(다시 검사 아님): 앞 검사가 남긴 조사 결론을 report.md와 analysis.json에서 지운다(옛 결론이 남지 않게)."""
    report = job / "report.md"
    if _kind(report) == "file":
        rows = report.read_text(encoding="utf-8").split("\n")
        kept = _without_investigation(rows)
        if kept != rows:
            try:
                _write_atomic(report, "\n".join(kept).encode("utf-8"))
            except OSError:
                print(WARN_REWRITE, file=sys.stderr)
    analysis, sha = _read_analysis(job)
    if isinstance(analysis, dict) and "investigation" in analysis:
        _save_analysis(job, {k: v for k, v in analysis.items() if k != "investigation"}, sha, "investigation_unwritten",
                       WARN_INVESTIGATION)


def _place_investigation(report: Path, lines: list[str], top: bool) -> bool:
    """조사 결론 줄(`issuepost.investigation_lines`)을 report.md에 넣는다(앞 검사의 줄은 지운다): 검증 통과면 CAUSE 칸 맨 위,
    근거 부족이면 `- 결론:` 줄 아래(결론처럼 보이지 않게). 넣을 자리가 없거나 못 쓰면 False."""
    if _kind(report) != "file":
        return False
    rows = _without_investigation(report.read_text(encoding="utf-8").split("\n"))
    i = next((i for i, r in enumerate(rows) if r.startswith("### CAUSE" if top else rep.CONCLUSION_PREFIX)), None)
    if i is None:
        return False
    i += 1
    while not top and i < len(rows) and rows[i].startswith("  - "):
        i += 1
    rows[i:i] = lines
    try:
        _write_atomic(report, "\n".join(rows).encode("utf-8"))
    except OSError:
        return False
    return True


def _decision_update(args, job: Path, analysis: dict, read_sha: str | None, *, hold: bool = False,
                     opinion: str | None = None, normal: bool = False, checks: list | None = None) -> dict:
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
        if any(c.get("cause") == selected and c.get("verdict") == "맞음" for c in checks or []):
            return {}       # 후보 확인이 채택 원인도 맞음이라 했으면 counter를 붙이지 않는다
        new = {**dec, "counter": {"cause": m.group(1)}}
    result, extra = _save_analysis(job, {**analysis, "decision": new}, read_sha, "decision_unwritten", WARN_DECISION)
    if result is None:
        return extra
    report = job / "report.md"
    if not rep.rewrite_line(report, rep.DECISION_PREFIX, [rep.decision_line(new, analysis.get("candidates") or [], normal)]):
        print(WARN_REWRITE, file=sys.stderr)
        return {**extra, "decision_unwritten": "report.md 판단 줄"}
    if not args.out:    # run이 남긴 리포트 표시 의무(같은 key)를 고친 줄로 바꾼다 — 옛 "원인 채택" 줄을 보이라고 하지 않게
        shown.record(job.parent, "triage", "report", job.name, key=f"report:{job.name}#{analysis.get('run')}",
                     lines=shown.report_core(report.read_text(encoding="utf-8")), must_show=result.get("must_show") or [],
                     path=str(job.absolute() / "report.md"))
    return extra


REFUTED_NEXT = "심층 분석이 채택 원인 {cause}를 아님으로 봄 — 탐색 분석으로 적합성 확인"
REFUTED_ASK = "(탐색 분석을 할지 묻고 — 답 전 원문 열람 금지 — 동의하면 triage.py explore {key}부터)"
WARN_EXPLORE = "경고: analysis.json 탐색 분석(explore)을 열지 못했다({why})"
CHECKS_CLIP = 200


def _refuted(analysis: dict, checks: list, bad: set) -> str | None:
    """5-1 `후보 확인`이 채택 원인(accepted `selected.cause`)을 `아님`이라 했으면 그 ID(근거 인용이 원문에 없는 항목은 빼고)."""
    dec = analysis.get("decision") or {}
    cause = (dec.get("selected") or {}).get("cause") if dec.get("state") == "accepted" else None
    hit = any(c["cause"] == cause and c["verdict"] == "아님" and i not in bad for i, c in enumerate(checks))
    return cause if cause and hit else None


def _refuted_next(job: Path, analysis: dict, cause: str) -> str | None:
    """5-2가 열려 있으면(`never` 아님) 적합성 확인 안내. 아직 타임라인 전이고 `ask`면 동의를 묻는 말을 붙인다. 안 열렸으면 None."""
    when = (analysis.get("explore") or {}).get("when")
    if when in (None, "never"):
        return None
    ask = when == "ask" and _kind(job / TIMELINE_FILE) != "file"
    return REFUTED_NEXT.format(cause=cause) + (REFUTED_ASK.format(key=analysis.get("key") or job.name) if ask else "")


def _open_fit_check(job: Path, analysis: dict, read_sha: str | None) -> tuple[dict, str | None, dict]:
    """5-2가 안 열렸고 run이 준비해 뒀으면(`explore-input.json` `fit_later` — `driver.explore`가 `never`·`--no-explore`를 보고 둔 값)
    analysis.json `explore`를 그 값으로 열고 report.md 심층 분석 줄 묶음 뒤에 탐색 분석 줄을 넣는다. 판단·점수·분류는 그대로다.
    → (analysis, 그 sha, 기록에 더할 칸 — 못 열었으면 `explore_unwritten: <사유>`)."""
    later = _load(job / EXPLORE_INPUT_FILE)
    later = later.get("fit_later") if isinstance(later, dict) else None
    if analysis.get("explore") or not isinstance(later, dict):
        return analysis, read_sha, {}
    result, extra = _save_analysis(job, {**analysis, "explore": later}, read_sha, "explore_unwritten", WARN_EXPLORE)
    if result is None:
        return analysis, read_sha, extra
    report = job / "report.md"
    rows = report.read_text(encoding="utf-8").split("\n") if _kind(report) == "file" else []
    i = next((i for i, r in enumerate(rows) if r.startswith(DEEP_PREFIX)), None)
    if i is not None:
        i += 1
        while i < len(rows) and rows[i].startswith("  - "):
            i += 1
        rows.insert(i, EXPLORE_PENDING_LINE.format(key=analysis.get("key") or job.name))
        try:
            _write_atomic(report, "\n".join(rows).encode("utf-8"))
        except OSError:
            i = None
    if i is None:
        print(WARN_REWRITE, file=sys.stderr)
        extra = {**extra, "explore_unwritten": "report.md 탐색 분석 줄"}
    return result, _read_analysis(job)[1], extra


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
        _clear_investigation(job)
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
    rec = _load(job / RECORD)
    if current and "TODO(LLM)" not in current and not recheck and isinstance(rec, dict) and isinstance(rec.get(purpose), dict):
        # 가-6: 이미 검사했다(다시 검사는 형식 경고 뒤 한 번뿐) — 멈출 일이 아니라 계속할 일이라 종료 1(해당 없음)
        raise _Stop(CHECK_FAILED, "이미 검사함", NEXT_CHECK_NA, "이미 검사했다 — 다시 검사는 형식 경고 뒤 한 번뿐(쓴 줄은 그대로 둔다)")
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
    if getattr(args, "recheck", False):     # 형식 경고 뒤 다시 검사가 실패: 첫 검사 결과(리포트 줄·확인할 내용·기록)를 그대로 둔다
        old = _load(job / RECORD)
        old = old.get(purpose) if isinstance(old, dict) else None
        _record(job, purpose, {**(old if isinstance(old, dict) else {}), "format_recheck": True, "recheck_error": label})
        print(f"{label} — 다시 검사 실패, 첫 검사 결과 유지", file=sys.stderr)
        _emit({"kept": RECHECK_KEPT, "recheck_error": label})
        return OK
    if (_rewrite(report, PREFIX[purpose], [SKIPPED[purpose].format(reason=label)], pending=not getattr(args, "recheck", False))
            and purpose == "explore"):
        _question_tail(report, QUESTION_SKIPPED)
    _record(job, purpose, {"error": label, "at": _now(), "env": env, "output_sha256": sha})
    if purpose == "explore":
        _clear_investigation(job)
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
    win_names, win_texts, win_bad = _summary_source(job, win_names, win_texts, win_bad)
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

    unread = sum(c["verdict"] == "?" for c in fields.get(evidence.CHECK_FIELD) or []) if purpose == "deep" else 0
    if unread or (purpose == "deep" and mode == "module" and not (fields.get("분석 스킬 의견") or "").strip()):
        print(f"경고: 후보 확인 칸에서 판정을 읽지 못했다({unread}줄 — report에 원문 그대로)" if unread
              else "경고: 후보 확인·분석 스킬 의견 칸이 비었다", file=sys.stderr)
    # 근거 원문 검사(설치 스킬만 raw_items: 마스킹이 바꾼 인용 = 준 파일 밖 원문 값)
    quotes = _quotes(purpose, fields)
    raw_items: frozenset[int] = frozenset()
    if mode == "skill":
        before = _quotes(purpose, _parse(purpose, mode, raw))
        if len(before) == len(quotes):
            raw_items = frozenset(i for i, (a, b) in enumerate(zip(before, quotes)) if a != b)
    res = fab_by_hyp = per_hyp = chain_v = alts = None
    check_bad: set = set()
    check_ok: set = set()       # A2: `후보 확인` 근거 인용이 원문 확인(ok)인 항목 — "규칙 1위와 같음"은 이것만
    source, tags = evidence.source_text(src_text) if src_skip is None and src_text is not None else (None, None)
    # R-06: 규칙 제안·[모듈] 줄의 `근거:` 문구도 사본에서 찾는다(인용만 넘기면 사본에만 있는 근거가 "근거 불일치"로 빠졌다)
    bases = ([m.group(1) for x in fields.get("rules") or [] if (m := RULE_BASIS_RX.search(_one(x)))]
             + [r["basis"] for r in modulelines.parse(text) if r["ok"]]) if purpose == "explore" else []
    copies: list[str] = []
    if purpose == "explore" and source is not None and (quotes or bases):
        # 탐색은 마스킹 사본 전체를 grep·구간 읽기 한다(최후의 보루, 11/25) — 인용 낱말이 든 사본 줄을 근거 원문에 더하고,
        # 원문 모양(logcat·syslog) 인용은 같은 행 문법으로 바꾼 것도 대조해 나은 쪽을 쓴다. 원문(사본 아닌 것)은 보지 않는다
        names, extra, copies = _copy_source(job, analysis, quotes + bases)
        if extra:
            source, tags = evidence.source_text("\n".join([src_text, extra]))
            src_rel = ([src_rel] if isinstance(src_rel, str) else list(src_rel or [])) + names
            alts = [evidence.raw_row(q) for q in quotes]
    if not quotes:
        src_skip = "인용 없음"
    elif src_skip is None:
        res = evidence.check_quotes(quotes, source, tags, raw_items=raw_items, alts=alts,
                                    copies=copies if purpose == "explore" else None)
        if purpose == "explore" and copies:     # A5: 행 모양 인용이 사본에서 다른 날 줄만 가리키면 원문 모양처럼 약함(`_quote_at`)
            for i, q in enumerate(quotes):
                if res["verdicts"][i] == "ok" and _other_day(q, events, copies):
                    res["verdicts"][i], res["weak"] = "weak", res["weak"] + 1
        if purpose == "explore":        # verdicts는 `_quotes` 순서 = 가설 순서대로 `로그로 확인`을 이어 붙인 것
            it = iter(res["verdicts"])
            per_hyp = [[next(it) for _ in h["로그로 확인"]] for h in fields["hyps"]]
            chain_v = [[next(it) for _ in evidence.chain_quotes(h)] for h in fields["hyps"]]     # 기대 체인 관측 줄(뒤에 붙였다)
            fab_by_hyp = [(a + b).count("fabricated") for a, b in zip(per_hyp, chain_v)]
            tail = list(it)             # 나머지 = `후보 확인` 인용(조사 모드 near_causes 대조 — 게이트는 가설 인용만 본다)
        else:                           # 심층: `근거` 뒤 verdicts가 `후보 확인` 인용 항목 순서
            tail = res["verdicts"][len(fields.get("근거") or []):]
        check_bad = {i for (i, _w), v in zip(_check_quoted(fields), tail) if v == "fabricated"}
        check_ok = {i for (i, _w), v in zip(_check_quoted(fields), tail) if v == "ok"}
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
    investigating = purpose == "explore" and (analysis.get("investigate") or {}).get("mode")     # 조사 모드(run이 판정)
    from triagelib import summary
    mech_before = (old.get(purpose) or {}).get("mech_no") if isinstance(old, dict) and isinstance(old.get(purpose), dict) else None
    inv, inv_warns = (_investigation(job, fields, per_hyp, chain_v, sha, events, getattr(args, "tt_defaults", None),
                                     analysis.get("platform"), before, copies,
                                     summary.after_of(getattr(args, "platform_cfg", None) or {}),
                                     mech_before if isinstance(mech_before, str) else None, normal1) if investigating
                     else (None, []))
    mech_g = next((g for g in (inv or {}).get("gate") or [] if g["name"] == "숫자 메커니즘"), None)
    mech_no = inv["cause"] if mech_g and not mech_g["ok"] and mech_g["why"].startswith(("재계산 답이 아니오", MECH_NO_CARRIED[:12])) else None
    if inv and normal1:     # R-16: 가장 유력이 정상이고 정상 근거 줄이 원문 확인 — 원인 조사 대상 아님(상태는 근거 부족 그대로)
        inv = {**inv, "status": "insufficient_evidence", "normal": True}
    top = (analysis.get("candidates") or [None])[0]
    if inv and inv["status"] == "identified" and isinstance(top, dict) and (top.get("cause") or top.get("type")):
        # R-24: 규칙 1위와 같음은 `후보 확인`이 그 ID를 맞음이라 했고 그 근거 인용이 원문 확인(ok)일 때만(A2 — `찾았는데 없음`뿐·약함·
        # 검사 건너뜀은 아니다). C-3b: 1위가 유형만(원인 미확인)이면
        # 그 유형의 원인 ID(`<유형>-NN`, near_causes가 주는 것)가 맞음일 때도 — 값은 같다고 본 원인 ID(줄에 그 ID를 적는다)
        same = (lambda c: c == top["cause"]) if top.get("cause") else (lambda c: str(c).startswith(f"{top['type']}-"))
        hit = next((c["cause"] for i, c in enumerate(fields.get(evidence.CHECK_FIELD) or [])
                    if same(c["cause"]) and c["verdict"] == "맞음" and i in check_ok), None)
        if hit:
            inv["top_match"] = hit
    # skill_patch --module과 같은 보류 기준 + 결정 2(R-09): 이번 조사 결론이 identified면 첫 점검·함정도 받는다
    confirmed = ((analysis.get("decision") or {}).get("state") == "accepted" and not hold) or bool(inv and inv["status"] == "identified")
    rule_lines, rules_kept, rules_why, module_lines = _rule_subs(
        purpose, fields.get("rules" if purpose == "explore" else "규칙 제안"), source, tags, res, text, confirmed)
    rules_dropped = sum(rules_why.values())
    unknown = _unknown_tags(events, quotes, res)
    unknown_lines = ([UNKNOWN_TAGS_SUB.format(kind=RULE_KIND[purpose], tags=", ".join(unknown["parser_unknown_tags"]))]
                     if unknown.get("parser_unknown_tags") else [])
    reason = _hold_reason(analysis, fields) if hold else None
    fmt = (_chain_warnings(fields, bool(investigating)) + _check_warnings(analysis, fields) + inv_warns
           + ([WARN_INV_TOP.format(top=_one(fields.get("top"))[:40])] if investigating and fields["hyps"] and _top_index(fields) is None
              else [])) if purpose == "explore" else []
    fmt_text = "; ".join(fmt)
    fmt_lines = [FORMAT_SUB.format(text=fmt_text if len(fmt_text) <= FORMAT_CLIP else fmt_text[:FORMAT_CLIP - 1] + "…")] if fmt else []
    lines = (_render(purpose, mode, _head(current, prefix, default), fields, sub, fab_by_hyp, normal_bad, check_bad)
             + subs + rule_lines + unknown_lines + fmt_lines)
    if _rewrite(report, prefix, lines, KEEP_SUB, pending=not args.recheck) and purpose == "explore":
        _question_tail(report, QUESTION_DONE if fields["hyps"] else QUESTION_DONE_NONE)
    unwritten = (_hold_lines(report, hold, (analysis.get("decision") or {}).get("state") == "held", reason == "normal")
                 if hold else [])
    if unwritten:
        print(WARN_HOLD.format(what="·".join(unwritten)), file=sys.stderr)
    if hold:
        dec_extra = _decision_update(args, job, analysis, read_sha, hold=True, normal=reason == "normal")
    elif purpose == "deep":
        dec_extra = _decision_update(args, job, analysis, read_sha, opinion=fields.get("분석 스킬 의견"),
                                     checks=fields.get(evidence.CHECK_FIELD) or [])
    else:
        dec_extra = {}
    # 5-1이 채택 원인을 아님으로 봤다: 판단은 그대로 두고 5-2 적합성 확인을 연다(보류는 5-2 `1위 판단`만 한다)
    refuted = _refuted(analysis, fields.get(evidence.CHECK_FIELD) or [], check_bad) if purpose == "deep" else None
    open_extra = {}
    if refuted:
        analysis, read_sha = _read_analysis(job)     # 판단을 고쳐 썼으면 그 뒤 내용
        analysis, read_sha, open_extra = _open_fit_check(job, analysis or {}, read_sha)
    checks_kept = ([rep._clip(_check_one(c, i in check_bad), CHECKS_CLIP) for i, c in enumerate(fields.get(evidence.CHECK_FIELD) or [])
                    if c["verdict"] != "?"] if purpose == "deep" else [])
    inv_extra = {}
    if inv:     # 조사 모드(run이 판정): 게이트 결과(위에서 계산) → analysis.json 먼저(포털이 읽는 기준), 그다음 report.md
        saved, inv_extra = _save_analysis(job, {**analysis, "investigation": inv}, read_sha, "investigation_unwritten",
                                          WARN_INVESTIGATION)
        if not _place_investigation(report, issuepost.investigation_lines(inv, (analysis.get("candidates") or [None])[0]),
                                    inv["status"] == "identified"):
            print(WARN_REWRITE, file=sys.stderr)
        elif not args.out and saved is not None:    # 리포트 표시 의무에 조사 결론 줄을 더한다(`shown.REPORT_CORE`)
            shown.record(job.parent, "triage", "report", job.name, key=f"report:{job.name}#{analysis.get('run')}",
                         lines=shown.report_core(report.read_text(encoding="utf-8")), must_show=saved.get("must_show") or [],
                         path=str(job.absolute() / "report.md"))

    counts = {k: (res or {}).get(k, 0) for k in ("fabricated", "weak", "raw")}
    n = (res or {}).get("n", 0)
    _record(job, purpose, {"mode": mode, "at": _now(), "env": env, "output_sha256": sha, "source": src_rel if res else None,
                           "quotes": n, **counts, **({"fit_hold": hold, "fit_hold_reason": reason} if hold else {}),
                           **({"top_fit": fields["top_fit"]["fit"] or "읽지 못함"} if fields.get("top_fit") else {}),
                           **({"top_fit_cause": fields["top_fit"]["cause"]} if (fields.get("top_fit") or {}).get("cause") else {}),
                           **({"fit_hold_unwritten": unwritten} if unwritten else {}), **dec_extra, **inv_extra,
                           **({"refuted": refuted} if refuted else {}), **open_extra, **({"checks": checks_kept} if checks_kept else {}),
                           **({"investigation": inv} if inv else {}), **({"mech_no": mech_no} if mech_no else {}),
                           **({"normal": [i + 1 for i, v in enumerate(normal_ok) if v]} if any(normal_ok) else {}),
                           **unknown, **({"rules": rules_kept} if rules_kept else {}), **({"rules_dropped": rules_dropped, "rules_dropped_why": rules_why} if rules_dropped else {}),
                           **({modulelines.KEPT_KEY: module_lines} if module_lines is not None else {}),
                           **({"format_warnings": fmt} if fmt else {}), **({"format_recheck": True} if args.recheck else {})})
    head = masking.mask_brief(lines[0], 300, off=off)     # 끔 DB: report.md 줄과 같은 글자(꼭 보일 줄 대조가 어긋나지 않게)
    fab = [sub.lstrip()] if counts["fabricated"] or before else []     # 앞 검사의 불일치도 보일 의무(RP-14)
    # 심층 분석은 결과 줄(첫 줄)을 늘 보인다 — 탐색은 지어낸 인용이 있을 때만(B2-6)
    _obligation(args, job, purpose, [head.removesuffix("…")] + fab if purpose == "deep" else fab)
    args.trace_extra = {"fabricated": counts["fabricated"]} if res else {}     # F9: 다시 검사해도 trace에 검사마다 수가 남는다
    warn = next((s.strip() for s in subs if s.startswith("  - 경고: 1위 판단")), None)
    _emit({"line": head, "evidence": sub.lstrip(), "quotes": n, **counts, **({"warning": warn} if warn else {}),
           **({"windows_excluded": win_bad} if win_bad else {}), **({"format_warnings": fmt} if fmt else {}),
           **({"investigation": inv["status"]} if inv else {}),
           **({"next": FORMAT_NEXT} if fmt and not args.recheck else {}),
           **({"next": nxt} if refuted and (nxt := _refuted_next(job, analysis, refuted)) else {})})
    return OK


def cmd_check_output(args, defaults: dict) -> int:
    purpose = args.purpose
    skipped = getattr(args, "skipped", None) is not None
    job = None
    try:
        job = _resolve_job(args, defaults)
        args.tt_defaults = defaults         # 게이트 6이 플랫폼 백엔드 기본 벤더 IPC 태그를 읽는다
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
