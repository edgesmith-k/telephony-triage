"""실패 스텝·발생 시각·스텝 앵커 (`AnchorMixin`)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import platforms
from common import compat, failedstep, lookat, stepanchor, userconfig
from common import logtime as lc

from .core import CLUE_FILE, LOOK_FILE, NeedsInput, _clip

# 중요 경고(report.KEY_WARNING) — 머리를 바꾸면 포털 경고 표(web.WARN_NOTE)도 같이(두 레포 맞춤 시험 test_real_plugin)
NO_STEP_TIME = "TC 실패 스텝에 시각 없음 — TC 시각으로 분석 구간을 정하지 못해 다음 출처로 정했다"
# sim1122 F5: TC 머리 날짜가 로그 날짜 범위에 없다(다른 날 로그·TC). 포털이 이 머리로 고른다 — 바꾸면 포털도
TC_DATE_DIFF = "TC 날짜와 로그 날짜가 다름: TC {tc}, 로그 {log} — 다른 날의 TC·로그일 수 있다(같은 시험의 것인지 확인)"
_CLOCK_RE = re.compile(r"(?<![\d:.\-])(\d{1,2}):(\d{2}):(\d{2})(?![\d:])")     # 스텝 칸의 시각만(자정 넘김 세기)
LOOK_TIME_ONLY = "기준 줄에 시각만 있어 로그에서 찾지 않았다 — 태그와 메시지 일부를 같이 적으면 그 줄을 찾는다"


def _parse_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _num(x: float):
    """정수로 떨어지면 int, 아니면 float (JSON에 180.0 대신 180)."""
    return int(x) if float(x).is_integer() else x


def _clue_text(c: dict, pb) -> tuple[str | None, str | None]:
    """problem.json 단서 → (찾을 글, 붙여 넣은 줄의 logcat 시각|None). 모양이 틀린 단서는 (None, None) — check-output이 이미
    걸렀지만 파일이 바뀌었을 수 있어 같은 식(`NAME_RE`·`TOKEN_RE`·`QUOTE_MAX`)으로 다시 본다."""
    n = c.get("comment")
    if not (n == "description" or (type(n) is int and n >= 1)):     # 경고·리포트의 "코멘트 n번"이 깨지지 않게
        return None, None
    name, token, quote = c.get("name"), c.get("token"), c.get("quote")
    ok_name = isinstance(name, str) and pb.NAME_RE.fullmatch(name)
    if c.get("kind") == "ipc" and ok_name and isinstance(token, str) and pb.TOKEN_RE.fullmatch(token):
        # 인용이 시각 붙은 로그 줄이면 그 시각도 — 그 시각의 줄이 로그에 있어야 쓴다(다른 로그·이전 회차의 같은 token을 막는다)
        return f"{name} (token={token})", lookat.stamp(quote) if isinstance(quote, str) else None
    if c.get("kind") == "ipc_name" and ok_name:
        return name, None
    if c.get("kind") == "log_line" and isinstance(quote, str) and 0 < len(quote) <= pb.QUOTE_MAX:
        return lookat.clean(quote), lookat.stamp(quote)
    return None, None


def _stamp_unmet(stamp: str | None, found: dict) -> bool:
    """붙인 줄의 시각이 있는데 찾은 곳에 그 시각의 줄이 없다(`stamp: none`, 읽지 못한 시각 — 찾기 결과에 `stamp`가 없을 때도)."""
    return bool(stamp) and bool(found.get("hits")) and found.get("stamp") in ("none", None)


def _outside(lines: list[dict], window) -> bool:
    """찾은 단서 줄(`{ts}`)이 모두 명시 기준의 분석 구간(시작, 끝) 밖인가. 구간이 없거나 시각을 못 읽으면 False."""
    lo, hi = (_parse_ts(x) for x in window) if window else (None, None)
    stamps = [_parse_ts(x.get("ts")) for x in lines]
    if lo is None or hi is None or not stamps or None in stamps:
        return False
    return all(t < lo or t > hi for t in stamps)


def _step_label(step) -> str:
    """마커의 스텝 값 → 표시 이름(번호만이면 `Step N`)."""
    text = str(step or "").strip()
    return f"Step {text}" if re.fullmatch(r"\d{1,4}", text) else text or "스텝 미상"


class AnchorMixin:
    def resolve_failed_step(self, auto: dict | None, masker) -> dict | None:
        """auto(이미 마스킹) + 이번 실행의 플래그 → 마스킹된 {text, source} | None. 원문은 이 함수 안에서만 쓴다."""
        a = self.args
        patterns = userconfig.get(self.cfg, "tracker.failed_step_patterns") or []
        result, warns = failedstep.resolve(getattr(a, "failed_step", None), auto, getattr(a, "steps_file", None), patterns, masker,
                                           userconfig.get(self.cfg, "failed_step") or {})
        for w in warns:
            if w not in self.warnings:
                self.warnings.append(w)
        return result

    def apply_failed_step(self, data: dict, meta_path: Path) -> None:
        """`issue.json`(extract 결과)에 실패 스텝을 맞춘다. 바뀐 것이 있을 때만 `issue.json`·`issue_meta.json`을 다시 쓴다."""
        for w in data.get("warnings") or []:
            if w not in self.warnings:
                self.warnings.append(str(w))
        self.failed_step = self.resolve_failed_step(data.get("failed_step_auto"), self.masker())
        if self.failed_step == data.get("failed_step"):
            return
        jira = data.setdefault("issue", {})
        if self.failed_step:
            data["failed_step"] = self.failed_step
            jira["failed_step"] = self.failed_step["text"]
        else:
            data.pop("failed_step", None)
            jira.pop("failed_step", None)
        (self.job / "issue.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                                            encoding="utf-8", newline="\n")
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if self.failed_step:
                meta["failed_step"] = self.failed_step["text"]
            else:
                meta.pop("failed_step", None)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")

    def out_failed_step(self) -> None:
        if self.failed_step:
            self.out["issue"]["failed_step"] = {"text": _clip(self.failed_step["text"], 120),
                                               "source": self.failed_step["source"]}

    def year(self, info: dict, logs: list[Path]) -> int | None:
        if self.args.year:
            return self.args.year
        logcat = info.get("logcat") or {}
        if logcat.get("year"):
            return int(logcat["year"])
        if self.answer("year"):
            return int(self.answer("year"))
        source = logcat.get("year_source") or userconfig.get(self.cfg, "logcat.year_source")
        if self.offline:
            return None
        mtime_year = datetime.fromtimestamp(logs[0].stat().st_mtime).year
        if source == "file-mtime":
            return mtime_year
        if source == "tracker" or not source:
            # Jira 발생 시각이 없다 → 묻지 않고 시각 후보(Step 2 --full)로 간다. 연도는 파일 시각으로 임시로 정한다.
            self.warnings.append(f"Jira 발생 시각이 없어 logcat 연도를 로그 파일 시각({mtime_year})으로 임시로 정했다. "
                                 "다르면 --year로 다시 실행한다.")
            return mtime_year
        this_year = datetime.now().year
        options = [{"value": str(mtime_year), "label": f"{mtime_year} (로그 파일 시각)"}]
        if this_year != mtime_year:
            options.append({"value": str(this_year), "label": f"{this_year} (올해)"})
        options.append({"value": "<YYYY>", "label": "직접 입력"})
        raise NeedsInput("year", "연도 없는 logcat의 연도를 정한다(logcat.year_source: ask).", options)

    def given_time(self, info: dict, tz: str | None, year: int | None) -> datetime | None:
        """사용자가 준 분석 기준 시각: `--answer time=<시각>`(full 아님) > `--issue-meta`의 `occurred_at`(손으로 쓴 메타). Jira 발생
        시각 칸은 로그와 다른 시계의 값이라 쓰지 않는다(D4 — `driver.jira`가 `info.occurred_at`을 비운다). 없거나 못 읽으면 None."""
        t = self.answer("time")
        if t and t != "full":
            dt = lc.normalize_ts(t, tz, year)
            if dt is not None:
                return dt
        return _parse_ts(info.get("occurred_at"))

    def step_anchor(self, logs: list[Path], tz: str | None, year: int | None, info: dict) -> dict | None:
        """분석 구간 앵커(기준 줄 > 로그 마커 > steps-file) → `{source, step, step_from, start, fail, window}` | None.

        `--answer anchor=off`면 없다. 기준 줄(`--look-at`)은 사용자가 직접 찍은 자리라 마커보다 먼저 찾는다(`parse_logcat ipc --find`,
        못 찾으면 경고하고 다음 출처). 마커 패턴(`site-defaults.yaml`의 `failed_step.marker_patterns`, 사용자 config로 바꿀 수
        없다)이 있거나 `--steps-file`이 있을 때만 `parse_logcat markers`를 돌린다. 앵커의 실패 시각이 로그 범위 밖이면 경고하고
        다음 출처로 넘어간다. steps-file의 원문 줄은 이 프로세스 안에서 시각만 뽑고 버린다."""
        self.anchor_off = self.answer("anchor") == "off"
        self.reference = None
        if self.anchor_off:
            if self.look_inputs()["at"]:
                self.warn("기준 줄(--look-at)은 --answer anchor=off라 쓰지 않았다")
            return None
        conf = userconfig.get(self.cfg, "failed_step") or {}
        site = self.defaults.get("failed_step") or {}
        # 설정 검사는 앵커 결과와 무관하게(기준 줄이 이겨도) 마커·steps-file이 있으면 늘 같은 자리에서 한다
        if ((site.get("marker_patterns") or getattr(self.args, "steps_file", None)) and self.clock_offset is None
                and conf.get("clock_offset") is not None):
            self.clock_offset = stepanchor.parse_offset(conf["clock_offset"])
            if self.clock_offset is None:
                self.warn(f"failed_step.clock_offset 형식이 맞지 않아 쓰지 않았다({str(conf['clock_offset'])[:40]})")
        jira_at = self.given_time(info, tz, year)      # 여러 곳 중 고르기·시각만 있는 TC 날짜·차이 경고의 기준(Jira 칸 값 아님)
        span = self.look_span(logs, tz, year, jira_at) or self.marker_span(logs, tz, year, conf, jira_at)
        if span is None:
            return None
        fail = span["fail"] or span["end"]
        if span["source"] == "look_at":     # 기준 줄 뒤를 넓게(재시도·후속 처리), 앞은 짧게 — 상수(VERIFY P2 20)
            start, end = fail - timedelta(seconds=lookat.PRE_SEC), fail + timedelta(seconds=lookat.POST_SEC)
        elif span["source"] == "step_order":
            start, end = span["start"], span["end"]
        else:
            start, end, warns = stepanchor.window(span, {"window": conf.get("window")})
            for w in warns:
                self.warn(w)
        anchor = {"source": span["source"], "step": span.get("step"), "step_from": span["step_from"],
                  "start": lc.format_ts(span["start"]) if span.get("start") else None, "fail": lc.format_ts(fail),
                  "window": (lc.format_ts(start), lc.format_ts(end))}
        anchor["location"] = self.location(span)
        if span["source"] == "look_at" and (self.look_result or {}).get("how") == "words":
            anchor["loose"] = True      # 낱말 순서로만 찾은 기준 줄 — 채택이어도 확정(confirmed)으로 올리지 않는다(driver._decision)
        self.reference = self.reference_of(span)
        if span.get("order"):
            anchor["order"] = span["order"]
        if jira_at:
            gap = stepanchor.gap_minutes(fail, jira_at)
            anchor["issue_gap_min"] = round(gap, 1)
            limit = conf.get("disagree_minutes", stepanchor.DEFAULT_DISAGREE_MINUTES)
            if isinstance(limit, (int, float)) and not isinstance(limit, bool) and gap > limit:
                hint = " (입력한 시각이 장비 시각이면 시계 차 때문일 수 있다)" if span["source"] in ("steps_file", "step_order") else ""
                what = "기준 줄" if span["source"] == "look_at" else "실패 스텝"
                self.warn(f"입력한 발생 시각과 {what} 시각이 {gap:.0f}분 다르다 — {'스텝' if what == '실패 스텝' else what} 시각 "
                          f"기준으로 분석했다(끄기: --answer anchor=off){hint}")     # 경고만 낸다. 구간은 바꾸지 않는다
        return anchor

    def location(self, span: dict) -> dict:
        """실패 지점 `{state, source, kind}`(analysis.json `decision.location`). 기준 줄은 ipc·token 일치(point) 1개면 confirmed,
        글자 일치(near) 1개면 found("한 곳에서 찾았다"이지 "이번 실패 지점을 확인했다"가 아니다), 여럿이면 multiple(곳 수는 같은
        요청으로 묶은 뒤). 로그 마커는 FAIL 1개 confirmed·여럿 multiple·START만 found. steps-file 시각·스텝 순서는 found(구간).
        채택이면 `driver._decision`이 자격 검사 결과로 다시 정한다. 앵커가 없으면 이 함수를 부르지 않는다(`NO_LOCATION`)."""
        src = span["source"]
        if src == "look_at":     # 같은 요청(IPC REQ→RSP·RIL 짝)으로 묶은 곳 수
            look = self.look_result or {}
            text = look.get("how") in ("text", "words")     # 글자 일치(낱말 순서 일치 포함)는 near — 한 곳이어도 found
            if self.look_inputs().get("source") == "model":     # 모델이 고른 줄: 문제 파악 단서처럼 확정으로 올리지 않는다(Y1)
                return {"state": "multiple" if look.get("places") != 1 else "found", "source": "model",
                        "kind": "near" if text else "point"}
            return {"state": "multiple" if look.get("places") != 1 else "found" if text else "confirmed", "source": src,
                    "kind": "near" if text else "point"}
        if src == "log_marker" and span.get("fail") is not None:
            return {"state": "confirmed" if span.get("n") == 1 else "multiple", "source": src, "kind": "range"}
        return {"state": "found", "source": src, "kind": "range"}

    def reference_of(self, span: dict) -> dict:
        """자격 검사 기준(`match_signatures.py --reference`, `common.eligibility`). 기준 줄은 `{kind: line, source, places, lines[]}`
        (lines = 고른 곳의 줄 `{line_ref, ts, phone, ipc?, ril?}`), 마커·steps-file은 `{kind: range, source, places, start, fail}`
        (places = 맞는 FAIL 마커 수, START만이면 fail null)."""
        src = span["source"]
        if src == "look_at":
            return {"kind": "line", "source": src, "places": (self.look_result or {}).get("places") or 1,
                    "lines": self.look_place}
        return {"kind": "range", "source": src, "places": span.get("n") or 1,
                "start": lc.format_ts(span["start"]) if span.get("start") else None,
                "fail": lc.format_ts(span["fail"]) if span.get("fail") else None}

    def problem_refs(self, logs: list[Path], tz: str | None, year: int | None, window=None) -> None:
        """Jira 단서 → 자격 검사 입력 `self.problem_use`
        `{problem: {types, not_in_db}|None, comment_adopt, refs[단서 기준], dropped[{comment, kind, why}]}` | None.

        단서 출처는 둘 중 하나다. ① 같은 JOB의 문제 파악 결과(`problem.json`, 단계 5-2)가 이번 이슈 입력으로 만든 것(해시 일치)이면
        그것만: `symptom.types`·`not_in_db`(설정 `eligibility.use_problem_types`가 거짓이면 둘 다 안 씀)와 `stale: false` 단서 —
        hypotheses·modules·unknown·side·rounds는 판정에 쓰지 않는다. ② 없거나 낡았으면 `JOB/issue.json` 코멘트(가린 글)에서
        스크립트로 뽑은 단서(`problem.extract_clues`, 유형 없음 — 설정 `eligibility.comment_clues`, 기본 참). `--look-at`이 있으면
        ②는 쓰지 않는다(개수만 경고 한 줄). 단서는 `parse_logcat ipc --find`(기준 줄과 같은 찾기 — 값은 문자열 비교만, 정규식·경로·
        명령으로 쓰지 않는다) 한 번으로 모두 찾는다: ipc = 이름+token, ipc_name = 이름 본문 일치, log_line = 인용 본문 일치.
        logcat 시각이 붙은 log_line은 그 시각의 줄이 로그에 있어야 쓴다(다른 로그·이전 회차 로그에서 붙인 줄을 본문만으로 잡지
        않게). 로그에 없는 단서는 버리고 `dropped`에 남긴다 — ①은 단서마다 경고, ②는 버림 요약 한 줄. 명시 기준(앵커)의 분석
        구간 `window`(시작, 끝)가 있고 찾은 단서 줄이 모두 그 밖이면 `outside: true`(자격 검사가 명시 기준과 다른 사건으로 본다 — H07).
        `--answer anchor=off`면 안 읽는다."""
        from . import problem as pb      # 지연 import(문제 파악 모듈은 Jira·플랫폼 모듈을 끌어온다)

        self.problem_use, self.clue_rows = None, []
        if self.anchor_off:
            return
        conf = userconfig.get(self.cfg, "eligibility") or {}
        conf = conf if isinstance(conf, dict) else {}

        def switch(key: str) -> bool:     # 참·거짓 값만 받는다 — 글자 "false" 등은 경고하고 기본(참)
            value = conf.get(key, True)
            if isinstance(value, bool):
                return value
            self.warn(f"설정 eligibility.{key} 값이 참·거짓(true/false)이 아니라 기본값 true로 본다")
            return True
        doc = self.fresh_problem(pb)
        problem, auto = None, None
        if doc is not None:
            sym = doc.get("symptom") if isinstance(doc.get("symptom"), dict) else {}
            if switch("use_problem_types"):
                problem = {"types": [t for t in sym.get("types") or [] if isinstance(t, str)][:pb.TYPES_MAX],
                           "not_in_db": sym.get("not_in_db") is True}
            clues = doc.get("clues") if isinstance(doc.get("clues"), list) else []
        else:
            clues, auto = self.comment_clues(pb, conf, switch)
            if auto is None:
                return
        todo, seen = [], set()
        for c in clues[:pb.CLUES_MAX]:
            if not isinstance(c, dict) or (c.get("stale") is not False and not (
                    c.get("stale") is True and lookat.stamp(c.get("quote") or ""))):
                continue    # 이전 회차 단서(stale)는 쓰지 않는다(H03) — 날짜 붙은 인용 줄은 그 시각이 이 로그에 있을 때만 쓴다(A592)
            text, stamp = _clue_text(c, pb)
            if text is None or (text, stamp) in seen:      # 같은 찾을 글은 한 번만(같은 곳을 두 단서로 세지 않게)
                continue
            seen.add((text, stamp))
            todo.append((c, text, stamp))
        founds = self.find_clues(logs, tz, year, [(text, stamp) for _, text, stamp in todo])
        origin = "스크립트" if auto is not None else "문제 파악"
        refs, dropped, old_missed = [], [], 0
        for (c, _, stamp), found in zip(todo, founds):
            where = "설명" if c.get("comment") == "description" else f"코멘트 {c.get('comment')}번"
            if _stamp_unmet(stamp, found):
                found = {"hits": 0, "why": "붙인 줄의 시각이 이 로그에 없음"}
            if not found.get("hits") and c.get("stale") is True:
                old_missed += 1     # 옛 회차 인용이 이 로그 것이 아니다 — 찾기 전 옛 회차 버림과 같다(다른 단서를 보류시키지 않는다)
                continue
            if not found.get("hits"):
                why = _clip(found.get("why") or "일치하는 줄 없음", 60)
                dropped.append({"comment": c.get("comment"), "kind": c["kind"], "why": why})
                if auto is None:      # 스크립트 단서는 아래 요약 한 줄로만
                    self.warn(f"{where} 단서, 로그에서 못 찾음({why})")
                continue
            refs.append({"kind": "line", "source": "comment", "comment": c.get("comment"), "clue": c["kind"],
                         "how": found.get("how"), "places": found.get("places") or 1, "lines": found.get("place") or [],
                         "origin": "script" if auto is not None else "problem",
                         **({"outside": True} if _outside(found.get("place") or [], window) else {})})
            self.clue_rows.append({"where": where, "clue": c["kind"], "ts": found.get("ts"), "places": refs[-1]["places"],
                                   "origin": origin})
        if auto is not None:
            parts = [f"{name} {n}" for name, n in (("옛 회차", auto["old_round"] + old_missed), ("상한", auto["over"]),
                                                   ("모양 안 맞음", auto.get("invalid", 0)), ("로그에 없음", len(dropped))) if n]
            if parts:
                self.warn("코멘트 단서(스크립트) 버림: " + " · ".join(parts))
            if auto.get("conflict") and todo:
                self.warn("코멘트에 서로 다른 token 값이 여럿이라(정정·정상과 실패를 함께 적음 등) 코멘트 단서로는 채택하지 않는다")
            if not todo:      # 찾을 단서가 없었다 — 기준 없음과 같다(reference.json을 쓰지 않는다)
                return
        # 찾았는데 확인 못 한 단서(dropped)·글의 token 충돌(conflict)이 있으면 자격 검사가 단서 판정 전체를 보류한다.
        # comment_adopt는 문제 파악 단서만 — 스크립트 단서는 위치 후보로만 쓰고 채택 자리에서 comment_unconfirmed로 보류(A474, D1).
        # ponytail: 스위치는 새로 두지 않는다 — 사내 측정 뒤 필요하면 `script_clue_adopt`
        self.problem_use = {"problem": problem, "comment_adopt": switch("comment_adopt") and auto is None, "refs": refs,
                            "dropped": dropped, **({"conflict": True} if (auto or {}).get("conflict") else {}),
                            **({"invalid": auto["invalid"]} if (auto or {}).get("invalid") else {})}

    def fresh_problem(self, pb) -> dict | None:
        """이번 이슈 입력(과 `--steps-file`)으로 만든 `problem.json` 내용 | None(없음 — 있는데 못 쓰면 경고)."""
        path = self.job / pb.RESULT_FILE
        if path.is_symlink() or not path.is_file():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        if not isinstance(doc, dict) or doc.get("schema_version") != 1:
            self.warn("문제 파악 결과(problem.json)를 읽지 못해 쓰지 않았다")
            return None
        if not self.issue_sha:      # 해시 기록 전(이전 버전)에 Jira 원문을 읽고 지운 작업
            self.warn("이 작업에는 이슈 입력 해시 기록이 없어 문제 파악 결과(problem.json)를 쓰지 않았다 — "
                      "Jira를 다시 읽고 triage.py problem부터 다시")
            return None
        if doc.get("source_sha256") != self.issue_sha:
            self.warn("문제 파악 결과(problem.json)가 이번 이슈 입력으로 만든 것이 아니라 쓰지 않았다 — triage.py problem부터 다시")
            return None
        steps = getattr(self.args, "steps_file", None)
        if steps:       # TC 파일을 주었으면 문제 파악 때의 TC 파일과도 같아야 한다(TC의 실패 줄·사유가 문제 파악 입력이다)
            try:
                sha = hashlib.sha256(Path(steps).expanduser().read_bytes()).hexdigest()
            except OSError:
                sha = None
            if sha is None or doc.get("steps_sha256") != sha:
                self.warn("문제 파악 결과(problem.json)가 이번 TC 파일(--steps-file)로 만든 것이 아니라 쓰지 않았다 — "
                          "같은 --steps-file로 triage.py problem부터 다시")
                return None
        return doc

    def comment_clues(self, pb, conf: dict, switch) -> tuple[list[dict], dict | None]:
        """`JOB/issue.json` 코멘트·설명(가린 글)에서 스크립트로 뽑은 단서 → (단서, 버림 수). 쓰지 않으면 ([], None):
        설정 `eligibility.comment_clues` 거짓, 이슈 글 없음(오프라인 `--issue-meta`), `--look-at` 있음(뽑힌 수만 경고),
        Jira 코멘트를 일부만 읽음(`text.comments_partial` — 최근 코멘트가 빠졌을 수 있어 회차를 못 가린다, 경고), 코멘트의 전체 수나
        순서를 모름(`text.comments_unchecked` — 뽑힌 수만 경고)."""
        if not switch("comment_clues"):
            return [], None
        try:
            text = json.loads((self.job / "issue.json").read_text(encoding="utf-8")).get("text")
        except (OSError, ValueError, AttributeError):
            return [], None
        # 기준 줄을 로그에서 **찾았을 때만** 코멘트 단서를 버린다 — 넣었지만 못 찾았으면 단서가 다음 기준이다(sim1121 S-15)
        look_at = bool((self.look_result or {}).get("hits"))
        if isinstance(text, dict) and not text.get("comments") and type(text.get("comments_skipped")) is int and not look_at:
            # 코멘트를 하나도 못 받았다(앞을 모두 건너뜀 — 포털이 8KB 넘는 마지막 코멘트 때문에 넘기지 않음, D3). 일부만 읽음과 다르다
            # 포털이 이 머리("마지막 댓글이 길어")로 알아본다(포털 fix/sim-1121) — 머리를 바꾸면 포털 표도 같이
            self.warn(f"마지막 댓글이 길어 포털이 댓글을 넘기지 않음(Jira 코멘트 {text['comments_skipped']}개 모두 못 받음) — 코멘트 "
                      "단서를 쓰지 못했다. 실패 지점(기준 줄)을 직접 넣거나 문제 파악으로")
        if not isinstance(text, dict) or not (text.get("comments") or text.get("description")):
            return [], None
        part = text.get("comments_partial")
        if isinstance(part, dict):
            if not look_at:
                self.warn(f"Jira 코멘트를 일부만 읽어(전체 {part.get('total')}개 중 {part.get('read')}개) 코멘트 단서를 뽑지 "
                          "않았다 — 최근 코멘트가 빠졌을 수 있다")
            return [], None
        unchecked = text.get("comments_unchecked")
        words = conf.get("retest_words", pb.RETEST_WORDS)
        if not (isinstance(words, list) and all(isinstance(w, str) for w in words)):
            if "retest_words" in conf:
                self.warn("설정 eligibility.retest_words 값이 글자 목록이 아니라 기본 재시험 낱말로 본다")
            words = pb.RETEST_WORDS
        vipc = platforms.load(self.defaults, getattr(self.args, "platform_name", None), require_enabled=False).vendor_ipc
        skipped = text.get("comments_skipped")
        clues, drop = pb.extract_clues([str(c) for c in text.get("comments") or []], str(text.get("description") or ""),
                                       vipc.request_prefix, vipc.error_prefix, words,
                                       first=skipped + 1 if type(skipped) is int and skipped > 0 else 1)
        if look_at or unchecked:
            if clues:
                self.warn(f"코멘트 단서 {len(clues)}개 안 씀 — " + ("기준 줄(--look-at)을 썼다" if look_at else
                          "Jira 코멘트의 전체 수·순서를 알 수 없다(코멘트 total·작성 시각 없음)"))
            return [], None
        return clues, drop

    def find_clues(self, logs: list[Path], tz: str | None, year: int | None, texts: list[tuple[str, str | None]]) -> list[dict]:
        """단서 찾을 글 `(글, 붙인 줄의 logcat 시각|None)` 목록 → 찾기 결과 목록(같은 순서). 로그는 한 번만 읽는다
        (`parse_logcat ipc --find JOB/clue-at.json`의 `{finds: […]}`, trace 단계 `3-clue`)."""
        if not texts:
            return []
        path = self.job / CLUE_FILE
        path.write_text(json.dumps({"finds": [{"look_at": t, "ref": None, **({"stamp": st} if st else {})} for t, st in texts]},
                                   ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        argv = ["ipc", *logs, "--rules", self.snap / "parser-rules", "--find", path]
        argv += (["--tz", tz] if tz else []) + (["--year", year] if year else [])
        _, data, _ = self.run.call("3-clue", "parse_logcat.py", argv)
        for w in (data or {}).get("warnings") or []:
            self.warn(_clip(w.get("message"), 120))
        founds = (data or {}).get("finds") or []
        return [f if isinstance(f, dict) else {} for f in founds] + [{}] * (len(texts) - len(founds))

    def clue_location(self, via: dict | None) -> dict | None:
        """앵커 없이 단서만 찾았을 때의 실패 지점(analysis.json `decision.location`): source comment, state found(확정 아님) —
        단서 일치가 여러 곳이면 multiple. kind는 사건이 붙은 단서(`via`, 없으면 첫 단서) 기준 ipc·token 일치 point·글자 일치 near.
        단서가 없으면 None."""
        refs = (self.problem_use or {}).get("refs") or []
        if not refs:
            return None
        ref = via or refs[0]
        many = (ref.get("places") or 1) > 1 if via else any((r.get("places") or 1) > 1 for r in refs)
        return {"state": "multiple" if many else "found", "source": "comment",
                "kind": "near" if ref.get("how") in ("text", "words") else "point"}

    def look_inputs(self) -> dict:
        """`--look-at`·`--look-note`(선택, 원문)를 이 프로세스에서 이슈 DB 설정대로 가린 값 `{at, note}`(없으면 None).
        원문은 여기서만 쓴다 — 하위 스크립트에는 가린 값을 담은 `JOB/look-at.json` 경로만 넘긴다(trace.jsonl에 원문 없음)."""
        if self._look is None:
            at, note = getattr(self.args, "look_at", None), getattr(self.args, "look_note", None)
            masked = self.masker(log_lines=True)(at) if at else None
            self._look = {"at": (lookat.clean(masked) or None) if at else None,
                          "note": (" ".join(self.masker()(note).split()) or None) if note else None,
                          # 붙여 넣은 줄의 logcat 시각, 없으면 앞의 날짜 없는 시각(`HH:MM:SS.mmm`) — 같은 곳 고르기(단계 5)
                          "stamp": lookat.stamp(masked) or lookat.clock(masked)}
            if at and getattr(self.args, "look_at_source", None) == "model":      # 모델이 코멘트에서 고른 줄(담당자 지정 아님)
                self._look["source"] = "model"
        return self._look

    def look_span(self, logs: list[Path], tz: str | None, year: int | None, jira_at) -> dict | None:
        """기준 줄을 로그에서 찾아(`parse_logcat ipc --find`) 그 줄 시각을 실패 시각으로 하는 span. 없거나 못 찾으면 None.
        결과 요약은 `self.look_result`(`{hits, picked, pick, how, ts, line, at}` | `{hits: 0, why}`)에 둔다."""
        text = self.look_inputs()["at"]
        if not text:
            if getattr(self.args, "look_at", None) and self.look_inputs()["stamp"]:     # 시각만 적은 기준 줄(`16:50:42`)
                self.warn(LOOK_TIME_ONLY)
            return None
        path = self.job / LOOK_FILE
        stamp = self.look_inputs()["stamp"]
        path.write_text(json.dumps({"look_at": text, "ref": lc.format_ts(jira_at) if jira_at else None,
                                    **({"stamp": stamp} if stamp else {})}, ensure_ascii=False)
                        + "\n", encoding="utf-8", newline="\n")
        argv = ["ipc", *logs, "--rules", self.snap / "parser-rules", "--find", path]
        argv += (["--tz", tz] if tz else []) + (["--year", year] if year else [])
        _, data, _ = self.run.call("3-lookat", "parse_logcat.py", argv)
        for w in (data or {}).get("warnings") or []:
            self.warn(_clip(w.get("message"), 120))
        found = (data or {}).get("find") or {}
        # 날짜 붙은 logcat 시각의 줄이 이 로그에 없다 — 코멘트 단서와 같은 규칙(다른 날·다른 로그의 줄을 본문만으로 잡지 않게, 코덱스 K01).
        # 날짜 없는 시각(`16:50:42`)은 장비 시계일 수 있어 지금처럼 같은 시각 고르기에만 쓴다
        if not lookat.CLOCK_ONLY.fullmatch(stamp or "") and _stamp_unmet(stamp, found):
            found = {"hits": 0, "why": "붙인 줄의 시각이 이 로그에 없음"}
        if not found.get("hits"):
            self.look_result = {"hits": 0, "why": _clip(found.get("why") or "결과 없음", 60)}
            self.warn(f"기준 줄을 로그에서 못 찾음({self.look_result['why']}) — 다음 출처로 분석 구간을 정했다")
            return None
        self.look_result = {k: found.get(k) for k in ("hits", "picked", "pick", "how", "ts", "line", "at", "places")}
        self.look_place = found.get("place") or []      # 자격 검사 기준 줄(reference_of) — 캐시·analysis.json에는 안 나간다
        ts = stepanchor._ts(found["ts"])
        return {"source": "look_at", "step": None, "step_from": None, "start": None, "fail": ts, "end": ts}

    def marker_span(self, logs: list[Path], tz: str | None, year: int | None, conf: dict, jira_at) -> dict | None:
        """로그 마커 > steps-file 시각 > steps-file 스텝 순서로 실패 구간 span. 마커 패턴·steps-file이 없으면 None."""
        site = self.defaults.get("failed_step") or {}
        steps_file = getattr(self.args, "steps_file", None)
        if not site.get("marker_patterns") and not steps_file:
            return None
        argv = ["markers", *logs, "--rules", self.snap / "parser-rules"]
        if tz:
            argv += ["--tz", tz]
        if year:
            argv += ["--year", year]
        step_rules = self.step_event_rules() if steps_file else []
        if step_rules:      # 스텝 이름은 인자로 넘기지 않는다: 규칙은 이슈 DB 설정에서 파서가 읽는다
            argv.append("--step-events")
        _, data, _ = self.run.call("3-markers", "parse_logcat.py", argv)
        data = data or {}
        for w in data.get("warnings") or []:
            self.warn(_clip(w.get("message"), 120))
        cov = data.get("coverage") or {}
        first, last = stepanchor._ts(cov.get("first_ts")), stepanchor._ts(cov.get("last_ts"))
        failed = self.failed_step["text"] if self.failed_step else None
        max_span = {**stepanchor.DEFAULT_WINDOW, **(conf.get("window") or {})}["max_span_sec"]

        def inside(t) -> bool:
            return bool(first and last and first <= t <= last)

        span = None
        if data.get("markers"):
            span, warns = stepanchor.find_span(data["markers"], failed, jira_at, conf.get("anchor_without_step", True),
                                               max_span_sec=max_span)
            for w in warns:
                self.warn(w)
            if span and not inside(span["fail"] or span["end"]):
                self.warn(f"스텝 마커의 실패 시각({lc.format_ts(span['fail'] or span['end'])})이 로그 범위 밖이라 쓰지 않았다")
                span = None
        if span is None and steps_file:
            span = self.steps_file_span(steps_file, tz, year, conf, jira_at, first, inside, last, bool(data.get("yearless")))
        if span is None and steps_file:
            span = self.step_order_span(data, step_rules, conf, last)
        return span

    def step_event_rules(self) -> list:
        """스냅샷 `issue-db.config.yaml`의 `step_events`(없거나 형식이 틀리면 빈 목록). 규칙 번호 = 목록 위치."""
        try:
            rules = compat.load_db_config(self.snap).get("step_events")
        except Exception:    # noqa: BLE001 — 호환성 문제는 compat 단계가 보고한다
            return []
        return [r for r in rules] if isinstance(rules, list) else []

    def step_order_span(self, data: dict, step_rules: list, conf: dict, last) -> dict | None:
        """steps-file의 스텝 순서를 로그의 흔적과 맞춰 실패 구간을 정한다(장비 시각을 쓰지 않는다). 못 정하면 None(경고)."""
        steps, fidx, warns, _ = self.steps_info()
        for w in warns:
            self.warn(self.masker()(w))     # FAIL 못 찾음 경고에는 읽은 표 머리(TC 원문)가 실린다
        if not fidx:            # FAIL 스텝이 없거나 앞선 PASS 스텝이 없으면 순서로 정할 것이 없다
            return None
        masker = self.masker()
        labels = [failedstep.label(row, masker) for row in steps]
        rule_of: dict[int, int | None] = {}
        for k, text in enumerate(labels):
            rule_of[k] = None
            for i, rule in enumerate(step_rules):
                pattern = rule.get("pattern") if isinstance(rule, dict) else None
                try:
                    hit = bool(pattern) and re.search(str(pattern), text)
                except re.error:
                    hit = False
                if hit:      # 처음 맞는 규칙이 이긴다. observable: false면 관측 불가
                    rule_of[k] = None if rule.get("observable") is False else i
                    break
        truncated = [r for w in data.get("warnings") or [] if w.get("code") == "step-events-truncated"
                     for r in w.get("truncated_rules") or []]
        cfg = {"order": conf.get("order"), "window": conf.get("window"),
               "coverage_last": last, "truncated_rules": truncated}
        result, info, more = stepanchor.order_walk(steps, fidx, rule_of, data.get("step_events") or [], cfg)
        for w in more:
            self.warn(w)
        summary = {k: info[k] for k in ("matched", "observable", "missed")}
        if result is None:
            self.order_fail = {**summary, "reason": info["reason"]}
            self.warn(f"스텝 순서 정렬 안 함: {info['reason']}")      # 다음 출처(입력한 시각 또는 로그 전체)는 리포트 줄이 말한다
            return None
        evidence = [(labels[k], ts, lab) for k, ts, lab in info["evidence"]]
        self.order_evidence = evidence
        self.check_failed_step_row(labels[fidx])
        order = {**summary, "unobservable": info["unobservable"],
                 "last": {"step": _clip(labels[result["last_step"]], 40), "ts": evidence[-1][1]},
                 "last_label": labels[result["last_step"]]}
        return {"source": "step_order", "step": labels[fidx] or None, "step_from": "failed_step",
                "start": result["start"], "fail": result["fail"], "end": result["end"], "order": order}

    def steps_info(self):
        """`failedstep.read_steps` 결과(스텝 목록, 실패 위치, 경고, zip 멤버) — steps-file을 한 번만 읽는다. 원문은 이 프로세스 안에서만 쓴다."""
        if self._steps is None:
            path = getattr(self.args, "steps_file", None)
            self._steps = failedstep.read_steps(path, userconfig.get(self.cfg, "failed_step") or {}) if path else ([], None, [], None)
        return self._steps

    def check_failed_step_row(self, row_label: str) -> None:
        """cli·Jira의 실패 스텝과 steps-file의 FAIL 스텝이 다르면 경고한다(구간은 steps-file 쪽으로 정한다)."""
        fs = self.failed_step
        if fs and fs.get("source") != "steps_file" and not stepanchor.same_step(row_label, fs["text"]):
            self.warn(f"실패 스텝({fs['source']})과 steps-file의 FAIL 스텝이 다르다 — 구간은 steps-file 순서로 정했다")

    def tc_date_ref(self, steps_file, conf: dict, zone, first, last, times: list, yearless: bool = False):
        """TC 머리 날짜(`failedstep.head_date`, 이름표 줄만)로 스텝 시각 기준 → 그 날짜(steps-file 시간대)의 실패 행 첫 시각 UTC | None
        (못 읽음·로그 해 ±1년 밖). `times`(첫 스텝부터 실패 스텝까지 시각 칸 원문)의 시각이 앞보다 1시간 넘게 작아질 때마다(자정
        넘김) 하루씩 올린다 — 머리 시작 이름표 줄에 시각이 있으면 그것이 첫 비교값(RP-11, 다른 이름표 줄의 시각은 쓰지 않는다 CP-6).
        기준을 실패 행 첫 시각으로 두면 행 안의 넘김(시작 23:59:50, 실패 00:00:20)은 `steps_file_times`의 12시간 규칙이 맞춘다(CP-5).
        머리 날짜가 로그 첫~끝 날짜에 없으면 `TC_DATE_DIFF` 경고(시계 차를 몰라도 낸다 — 하루 넘는 차이는 시계 차가 아니다. ±1년 밖이어도
        경고는 낸다 CP-7). `yearless`(로그 줄에 연도가 없어 `--year`로 읽음)면 월·일만 비교하고 로그의 해를 쓴다 — 가정한 해와 TC 해가
        달라도 같은 날이다(oFono 확인 P1-1)."""
        text, _ = failedstep.read_lines(steps_file)
        got = failedstep.head_date(text, conf) if text is not None else None
        if got is None:
            return None
        (y, mo, d), clock = got
        try:
            local = lc.get_tz(zone)
        except ValueError:      # 알 수 없는 타임존 — steps_file_times가 같은 경고를 낸다
            return None
        fit = None
        if first and last:
            days = sorted({first.astimezone(local).date(), last.astimezone(local).date()})
            for yy in sorted({days[0].year, days[-1].year}) if yearless else (y,):
                try:
                    tc_day = datetime(yy, mo, d).date()
                except ValueError:      # 2-29를 평년으로
                    continue
                if days[0] <= tc_day <= days[-1]:
                    fit = yy
                    break
            if fit is None:
                span = days[0].isoformat() + (f"~{days[-1].isoformat()}" if days[-1] != days[0] else "")
                self.warn(TC_DATE_DIFF.format(tc=f"{y:04d}-{mo:02d}-{d:02d}", log=span))
        if fit is not None:
            y = fit
        elif first and abs(y - first.astimezone(local).year) > 1:      # 해가 동떨어지면 시험 날짜가 아니다(경고는 위에서 냈다)
            return None
        prev = clock[0] * 3600 + clock[1] * 60 + clock[2] if clock else None
        wraps, sec = 0, 0
        for raw in times:
            m = _CLOCK_RE.search(str(raw or ""))
            if not m:
                sec = 0
                continue
            sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            if prev is not None and sec < prev - 3600:      # ponytail: 1시간 넘게 거꾸로 가면 자정 넘김으로 본다(스텝 순서 흔들림은 무시)
                wraps += 1
            prev = sec
        return (datetime(y, mo, d, tzinfo=local) + timedelta(days=wraps, seconds=sec)).astimezone(timezone.utc)

    def steps_file_span(self, steps_file, tz, year, conf: dict, jira_at, first, inside, last=None, yearless=False) -> dict | None:
        steps, fidx, warns, _ = self.steps_info()
        for w in warns:
            self.warn(self.masker()(w))     # FAIL 못 찾음 경고에는 읽은 표 머리(TC 원문)가 실린다
        row = steps[fidx] if fidx is not None else None
        if row is not None:      # 표의 FAIL 스텝(첫 FAIL = 마지막으로 실행된 스텝)의 시각
            line, label = row.get("time_raw"), failedstep.label(row, self.masker())
        else:                    # 표로 읽지 못하면 failed_step_patterns에 맞는 줄에서
            text, _ = failedstep.read_lines(steps_file)     # 읽지 못한 경고는 resolve_failed_step이 이미 냈다
            if text is None:
                return None
            # 표(열 이름 줄)를 읽었는데 FAIL 스텝이 없으면 패턴으로 다른 줄을 잡지 않는다 — "FAIL 스텝을 찾지 못했다" 경고와 같은
            # 쪽으로(요약 표 `Verdict | FAIL`·번호 없는 프리앰블 `P | … | FAIL` 줄을 실패 지점으로 정하지 않게, sim1121 리뷰)
            if failedstep.header_line(text, conf) is not None:
                return None
            patterns = userconfig.get(self.cfg, "tracker.failed_step_patterns") or []
            step, line = failedstep.find_line(text, patterns)
            if step is None:        # 패턴에도 맞는 줄이 없다 — FAIL 스텝을 못 찾은 경고는 read_steps가 이미 냈다
                return None
            label = failedstep.normalize(self.masker()(failedstep.numbered(step, line) or ""), 80)
        zone = conf.get("steps_file_tz") or tz or userconfig.get(self.cfg, "logcat.timezone")
        times = [r.get("time_raw") for r in steps[: fidx + 1]] if row is not None else [line]
        tc_ref = self.tc_date_ref(steps_file, conf, zone, first, last, times, yearless)
        if not line:
            self.warn(NO_STEP_TIME)
            return None
        ref = tc_ref or jira_at or first
        try:
            start, fail = stepanchor.steps_file_times(line, zone, year or (ref.year if ref else None), ref)
        except ValueError as exc:       # 알 수 없는 타임존
            self.warn(f"steps-file 시각을 해석하지 못했다({exc}) — 앵커 없이 진행")
            return None
        if fail is None:
            self.warn(NO_STEP_TIME)
            return None
        if self.clock_offset is None:       # 장비 시계와 단말 시계는 다를 수 있다 — 맞출 수 없으면 쓰지 않는다
            self.clock = {"mode": "none", "reason": "시계 차 모름"}
            self.warn("장비 시각 미사용: 시계 정렬 불가(시계 차 모름) — --clock-offset으로 맞출 수 있다")
            return None
        shift = timedelta(seconds=self.clock_offset)
        fail += shift
        start = start + shift if start else None
        self.clock = {"mode": "manual", "offset_sec": _num(self.clock_offset)}
        if not inside(fail):
            self.warn(f"steps-file의 실패 시각({lc.format_ts(fail)})이 로그 범위 밖이라 쓰지 않았다")
            return None
        if row is not None:
            self.check_failed_step_row(label)
        return {"source": "steps_file", "step": label or None, "step_from": "failed_step",
                "start": start if start and start < fail else None, "fail": fail, "end": fail}

    def occurred(self, info: dict, logs: list[Path], tz: str | None, year: int | None) -> str | None:
        bad = None
        if self.answer("time"):
            if self.answer("time") == "full":
                return None     # 시각 없이 로그 전체 — answers["time"]은 "full"로 남긴다(캐시 키 구분)
            dt = lc.normalize_ts(self.answer("time"), tz, year)
            if dt is not None:
                # 파서(--around)는 오프셋 있는 ISO만 받는다: 타임존 없는 ISO·logcat 스탬프는 로그 tz로 정규화해 넘기고 답도 바꿔 둔다
                value = lc.format_ts(dt)
                self.state.answers["time"] = value
                if "time" in self.given:
                    self.given["time"] = value
                return value
            # 읽을 수 없는 답("…KST" 등)은 파서까지 보내지 않고 다시 묻는다 — 하위 스크립트 종료 2로 끝나지 않게 (eval 67)
            bad = self.answer("time")
            self.state.answers.pop("time", None)
            self.given.pop("time", None)
        if info.get("occurred_at"):
            return info["occurred_at"]
        full = self.parse(logs, None, tz, year, self.job / "events-full.json")
        hits = self.match(self.job / "events-full.json", None, self.job / "match-full.json", regress=True)
        times = []
        for t in hits.get("types") or []:
            if t.get("S") and t.get("evidence"):
                times.append((min(e["ts"] for e in t["evidence"]), t["type"]))
        times.sort()
        if bad is None:
            # 앵커(기준 줄을 못 찾은 경우 포함)·Jira 시각·time 답이 다 없다 → 묻지 않고 로그 전체로 간다('full' 답과 같은 경로). 찾은 시각 후보는
            # `step_anchor.time_candidates`·탐색 입력에 남기고, 이 전체 파싱은 본 분석이 다시 쓴다(`core`)
            self.time_candidates = [{"ts": ts, "type": tid} for ts, tid in times[:3]]
            self.full_events = full
            return None
        options = [{"value": ts, "label": f"{ts} {tid}"} for ts, tid in times[:3]]
        cov = full.get("coverage") or {}
        jumps = len(cov.get("clock_anomalies") or [])
        question = ("분석 기준 시각이 없다(Jira 발생 시각 칸은 쓰지 않는다). 증상 시그니처가 충족된 시각 후보에서 고르거나, 시각 없이 로그 전체로 분석한다."
                    if options else
                    "분석 기준 시각이 없다 — 후보가 없으니 시각을 답하거나 '시각 없이 로그 전체'를 고른다.")
        options.append({"value": "full", "label": "시각 없이 로그 전체"})
        # 읽을 수 없는 답을 준 경우만 다시 묻는다(사용자가 시각을 주려 했다)
        question = (f"답한 시각 '{_clip(bad, 60)}'을 읽지 못했다 — 후보 값 그대로, ISO 8601(예: 2026-09-20T14:32:00+09:00), "
                    "또는 시각 없이 보려면 'full'로 다시 답한다. " + question)
        if jumps:
            question += f" 로그에 시계 이상(역행·점프) {jumps}건 — 후보 시각이 실제와 다를 수 있다(재부팅·NITZ 전 가능)."
        extra = {}
        if hits.get("errors"):      # 판정 불가 유형(S: null)은 후보 시각에서 빠진다 — 숨기지 않는다
            n = sum(1 for t in hits.get("types") or [] if t.get("S") is None)
            m = sum(1 for c in hits.get("causes") or [] if c.get("C") is None)
            label = f"판정 불가 유형 {n}" + (f"·원인 {m}개" if m else "개")
            question += (f" {label}(시그니처 시간 초과·오류) — 후보 시각이 빠졌을 수 있다." if n else
                         f" {label}(시그니처 시간 초과·오류) — 후보 시각(증상)은 영향 없음.")
            extra["unjudged"] = n
        raise NeedsInput("time", question, options, log_range=[cov.get("first_ts"), cov.get("last_ts")], **extra)

    def anchor_out(self, anchor: dict | None, info: dict, outside: dict | None = None) -> dict | None:
        """`analysis.json`의 `step_anchor`: 앵커가 있거나 실패 스텝·시각 답 full이 있을 때만(없으면 키가 없다)."""
        if anchor:      # 기준 줄(look_at)은 스텝이 아니다 — `step`을 내지 않는다(포털이 TC 스텝으로 보이지 않게)
            out = {"source": anchor["source"],
                   "step": None if anchor["source"] == "look_at" else _clip(_step_label(anchor.get("step")), 80),
                   "step_from": anchor["step_from"] if anchor["step_from"] != "failed_step" else None,
                   "span": [anchor["start"], anchor["fail"]], "issue_gap_min": anchor.get("issue_gap_min")}
        elif self.answer("time") == "full":
            out = {"source": "none"}      # 기준 시각 없음 — 로그 전체를 봤다
        elif self.time_candidates is not None:     # 시각 입력이 없어 묻지 않고 로그 전체를 봤다 — 찾은 증상 시각 후보(≤3)
            out = {"source": "symptom_scan", "time_candidates": [dict(t) for t in self.time_candidates]}
        elif self.failed_step or self.clock or self.order_fail or self.look_result:
            # `issue` = 입력한 발생 시각(`--answer time=`·`--issue-meta` occurred_at, `given_time`) — Jira 칸 값은 아니다(D4)
            out = {"source": "issue" if info.get("occurred_at") or self.answer("time") else "symptom_scan"}
        else:
            return None
        if anchor and anchor.get("order"):
            o = anchor["order"]
            out["order"] = {"matched": o["matched"], "observable": o["observable"], "missed": o["missed"], "last": dict(o["last"])}
        elif self.order_fail:
            out["order"] = dict(self.order_fail)
        if self.clock:
            out["clock"] = dict(self.clock)
        if self.look_result:     # 기준 줄: 일치 수·고른 순번(못 찾았으면 hits 0). 4KB 압축 때 flows 다음으로 뺀다
            out["look"] = {k: self.look_result[k] for k in ("hits", "picked") if self.look_result.get(k) is not None}
        if anchor and outside and outside.get("total"):
            out["outside_errors"] = outside["total"]
        if self.focus:
            out["focus"] = self.focus[:3]
        return {k: v for k, v in out.items() if v is not None}
