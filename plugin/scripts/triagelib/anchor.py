"""실패 스텝·발생 시각·스텝 앵커 (`AnchorMixin`)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import compat, failedstep, lookat, stepanchor, userconfig
from common import logtime as lc

from .core import CLUE_FILE, LOOK_FILE, NeedsInput, _clip


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
        return f"{name} (token={token})", None
    if c.get("kind") == "ipc_name" and ok_name:
        return name, None
    if c.get("kind") == "log_line" and isinstance(quote, str) and 0 < len(quote) <= pb.QUOTE_MAX:
        return lookat.clean(quote), lookat.stamp(quote)
    return None, None


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
        jira_at = _parse_ts(info.get("occurred_at"))
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
        self.reference = self.reference_of(span)
        if span.get("order"):
            anchor["order"] = span["order"]
        if jira_at:
            gap = stepanchor.gap_minutes(fail, jira_at)
            anchor["issue_gap_min"] = round(gap, 1)
            limit = conf.get("disagree_minutes", stepanchor.DEFAULT_DISAGREE_MINUTES)
            if isinstance(limit, (int, float)) and not isinstance(limit, bool) and gap > limit:
                hint = " (Jira 시각이 장비 시각이면 시계 차 때문일 수 있다)" if span["source"] in ("steps_file", "step_order") else ""
                what = "기준 줄" if span["source"] == "look_at" else "실패 스텝"
                self.warn(f"Jira 발생 시각과 {what} 시각이 {gap:.0f}분 다르다 — {'스텝' if what == '실패 스텝' else what} 시각 "
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
            text = look.get("how") == "text"
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

    def problem_refs(self, logs: list[Path], tz: str | None, year: int | None) -> None:
        """같은 JOB의 문제 파악 결과(`problem.json`, 단계 5-2) → 자격 검사 입력 `self.problem_use`
        `{problem: {types, not_in_db}|None, comment_adopt, refs[단서 기준], dropped[{comment, kind, why}]}` | None.

        이번 실행이 읽은 이슈 입력의 해시(`self.issue_sha`)가 problem.json `source_sha256`과 같을 때만 읽는다(아니면 경고하고 무시).
        `symptom.types`·`not_in_db`(설정 `eligibility.use_problem_types`가 거짓이면 둘 다 안 씀)와 `stale: false` 단서만 쓴다 —
        hypotheses·modules·unknown·side·rounds는 판정에 쓰지 않는다. 단서는 `parse_logcat ipc --find`(기준 줄과 같은 찾기 — 값은
        문자열 비교만, 정규식·경로·명령으로 쓰지 않는다)로 찾는다: ipc = 이름+token, ipc_name = 이름 본문 일치, log_line = 인용 본문
        일치. 로그에 없는 단서는 버리고 경고("코멘트 n번 단서, 로그에서 못 찾음")와 `dropped`에 남긴다. `--answer anchor=off`면 안 읽는다."""
        from . import problem as pb      # 지연 import(문제 파악 모듈은 Jira·플랫폼 모듈을 끌어온다)

        self.problem_use, self.clue_rows = None, []
        path = self.job / pb.RESULT_FILE
        if self.anchor_off or path.is_symlink() or not path.is_file():
            return
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        if not isinstance(doc, dict) or doc.get("schema_version") != 1:
            self.warn("문제 파악 결과(problem.json)를 읽지 못해 쓰지 않았다")
            return
        if not self.issue_sha:      # 해시 기록 전(이전 버전)에 Jira 원문을 읽고 지운 작업
            self.warn("이 작업에는 이슈 입력 해시 기록이 없어 문제 파악 결과(problem.json)를 쓰지 않았다 — "
                      "Jira를 다시 읽고 triage.py problem부터 다시")
            return
        if doc.get("source_sha256") != self.issue_sha:
            self.warn("문제 파악 결과(problem.json)가 이번 이슈 입력으로 만든 것이 아니라 쓰지 않았다 — triage.py problem부터 다시")
            return
        steps = getattr(self.args, "steps_file", None)
        if steps:       # TC 파일을 주었으면 문제 파악 때의 TC 파일과도 같아야 한다(TC의 실패 줄·사유가 문제 파악 입력이다)
            try:
                sha = hashlib.sha256(Path(steps).expanduser().read_bytes()).hexdigest()
            except OSError:
                sha = None
            if sha is None or doc.get("steps_sha256") != sha:
                self.warn("문제 파악 결과(problem.json)가 이번 TC 파일(--steps-file)로 만든 것이 아니라 쓰지 않았다 — "
                          "같은 --steps-file로 triage.py problem부터 다시")
                return
        conf = userconfig.get(self.cfg, "eligibility") or {}
        conf = conf if isinstance(conf, dict) else {}
        sym = doc.get("symptom") if isinstance(doc.get("symptom"), dict) else {}
        problem = None
        if conf.get("use_problem_types", True) is not False:
            problem = {"types": [t for t in sym.get("types") or [] if isinstance(t, str)][:pb.TYPES_MAX],
                       "not_in_db": sym.get("not_in_db") is True}
        refs, dropped, seen = [], [], set()
        clues = doc.get("clues") if isinstance(doc.get("clues"), list) else []
        for c in clues[:pb.CLUES_MAX]:
            if not isinstance(c, dict) or c.get("stale") is not False:     # 이전 회차 단서(stale)는 쓰지 않는다(H03)
                continue
            text, stamp = _clue_text(c, pb)
            if text is None or (text, stamp) in seen:      # 같은 찾을 글은 한 번만(같은 곳을 두 단서로 세지 않게)
                continue
            seen.add((text, stamp))
            where = "설명" if c.get("comment") == "description" else f"코멘트 {c.get('comment')}번"
            find = self.job / CLUE_FILE
            find.write_text(json.dumps({"look_at": text, "ref": None, **({"stamp": stamp} if stamp else {})},
                                       ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            argv = ["ipc", *logs, "--rules", self.snap / "parser-rules", "--find", find]
            argv += (["--tz", tz] if tz else []) + (["--year", year] if year else [])
            _, data, _ = self.run.call("3-clue", "parse_logcat.py", argv)
            for w in (data or {}).get("warnings") or []:
                self.warn(_clip(w.get("message"), 120))
            found = (data or {}).get("find") or {}
            if not found.get("hits"):
                why = _clip(found.get("why") or "일치하는 줄 없음", 60)
                dropped.append({"comment": c.get("comment"), "kind": c["kind"], "why": why})
                self.warn(f"{where} 단서, 로그에서 못 찾음({why})")
                continue
            refs.append({"kind": "line", "source": "comment", "comment": c.get("comment"), "clue": c["kind"],
                         "how": found.get("how"), "places": found.get("places") or 1, "lines": found.get("place") or []})
            self.clue_rows.append({"where": where, "clue": c["kind"], "ts": found.get("ts"), "places": refs[-1]["places"]})
        self.problem_use = {"problem": problem, "comment_adopt": conf.get("comment_adopt", True) is not False, "refs": refs,
                            "dropped": dropped}

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
                "kind": "near" if ref.get("how") == "text" else "point"}

    def look_inputs(self) -> dict:
        """`--look-at`·`--look-note`(선택, 원문)를 이 프로세스에서 이슈 DB 설정대로 가린 값 `{at, note}`(없으면 None).
        원문은 여기서만 쓴다 — 하위 스크립트에는 가린 값을 담은 `JOB/look-at.json` 경로만 넘긴다(trace.jsonl에 원문 없음)."""
        if self._look is None:
            at, note = getattr(self.args, "look_at", None), getattr(self.args, "look_note", None)
            masked = self.masker(log_lines=True)(at) if at else None
            self._look = {"at": (lookat.clean(masked) or None) if at else None,
                          "note": (" ".join(self.masker()(note).split()) or None) if note else None,
                          "stamp": lookat.stamp(masked)}     # 붙여 넣은 줄의 logcat 시각(같은 곳 고르기, 단계 5)
        return self._look

    def look_span(self, logs: list[Path], tz: str | None, year: int | None, jira_at) -> dict | None:
        """기준 줄을 로그에서 찾아(`parse_logcat ipc --find`) 그 줄 시각을 실패 시각으로 하는 span. 없거나 못 찾으면 None.
        결과 요약은 `self.look_result`(`{hits, picked, pick, how, ts, line, at}` | `{hits: 0, why}`)에 둔다."""
        text = self.look_inputs()["at"]
        if not text:
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
            span = self.steps_file_span(steps_file, tz, year, conf, jira_at, first, inside)
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
            patterns = userconfig.get(self.cfg, "tracker.failed_step_patterns") or []
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
        question = ("Jira에 발생 시각이 없다. 증상 시그니처가 충족된 시각 후보에서 고르거나, 시각 없이 로그 전체로 분석한다."
                    if options else
                    "Jira에 발생 시각이 없다 — 후보가 없으니 시각을 답하거나 '시각 없이 로그 전체'를 고른다.")
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
            out = {"source": "issue" if info.get("occurred_at") and not self.answer("time") else "symptom_scan"}
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
