"""실패 스텝·발생 시각·스텝 앵커 (`AnchorMixin`)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import compat, failedstep, stepanchor, userconfig
from platforms.android import logcat as lc

from .core import NeedsInput, _clip


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


def _step_label(step) -> str:
    """마커의 스텝 값 → 표시 이름(번호만이면 `Step N`)."""
    text = str(step or "").strip()
    return f"Step {text}" if re.fullmatch(r"\d{1,4}", text) else text or "스텝 미상"


class AnchorMixin:
    def resolve_failed_step(self, auto: dict | None, masker) -> dict | None:
        """auto(이미 마스킹) + 이번 실행의 플래그 → 마스킹된 {text, source} | None. 원문은 이 함수 안에서만 쓴다."""
        a = self.args
        patterns = userconfig.get(self.cfg, "jira.failed_step_patterns") or []
        result, warns = failedstep.resolve(getattr(a, "failed_step", None), auto, getattr(a, "steps_file", None), patterns, masker,
                                           userconfig.get(self.cfg, "failed_step") or {})
        for w in warns:
            if w not in self.warnings:
                self.warnings.append(w)
        return result

    def apply_failed_step(self, data: dict, meta_path: Path) -> None:
        """`jira.json`(extract 결과)에 실패 스텝을 맞춘다. 바뀐 것이 있을 때만 `jira.json`·`jira_meta.json`을 다시 쓴다."""
        for w in data.get("warnings") or []:
            if w not in self.warnings:
                self.warnings.append(str(w))
        self.failed_step = self.resolve_failed_step(data.get("failed_step_auto"), self.masker())
        if self.failed_step == data.get("failed_step"):
            return
        jira = data.setdefault("jira", {})
        if self.failed_step:
            data["failed_step"] = self.failed_step
            jira["failed_step"] = self.failed_step["text"]
        else:
            data.pop("failed_step", None)
            jira.pop("failed_step", None)
        (self.job / "jira.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
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
            self.out["jira"]["failed_step"] = {"text": _clip(self.failed_step["text"], 120),
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
        if source == "jira" or not source:
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

    def step_anchor(self, logs: list[Path], tz: str | None, year: int | None, info: dict) -> dict | None:
        """실패 스텝 앵커(로그 마커 > steps-file) → `{source, step, step_from, start, fail, window}` | None.

        마커 패턴(`site-defaults.yaml`의 `failed_step.marker_patterns`, 사용자 config로 바꿀 수 없다)이 있거나 `--steps-file`이
        있을 때만 `parse_logcat markers`를 돌린다. 앵커의 실패 시각이 로그 범위 밖이면 경고하고 다음 출처로 넘어간다.
        steps-file의 원문 줄은 이 프로세스 안에서 시각만 뽑고 버린다."""
        self.anchor_off = self.answer("anchor") == "off"
        if self.anchor_off:
            return None
        site = self.defaults.get("failed_step") or {}
        steps_file = getattr(self.args, "steps_file", None)
        if not site.get("marker_patterns") and not steps_file:
            return None
        conf = userconfig.get(self.cfg, "failed_step") or {}
        if self.clock_offset is None and conf.get("clock_offset") is not None:
            self.clock_offset = stepanchor.parse_offset(conf["clock_offset"])
            if self.clock_offset is None:
                self.warn(f"failed_step.clock_offset 형식이 맞지 않아 쓰지 않았다({str(conf['clock_offset'])[:40]})")
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
        jira_at = _parse_ts(info.get("occurred_at"))
        failed = self.failed_step["text"] if self.failed_step else None
        window_cfg = {"window": conf.get("window")}
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
            span = self.steps_file_span(steps_file, tz, year, conf, jira_at, first, inside)
        if span is None and steps_file:
            span = self.step_order_span(data, step_rules, conf, last)
        if span is None:
            return None
        fail = span["fail"] or span["end"]
        if span["source"] == "step_order":
            start, end = span["start"], span["end"]
        else:
            start, end, warns = stepanchor.window(span, window_cfg)
            for w in warns:
                self.warn(w)
        anchor = {"source": span["source"], "step": span.get("step"), "step_from": span["step_from"],
                  "start": lc.format_ts(span["start"]) if span.get("start") else None, "fail": lc.format_ts(fail),
                  "window": (lc.format_ts(start), lc.format_ts(end))}
        if span.get("order"):
            anchor["order"] = span["order"]
        if jira_at:
            gap = stepanchor.gap_minutes(fail, jira_at)
            anchor["jira_gap_min"] = round(gap, 1)
            limit = conf.get("disagree_minutes", stepanchor.DEFAULT_DISAGREE_MINUTES)
            if isinstance(limit, (int, float)) and not isinstance(limit, bool) and gap > limit:
                hint = " (Jira 시각이 장비 시각이면 시계 차 때문일 수 있다)" if span["source"] in ("steps_file", "step_order") else ""
                self.warn(f"Jira 발생 시각과 실패 스텝 시각이 {gap:.0f}분 다르다 — 스텝 시각 기준으로 분석했다"
                          f"(끄기: --answer anchor=off){hint}")     # 경고만 낸다. 구간은 바꾸지 않는다
        return anchor

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
            self.warn(w)
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
            self.warn(f"스텝 순서 정렬 안 함: {info['reason']} — Jira 발생 시각 기준으로 분석했다")
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

    def steps_file_span(self, steps_file, tz, year, conf: dict, jira_at, first, inside) -> dict | None:
        steps, fidx, warns, _ = self.steps_info()
        for w in warns:
            self.warn(w)
        row = steps[fidx] if fidx is not None else None
        if row is not None:      # 표의 FAIL 스텝(첫 FAIL = 마지막으로 실행된 스텝)의 시각
            line, label = row.get("time_raw"), failedstep.label(row, self.masker())
        else:                    # 표로 읽지 못하면 failed_step_patterns에 맞는 줄에서
            text, _ = failedstep.read_lines(steps_file)     # 읽지 못한 경고는 resolve_failed_step이 이미 냈다
            if text is None:
                return None
            patterns = userconfig.get(self.cfg, "jira.failed_step_patterns") or []
            step, line = failedstep.find_line(text, patterns)
            label = failedstep.normalize(self.masker()(failedstep.numbered(step, line) or ""), 80)
        if not line:
            return None
        zone = conf.get("steps_file_tz") or tz or userconfig.get(self.cfg, "logcat.timezone")
        ref = jira_at or first
        try:
            start, fail = stepanchor.steps_file_times(line, zone, year or (ref.year if ref else None), ref)
        except ValueError as exc:       # 알 수 없는 타임존
            self.warn(f"steps-file 시각을 해석하지 못했다({exc}) — 앵커 없이 진행")
            return None
        if fail is None:
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

    def occurred(self, info: dict, logs: list[Path], tz: str | None, year: int | None) -> str:
        if self.answer("time"):
            return self.answer("time")
        if info.get("occurred_at"):
            return info["occurred_at"]
        full = self.parse(logs, None, tz, year, self.job / "events-full.json")
        hits = self.match(self.job / "events-full.json", None, self.job / "match-full.json", regress=True)
        times = []
        for t in hits.get("types") or []:
            if t.get("S") and t.get("evidence"):
                times.append((min(e["ts"] for e in t["evidence"]), t["type"]))
        times.sort()
        options = [{"value": ts, "label": f"{ts} {tid}"} for ts, tid in times[:3]]
        cov = full.get("coverage") or {}
        jumps = len(cov.get("clock_anomalies") or [])
        question = ("Jira에 발생 시각이 없다. 증상 시그니처가 충족된 시각 후보에서 고르게 한다"
                    + ("." if options else " — 후보가 없으니 시각을 묻는다."))
        if jumps:
            question += f" 로그에 시계 이상(역행·점프) {jumps}건 — 후보 시각이 실제와 다를 수 있다(재부팅·NITZ 전 가능)."
        raise NeedsInput("time", question, options, log_range=[cov.get("first_ts"), cov.get("last_ts")])

    def anchor_out(self, anchor: dict | None, info: dict, outside: dict | None = None) -> dict | None:
        """`analysis.json`의 `step_anchor`: 앵커가 있거나 실패 스텝이 있을 때만(없으면 키가 없다)."""
        if anchor:
            out = {"source": anchor["source"], "step": _clip(_step_label(anchor.get("step")), 80),
                   "step_from": anchor["step_from"] if anchor["step_from"] != "failed_step" else None,
                   "span": [anchor["start"], anchor["fail"]], "jira_gap_min": anchor.get("jira_gap_min")}
        elif self.failed_step or self.clock or self.order_fail:
            out = {"source": "jira" if info.get("occurred_at") and not self.answer("time") else "symptom_scan"}
        else:
            return None
        if anchor and anchor.get("order"):
            o = anchor["order"]
            out["order"] = {"matched": o["matched"], "observable": o["observable"], "missed": o["missed"], "last": dict(o["last"])}
        elif self.order_fail:
            out["order"] = dict(self.order_fail)
        if self.clock:
            out["clock"] = dict(self.clock)
        if anchor and outside and outside.get("total"):
            out["outside_errors"] = outside["total"]
        if self.focus:
            out["focus"] = self.focus[:3]
        return {k: v for k, v in out.items() if v is not None}
