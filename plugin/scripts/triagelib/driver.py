"""analyze Step 0~5 드라이버 (`Driver`, 믹스인: anchor·cache·report)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

import platforms
import trackers
from common import compat, eligibility, evidence, failedstep, issuedb, lookat, masking, stepanchor, userconfig
from common import flows as flowlib
from common import logtime as lc
from common.exitcodes import CHECK_FAILED, USAGE

from .anchor import AnchorMixin, _parse_ts
from .cache import CacheMixin, State, _digest, _file_sha
from .core import (ELIGIBILITY_FILE, ERROR_EVENT_RE, EXPLORE_MAX_LINES, EXTRACTOR_CODES, EXPLORE_WHEN, PLATFORM_ANSWER, Fail, NeedsInput,
                   MODULE_RECORD_DIR, Runner, SEARCH_LIMIT, SNAPSHOT_DIR, STALE_FILES, STATE_FILE, Stopped, TOP, _clip,
                   FIND_TEXT_ITEMS, PARTIAL_ANALYSIS_MAX, REFERENCE_FILE)
from .report import ReportMixin, _ref_label, _unique_evidence, flow_section, lead_first

MASKED_DIR = "logs-masked"       # 원문 마스킹 사본(parse_logcat.py mask-copy, 종합 리뷰 G①) — 모델이 읽을 대상


# 5-1·5-2 질문 대기(when: ask) 동안의 한 줄 안내(analysis.json `analyzer.note`·`explore.note`): 답 전에 원문을 열어 보는 일을 막는
# 안내일 뿐이다(guard 규칙 10은 통째 읽기만 막는다).
NOTE_LABEL = "제출자 참고(판단 근거·단서 아님): "     # analysis.json issue.submitter_note 머리(R5)
# ponytail: 포털 NOTE_MAX(2000자)와 맞춘 값 — 머리말은 세지 않는다. analysis.json 4KB 예산을 넘으면 fit이 먼저 200자, 다른 후보 근거를 빼기 전 80자로 줄이고 마지막에 표시로 바꾼다
NOTE_MAX = 2000
ASK_NOTE = "답 전 로그 원문 grep·sed·Read 금지 — report.md를 보이고 묻는다(SKILL {step})"


def _ask_note(when, step: str) -> dict:
    return {"note": ASK_NOTE.format(step=step)} if when == "ask" else {}


def _unjudged(match: dict) -> dict | None:
    """match.json에서 판정 불가(시그니처 시간 초과·오류로 `S: null`·`C: null`) 유형·원인 요약. 오류가 없으면 None.
    대표 오류는 판정 불가 항목의 `error`에서 고른다. 충족된 유형의 다른 시그니처만 오류였으면(S/C 영향 없음)
    `count` 0에 `errors`만 채운다(그래도 재사용 캐시는 쓰지 않는다)."""
    errors = match.get("errors") or []
    types = [t for t in match.get("types") or [] if t.get("S") is None]
    causes = [c for c in match.get("causes") or [] if c.get("C") is None]
    if not errors and not types and not causes:
        return None
    picked = []
    for item in types + causes:
        sig, _, msg = str(item.get("error") or "").partition(": ")
        if sig and {"signature": sig, "error": msg} not in picked:
            picked.append({"signature": sig, "error": msg})
    if not picked:
        picked = [{"signature": e.get("signature") or e.get("extractor") or e.get("code"), "error": e.get("error")}
                  for e in errors]
    out = {"count": len(types), "types": [t["type"] for t in types][:5]}
    if causes:
        out.update(cause_count=len(causes), causes=[c["cause"] for c in causes][:5])
    out["errors"] = [{"signature": _clip(e["signature"], 80), "error": _clip(e["error"], 80)} for e in picked[:2]]
    return out


def _observation_summary(events: dict) -> dict | None:
    """events.json `observation`이 불완전이면 `{count, extractor, timeout, errors[≤2 {code, error(≤80)}]}`, 완전하면 None.
    `extractor` = extractor 오류 수, 그중 `timeout` = 시간 초과(비결정 — 캐시 제외). 예시는 파일·외부 파서 것 하나·extractor 것
    하나 순(리포트 줄 라벨과 같은 순서 — 파일 문제는 사용자가 고칠 수 있어 먼저).
    `unjudged`(매처 시그니처 오류)와 따로 둔다 — 정상 불일치가 아니라 로그를 다 보지 못한 것이다. 분석은 그대로 잇는다."""
    obs = events.get("observation") or {}
    if obs.get("complete", True):
        return None
    errors = obs.get("errors") or []
    ext = [e for e in errors if e.get("code") in EXTRACTOR_CODES]
    other = [e for e in errors if e.get("code") not in EXTRACTOR_CODES]
    return {"count": len(errors), "extractor": len(ext), "timeout": sum(e.get("code") == "pattern-timeout" for e in ext),
            "errors": [{"code": e.get("code"), "error": _clip(e.get("error"), 80)} for e in other[:1] + ext[:1]]}


NO_LOCATION = {"state": "none", "source": None, "kind": None}


def _adopted_location(location: dict, why: str | None, cond_line: bool = False, loose: bool = False) -> dict:
    """채택이면 실패 지점 상태를 자격 검사 결과로 정한다: confirmed/point는 기준 줄 자체가 붙은 사건의 증상·원인 근거 줄이거나 같은
    RIL 요청일 때(`same_line`, 조건 줄로만 붙은 `cond_line`이 아님)만이다 — 포털은 accepted + confirmed면 본 분석을 건너뛴다.
    `cp_point`는 found/point(IPC 응답 뒤 2초 안 첫 사건 — 같은 요청이라는 근거가 없다), 구간(`range`)은 found·kind 그대로(FAIL
    마커는 스텝을 감쌀 뿐 실패 사건 줄이 아니고, 스텝 안에 복구된 일시 실패가 있을 수 있다), 조건 줄로만 붙은 `same_line`은
    found·kind 그대로(되풀이되는 조건 줄을 글자로 짚은 것일 수 있다), 그 밖(근처 등)도 found. 문제 파악 허용 유형은 CP 점·근처·
    구간에서만 사건을 고르므로 유형 거르기로 고른 채택도 늘 found다. comment 출처는 늘 found("한 곳에서 찾았다" ≠ "이번 실패
    지점을 확인했다"). 모델이 코멘트에서 고른 기준 줄(`--look-at-source model`, source model)과 낱말 순서로만 찾은 기준 줄
    (`loose`, 찾기 방식 words — 사람이 대충 적은 줄의 낱말이 그 줄에 순서대로 있을 뿐이다)도 같다."""
    if location.get("source") in ("comment", "model") or loose:      # kind는 단서 찾기 방식(ipc·token point, 글자 near) 그대로
        return {**location, "state": "found"}
    if why == "same_line" and not cond_line:
        return {**location, "state": "confirmed", "kind": "point"}
    if why == "cp_point":
        return {**location, "state": "found", "kind": "point"}
    return {**location, "state": "found"}


def _decision(candidates: list[dict], anchor: dict | None, elig: dict | None, clue_location: dict | None = None) -> dict:
    """판단 상태(단계 5): 자격 검사(`match.json` → `eligibility`, `common.eligibility`)가 기준 사건에 붙은 원인만 채택한다 — 후보
    목록·순서·점수는 그대로(채택 원인이 --top 밖이면 매처가 후보 끝에 붙였다). 사유는 처음 맞는 것: 후보 없음 → 실패 지점(앵커)
    없음 → 자격 검사 사유(symptom_not_found → ambiguous → ineligible → cause_unjudged·cause_unconfirmed) → 채택.
    `check`·`events[]`(≤3, 붙은 사건 먼저)·`events_total`은 표시용(전체는 JOB/eligibility.json). `fit_check`(적합성 확인 보류)와
    `counter`(심층 분석 반대 의견)는 check-output만 붙인다. 앵커가 없고 문제 파악 단서만 로그에서 찾았으면 실패 지점은 그 단서
    (`clue_location` — source comment, state found)이고 판정은 자격 검사가 한다."""
    location = dict((anchor or {}).get("location") or clue_location or NO_LOCATION)
    elig = elig or {}
    extra = {"check": {"why": elig.get("why"), "checked": elig.get("checked", 0), "total": elig.get("total", 0),
                       **({"via": elig["via"]} if elig.get("via") else {})},     # 사건이 붙은 코멘트 단서(출처 origin)
             "events": (elig.get("events") or [])[:eligibility.EVENTS_MAX], "events_total": elig.get("events_total", 0)}
    picked = next((c for c in candidates if elig.get("cause") and c["cause"] == elig["cause"]), None)
    if not candidates:
        reason = "no_candidate"
    elif anchor is None and clue_location is None:
        reason = "no_reference"
    elif elig.get("state") == "accepted" and picked:
        return {"state": "accepted", "reason": "anchored_top",
                "selected": {"category": picked.get("category"), "type": picked["type"], "cause": picked["cause"]},
                "location": _adopted_location(location, elig.get("why"), elig.get("cond_line") is True,
                                              (anchor or {}).get("loose") is True), **extra}
    elif elig.get("state") == "accepted":      # 채택 원인이 후보에 없다(매처는 순위 원인만 붙이므로 정상 입력에선 없음) — 보류
        reason, extra["check"]["why"] = "ineligible", "cause_not_in_candidates"
    else:
        reason = elig.get("reason") or "cause_unconfirmed"
    return {"state": "held", "reason": reason, "selected": None, "location": location, **extra}


def _unjudged_label(u: dict) -> str:
    """`판정 불가 유형 N개` 또는 `판정 불가 유형 N·원인 M개`."""
    return f"판정 불가 유형 {u['count']}" + (f"·원인 {u['cause_count']}개" if u.get("cause_count") else "개")


def _backward_pids(anomalies: list) -> dict:
    """시계 이상 가운데 역행 수 `n`과 앞뒤 줄 pid를 아는 것 `known`·그중 같은 pid `same`."""
    back = [a for a in anomalies if isinstance(a, dict) and a.get("kind") == "backward"]
    known = [a for a in back if isinstance(a.get("same_pid"), bool)]
    return {"n": len(back), "known": len(known), "same": sum(1 for a in known if a["same_pid"])}


class Driver(AnchorMixin, CacheMixin, ReportMixin):
    def __init__(self, args, defaults: dict):
        self.args = args
        self.defaults = defaults
        # 선택 플랫폼(triage.py main이 `platforms.session.resolve`로 정한다). 하위 스크립트에는 TT_PLATFORM으로 넘긴다
        self.platform = getattr(args, "platform_name", None) or userconfig.TOP_PROFILE
        self.cfg = userconfig.merged(defaults, platform=self.platform)
        self.key = args.key
        self.offline = args.offline_db is not None
        self.analysis_only = bool(getattr(args, "analysis_only", False))   # 이슈 DB에 기록하지 않는 분석 전용(RF-7)
        self.run = Runner(args.plugin_root)
        self.run.env[platforms.ENV] = self.platform
        self.state = State(None)
        self.job: Path | None = None
        self.snap: Path | None = None
        self.locked = False
        self._platform_spec: platforms.PlatformSpec | None = None
        self.warnings: list[str] = []
        self.notes: list[str] = []
        self.out: dict = {"key": self.key}
        self.failed_step: dict | None = None     # 마스킹된 {text, source}. 없으면 None (선택 값)
        self.anchor_off = False
        self._look: dict | None = None           # --look-at·--look-note를 가린 값 {at, note} (look_inputs)
        self.look_result: dict | None = None     # 기준 줄 찾기 결과 {hits, picked, pick, how, ts, line, at, places} | {hits: 0, why}
        self.look_place: list = []               # 기준 줄 찾기의 고른 곳 줄(자격 검사 기준, anchor.reference_of)
        self.reference: dict | None = None       # 자격 검사 기준(step_anchor가 정함, match_signatures --reference)
        self.jira_time_unused = False            # Jira 발생 시각 칸 값이 있었으나 분석에 쓰지 않았다(D4) — report.md 표시
        self.issue_sha: str | None = None        # 이번 실행이 읽은 이슈 입력 파일의 sha256(problem.json source_sha256과 대조)
        self.problem_use: dict | None = None     # problem.json에서 자격 검사에 쓰는 것(anchor.problem_refs) | None
        self.clue_rows: list[dict] = []          # 로그에서 찾은 문제 파악 단서 {where, clue, ts, places}(report.md 한 줄씩)
        self.clock_offset: float | None = None   # 장비 시각 → 단말 시각 시계 차(초). --clock-offset > failed_step.clock_offset
        self._steps = None                       # read_steps 결과 캐시 (steps-file은 한 번만 읽는다)
        self.order_fail: dict | None = None      # 스텝 순서 정렬을 시도했으나 앵커를 못 정한 이유 {matched, observable, missed, reason}
        self.order_evidence: list[tuple[str, str, str]] = []   # (스텝 이름, 로그 시각, 흔적 이름) — 리포트용(마스킹됨)
        self.clock: dict | None = None           # 시계 정렬 결과 {mode: manual|none, offset_sec | reason}
        self.focus: list[str] = []               # match.step_focus.types (순위 참고용 우선 유형)
        self.time_candidates: list[dict] | None = None   # 시각 입력 없이 로그 전체를 볼 때 찾은 증상 시각 후보 [{ts, type}] (≤3)
        self.full_events: dict | None = None     # 그때 만든 전체 파싱(`events-full.json`) — 본 분석이 다시 파싱하지 않고 쓴다
        self.prior: dict | None = None           # 이전 실행의 1위·탐색 가설·기준 줄 조회(`analysis.json prior`, 재실행일 때만)
        self.steps_member: str | None = None     # steps-file이 zip일 때 읽은 멤버 경로(마스킹·≤120자) — 리포트용
        self.log_inputs: list[dict] = []         # 입력 로그 원본 [{path, name, sha, size}] (bugreport는 원본 파일)
        self.auto_invalid = False                # `code.auto_select`가 불리언이 아니었다
        self.code_auto: str | None = None        # 자동 선택한 코드 프로필(`code.auto_select`). 없으면 None
        self.reuse: dict | None = None           # 재사용 결정 {hit, run, reason?, changed?} — 오프라인·첫 실행은 None
        # 플랫폼 정하기(triagelib/pick.py, 켠 플랫폼 2개 이상만). 없으면 None이고 출력은 이전과 같다(17-platforms §11)
        self.picked = getattr(args, "platform_implicit", None)               # `--platform` 없이 고르는 플랫폼(암묵 선택)
        self.pick: dict | None = getattr(args, "platform_pick", None)        # 이번 실행이 고른 근거 {platform, source, note, line}
        if self.pick:
            self.notes.append(self.pick["note"])

    # 공통 ---------------------------------------------------------------------------------------

    @property
    def platform_spec(self) -> platforms.PlatformSpec:
        """선택 플랫폼의 계약. 잘못되면 사용 오류(종료 코드 2)."""
        if self._platform_spec is None:
            try:
                self._platform_spec = platforms.get(self.platform)
            except platforms.PlatformConfigError as exc:
                raise Fail(USAGE, str(exc)) from exc
        return self._platform_spec

    def platform_out(self) -> str | None:
        """출력 `platform`: android가 아니거나, 암묵 선택(`--platform` 없이 고르는 플랫폼) 또는 지정(`--platform`·`TT_PLATFORM`)과
        다를 때(K8·D5). 켠 플랫폼이 하나면 K8 그대로."""
        if self.platform != userconfig.TOP_PROFILE or self.picked is None:
            return None if self.platform == userconfig.TOP_PROFILE else self.platform
        explicit = self.args.platform or os.environ.get(platforms.ENV)
        if self.picked != self.platform or (self.pick and explicit and explicit != self.platform):
            return self.platform
        return None

    def mark_platform_answer(self) -> bool:
        """이 작업 플랫폼을 답(`--answer platform=`, 또는 그 답으로 이어 가는 작업)으로 정했으면 상태 `platform_answer`에 남긴다 —
        스킬이 다음 호출에서 답을 빼도 `pick`이 다시 묻지 않는다(17-platforms §11-3). 바뀌었으면 True(저장은 부른 쪽)."""
        if self.offline or not (self.pick and self.pick.get("answered")) or self.state.data.get(PLATFORM_ANSWER) == self.platform:
            return False
        self.state.data[PLATFORM_ANSWER] = self.platform
        return True

    @property
    def platform_label(self) -> str:
        """리포트·질문 라벨 ("Android")."""
        return self.platform_spec.label

    def answer(self, kind: str):
        return self.state.answers.get(kind)

    def jira_tool(self, name: str) -> str | None:
        return userconfig.get(self.cfg, f"tracker.tools.{name}") or None

    # Step 0 ---------------------------------------------------------------------------------------

    def preflight_args(self) -> None:
        a = self.args
        if getattr(a, "clock_offset", None) is not None:
            self.clock_offset = stepanchor.parse_offset(a.clock_offset)
            if self.clock_offset is None:
                raise Fail(USAGE, f"--clock-offset 형식이 맞지 않는다: {a.clock_offset!s:.40} "
                                  "(예: +3m, -90s, +1h2m3s, +00:03:00, 180 — 하루(86400초) 이내)")
        for flag in ("look_at", "look_note"):     # 원문은 메시지에 싣지 않는다
            if len(getattr(a, flag, None) or "") > lookat.TEXT_MAX:
                raise Fail(USAGE, f"--{flag.replace('_', '-')}는 {lookat.TEXT_MAX}자 이하로 준다")
        if self.analysis_only and (a.dry_run or self.offline):
            raise Fail(USAGE, "--analysis-only는 " + ("--dry-run" if a.dry_run else "--offline-db")
                       + "과 함께 쓰지 않는다(분석 전용은 이슈 DB에 기록하지 않는 실행이다).")
        if self.offline and getattr(a, "more_logs", None):
            raise Fail(USAGE, "--more-logs는 --offline-db와 함께 쓰지 않는다(이전 분석의 로그 이력이 없다) — --logs에 모두 준다.")
        if self.offline:
            if not a.out:
                raise Fail(USAGE, "--offline-db에는 --out <dir>이 필요하다.")
            if not (a.issue_meta or a.issue_file):
                raise Fail(USAGE, "--offline-db에는 --issue-meta 또는 --issue-file이 필요하다.")
            return
        if a.issue_meta:
            raise Fail(USAGE, "--issue-meta는 --offline-db(오프라인 평가)에서만 쓴다.")
        if a.issue_file and not (a.dry_run or self.analysis_only):
            raise Fail(USAGE, "--issue-file은 --dry-run 또는 --analysis-only와 함께만 받는다(실제 PR은 Jira MCP 값으로만 만든다).")
        if userconfig.load_user() is None:
            raise Fail(USAGE, "사용자 config가 없다. /telephony-triage:setup을 먼저 실행한다.")
        if not (a.issue_raw or a.issue_file) and not self.jira_tool("get_issue"):
            raise Fail(USAGE, "tracker.tools.get_issue 매핑이 비어 있다. 도구 이름을 추측하지 말고 /telephony-triage:setup의 "
                              "Jira 도구 매핑을 확인한다(연습은 --dry-run --issue-file <yaml>).")

    def check_key(self) -> None:
        if self.offline:
            db = Path(self.args.offline_db)
        else:
            wd = Path(str(userconfig.get(self.cfg, "work_dir"))).expanduser()
            db = wd / SNAPSHOT_DIR if (wd / SNAPSHOT_DIR / "issue-db.config.yaml").is_file() else \
                Path(str(userconfig.get(self.cfg, "issue_db.path") or "")).expanduser()
        code, data, _ = self.run.call("0-key", "jira_fields.py", ["check-key", self.key, "--db", db], expect=(0, 1))
        if code == 1:
            raise Fail(CHECK_FAILED, f"Jira 키 {self.key}가 형식({(data or {}).get('regex')})에 맞지 않는다. 키를 다시 묻는다.")
        # 작업 디렉토리·lock·브랜치·피드백 파일은 check-key가 낸 작업 키(트래커 parse_key 정규화)로 만든다(jira는 입력 그대로)
        key = (data or {}).get("key")
        if not isinstance(key, str) or not key:
            raise Fail(CHECK_FAILED, f"check-key가 작업 키를 내지 않았다({self.key}).")
        self.key = self.out["key"] = key

    def open_job(self) -> None:
        if self.offline:
            self.snap = Path(self.args.offline_db).resolve()
            self.job = Path(self.args.out).resolve()
            self.job.mkdir(parents=True, exist_ok=True)
        else:
            wd = Path(str(userconfig.get(self.cfg, "work_dir"))).expanduser()
            self.snap = wd / SNAPSHOT_DIR
            self.job = userconfig.ensure_private_dir(wd / self.key)
        self.run.open_trace(self.job / "trace.jsonl")
        if self.pick:
            self.run.note("platform", platform=self.platform, source=self.pick["source"])
        self.state = State(None if self.offline else self.job / STATE_FILE)
        if self.offline:   # 오프라인 DB는 스냅샷·config check를 거치지 않으므로 여기서 플랫폼 선언을 대조한다
            mismatch = compat.check_platform(compat.load_db_config(self.snap), self.platform)
            if mismatch:
                raise Fail(USAGE, mismatch[0]["message"])
        else:      # 다시 실행할 때 플랫폼이 다르면 이어 가지 않는다(작업 디렉토리는 플랫폼 work_dir에 있지만 상태로도 막는다)
            recorded = self.state.data.get("platform")
            if recorded and recorded != self.platform:
                raise Fail(USAGE, f"이 작업은 {recorded} 플랫폼이다 — --platform {recorded}로 다시 실행한다")
            if self.platform != userconfig.TOP_PROFILE and recorded != self.platform:
                self.state.data["platform"] = self.platform
            self.mark_platform_answer()    # lock 질문에서 멈춰도 `pending`과 함께 저장된다(lock을 새로 잡으면 아래 lock()이 다시 남긴다)
        self.given: dict[str, str] = {}
        for item in self.args.answer or []:
            kind, sep, value = item.partition("=")
            if not sep or not kind:
                raise Fail(USAGE, f"--answer는 <kind>=<값> 형식이다: {item}")
            self.given[kind.strip()] = value.strip()
        self.state.answers.update(self.given)

    def lock(self) -> None:
        owner = self.state.data.get("owner")
        if owner:
            _, data, _ = self.run.call("0-lock", "db_pr.py", ["lock", "status"])
            held = (data or {}).get("lock") or {}
            if held.get("job") == self.key and held.get("owner") == owner:
                self.run.env["TT_LOCK_OWNER"] = owner
                self.locked = True
                self.clear_pending()
                return
        choice = self.answer("lock")
        if choice == "stop":
            if self.state.path is not None and self.state.path.is_file() and self.state.data.pop("pending", None) is not None:
                self.state.save()     # 답한 lock 질문이 job_status에 남지 않게 한다
            raise Stopped("사용자가 lock 대기 대신 중단을 골랐다.")
        if choice == "release-other":
            _, data, _ = self.run.call("0-lock", "db_pr.py", ["lock", "status"])
            other = ((data or {}).get("lock") or {}).get("job")
            if other and other != self.key:
                self.run.call("0-lock", "db_pr.py", ["lock", "release", other, "--force"])
        argv = ["lock", "acquire", self.key, "--command", "analyze"]
        if choice == "take-over":
            argv.append("--take-over")
        code, data, err = self.run.call("0-lock", "db_pr.py", argv, expect=(0, 2))
        if code == 2:
            holder = (data or {}).get("holder")
            if not holder:
                raise Fail(USAGE, err.strip())
            age = holder.get("age_sec")
            if holder.get("job") != self.key:
                raise NeedsInput("lock", f"다른 작업 {holder.get('job')}({holder.get('command')}, {age}초 전 갱신)이 세션 lock을 "
                                         "갖고 있다. 그 세션이 끝났는가?",
                                 [{"value": "release-other", "label": "끝났다 — 강제로 풀고 진행"},
                                  {"value": "stop", "label": "아니다 — 중단"}])
            raise NeedsInput("lock", f"같은 이슈의 lock이 {age}초 전에 갱신됐다. 다른 세션이 진행 중일 수 있다. 이어받을까?",
                             [{"value": "take-over", "label": "이어받는다"}, {"value": "stop", "label": "중단"}])
        owner = data["lock"]["owner"]
        self.state.reset(owner)   # 새 세션: 이전 세션의 답·진행 상태(`pending` 포함)는 쓰지 않는다
        self.state.answers.update({k: v for k, v in self.given.items() if k != "lock"})
        self.run.env["TT_LOCK_OWNER"] = owner
        self.locked = True
        self.state.save()

    def check_carried(self) -> None:
        """분석 전용 뒤 새 세션이 이어받은 답(`State.reset`)은 로그·Jira 추출·설정 해시가 같을 때만 쓴다. 다르면 버리고 다시 묻는다."""
        carried = self.state.data.get("carried")
        if not isinstance(carried, dict):
            return
        keys = [k for k in carried.get("keys") or [] if k in self.state.answers and k not in self.given]
        if all(carried.get(k) == v for k, v in self.fingerprint().items()):
            if keys:     # 표시는 ok로 끝날 때까지 남긴다(그 사이 다른 질문에서 멈춰도 다음 실행이 다시 알린다, `save_job`이 지운다)
                self.notes.append(f"분석 전용 실행에서 받은 답({', '.join(keys)})을 이어 썼다 — 바꾸려면 --answer <kind>=<값>")
            return
        for k in keys:
            self.state.answers.pop(k, None)
        self.state.data.pop("carried", None)
        self.state.save()

    def clear_pending(self) -> None:
        """lock을 잡은 뒤 이전 실행의 질문 표시(needs_input `pending`)를 지운다(lock 질문은 lock을 못 잡으면 남는다)."""
        if self.state.data.pop("pending", None) is not None:
            self.state.save()

    def cleanup(self) -> None:
        """잔여 worktree·도구 브랜치는 묻지도 지우지도 않는다. 목록만 보고 notes로 알린다(정리는 `/telephony-triage:sync`)."""
        if not self.state.data.get("cleanup_done"):
            _, data, _ = self.run.call("0-cleanup", "db_pr.py", ["cleanup", "--dry-run"])
            targets = (data or {}).get("targets") or []
            if targets:
                self.state.data["cleanup_targets"] = len(targets)
            self.state.data["cleanup_done"] = True
            self.state.save()
        count = self.state.data.get("cleanup_targets")
        if count:
            self.notes.append(f"잔여 worktree·도구 브랜치 {count}개(붙여넣은 스텝 원문이 남아 있을 수 있음) — "
                              "`/telephony-triage:sync`에서 정리")

    def existing_plan(self) -> None:
        plan_path = self.job / "plan.json"
        info = {"exists": plan_path.is_file()}
        if info["exists"]:
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                plan = {}
            source = plan.get("source")
            choice = self.answer("plan")
            options = [{"value": "new", "label": "새로 시작(기존 계획 덮어씀)"}]
            if source == "analyze":
                options.insert(0, {"value": "resume", "label": "이어서"})
            if choice not in [o["value"] for o in options]:
                raise NeedsInput("plan", f"이 Jira의 작업 계획이 이미 있다(source: {source}). 어떻게 할까?", options,
                                 pr_number=(plan.get("pr") or {}).get("number"))
            info.update(source=source, choice=choice, pr_number=(plan.get("pr") or {}).get("number"),
                        issue_origin=(plan.get("issue") or {}).get("origin"))
            if choice == "resume":      # 이어서: 분류를 다시 묻지 않는다 (07-workflow, eval 11)
                info["next"] = "리포트를 보인 뒤 Step 7(분류 질문·계획 작성) 없이 기존 JOB/plan.json으로 Step 8 진행"
            if not self.state.data.get("pending_cleared"):
                pending = userconfig.pending_feedback_dir(self.cfg)
                removed = [p.name for p in pending.glob(f"{self.key}-*.yaml")] if pending.is_dir() else []
                for name in removed:
                    (pending / name).unlink(missing_ok=True)
                info["pending_removed"] = len(removed)
                self.state.data["pending_cleared"] = True
                self.state.save()
        pending = userconfig.pending_feedback_dir(self.cfg)
        others = [p for p in pending.glob("*.yaml") if not p.name.startswith(f"{self.key}-")] if pending.is_dir() else []
        if others:
            self.notes.append(f"다른 Jira의 pending 피드백 {len(others)}건이 이번 PR에 함께 올라간다")
        self.out["plan"] = info

    def plan_info(self) -> None:
        """분석 전용: 기존 계획이 있는지만 알린다. 묻지 않고, 계획·pending 피드백은 건드리지 않는다."""
        plan_path = self.job / "plan.json"
        info = {"exists": plan_path.is_file()}
        if info["exists"]:
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                plan = {}
            info.update(source=plan.get("source"), pr_number=(plan.get("pr") or {}).get("number"))
        self.out["plan"] = info

    # Step 1 ---------------------------------------------------------------------------------------

    def snapshot(self) -> None:
        snap = self.state.data.get("snapshot")
        if not snap or self.args.refresh or not (self.snap / "issue-db.config.yaml").is_file():
            _, data, _ = self.run.call("1-snapshot", "db_pr.py", ["snapshot", "--job", self.key])
            lint = data.get("post_lint") or {}
            snap = {"sha": data.get("snapshot_sha"), "pulled": data.get("pulled"),
                    "pull_skipped_reason": data.get("pull_skipped_reason"),
                    "post_lint": {"errors": lint.get("errors"), "warnings": lint.get("warnings"),
                                  "findings": [f"{f.get('code')}: {f.get('file')}" for f in
                                               (lint.get("findings") or [])[:3]]}}
            self.state.data["snapshot"] = snap
            self.state.save()
        self.out["snapshot"] = snap

    def compat(self) -> None:
        for_ = "dry-run" if self.args.dry_run or self.analysis_only else "write"
        code, data, err = self.run.call("1-check", "config.py", ["check", "--db", self.snap, "--for", for_],
                                        expect=(0, 2))
        if code == 2 and not isinstance(data, dict):
            raise Fail(USAGE, err.strip())
        mismatch = [r for r in data.get("reasons") or [] if r.get("code") == compat.PLATFORM_MISMATCH]
        if mismatch:      # 다른 플랫폼 이슈 DB: 읽기 전용으로도 계속하지 않는다(K5)
            raise Fail(USAGE, str(mismatch[0].get("message")))
        unsupported = [r for r in data.get("reasons") or [] if r.get("code") == compat.FEATURE_UNSUPPORTED]
        if unsupported:   # 모르는 시그니처 feature: 분석 중단(읽기 전용으로 계속하지 않는다)
            raise Fail(USAGE, f"{compat.FEATURE_UNSUPPORTED}: {unsupported[0].get('message')}")
        ok = data["push_allowed"] if for_ == "write" else data["writable"]
        self.out["mode"] = "analysis-only" if self.analysis_only else "write" if ok else "read-only"
        if not ok and not self.analysis_only:
            self.out["read_only_reasons"] = [r.get("code") for r in data.get("reasons") or []]
            hint = "; ".join(str(r["message"]) for r in data.get("reasons") or [] if r.get("message"))
            if hint:
                self.out["read_only_hint"] = _clip(hint, 200)
        backend = [r for r in data.get("reasons") or [] if r.get("code") == "parser-backend-mismatch"]
        if backend:
            self.warnings.append("백엔드 불일치 — 결과가 팀 기준과 다를 수 있음")

    # Step 2 ---------------------------------------------------------------------------------------

    def jira(self) -> dict:
        a = self.args
        meta_path = self.job / "issue_meta.json"
        if self.offline and a.issue_meta:
            meta = json.loads(Path(a.issue_meta).read_text(encoding="utf-8"))
            self.issue_sha = hashlib.sha256(Path(a.issue_meta).read_bytes()).hexdigest()
            masker = self.masker()
            auto = None
            if meta.get("failed_step"):
                auto = {"text": failedstep.normalize(masker(str(meta["failed_step"]))), "source": "field"}
            self.failed_step = self.resolve_failed_step(auto, masker)
            if self.failed_step:
                meta["failed_step"] = self.failed_step["text"]
            else:
                meta.pop("failed_step", None)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
            info = {"key": self.key, "origin": "file", "occurred_at": meta.get("occurred_at"), "sw": meta.get("sw"),
                    "summary": meta.get("summary") or "", "missing": [], "logcat": {},
                    "sim_slot": None if meta.get("sim_slot") in (None, "") else str(meta["sim_slot"])}
            self.out["issue"] = {k: info[k] for k in ("origin", "occurred_at", "sw", "sim_slot")}
            self.out_failed_step()
            return info
        raw_default = self.job / "issue_raw.json"
        if not (a.issue_raw or a.issue_file or raw_default.is_file()):
            self.adopt_raw(raw_default)
        reuse = self.state.data.get("issue_done") and (self.job / "issue.json").is_file()
        if reuse and not (a.dry_run or self.analysis_only or a.issue_raw or a.issue_file):
            try:     # --issue-file 추출(연습·분석 전용)은 쓰기 실행에 이어 쓰지 않는다 — 실제 PR은 Jira MCP 값으로만
                reuse = json.loads((self.job / "issue.json").read_text(encoding="utf-8")).get("origin") != "file"
            except (OSError, json.JSONDecodeError, AttributeError):
                reuse = False
        if a.issue_raw and not Path(a.issue_raw).is_file() and reuse:
            source, origin = None, None    # 첫 실행이 --consume으로 지웠다
        elif a.issue_raw or a.issue_file:
            source, origin = Path(a.issue_raw or a.issue_file), "mcp" if a.issue_raw else "file"
        elif raw_default.is_file():
            source, origin = raw_default, "mcp"
        elif reuse:
            source, origin = None, None
        else:
            # 읽기 도구 인자 안내는 트래커가 정할 때만 더한다(jira는 None — 출력 불변)
            adapter = trackers.of(self.cfg)
            read = adapter.read_args("get_issue", self.key)
            extra = {} if read is None else {"tool_args": read,
                                             "comments_args": adapter.read_args("get_comments", self.key)}
            raise NeedsInput("issue", "Jira MCP로 이슈를 읽는다. 응답은 hook이 JOB/issue_raw.json에 저장하고 마스킹 요약만 보여준다. "
                                     "읽은 뒤 같은 명령을 다시 실행한다.", [],
                             tool=self.jira_tool("get_issue"), comments_tool=self.jira_tool("get_comments"),
                             save_to=str(raw_default), **extra)
        if source is not None:     # 문제 파악(problem.json source_sha256)과 같은 입력인지 대조할 해시 — --consume이 지우기 전에
            self.issue_sha = self.state.data["issue_sha256"] = hashlib.sha256(Path(source).read_bytes()).hexdigest()
            argv = ["extract", source, "--origin", origin, "--db", self.snap, "--meta-out", meta_path]
            if origin == "mcp":
                argv.append("--consume")   # 원문을 work_dir에 남기지 않는다 (08-safety.md §8.1)
            _, data, _ = self.run.call("2-jira", "jira_fields.py", argv)
            (self.job / "issue.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                                                 encoding="utf-8", newline="\n")
            self.state.data["issue_done"] = True
            self.state.save()
        else:
            self.issue_sha = self.state.data.get("issue_sha256")
        data = json.loads((self.job / "issue.json").read_text(encoding="utf-8"))
        if data.get("key") and data["key"] != self.key:
            raise Fail(USAGE, f"Jira 응답의 키({data['key']})가 {self.key}와 다르다.")
        self.apply_failed_step(data, meta_path)
        text = data.get("text") or {}
        # Jira 발생 시각 칸은 로그와 다른 시계(장비·PC)의 값이다 — 분석 구간·근접 중심·기준 줄 고르기에 쓰지 않고 표시만 한다(D4).
        # 분석 기준 시각은 사용자가 준 시각(`--answer time=`)·TC 파일·기준 줄·단서뿐(`AnchorMixin.given_time`)
        self.jira_time_unused = bool(data.get("occurred_at"))
        if meta_path.is_file():     # 이전 판 extract가 메타에 넣은 Jira 시각(매처 근접 중심)도 뺀다 — 준 시각은 write_meta가 다시 쓴다
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.pop("occurred_at", None) is not None:
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        info = {"key": self.key, "origin": data.get("origin"), "occurred_at": None,
                "sw": (data.get("issue") or {}).get("sw"), "platform_version": (data.get("issue") or {}).get("platform_version") or data.get("platform_version_all"),
                "sim_slot": data.get("sim_slot"), "summary": text.get("summary") or "", "missing": data.get("missing") or [],
                "logcat": data.get("logcat") or {}, "jira_block": data.get("issue") or {}}
        self.out["issue"] = {"origin": info["origin"], "occurred_at": data.get("occurred_at"), "sw": info["sw"],
                             "platform_version": info["platform_version"], "sim_slot": info["sim_slot"],
                             "summary": _clip(info["summary"], 160),
                             "description": _clip(text.get("description"), 240),
                             # 제출자 참고 글 — 모델이 판단 근거로 읽지 않게 값에 표시를 붙인다(SKILL.md는 바이트 한도라 설명 줄을 못 더함)
                             **({"submitter_note": NOTE_LABEL + _clip(text["note"], NOTE_MAX)} if text.get("note") else {}),
                             "comments": len(text.get("comments") or []), "missing": info["missing"]}
        self.out_failed_step()
        return info

    def adopt_raw(self, dest: Path) -> None:
        """hook은 `--platform`을 몰라 Jira 원문을 암묵 선택 플랫폼 work_dir에 둔다. 이 작업 플랫폼이 다르면 그 원문을 이 JOB으로 옮기고
        (이어 `--consume` 추출이 지운다) 빈 작업 디렉토리는 지운다(17-platforms §11-4). 키 대조는 추출 뒤 기존 검사."""
        if self.picked is None or self.picked == self.platform:
            return
        other = Path(str(userconfig.get(userconfig.merged(self.defaults, platform=self.picked), "work_dir"))).expanduser() / self.key
        src = other / "issue_raw.json"
        if not src.is_file():
            return
        try:
            os.replace(src, dest)
        except OSError:          # 다른 파일 시스템
            try:
                shutil.move(str(src), str(dest))
            except OSError as exc:      # lock은 main이 푼다. 원문 내용은 내지 않는다(경로만)
                if src.exists():
                    dest.unlink(missing_ok=True)    # 반쯤 복사된 파일을 원문으로 쓰지 않게
                raise Fail(USAGE, f"Jira 원문을 옮기지 못했다: {src} → {dest} ({exc.strerror or type(exc).__name__}) — "
                                  "권한·디스크를 확인하고 다시 실행한다") from exc
        try:
            other.rmdir()
        except OSError:
            pass                 # 다른 파일이 있으면 그대로 둔다
        self.run.note("platform-raw", moved_from=self.picked)

    # 실패 스텝(선택, 보조 정보) ----------------------------------------------------------------------

    def masker(self, log_lines: bool = False):
        try:
            return masking.for_db(compat.load_db_config(self.snap), log_lines=log_lines)
        except Exception:    # noqa: BLE001 — 호환성 문제(`mask:` 형식 등)는 compat 단계가 보고한다
            return masking.for_db({}, log_lines=log_lines)

    def existing_record(self) -> None:
        _, data, _ = self.run.call("2-existing", "db_search.py", [self.key, "--db", self.snap, "--limit", SEARCH_LIMIT])
        record = next((r for r in (data or {}).get("results") or [] if r.get("kind") == "issue"), None)
        if record:
            self.out["existing"] = {"cause": record.get("cause"), "type": record.get("type"), "date": record.get("date")}
            if self.analysis_only:
                return      # 기록하지 않는 실행: 기존 분류만 알리고 재분석 여부는 묻지 않는다
            choice = self.answer("reanalyze")
            if choice is None:
                raise NeedsInput("reanalyze", f"이 Jira는 이미 {record.get('cause')}(으)로 분류돼 있다. 재분석할까?",
                                 [{"value": "yes", "label": "재분석(재분류면 Step 7 reclassify)"},
                                  {"value": "no", "label": "그만둔다"}])
            if choice == "no":
                raise Stopped("이미 분류된 Jira — 재분석하지 않기로 했다.")

    def open_prs(self) -> None:
        cached = self.state.data.get("preflight")
        if cached is None:   # 같은 세션의 재실행은 다시 fetch하지 않는다
            _, data, _ = self.run.call("2-preflight", "db_pr.py", ["preflight", "--branch", f"issue/{self.key}",
                                                                  "--search", self.key, "--issue", self.key])
            cached = {"prs": [{"number": p.get("number"), "url": p.get("url")}
                              for p in (data or {}).get("open_prs") or []],
                      "warnings": [_clip(w, 160) for w in (data or {}).get("warnings") or []]}
            self.state.data["preflight"] = cached
            self.state.save()
        prs = cached["prs"]
        self.out["open_prs"] = prs
        self.warnings += cached["warnings"]
        if prs and self.answer("open_pr") is None:
            raise NeedsInput("open_pr", f"이 Jira의 열린 PR이 {len(prs)}개 있다. 계속할까?",
                             [{"value": "continue", "label": "계속"}, {"value": "stop", "label": "중단"}], prs=prs)
        if self.answer("open_pr") == "stop":
            raise Stopped("열린 PR이 있어 중단했다.")

    # Step 2-1 / 3 -----------------------------------------------------------------------------------

    def check_more_logs(self) -> None:
        """`--more-logs`는 이전 분석의 로그가 있어야 한다(없으면 종료 코드 2). lock 직후에 해서 Jira 읽기 전에 알린다."""
        if getattr(self.args, "more_logs", None) and not (self.state.job.get("logs") or []):
            raise Fail(USAGE, "이전 분석 로그가 없다 — --logs로 시작한다")

    def combine_more_logs(self) -> list[str]:
        """이전 로그(`job.logs`) 뒤에 `--more-logs`를 붙인 경로 목록. 순서를 지켜 기존 `f<순번>`이 유지된다(D7).
        이미 있는 경로는 조용히, 내용(sha256)이 같은 다른 경로는 경고하고 건너뛴다."""
        known = [dict(f) for f in self.state.job.get("logs") or []]
        paths = [f["path"] for f in known]
        shas = {f.get("sha"): f for f in known}
        for raw in self.args.more_logs:
            p = Path(raw).expanduser().resolve()
            if not p.is_file():
                raise Fail(USAGE, f"로그 파일이 없습니다: {p}")
            if str(p) in paths:
                continue
            sha = _file_sha(p)
            if sha in shas:
                self.warn(f"more-logs-duplicate: {p.name}은(는) 이미 있는 {shas[sha].get('name')}와 내용이 같아 건너뛰었다")
                continue
            paths.append(str(p))
            shas[sha] = {"name": p.name}
        return paths

    def logs(self) -> list[Path]:
        if getattr(self.args, "more_logs", None):
            paths = self.combine_more_logs()
        else:
            paths = self.args.logs or self.state.data.get("logs")
        if not paths:
            log_dir = userconfig.get(self.cfg, "log_dir")
            found = []
            if log_dir and Path(str(log_dir)).expanduser().is_dir():
                files = [p for p in Path(str(log_dir)).expanduser().iterdir() if p.is_file()]
                found = [str(p) for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:10]]
            raise NeedsInput("logs", "분석할 logcat/bugreport 경로가 없다. 고르거나 입력받아 --logs로 다시 실행한다.",
                             [{"value": f, "label": Path(f).name} for f in found])
        resolved = [Path(p).expanduser().resolve() for p in paths]
        for p in resolved:
            if not p.is_file():
                raise Fail(USAGE, f"로그 파일이 없습니다: {p}")
        if not self.offline:
            self.state.data["logs"] = [str(p) for p in resolved]
            self.state.save()
            self.log_inputs = [{"path": str(p), "name": p.name, "sha": _file_sha(p), "size": p.stat().st_size}
                               for p in resolved]
        capture = self.platform_spec.capture
        out, build = [], {}
        for p in resolved:
            if capture is None or not capture.looks_like(p):
                out.append(p)
                continue
            # 같은 이름(a/bugreport.txt, b/bugreport.txt)이 서로 덮지 않도록 해석된 경로 해시를 붙인다
            # ponytail: 경로 해시 8자, 충돌은 이론상 가능하나 한 작업의 입력 수가 작아 무시. 늘면 16자
            dest = self.job / "logs" / f"{re.sub(r'[^A-Za-z0-9._-]', '_', p.stem)}-{_digest(str(p))[:8]}"
            _, data, _ = self.run.call("3-bugreport", "parse_logcat.py", ["extract-bugreport", p, "--out", dest])
            out += [Path(f["path"]) for f in (data or {}).get("files") or []]
            build = {k: v for k, v in ((data or {}).get("build") or {}).items() if v} or build
        if build:
            self.out["build"] = {k: _clip(v, 120) for k, v in build.items() if isinstance(v, str)}
        if not out:
            raise Fail(USAGE, "bugreport에서 logcat 섹션을 찾지 못했다.")
        return self.mask_copy(out)

    def mask_copy(self, logs: list[Path]) -> list[Path]:
        """원문을 받자마자 `<JOB>/logs-masked/`에 마스킹 사본(줄 번호 그대로)을 만든다(종합 리뷰 G① 축소판): 모델이 grep·sed·Read할 대상은
        이쪽이다(guard 규칙 10 문구·rules.md). 상한보다 큰 파일은 스크립트가 건너뛰고 경고한다(`mask-copy-skipped` → warnings).

        돌려주는 것은 **파싱 대상**: 사본이 있으면 사본, 건너뛴 파일만 원문(같은 순서 — `line_ref.file_index` 불변). 파서가 사본을
        읽어야 events·timeline·근거 원문의 토큰 번호가 모델이 보는 사본과 같다(코덱스 리뷰 R1: 시간 창 안 이벤트만 가리면 창 밖에서
        먼저 나온 값의 번호가 밀려 같은 값이 `<IMSI#1>`/`<IMSI#2>`로 갈렸다). `--mask`는 그대로 둔다(사본의 토큰은 보호되고 남은 것만
        가린다). 건너뛴 파일이 섞이면 그 파일의 값은 사본과 번호가 다를 수 있어 경고한다."""
        dest = self.job / MASKED_DIR
        _, data, _ = self.run.call("3-mask", "parse_logcat.py",
                                   ["mask-copy", *logs, "--out", dest, "--rules", self.snap / "parser-rules"])
        files = (data or {}).get("files") or []
        for w in (data or {}).get("warnings") or []:
            if w.get("code") == "mask-copy-nul":
                self.warn(f"mask-copy-nul: {w.get('message')}")
        targets, copies = list(logs), {}
        for f in files:
            if f.get("skipped"):
                self.warn(f"mask-copy-skipped: {f.get('name')} {f.get('reason', '')} — 원문은 grep -n·sed -n 구간으로만")
            elif f.get("path") and f.get("source"):
                copies[str(f["source"])] = Path(f["path"])
        if copies:
            targets = [copies.get(str(p), p) for p in logs]
            if any(f.get("skipped") for f in files):
                self.warn("mask-copy-mixed: 사본 없는 파일이 섞여 그 파일 값의 토큰 번호는 사본과 다를 수 있다")
        self.masked = {"dir": MASKED_DIR, "files": [f["name"] for f in files if not f.get("skipped")],   # JOB 상대(출력 결정성)
                       "skipped": [f["name"] for f in files if f.get("skipped")]}
        return targets

    def auto_select(self) -> bool:
        """`code.auto_select`: 사용자 config > site-defaults > 기본 true (02-config.md). 유효 값은 불리언뿐이고(`type(v) is bool`),
        그 밖(문자열·0/1·null)은 `explore.when`처럼 warnings에 남기고 묻는 쪽(false)으로 본다."""
        # site-defaults를 직접 본다: from_site_defaults는 code 키를 옮기지 않는다(setup도 code를 사용자 config에 쓰지 않는다)
        value = True
        for source in (userconfig.load_user() or {}, self.defaults):
            node = source.get("code")
            if isinstance(node, dict) and "auto_select" in node:
                value = node["auto_select"]
                break
        if type(value) is not bool:
            self.warnings.append(f"code.auto_select 값이 잘못됐다({value}). 묻기로 본다")
            self.auto_invalid = True     # needs_input 출력에는 warnings가 없으므로 질문 문구로도 알린다
            return False
        return value

    def code_suggest(self, version: str | None) -> dict:
        argv = ["suggest"] + (["--version", version] if version else [])
        _, data, _ = self.run.call("2-1-code", "code_roots.py", argv)
        return data or {}

    def code_question(self, version: str | None, suggested: dict, text: str | None = None) -> NeedsInput:
        primary = self.platform_spec.primary_root
        cands = suggested.get("candidates") or []

        def head(c: dict) -> str:
            return f"{c.get('name') or '최근'} {self.platform_label} {c.get('platform_version') or '?'}"

        def where(c: dict) -> str:     # 주 루트 경로(자르지 않는다)
            path = (c.get("roots") or {}).get(primary)
            return f" — {path}" if path else ""

        options = [{"value": c.get("name") or ",".join(f"{k}={v}" for k, v in (c.get("roots") or {}).items()),
                    "label": head(c) + where(c) + (" (추천)" if c.get("recommended") else "")}
                   for c in cands]
        # 질문당 선택지 4개(AskUserQuestion 상한): 후보 둘(추천이 첫째) + 직접 입력 + 건너뛰기, 나머지 후보는 문구에
        options, rest = options[:2], options[2:]
        options += [{"value": "<경로 또는 키=경로,…>", "label": "직접 입력"},
                    {"value": "skip", "label": "코드 분석 건너뛰기(로그 기반 분석만)"}]
        text = text or f"코드 경로를 고른다 (대상: {self.platform_label} {version or '?'})."
        if rest:    # 이름 없는 최근 경로는 직접 입력에 그대로 적을 수 있게 경로 값(모든 루트)을 함께
            names = [head(c) + (where(c) if c.get("name") else f" {o['value']}") for o, c in zip(rest, cands[2:])]
            text += f" (그 밖 후보: {', '.join(names)} — 직접 입력에 이름이나 경로를 적는다)"
        return NeedsInput("code", text + (" (code.auto_select 값이 잘못돼 묻기로 본다)" if self.auto_invalid else ""), options)

    @staticmethod
    def code_auto_profile(suggested: dict) -> str | None:
        """버전이 일치하는 프로필이 정확히 1개일 때만 그 이름(최근 사용 경로는 세지 않는다)."""
        hits = [c.get("name") for c in suggested.get("candidates") or [] if c.get("kind") == "profile" and c.get("match")]
        return hits[0] if len(hits) == 1 else None

    def code(self, version: str | None) -> dict | None:
        if self.offline:
            return None
        choice = self.args.code or self.answer("code")
        auto = False
        suggested: dict | None = None
        auto_on = self.auto_select()      # 답이 있어도 점검해 잘못된 값의 경고가 ok 출력에 남게 한다
        if choice is None and version and auto_on:     # Jira 버전이 없으면 자동 선택하지 않는다
            choice = self.state.data.get("code_auto")             # 이전 실행이 자동 선택한 프로필
            if choice is None:
                suggested = self.code_suggest(version)
                choice = self.code_auto_profile(suggested)
            auto = choice is not None
        if choice is None:
            raise self.code_question(version, suggested if suggested is not None else self.code_suggest(version))
        if choice == "skip":
            return {"skipped": True}
        argv = ["validate", choice, "--db", self.snap] + (["--version", version] if version else [])
        code, data, _ = self.run.call("2-1-code", "code_roots.py", argv, expect=(0, 2))
        if code == 2 or not (data or {}).get("valid"):
            self.state.answers.pop("code", None)
            if auto:
                self.state.data.pop("code_auto", None)
            self.state.save()
            reason = "코드 경로가 유효하지 않다: " + "; ".join((data or {}).get("errors") or ["?"])
            if auto:     # 자동 선택이 틀렸으면 전체 선택지로 다시 묻는다(자동 선택 결과는 기록하지 않는다)
                raise self.code_question(version, self.code_suggest(version), reason)
            raise NeedsInput("code", reason, [{"value": "skip", "label": "코드 분석 건너뛰기"}])
        if auto and not self.state.data.get("code_auto"):
            self.state.data["code_auto"] = choice
            self.state.save()
        mismatch = [w for w in data.get("warnings") or [] if "다르다" in w]
        if mismatch and self.answer("code_confirm") is None:
            raise NeedsInput("code_confirm", mismatch[0], [{"value": "yes", "label": "이 트리로 계속"},
                                                           {"value": "skip", "label": "코드 분석 건너뛰기"}])
        if self.answer("code_confirm") == "skip":
            return {"skipped": True}
        # 경로는 notes(출력 JSON·analysis.json — report.md·Jira 코멘트·이슈 DB로 가지 않는다)에만 보인다.
        # must_show는 Jira 코멘트로 가므로(issue_post) 자동 선택 must_show 줄에는 경로를 넣지 않는다
        path = ((data or {}).get("roots") or {}).get(self.platform_spec.primary_root)
        if auto and path:
            self.notes.append(f"코드 분석 트리 자동 선택 경로: {choice} — {path}")
        profiles = {p.get("name") for p in self.cfg.get("code_profiles") or []}
        if choice not in profiles and not self.state.data.get("code_remembered"):
            # 07 §Step 2-1 5번: 트리 추정 버전이 있을 때만 개인 프로필로 저장(Jira 버전으로 대신하지 않는다 — 문구 값·다른
            # 버전 트리가 굳지 않게). dry-run·분석 전용은 최근 경로만
            keep = None if self.args.dry_run or self.analysis_only else data.get("estimated_version")
            _, saved, _ = self.run.call("2-1-code", "code_roots.py",
                                        ["remember", choice] + (["--platform-version", str(keep)] if keep else []))
            if (saved or {}).get("saved"):
                self.state.data["code_saved"] = (f"{saved['profile']} ({self.platform_label} {saved['platform_version']}"
                                                  + (f", {path})" if path else ")"))
            self.state.data["code_remembered"] = True
            self.state.save()
        if self.state.data.get("code_saved"):     # 저장한 실행이 질문으로 멈췄어도 ok 출력까지 알린다
            self.notes.append(f"코드 경로를 프로필로 저장: {self.state.data['code_saved']} — 이름 변경·삭제는 config.py set code_profiles")
        self.code_auto = choice if auto else None
        return {"skipped": False, "roots": choice, "tree_version": data.get("estimated_version"),
                "warnings": data.get("warnings") or []}

    def parse(self, logs: list[Path], around: str | None, tz: str | None, year: int | None, out: Path | None,
              between: tuple[str, str] | None = None, step: str = "3-parse") -> dict:
        argv = ["parse", *logs]
        if between:
            argv += ["--between", between[0], between[1]]
        else:
            argv += ["--around", around] if around else ["--full"]
        if around and not between and self.args.minutes:
            argv += ["--minutes", self.args.minutes]
        argv += ["--rules", self.snap / "parser-rules", "--mask"]
        if tz:
            argv += ["--tz", tz]
        if year:
            argv += ["--year", year]
        _, data, _ = self.run.call(step, "parse_logcat.py", argv)
        if out is not None:
            out.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return data

    def outside_errors(self, info: dict, logs: list[Path], tz: str | None, year: int | None, anchor: dict | None,
                       cov: dict) -> dict | None:
        """앵커 구간 밖 입력한 발생 시각(`given_time` — Jira 칸 값 아님) 근처의 오류 이벤트(근거·점수에 쓰지 않는다, 리포트 안내용).
        그 시각이 분석 구간 밖이고 로그 범위 안일 때만 마스킹 파싱을 한 번 더 한다(파일은 쓰지 않는다)."""
        jira_at = self.given_time(info, tz, year)
        if not anchor or jira_at is None:
            return None
        start, end = _parse_ts(anchor["window"][0]), _parse_ts(anchor["window"][1])
        first, last = stepanchor._ts(cov.get("first_ts")), stepanchor._ts(cov.get("last_ts"))
        if start is None or end is None or (start <= jira_at <= end) or not (first and last and first <= jira_at <= last):
            return None
        at = lc.format_ts(jira_at)
        data = self.parse(logs, at, tz, year, None, step="3-parse-outside")
        errors = [self.error_row(e) for e in (data or {}).get("events") or []
                  if e.get("event") and ERROR_EVENT_RE.search(str(e["event"]))
                  and not ((t := _parse_ts(e.get("ts"))) and start <= t <= end)]    # 분석 범위 안의 이벤트는 이미 근거 후보다
        return {"at": at, "total": len(errors), "rows": errors[:3]}

    def match(self, events: Path, meta: Path | None, out: Path, regress: bool = False) -> dict:
        """매처를 돌려 `out`(match.json)에 쓴다. 분석 모드는 자격 검사 기준(`self.reference`)을 `JOB/reference.json`으로 넘기고,
        매처 출력의 `eligibility`(사건 전부)는 match.json에서 떼어 `JOB/eligibility.json`에 쓴다(돌려주는 값에는 남긴다)."""
        argv = ["--db", self.snap, "--events", events, "--top", 0 if regress else TOP]
        if meta is not None:
            argv += ["--issue-meta", meta]
        if not regress:     # 이전 실행의 자격 검사 기록이 이번 결과로 읽히지 않게(이번 매처가 다시 쓴다)
            (self.job / ELIGIBILITY_FILE).unlink(missing_ok=True)
            (self.job / REFERENCE_FILE).unlink(missing_ok=True)
        if regress:
            argv.append("--regress")
        elif self.reference or self.problem_use:     # {refs: 명시 기준 + 단서, problem, comment_adopt, dropped}(단계 5-2)
            use = self.problem_use or {}
            bundle = {"refs": ([self.reference] if self.reference else []) + use.get("refs", []),
                      "problem": use.get("problem"), "comment_adopt": use.get("comment_adopt", True),
                      "dropped": use.get("dropped", []), **({"conflict": True} if use.get("conflict") else {}),
                      **({"invalid": use["invalid"]} if use.get("invalid") else {})}
            ref = self.job / REFERENCE_FILE
            ref.write_text(json.dumps(bundle, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            argv += ["--reference", ref]
        _, data, _ = self.run.call("4-match" if not regress else "2-time", "match_signatures.py", argv)
        elig = data.pop("eligibility", None)
        out.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if elig is not None:
            (self.job / ELIGIBILITY_FILE).write_text(json.dumps(elig, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                                                     newline="\n")
            data["eligibility"] = elig
        return data

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    # Step 4·5 --------------------------------------------------------------------------------------

    def cause_entry(self, cause_id: str) -> dict:
        """원인 하나의 `db_search.py` 항목(없으면 {}). 같은 실행 안에서는 한 번만 부른다."""
        cache = self.__dict__.setdefault("_cause_entries", {})
        if cause_id not in cache:
            _, data, _ = self.run.call("4-db", "db_search.py", [cause_id, "--db", self.snap, "--limit", 1])
            cache[cause_id] = next((r for r in (data or {}).get("results") or [] if r.get("id") == cause_id), {})
        return cache[cause_id]

    def mark_not_a_bug(self, decision: dict) -> None:
        """기준 사건(ref)의 원인이 이슈 DB에서 버그 아님(`fix.status: not-a-bug` 또는 `resolution_type: user-setting` — 시험·설정 조작이
        만든 동작, 포털 `not_a_bug`와 같은 기준)이면 그 사건에 `not_a_bug: true`(판단 줄·포털이 "시험 조작으로 알려진 규칙"으로 보인다)."""
        for e in decision.get("events") or []:
            entry = self.cause_entry(e["cause"]) if e.get("ref") and e.get("cause") else {}
            if (entry.get("fix") or {}).get("status") == "not-a-bug" or entry.get("resolution_type") == "user-setting":
                e["not_a_bug"] = True

    def cause_info(self, cause_id: str) -> dict:
        entry = self.cause_entry(cause_id)
        fix = entry.get("fix") or {}
        return {"resolution": _clip(entry.get("resolution"), 120),
                "resolution_verification": entry.get("resolution_verification"),
                "fix_status": fix.get("status"), "issue_count": entry.get("issue_count"),
                "issue_recent": (entry.get("issues") or [])[:3], "code_refs": entry.get("code_refs") or []}

    def resolve_code(self, code: dict | None, version: str | None, candidates: list[dict]) -> dict:
        if not code or code.get("skipped"):
            return {"skipped": True}
        resolved, moved = [], []
        for cand in candidates:
            for ref in cand.pop("_code_refs", []):
                versions = [str(v) for v in ref.get("platform_versions") or []]
                if versions and version and str(version) not in versions and not (   # 숫자만인 목록은 글자 그대로(Android)
                        any(not v.isdigit() for v in versions) and flowlib.version_match(versions, version)):
                    continue
                code_rc, data, _ = self.run.call("5-resolve", "code_roots.py",
                                                 ["resolve", ref["ref"], "--roots", code["roots"]], expect=(0, 2))
                if code_rc == 0 and data.get("exists"):
                    resolved.append({"cause": cand["cause"], "ref": ref["ref"], "path": data["path"],
                                     "symbol": ref.get("symbol")})
                elif ref.get("symbol"):
                    _, found, _ = self.run.call("5-resolve", "code_roots.py",
                                                ["find-symbol", ref["symbol"], "--roots", code["roots"]])
                    hit = next(iter((found or {}).get("matches") or []), None)
                    moved.append({"cause": cand["cause"], "ref": ref["ref"], "symbol": ref["symbol"],
                                  "new_ref": hit.get("ref") if hit else None, "line": hit.get("line") if hit else None})
        return {"skipped": False, "roots": code["roots"], "tree_version": code.get("tree_version"),
                "resolved": resolved[:6], "moved": moved[:6]}

    # C′ 부분 일치·코드 대조 (04-parser-matching.md §5.12) — 표시 전용, 판정·점수 불변 -------------------------------

    def partial(self, match: dict, code: dict | None, events_path: Path, events_doc: dict) -> tuple[list, list]:
        """match.json `partial[]` → (analysis.json용 ≤ 3개, report.md 보조 정보 같은 순서). 코드 루트를 골랐고
        missing·absent가 있으면 `code_roots.py find-text`로 대조한다(코드 줄 글자는 받지도 쓰지도 않는다)."""
        items = (match.get("partial") or [])[:PARTIAL_ANALYSIS_MAX]
        out, extra = [], []
        for p in items:
            out.append({k: v for k, v in {
                "kind": p["kind"], "type": p["type"], "cause": p.get("cause"), "signature": p["signature"],
                "matched": p["matched"], "missing": [m["desc"] for m in p.get("missing") or []][:3],
                "blocked_by": p.get("blocked_by"),
                "at": [r for r in (_ref_label(h.get("line_ref")) for h in p.get("hits") or []) if r][:3]}.items()
                if v is not None})
            extra.append({"hits": [f"{h['condition']}" + (f" ({_ref_label(h.get('line_ref'))})"
                                                          if _ref_label(h.get("line_ref")) else "")
                                   for h in p.get("hits") or []],
                          "missing": [(m.get("id") or f"#{k + 1}") + f" `{m['desc']}`"
                                      for k, m in enumerate(p.get("missing") or [])],
                          "order": p.get("order"), "gap_sec": p.get("gap_sec"), "width_sec": p.get("width_sec"), "code": []})
        need = [n for n, p in enumerate(items) if p["kind"] in ("missing", "absent")]
        if not need or not code or code.get("skipped"):
            return out, extra
        rules = None
        try:
            from common import parser_rules
            rules = parser_rules.load(Path(self.snap) / "parser-rules")
        except Exception:     # noqa: BLE001 — 규칙을 못 읽으면 must_event는 도출 불가로 둔다
            rules = None
        tags = sorted({str(e.get("tag")) for e in events_doc.get("events") or [] if e.get("tag")}
                      | set((rules.tag_exact if rules else {}) or {}))
        lit_items, code_refs, owner = [], [], {}
        for n in need:
            p = items[n]
            if p.get("cause"):
                code_refs += [r.get("ref") for r in self.cause_info(p["cause"]).get("code_refs") or [] if r.get("ref")]
            for k, m in enumerate(p.get("missing") or []):
                pattern = m.get("pattern")
                if m.get("kind") == "event":
                    ext = [x for x in (rules.extractors if rules else []) if x.event == m.get("event")]
                    pattern = ext[0].patterns[0].pattern if len(ext) == 1 and len(ext[0].patterns) == 1 else None
                label = m.get("id") or f"#{k + 1}"      # report.md 없는 조건 이름과 같게
                lid = f"{n}:{label}"
                owner[lid] = (n, label)
                lit_items.append({"id": lid, "pattern": pattern})
        skipped = lit_items[FIND_TEXT_ITEMS:]
        spec = self.job / "find-text-literals.json"
        spec.write_text(json.dumps({"tags": tags, "code_refs": sorted(set(code_refs)), "items": lit_items[:FIND_TEXT_ITEMS]},
                                   ensure_ascii=False), encoding="utf-8", newline="\n")
        rc, data, _ = self.run.call("5-code-text", "code_roots.py",
                                    ["find-text", "--roots", code["roots"], "--literals", spec, "--events", events_path],
                                    expect=(0, 2))
        found = {i["id"]: i for i in ((data or {}).get("items") or [])} if rc == 0 else {}
        scope = (data or {}).get("scope") or {}
        for lit in lit_items:
            n, cid = owner[lit["id"]]
            res = found.get(lit["id"]) if lit not in skipped else None
            status = "skipped" if lit in skipped else (res or {}).get("status", "unavailable")
            out[n].setdefault("code", []).append(":".join([cid, status] + (res or {}).get("refs", [])[:1]))
            extra[n]["code"].append({"id": cid, "status": status, "refs": (res or {}).get("refs") or [],
                                     "log_refs": (res or {}).get("log_refs") or [], "scope": scope})
        return out, extra

    def flows(self, logs: list[Path], tz: str | None, year: int | None, around: str | None, events: dict,
              version: str | None, ranked: list | None = None, top: dict | None = None) -> tuple[list | None, list | None]:
        """성공 흐름 점검 (04-parser-matching.md §5.13, 표시 전용 — S/C·점수 불변): `parse_logcat.py flows`(전체 로그) →
        `JOB/flow.json` → (analysis.json `flows[]`, report.md 줄). 스냅샷에 흐름 파일이 없으면 부르지 않고 (None, None)이다 —
        출력이 이전과 같다. `ranked`: 매칭 후보 원인 ID(순위 순) — "이 단계의 원인"에서 먼저 보인다. `top`: 1위 후보
        `{cause, category, unjudged(1위 유형의 원인 판정 불가), ts(근거 시각)}` — 흐름 제안 줄(`report._flow_hint`)."""
        snap = Path(self.snap)
        config = compat.load_db_config(snap)
        if not flowlib.files(snap, config):
            (self.job / "flow.json").unlink(missing_ok=True)      # 흐름을 뺀 스냅샷: 이전 실행의 flow.json을 남기지 않는다
            return None, None
        argv = ["flows", *logs, "--rules", snap / "parser-rules"] + (["--tz", tz] if tz else []) + (["--year", year] if year else [])
        _, data, _ = self.run.call("4-flows", "parse_logcat.py", argv)
        for w in (data or {}).get("warnings") or []:      # 흐름 파일 오류·패턴 시간 초과(그 흐름만 건너뜀)
            self.warn(_clip(w.get("message"), 120))
        (self.job / "flow.json").write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        causes: dict[str, list] = {}       # 원인 `flow_step`(선택 칸) → 벗어난 단계에 걸린 active 원인
        for type_md in issuedb.type_files(snap, config):
            for c in issuedb.read_frontmatter(type_md).get("causes") or []:
                if c.get("flow_step") and str(c.get("status", "active")) == "active":
                    causes.setdefault(str(c["flow_step"]), []).append((str(c.get("id")), str(c.get("title", ""))))
        return flow_section(data or {}, (events.get("input") or {}).get("window"), around, version, causes, ranked or (), top,
                            flowlib.log_end_sec(config))

    def explore(self, candidates: list[dict]) -> dict | None:
        """Step 5-2 탐색 분석 해당 여부: 후보 없음·원인 미확인이면 `{reason, when}`, 1위 C=1이면 `run --explore`·`explore.when:
        always`·확인할 내용(`--look-note`)이 있을 때만 `fit_check`(적합성 확인), 아니면 None. 끄는 쪽이 이긴다: `never`면
        `--explore`여도, `--no-explore`면 `always`여도 열지 않는다(FR-07). 확인할 내용은 사용자 질문이라 분석 요청으로 본다(FR-16 —
        포털 R1과 같은 논리, 답은 탐색 분석이 한다).

        타임라인은 만들지 않는다(동의 뒤 `triage.py explore`가 `explore_input()`의 값으로 만든다). 판정은 하지 않는다(07-workflow.md §Step 5-2).
        """
        when = userconfig.get(self.cfg, "explore.when", "ask")
        if when not in EXPLORE_WHEN:
            self.warnings.append(f"explore.when 값이 잘못됐다({when}). ask로 본다")
            when = "ask"
        if candidates and candidates[0]["C"]:
            # 확신 일치도 탐색을 묻지 않고 하는 세션이면 1위가 증상을 설명하는지 확인할 맥락을 준다. 그 밖은 이전과 같다(묻지 않음)
            if when == "never" or self.args.explore is False or (
                    when != "always" and not self.args.explore and not self.look_inputs()["note"]):
                return None
            reason = "fit_check"
        else:
            reason = "cause_unconfirmed" if candidates else "no_candidate"
        return {"reason": reason, "when": when, **_ask_note(when, "5-2")}

    def explore_input(self, around: str | None, anchor: dict | None) -> dict:
        """`JOB/explore-input.json`의 내용(마스킹된 값만): 타임라인 머리·줄 수 상한. `core`에 들어가 캐시된다."""
        limit = userconfig.get(self.cfg, "explore.timeline_max_lines", EXPLORE_MAX_LINES)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 20 <= limit <= 1000:
            self.warnings.append(f"explore.timeline_max_lines 값이 잘못됐다({limit}). {EXPLORE_MAX_LINES}로 본다")
            limit = EXPLORE_MAX_LINES
        step = getattr(self, "failed_step", None)
        out = {"around": around, "failed_step": step["text"] if step else None, "limit": limit,
               "anchor": {k: anchor.get(k) for k in ("source", "step", "start", "fail")} if anchor else None}
        if getattr(self, "time_candidates", None):     # 시각 입력 없이 전체를 봤을 때의 증상 시각 후보(사건 후보)
            out["time_candidates"] = [dict(t) for t in self.time_candidates]
        look, found = self.look_inputs(), self.look_result or {}
        if look["at"] or look["note"]:      # 타임라인 머리: 기준 줄(사용자 입력)·찾은 시각·일치 위치, 확인할 내용
            out["look_at"] = {"line": look["at"], "note": look["note"], "ts": found.get("ts"), "hits": found.get("hits"),
                              "at": found.get("at"), **({"source": "model"} if look.get("source") else {})}
        return out

    # 실행 ------------------------------------------------------------------------------------------

    def execute(self) -> dict:
        ctx = self.prepare()
        parts = None if self.offline else self.inputs(ctx)
        request_hash = None if parts is None else _digest(parts)
        core = self.reuse_check(parts, request_hash) if parts is not None else None   # 적중이면 캐시된 core
        hit = core is not None
        if hit:
            self.restore(core)
        else:
            core = self.core(ctx)
        return self.assemble(ctx, core, parts, request_hash, hit)

    def drop_stale_records(self) -> None:
        """이전 실행의 탐색·모듈 스킬 산출물은 이번 결과가 아니다(타임라인은 동의 뒤 `explore`가, 모듈 기록은 `module`·
        `check-output`이 만든다, B2 §7.4). 링크는 따라가지 않고 링크만 지운다. 없으면 아무것도 바꾸지 않는다."""
        for name in STALE_FILES:
            path = self.job / name
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode):
                continue
            path.unlink(missing_ok=True)
        path = self.job / MODULE_RECORD_DIR
        try:
            st = os.lstat(path)
        except OSError:
            return
        if stat.S_ISDIR(st.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    def read_prior(self) -> dict | None:
        """재실행·답글 턴에 줄 이전 실행의 요약(`analysis.json prior`, 마스킹된 값만) — `drop_stale_records`가 지우기 전에 읽는다.
        top = 직전 실행 1위(state `job.runs`), looked = 이전 실행의 가린 기준 줄(state), hyps·none = `check-output`을 통과했고
        그 뒤 바뀌지 않은(기록 `output_sha256` == 지금 파일) `explore-output.md`의 가설 머리·반대 근거·`가설 없음` 이유.
        hyps는 근거 원문 검사를 했고(`source`) 원문에 없는 인용이 0일 때만(검사 건너뜀·`fabricated` > 0이면 뺀다).
        unfit = 가설이 있는데 1위 부적합 보류(`fit_hold`, `1위 판단: 부적합`)면 `<원인 ID> — <이유>`(≤120 — 가설 없음이면 none이 그 이유다).
        hyps·none·unfit은 state `job.prior_explore`에도 남겨 산출물이 지워진 뒤(질문 턴·다음 실행)에도 넘긴다 — 새 검사 기록이 있으면
        그것으로 바꾸고, 그 검사가 실패했거나 출력이 바뀌었으면 지운다. top 말고 아무것도 없으면 None(키가 없다)."""
        def regular(path: Path) -> bool:
            try:
                return stat.S_ISREG(os.lstat(path).st_mode)
            except OSError:
                return False

        runs = self.state.job.get("runs") or []
        top = (runs[-1].get("top") or {}) if runs else {}
        out: dict = {"top": top.get("cause") or top.get("type")}
        looked: list[str] = []
        for r in runs:
            if r.get("look") and r["look"] not in looked:
                looked.append(r["look"])
        out["looked"] = looked[-3:]
        rec = None
        if regular(self.job / "check-output.json"):
            try:
                rec = (json.loads((self.job / "check-output.json").read_text(encoding="utf-8")) or {}).get("explore")
            except (OSError, ValueError, AttributeError):
                rec = None
        if isinstance(rec, dict):           # 새 검사 기록이 있다 — 통과·같은 바이트일 때만 넘기고 남긴다
            judged = None
            path = self.job / "explore-output.md"
            if rec.get("mode") and not rec.get("error") and rec.get("output_sha256") and regular(path):
                try:
                    data = path.read_bytes()
                    fields = (evidence.parse_explore(data.decode("utf-8")) or {}
                              if hashlib.sha256(data).hexdigest() == rec["output_sha256"] else None)
                except (OSError, UnicodeDecodeError):
                    fields = None
                if fields is not None:
                    # FR-10①: 가설은 근거 원문 검사를 실제로 했고(source 있음 — 건너뜀 아님) 원문에 없는 인용이 0일 때만 넘긴다.
                    # weak는 남긴다(정밀도만 다른 정상 인용 오탐 여지). `가설 없음` 이유는 인용이 없어 그대로 넘긴다.
                    # 구버전 check-output 기록(source·fabricated 키 없음)은 검사 불명으로 보고 탈락시킨다(의도한 fail-closed, 비용은 탐색 1회)
                    checked = bool(rec.get("source")) and rec.get("fabricated") == 0
                    judged = {"hyps": [_clip(h["가설"] + (f" — 반대: {h['반대 근거']}"
                                                         if h.get("반대 근거") not in (None, "", "없음") else ""), 120)
                                       for h in fields.get("hyps") or []][:3] if checked else [],
                              "none": _clip(fields.get("none"), 120),
                              # sim1122 F2: 1위 부적합 보류(가설이 있어도)는 다음 실행에도 넘긴다 — 재실행 뒤 1위가 말없이 다시 채택되지 않게
                              "unfit": _clip(f"{rec['fit_hold']} — {(fields.get('top_fit') or {}).get('why') or fields.get('none') or ''}"
                                             .rstrip(" —"), 120) if isinstance(rec.get("fit_hold"), str) and fields.get("hyps") else None}
                    judged = {k: v for k, v in judged.items() if v} or None
            if judged:
                self.state.job["prior_explore"] = judged
            else:
                self.state.job.pop("prior_explore", None)
            self.state.save()
        out.update(self.state.job.get("prior_explore") or {})
        out = {k: v for k, v in out.items() if v}
        # 1위만 있으면(이전 판단·조회 없음) 넘기지 않는다 — 같은 입력의 재실행 출력이 이전과 같게(`reuse.prev_top`이 이미 있다)
        return out if set(out) - {"top"} else None

    def prepare(self) -> dict:
        """Step 0~2와 입력 정리(로그·코드·시간대·연도). 여기까지는 재사용 여부와 상관없이 항상 한다."""
        self.preflight_args()
        self.check_key()
        self.open_job()
        self.prior = self.read_prior()       # 이전 탐색 산출물을 지우기 전에 추린다
        self.drop_stale_records()
        if not self.offline:
            self.lock()
            if self.mark_platform_answer():      # 새 lock(State.reset)이 지웠으면 다시 남긴다
                self.state.save()
            self.check_more_logs()
            if self.analysis_only:
                self.plan_info()
            else:
                self.cleanup()
                self.existing_plan()
            self.snapshot()
            self.compat()
        info = self.jira()
        if not self.offline:
            self.existing_record()
            if not self.analysis_only:
                self.open_prs()
        logs = self.logs()
        if not self.offline:
            self.check_carried()
        version = info.get("platform_version") or None
        code = self.code(version)
        tz = self.args.tz or (info.get("logcat") or {}).get("tz")
        year = self.year(info, logs)
        return {"info": info, "logs": logs, "version": version, "code": code, "tz": tz, "year": year}

    def write_meta(self, anchor: dict | None) -> Path | None:
        """`time` 답을 issue_meta.json에, 앵커가 있으면 match_meta.json(근접 중심 = 스텝 실패 시각)에 쓴다 → 매처에 줄 메타 경로.
        답 `full`(시각 없이 로그 전체)은 시각이 아니라 `occurred_at`에 쓰지 않고, 남아 있던 값도 지운다 — 매처 `_parse_iso`가
        종료 2로 죽고, 남겨 두면 "기준 시각 없음"이라면서 근접 보너스가 옛 시각(예: CP 시계 Jira 값)에 걸린다."""
        meta_path = self.job / "issue_meta.json"
        if self.answer("time") == "full":
            if meta_path.is_file():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.pop("occurred_at", None) is not None:
                    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        elif self.answer("time"):
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {"key": self.key}
            meta["occurred_at"] = self.answer("time")
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        match_meta = meta_path if meta_path.is_file() else None
        if anchor:      # 근접 보너스 중심을 스텝 실패 시각으로. issue_meta.json은 건드리지 않는다
            base = json.loads(meta_path.read_text(encoding="utf-8")) if match_meta else {"key": self.key}
            match_meta = self.job / "match_meta.json"
            match_meta.write_text(json.dumps({**base, "occurred_at": anchor["fail"]}, ensure_ascii=False, indent=1),
                                  encoding="utf-8", newline="\n")
        return match_meta

    # 분석 core: 파싱·매칭·후보 정보 --------------------------------------------------------------------------

    def core(self, ctx: dict) -> dict:
        """입력이 같으면 결과도 같은 부분(Step 3~5). 재사용 캐시에 그대로 들어가므로 마스킹된 값만 둔다."""
        info, logs, version, code, tz, year = (ctx[k] for k in ("info", "logs", "version", "code", "tz", "year"))
        warn0 = len(self.warnings)
        anchor = self.step_anchor(logs, tz, year, info)
        self.problem_refs(logs, tz, year, anchor["window"] if anchor else None)
        around = anchor["fail"] if anchor else self.occurred(info, logs, tz, year)
        events_path = self.job / "events.json"
        if around is None and anchor is None and self.full_events is not None:     # occurred()의 전체 파싱과 같은 인자
            events = self.full_events
            events_path.write_text(json.dumps(events, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        else:
            events = self.parse(logs, around, tz, year, events_path, between=anchor["window"] if anchor else None)
        cov = events.get("coverage") or {}
        if cov.get("window_in_range") is False:
            choice = self.answer("window")
            if choice is None and not self.offline:
                raise NeedsInput("window", f"로그 범위 밖이다(파일 {cov.get('first_ts')}~{cov.get('last_ts')}, 발생 {around}). "
                                           "파일 전체로 다시 파싱할까?",
                                 [{"value": "full", "label": "전체 파싱"}, {"value": "keep", "label": "그대로(매칭 없음으로 보고)"}])
            if choice == "full":
                events = self.parse(logs, None, tz, year, events_path)
                cov = events.get("coverage") or {}      # 재파싱 후 갱신 — 안 하면 logs.in_range가 False로 남는다
        outside = self.outside_errors(info, logs, tz, year, anchor, cov)
        match_meta = self.write_meta(anchor)
        match = self.match(events_path, match_meta, self.job / "match.json")
        self.focus = list((match.get("step_focus") or {}).get("types") or [])
        unjudged = _unjudged(match)
        cause_unjudged = {c["type"] for c in match.get("causes") or [] if c.get("C") is None}
        candidates = []
        for c in match.get("candidates") or []:
            cand = {"type": c["type"], "cause": c["cause"], "title": _clip(c.get("title"), 60),
                    "category": c.get("category"), "score": c["score"], "confidence": c["confidence"],
                    "S": c["S"], "C": c["C"], "phones": sorted({e.get("phone_id") for e in c.get("evidence") or []
                                                                if e.get("phone_id") is not None}),
                    "evidence": [{"ts": e.get("ts"), "tag": e.get("tag"), "msg": _clip(e.get("msg"), 140),
                                  "event": e.get("event"),
                                  "_ref": _ref_label(e.get("line_ref")),   # report.md 전용, analysis.json에는 안 나간다
                                  **({"_count": e["count"]} if e.get("count") else {})}   # min_count ≥ 2 조건만(report.md `×N`)
                                 for e in _unique_evidence(c.get("evidence") or [])[:10]],
                    "fix_judgement": (c.get("fix_judgement") or {}).get("judgement"),
                    "fix_message": _clip((c.get("fix_judgement") or {}).get("message"), 100),
                    "related": [r.get("cause") for r in c.get("related") or []],
                    **({"clock_flags": c["clock_flags"]} if c.get("clock_flags") else {})}   # 표시 전용 (판정 불변)
            if c["cause"] is None and c["type"] in cause_unjudged:   # report.md 전용: 원인 미확인이 아니라 판정 불가
                cand["_cause_unjudged"] = True
            if c.get("version_match") is False:   # 표시 전용 (순위·score 무관)
                cand["_version_mismatch"] = c.get("platform_versions")   # report.md 전용
            if c["cause"]:
                extra = self.cause_info(c["cause"])
                cand["_code_refs"] = extra.pop("code_refs")
                cand.update(extra)
            candidates.append(cand)
        no_candidate = None if candidates else self.no_candidate_hints(info, events)
        partial, partial_report = (self.partial(match, code, events_path, events) if match.get("partial") is not None
                                   else (None, None))
        top = ({"cause": candidates[0]["cause"], "category": candidates[0]["category"],
                "unjudged": bool(candidates[0].get("_cause_unjudged")),     # 1위 유형의 원인 판정 불가만
                "ts": [e["ts"] for e in candidates[0]["evidence"]]} if candidates else None)
        flows, flow_lines = self.flows(logs, tz, year, around, events, version, [c["cause"] for c in candidates if c["cause"]],
                                       top)
        code_out = self.resolve_code(code, version, candidates)
        decision = _decision(candidates, anchor, match.get("eligibility"), self.clue_location((match.get("eligibility") or {}).get("via")))
        self.mark_not_a_bug(decision)
        analyzer = self.analyzer(lead_first(decision, candidates))     # 심층 분석 카테고리: 채택 원인(없으면 1위)
        explore = self.explore(lead_first(decision, candidates))     # 적합성 확인도 채택 원인 기준
        explore_input = self.explore_input(around, anchor) if explore and explore["when"] != "never" else None
        if explore_input is not None and partial:    # 탐색 입력: 부분 일치 앞 3개(키·없는 조건 id)·맞은 근거 시각(보조 중심)
            explore_input["partial"] = [{"signature": p["signature"],
                                         "missing": [m.get("id") or m["desc"] for m in q.get("missing") or []]}
                                        for p, q in zip(partial, match["partial"])]
            explore_input["around_alt"] = sorted({h["ts"] for q in match["partial"][:len(partial)]
                                                  for h in q.get("hits") or []})[:3]
        uncollected = [] if candidates and candidates[0]["C"] else \
            [{"tag": _clip(u.get("tag"), 40), "lines": u.get("lines"), "warn": u.get("warn")}
             for u in events.get("uncollected_tags") or []][:3]
        for cand in candidates:
            cand.pop("_code_refs", None)
        extra_warnings = [_clip(w.get("message"), 120) for w in (events.get("warnings") or []) + (match.get("warnings") or [])]
        if unjudged:
            err = (unjudged.get("errors") or [{}])[0]
            extra_warnings.append(_clip(f"{_unjudged_label(unjudged)} — 시그니처 시간 초과·오류: "
                                        f"{err.get('signature')}: {err.get('error')}", 120))
        observation = _observation_summary(events)
        if cov.get("clock_anomalies"):
            extra_warnings.append("시계 이상(재부팅·NITZ 전 가능) — 증상 시각 스캔(--answer time=…)을 제안한다")
        member = self.steps_info()[3]
        self.steps_member = _clip(self.masker()(member), 120) if member else None
        return {
            "around": around, "anchor": anchor, "outside": outside, "candidates": candidates,
            "decision": decision,
            "pending_causes": [{"cause": p["cause"], "title": _clip(p.get("title"), 50)}
                               for p in match.get("pending_causes") or []][:TOP],
            "no_candidate": no_candidate, "unjudged": unjudged, "observation": observation, "code": code_out,
            "partial": partial, "partial_report": partial_report, "absence_basis": match.get("absence_basis"),
            "partial_unjudged": bool(unjudged) or bool(cause_unjudged), "analyzer": analyzer, "explore": explore,
            "explore_input": explore_input,
            **({"flows": flows, "flow_lines": flow_lines} if flow_lines is not None else {}),
            "logs": {"files": [p.name for p in logs], "window": (events.get("input") or {}).get("window"),
                     "range": [cov.get("first_ts"), cov.get("last_ts")], "in_range": cov.get("window_in_range"),
                     "clock_anomalies": len(cov.get("clock_anomalies") or []), "events": len(events.get("events") or []),
                     "masked": getattr(self, "masked", None),
                     **({"uncollected_tags": uncollected} if uncollected else {})},
            "warnings_core": self.warnings[warn0:], "extra_warnings": extra_warnings,
            # 시계 역행 수와 그중 앞뒤 줄 pid가 같은 수(리포트 시계 이상 줄의 단서, analysis.json에는 안 나간다 — sim1122 F6)
            "clock_backward": _backward_pids(cov.get("clock_anomalies") or []),
            "attrs": {"clock": self.clock, "order_fail": self.order_fail, "order_evidence": self.order_evidence,
                      "focus": self.focus, "steps_member": self.steps_member, "look": self.look_result, "clues": self.clue_rows,
                      "time_candidates": self.time_candidates},
        }

    def analyzer(self, candidates: list[dict]) -> dict | None:
        # self.cfg = 선택 플랫폼의 config: android 밖 플랫폼은 platforms.<p>.analyzers만(android 것을 물려받지 않는다, 17 §10)
        if not candidates:
            return None
        # 5-1 출처는 userconfig.deep_source 하나가 정한다(B2-3). 설치 스킬(레거시·prefer: skill)은 키·순서 그대로
        cat = candidates[0].get("category") or ""
        conf = (self.cfg.get("analyzers") or {}).get(cat)
        conf = conf if isinstance(conf, dict) else {}
        src = userconfig.deep_source(self.cfg, cat)
        if src["source"] == "skill" or (src["source"] == "none" and conf and "prefer" not in conf):
            when = conf.get("when", "ask")
            return {"skill": conf.get("skill"), "when": when, **_ask_note(when, "5-1")}
        if src["source"] == "module":
            return {"category": cat, "when": src["when"], **_ask_note(src["when"], "5-1")}
        if src["source"] == "error":         # when: never → SKILL "never면 생략"이 5-1 질문을 건너뛴다
            return {"error": _clip(userconfig.deep_source_problem(self.cfg, cat) or "설정 오류", 120), "when": "never"}
        return None

    def release(self) -> bool:
        if self.locked and self.run.env.get("TT_LOCK_OWNER"):
            try:
                self.run.call("end", "db_pr.py", ["lock", "release", self.key])
                self.state.data["owner"] = None
                self.state.save()
                return True
            except Fail:
                pass
        return False
