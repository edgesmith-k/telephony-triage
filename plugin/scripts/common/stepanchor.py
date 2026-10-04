"""실패 스텝 기준 분석 구간 (07-workflow.md §Step 3, contracts.md §3.2 `parse_logcat.py markers`).

시험 자동화가 logcat에 남기는 스텝 마커(`TestRunner: Step 5 FAIL` 등)나 시험 절차 첨부 파일의 시각으로
**실패한 스텝의 시간 구간**을 정한다. 이 구간은 **어디를(시간 범위) 볼지**만 정한다. 원인(S/C)은 여전히 로그
시그니처가 정한다. 마커 표기는 사내마다 다르다 — TODO(SITE:S22) (`plugin/site-defaults.yaml`의 `failed_step`).

순수 함수(표준 라이브러리만). 시각은 모두 UTC `datetime`이고, 입력 마커는 `parse_logcat.py markers` 출력의
`{ts, step, status, tag, msg}`(마스킹됨)다. 정규식 오류는 경고로 바꾸고 예외를 내지 않는다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from . import failedstep

UTC = timezone.utc
MARKER_MAX = 2000

DEFAULT_STATUS = {
    "start": ["start", "begin", "시작"],
    "pass": ["pass", "ok", "성공"],
    "fail": ["fail", "ng", "error", "실패"],
}
DEFAULT_WINDOW = {"pre_sec": 60, "post_sec": 30, "fail_only_pre_sec": 120, "max_span_sec": 900}
DEFAULT_DISAGREE_MINUTES = 10

_STEP_NUM_RE = re.compile(r"(?i)^\s*(?:step|스텝|단계|#)?\s*(\d{1,4})\b")
_LEAD_RE = re.compile(r"(?i)^\s*(?:(?:step|스텝|단계|#)?\s*\d{1,4}\b)?[\s.):|\-]*")
_NAME_MIN = 4

# steps-file 시각: ISO(오프셋 선택) | logcat 스탬프(연도 없음) | 시각만. 왼쪽부터 겹치지 않게 찾는다.
_TS_RE = re.compile(
    r"(?P<iso>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?)"
    r"|(?P<stamp>(?<![\d-])\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?)"
    r"|(?P<time>(?<![\d:.\-])\d{1,2}:\d{2}:\d{2}(?:\.\d{1,9})?(?![\d:]))"
)


# -- 마커 ----------------------------------------------------------------------------------------


def compile_markers(patterns) -> tuple[list[re.Pattern], list[str]]:
    """마커 정규식 컴파일. `(step, status)` 이름 그룹이 없거나 컴파일되지 않으면 경고하고 건너뛴다."""
    out: list[re.Pattern] = []
    warnings: list[str] = []
    for p in patterns or []:
        try:
            rx = re.compile(str(p))
        except (re.error, TypeError, ValueError) as exc:
            warnings.append(f"failed_step.marker_patterns 정규식 오류({str(p):.60}): {exc} — 건너뜀")
            continue
        if "step" not in rx.groupindex or "status" not in rx.groupindex:
            warnings.append(f"failed_step.marker_patterns에 (?P<step>)·(?P<status>) 그룹이 없다({str(p):.60}) — 건너뜀")
            continue
        out.append(rx)
    return out, warnings


def status_of(raw, mapping=None) -> str | None:
    """마커 상태 문구 → `start|pass|fail|None` (casefold 비교)."""
    key = " ".join(str(raw or "").split()).casefold()
    if not key:
        return None
    mapping = mapping if isinstance(mapping, dict) and mapping else DEFAULT_STATUS
    for state in ("start", "pass", "fail"):
        words = mapping.get(state) or []
        if isinstance(words, str):
            words = [words]
        if key in {" ".join(str(w).split()).casefold() for w in words}:
            return state
    return None


# -- 스텝 이름 비교 --------------------------------------------------------------------------------


def step_number(text) -> int | None:
    """`Step 5`, `스텝 5`, `단계 5`, `#5`, `5 | ...`의 앞쪽 번호. 없으면 None."""
    m = _STEP_NUM_RE.match(str(text or ""))
    return int(m.group(1)) if m else None


def _name(text) -> str:
    """번호·`Step N`·구분 기호를 뗀 스텝 이름의 비교 키."""
    return failedstep.group_key(_LEAD_RE.sub("", str(text or ""), count=1))


def same_step(marker_step, failed_text, names_only: bool = False) -> bool:
    """마커의 스텝 값과 실패 스텝 텍스트가 같은 스텝인가.

    둘 다 번호가 있으면 번호가 같은지만 본다(`names_only`가 아니면). 그렇지 않으면 번호를 뗀 이름의 `group_key`가
    같거나, 짧은 쪽이 4자 이상이고 긴 쪽에 들어 있으면 같다."""
    if not names_only:
        a, b = step_number(marker_step), step_number(failed_text)
        if a is not None and b is not None:
            return a == b
    left, right = _name(marker_step), _name(failed_text)
    if not left or not right:
        return False
    if left == right:
        return True
    short, long_ = sorted((left, right), key=len)
    return len(short) >= _NAME_MIN and short in long_


# -- 구간 ----------------------------------------------------------------------------------------


def _ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def gap_minutes(a, b) -> float:
    """두 시각 차이(분, 절댓값)."""
    return abs((_ts(a) - _ts(b)).total_seconds()) / 60.0


def _closest(items: list[tuple[datetime, dict]], jira_at) -> tuple[datetime, dict]:
    if jira_at is None:
        return items[0]
    return min(items, key=lambda it: (abs((it[0] - jira_at).total_seconds()), it[0]))


def find_span(markers, failed_text, jira_at, allow_without_step: bool = True,
              max_span_sec: int = DEFAULT_WINDOW["max_span_sec"]):
    """마커 목록에서 실패 스텝의 구간을 찾는다. `(span | None, warnings)`.

    span: `{source: "log_marker", step, step_from: "failed_step"|"marker", start, fail, end}`. 시각은 UTC datetime,
    `start`는 없을 수 있다. FAIL 마커가 있으면 `fail == end`, 시작만 있으면(`fail: None`) `end`는 다음 마커 시각
    (없으면 `start + max_span_sec`)이다. 실패 스텝을 모르면 `allow_without_step`일 때만 FAIL 마커 자체를 쓴다."""
    jira_at = _ts(jira_at) if jira_at else None
    rows: list[tuple[datetime, dict]] = []
    for m in markers or []:
        t = _ts(m.get("ts"))
        if t is not None and m.get("status") in ("start", "pass", "fail"):
            rows.append((t, m))
    rows.sort(key=lambda it: it[0])      # 안정 정렬: 같은 시각이면 파일 순서
    warnings: list[str] = []
    have_step = bool(failed_text and str(failed_text).strip())
    if not have_step and not allow_without_step:
        return None, warnings

    def matches(m) -> bool:
        return same_step(m.get("step"), failed_text) if have_step else True

    fails = [(i, t, m) for i, (t, m) in enumerate(rows) if m["status"] == "fail" and matches(m)]
    if fails:
        if len(fails) > 1:
            warnings.append(f"FAIL 마커 {len(fails)}개 — Jira 발생 시각에 가장 가까운 것(없으면 첫 번째)을 골랐다")
        pick = _closest([(t, {"i": i, "m": m}) for i, t, m in fails], jira_at)
        fail_t, ref = pick
        idx, marker = ref["i"], ref["m"]
        step = marker.get("step")
        start = None
        for t, m in reversed(rows[:idx]):
            if m["status"] == "start" and same_marker_step(m.get("step"), step):
                start = t
                break
        if start is None and idx > 0:
            start = rows[idx - 1][0]
        return {"source": "log_marker", "step": step, "step_from": "failed_step" if have_step else "marker",
                "start": start, "fail": fail_t, "end": fail_t}, warnings
    if not have_step:
        return None, warnings

    # FAIL 마커가 없고 START만 있는 스텝(실패 직후 로그가 끊김): 같은 스텝의 PASS·FAIL이 뒤에 없는 마지막 START
    starts = []
    for i, (t, m) in enumerate(rows):
        if m["status"] != "start" or not matches(m):
            continue
        if any(m2["status"] in ("pass", "fail") and same_marker_step(m2.get("step"), m.get("step"))
               for _, m2 in rows[i + 1:]):
            continue
        starts.append((i, t, m))
    if not starts:
        return None, warnings
    i, start, marker = starts[-1]
    nxt = next((t for t, _ in rows[i + 1:] if t > start), None)
    end = nxt or start + timedelta(seconds=max_span_sec)
    warnings.append("FAIL 마커 없이 START만 있다 — 다음 마커(없으면 최대 구간) 전까지를 실패 구간으로 봤다")
    return {"source": "log_marker", "step": marker.get("step"), "step_from": "failed_step",
            "start": start, "fail": None, "end": end}, warnings


def same_marker_step(a, b) -> bool:
    """마커 두 개의 스텝 값이 같은가(번호가 있으면 번호, 아니면 이름)."""
    return same_step(a, b)


def _window_cfg(cfg) -> dict:
    out = dict(DEFAULT_WINDOW)
    for k, v in ((cfg or {}).get("window") or {}).items():
        if k in out and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            out[k] = v
    return out


def window(span: dict, cfg=None) -> tuple[datetime, datetime, list[str]]:
    """span → 분석 구간 `(start, end, warnings)`.

    시작이 있으면 `[start - pre_sec, fail + post_sec]`, 실패 시각만 있으면 `[fail - fail_only_pre_sec, fail + post_sec]`.
    `fail - start`가 `max_span_sec`을 넘으면 시작을 그만큼으로 당겨 쓴다(경고)."""
    w = _window_cfg(cfg)
    fail = span.get("fail") or span["end"]
    start = span.get("start")
    warnings: list[str] = []
    if start is not None and start > fail:
        start = None
    if start is None:
        return (fail - timedelta(seconds=w["fail_only_pre_sec"]), fail + timedelta(seconds=w["post_sec"]), warnings)
    length = (fail - start).total_seconds()
    if length > w["max_span_sec"]:
        warnings.append(f"스텝 구간이 {int(length)}초로 길어 끝에서 {int(w['max_span_sec'])}초만 분석 범위에 넣었다")
        start = fail - timedelta(seconds=w["max_span_sec"])
    return start - timedelta(seconds=w["pre_sec"]), fail + timedelta(seconds=w["post_sec"]), warnings


# -- 시계 차 -------------------------------------------------------------------------------------

OFFSET_MAX_SEC = 86400
_OFF_HMS_RE = re.compile(r"^(?P<sign>[+-]?)(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?(?:(?P<s>\d+(?:\.\d+)?)s)?$")
_OFF_CLOCK_RE = re.compile(r"^(?P<sign>[+-]?)(?:(?P<h>\d+):)?(?P<m>\d{1,2}):(?P<s>\d{1,2}(?:\.\d+)?)$")
_OFF_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def parse_offset(value) -> float | None:
    """장비 시각 → 단말(logcat) 시각으로 옮기는 시계 차(초): **단말 시각 = 장비 시각 + offset**. 형식이 틀리면 None.

    허용: `±XhYmZ(.f)s`(단위 1개 이상, 부호 선택), `±HH:MM:SS(.f)`, `±MM:SS`, 초 단위 정수·실수(문자열 가능).
    절댓값이 86400초(1일)를 넘으면 None이다."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        out = float(value)
    else:
        text = "".join(str(value).split()).casefold()
        if not text:
            return None
        sign = -1.0 if text.startswith("-") else 1.0
        if _OFF_NUM_RE.match(text):
            out = float(text)
        elif (m := _OFF_CLOCK_RE.match(text)):
            out = sign * (int(m.group("h") or 0) * 3600 + int(m.group("m")) * 60 + float(m.group("s")))
        elif (m := _OFF_HMS_RE.match(text)) and any(m.group(g) for g in ("h", "m", "s")):
            out = sign * (int(m.group("h") or 0) * 3600 + int(m.group("m") or 0) * 60 + float(m.group("s") or 0))
        else:
            return None
    if out != out or abs(out) > OFFSET_MAX_SEC:      # NaN·범위 밖
        return None
    return out + 0.0


# -- 시험 절차 파일의 시각 ---------------------------------------------------------------------------


def steps_file_times(line, tz, year, ref_dt=None):
    """실패 스텝 줄(원문)에서 시각 최대 2개 → `(start | None, fail | None)` (UTC datetime).

    첫 시각이 시작, 둘째가 실패이고 하나뿐이면 실패 시각이다. 오프셋 있는 ISO는 그대로, 오프셋 없는 ISO와
    logcat 스탬프(`MM-DD HH:MM:SS(.mmm)`)는 `tz`·`year`로, 시각만(`HH:MM:SS`)은 `ref_dt`(Jira 발생 시각 또는
    로그 첫 시각)의 날짜를 쓰고 `ref_dt`보다 12시간 넘게 앞서면 하루 뒤로 본다. 줄 원문은 돌려주지 않는다."""
    from parser_backends import logcat

    ref = _ts(ref_dt) if ref_dt else None
    found: list[datetime] = []
    for m in _TS_RE.finditer(str(line or "")):
        dt = None
        if m.group("iso"):
            dt = logcat.normalize_ts(m.group("iso").replace(" ", "T", 1), tz, year)
        elif m.group("stamp"):
            text = m.group("stamp").replace("T", " ")
            if "." not in text:
                text += ".000"
            dt = logcat.normalize_ts(text, tz, year)
        elif ref is not None:
            h, mi, rest = m.group("time").split(":", 2)
            sec, _, frac = rest.partition(".")
            try:
                zone = logcat.get_tz(tz)
                local_ref = ref.astimezone(zone)
                naive = datetime(local_ref.year, local_ref.month, local_ref.day, int(h), int(mi), int(sec),
                                 int((frac or "0")[:6].ljust(6, "0")))
            except ValueError:
                continue
            dt = naive.replace(tzinfo=zone).astimezone(UTC)
            if dt < ref - timedelta(hours=12):
                dt += timedelta(days=1)
        if dt is not None:
            found.append(dt)
        if len(found) == 2:
            break
    if not found:
        return None, None
    if len(found) == 1:
        return None, found[0]
    return found[0], found[1]


# -- 스텝 순서 정렬 ----------------------------------------------------------------------------------

DEFAULT_ORDER = {"min_matched": 1, "max_missing": 1, "pre_sec": 10, "fail_post_sec": 120}


def _order_cfg(cfg) -> dict:
    out = dict(DEFAULT_ORDER)
    for k, v in ((cfg or {}).get("order") or {}).items():
        if k in out and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            out[k] = v
    return out


def _walk(steps, failed_idx, rule_of, by_rule, start_after=None):
    """PASS 스텝을 순서대로 걸으며 규칙의 흔적을 찾는다. `(matches[(k, dt, seq, label, ts 원문)], observable, missed, unobservable)`.

    스텝마다 그 스텝 규칙의 흔적 중 `(ts, seq)`가 커서보다 뒤인 **가장 이른 것**을 쓰고 커서를 옮긴다. 없으면 놓친 것이다.
    규칙이 없거나 관측 불가인 스텝은 세기만 한다(놓친 것이 아니다)."""
    cursor = start_after
    matches, observable, missed, unobservable = [], 0, 0, 0
    for k in range(min(failed_idx, len(steps))):
        rule = rule_of.get(k) if isinstance(rule_of, dict) else (rule_of[k] if k < len(rule_of) else None)
        if rule is None:
            unobservable += 1
            continue
        observable += 1
        pick = next((h for h in by_rule.get(rule, ()) if cursor is None or (h[0], h[1]) > cursor), None)
        if pick is None:
            missed += 1
            continue
        matches.append((k, *pick))
        cursor = (pick[0], pick[1])
    return matches, observable, missed, unobservable


def order_walk(steps, failed_idx, rule_of, hits, cfg=None):
    """스텝 순서로 실패 구간을 정한다(순수·결정적). `(result | None, info, warnings)`.

    `steps`: `failedstep.parse_steps` 목록(첫 FAIL까지), `failed_idx`: 실패 스텝 위치, `rule_of`: 스텝 위치 → `step_events`
    규칙 번호(없거나 관측 불가면 None; dict 또는 목록), `hits`: `parse_logcat markers --step-events`의 `step_events`
    (`{rule, ts, seq, label}`), `cfg`: `failed_step` 설정(`order`·`window.max_span_sec`)에 `coverage_last`(로그 끝 시각)와
    `truncated_rules`(상한에 걸린 규칙 번호)를 더한 것.

    `info = {matched, observable, missed, unobservable, evidence[(스텝 위치, ts, 라벨)], reason?}`. 앵커를 못 정하면
    `result`가 None이고 `info["reason"]`에 사유가 있다. 앵커가 있으면 `result = {start, fail, end, last_ts, failed_hit,
    last_step}`(UTC datetime; `fail`은 실패 스텝의 흔적이 있으면 그 시각, 없으면 마지막 일치 시각). 끝은 로그 범위로 자를 뿐 버리지 않는다."""
    conf = _order_cfg(cfg)
    by_rule: dict[int, list] = {}
    for h in sorted((h for h in hits or [] if _ts(h.get("ts")) is not None),
                    key=lambda h: (_ts(h["ts"]), int(h.get("seq") or 0))):
        by_rule.setdefault(h["rule"], []).append((_ts(h["ts"]), int(h.get("seq") or 0), str(h.get("label") or ""), h["ts"]))
    warnings: list[str] = []
    info = {"matched": 0, "observable": 0, "missed": 0, "unobservable": 0, "evidence": []}
    if failed_idx is None or not steps:
        info["reason"] = "실패 스텝 위치를 모름"
        return None, info, warnings
    matches, observable, missed, unobservable = _walk(steps, failed_idx, rule_of, by_rule)
    info.update(matched=len(matches), observable=observable, missed=missed, unobservable=unobservable,
                evidence=[(k, raw, label) for k, _, _, label, raw in matches])
    used = {_rule(rule_of, k) for k in range(min(failed_idx, len(steps))) if _rule(rule_of, k) is not None}
    truncated = set((cfg or {}).get("truncated_rules") or ())

    def fail(reason: str):
        info["reason"] = reason
        return None, info, warnings

    if observable == 0:
        return fail("관측 가능한 PASS 스텝 없음")
    if used & truncated:
        return fail("스텝 흔적이 상한을 넘어 일부만 읽었다")
    if len(matches) < conf["min_matched"]:
        return fail(f"일치한 스텝이 적다({len(matches)}개, 최소 {int(conf['min_matched'])}개)")
    last_observable = max(k for k in range(min(failed_idx, len(steps))) if _rule(rule_of, k) is not None)
    if not matches or matches[-1][0] != last_observable:
        return fail("마지막 관측 가능 스텝 미발견")
    if missed > conf["max_missing"]:
        return fail(f"놓친 스텝 {missed}개")
    again = _walk(steps, failed_idx, rule_of, by_rule, start_after=(matches[0][1], matches[0][2]))[0]
    if len(again) >= len(matches):
        return fail("스텝 순서가 로그에 두 번 이상(반복 실행)")

    last_k, last_ts, last_seq, _, _ = matches[-1]
    failed_rule = _rule(rule_of, failed_idx)
    h_f = None
    if failed_rule is not None:
        h_f = next((h[0] for h in by_rule.get(failed_rule, ()) if (h[0], h[1]) > (last_ts, last_seq)), None)
    max_span = ((cfg or {}).get("window") or {}).get("max_span_sec", DEFAULT_WINDOW["max_span_sec"])
    if not isinstance(max_span, (int, float)) or isinstance(max_span, bool) or max_span < 0:
        max_span = DEFAULT_WINDOW["max_span_sec"]
    ends = [last_ts + timedelta(seconds=max_span)]
    cov_last = _ts((cfg or {}).get("coverage_last")) if (cfg or {}).get("coverage_last") else None
    if cov_last is not None:
        ends.append(cov_last)
    if h_f is not None:
        ends.append(h_f + timedelta(seconds=conf["fail_post_sec"]))
    start = last_ts - timedelta(seconds=conf["pre_sec"])
    end = max(min(ends), last_ts)
    return {"start": start, "fail": h_f or last_ts, "end": end, "last_ts": last_ts, "failed_hit": h_f,
            "last_step": last_k}, info, warnings


def _rule(rule_of, k):
    if isinstance(rule_of, dict):
        return rule_of.get(k)
    return rule_of[k] if 0 <= k < len(rule_of) else None
