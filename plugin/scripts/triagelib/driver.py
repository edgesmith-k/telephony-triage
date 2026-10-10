"""analyze Step 0~5 드라이버 (`Driver`, 믹스인: anchor·cache·report)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from common import compat, events, failedstep, masking, stepanchor, userconfig
from common.exitcodes import CHECK_FAILED, USAGE

from .anchor import AnchorMixin, _parse_ts
from .cache import CacheMixin, State, _digest, _file_sha
from .core import (ERROR_EVENT_RE, EXPLORE_INPUT_FILE, EXPLORE_MAX_LINES, EXPLORE_WHEN, Fail, NeedsInput, Runner,
                   SEARCH_LIMIT, SNAPSHOT_DIR, STATE_FILE, Stopped, TIMELINE_FILE, TOP, _clip, _module)
from .report import ReportMixin, _ref_label, _unique_evidence


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


def _unjudged_label(u: dict) -> str:
    """`판정 불가 유형 N개` 또는 `판정 불가 유형 N·원인 M개`."""
    return f"판정 불가 유형 {u['count']}" + (f"·원인 {u['cause_count']}개" if u.get("cause_count") else "개")


class Driver(AnchorMixin, CacheMixin, ReportMixin):
    def __init__(self, args, defaults: dict):
        self.args = args
        self.defaults = defaults
        self.cfg = userconfig.merged(defaults)
        self.key = args.key
        self.offline = args.offline_db is not None
        self.analysis_only = bool(getattr(args, "analysis_only", False))   # 이슈 DB에 기록하지 않는 분석 전용(RF-7)
        self.run = Runner(args.plugin_root)
        self.state = State(None)
        self.job: Path | None = None
        self.snap: Path | None = None
        self.locked = False
        self.warnings: list[str] = []
        self.notes: list[str] = []
        self.out: dict = {"key": self.key}
        self.failed_step: dict | None = None     # 마스킹된 {text, source}. 없으면 None (선택 값)
        self.anchor_off = False
        self.clock_offset: float | None = None   # 장비 시각 → 단말 시각 시계 차(초). --clock-offset > failed_step.clock_offset
        self._steps = None                       # read_steps 결과 캐시 (steps-file은 한 번만 읽는다)
        self.order_fail: dict | None = None      # 스텝 순서 정렬을 시도했으나 앵커를 못 정한 이유 {matched, observable, missed, reason}
        self.order_evidence: list[tuple[str, str, str]] = []   # (스텝 이름, 로그 시각, 흔적 이름) — 리포트용(마스킹됨)
        self.clock: dict | None = None           # 시계 정렬 결과 {mode: manual|none, offset_sec | reason}
        self.focus: list[str] = []               # match.step_focus.types (순위 참고용 우선 유형)
        self.steps_member: str | None = None     # steps-file이 zip일 때 읽은 멤버 경로(마스킹·≤120자) — 리포트용
        self.log_inputs: list[dict] = []         # 입력 로그 원본 [{path, name, sha, size}] (bugreport는 원본 파일)
        self.auto_invalid = False                # `code.auto_select`가 불리언이 아니었다
        self.code_auto: str | None = None        # 자동 선택한 코드 프로필(`code.auto_select`). 없으면 None
        self.reuse: dict | None = None           # 재사용 결정 {hit, run, reason?, changed?} — 오프라인·첫 실행은 None

    # 공통 ---------------------------------------------------------------------------------------

    def answer(self, kind: str):
        return self.state.answers.get(kind)

    def jira_tool(self, name: str) -> str | None:
        return userconfig.get(self.cfg, f"jira.tools.{name}") or None

    # Step 0 ---------------------------------------------------------------------------------------

    def preflight_args(self) -> None:
        a = self.args
        if getattr(a, "clock_offset", None) is not None:
            self.clock_offset = stepanchor.parse_offset(a.clock_offset)
            if self.clock_offset is None:
                raise Fail(USAGE, f"--clock-offset 형식이 맞지 않는다: {a.clock_offset!s:.40} "
                                  "(예: +3m, -90s, +1h2m3s, +00:03:00, 180 — 하루(86400초) 이내)")
        if self.analysis_only and (a.dry_run or self.offline):
            raise Fail(USAGE, "--analysis-only는 " + ("--dry-run" if a.dry_run else "--offline-db")
                       + "과 함께 쓰지 않는다(분석 전용은 이슈 DB에 기록하지 않는 실행이다).")
        if self.offline and getattr(a, "more_logs", None):
            raise Fail(USAGE, "--more-logs는 --offline-db와 함께 쓰지 않는다(이전 분석의 로그 이력이 없다) — --logs에 모두 준다.")
        if self.offline:
            if not a.out:
                raise Fail(USAGE, "--offline-db에는 --out <dir>이 필요하다.")
            if not (a.jira_meta or a.jira_file):
                raise Fail(USAGE, "--offline-db에는 --jira-meta 또는 --jira-file이 필요하다.")
            return
        if a.jira_meta:
            raise Fail(USAGE, "--jira-meta는 --offline-db(오프라인 평가)에서만 쓴다.")
        if a.jira_file and not (a.dry_run or self.analysis_only):
            raise Fail(USAGE, "--jira-file은 --dry-run 또는 --analysis-only와 함께만 받는다(실제 PR은 Jira MCP 값으로만 만든다).")
        if userconfig.load_user() is None:
            raise Fail(USAGE, "사용자 config가 없다. /telephony-triage:setup을 먼저 실행한다.")
        if not (a.jira_raw or a.jira_file) and not self.jira_tool("get_issue"):
            raise Fail(USAGE, "jira.tools.get_issue 매핑이 비어 있다. 도구 이름을 추측하지 말고 /telephony-triage:setup의 "
                              "Jira 도구 매핑을 확인한다(연습은 --dry-run --jira-file <yaml>).")

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
        self.state = State(None if self.offline else self.job / STATE_FILE)
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
                return
        choice = self.answer("lock")
        if choice == "stop":
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
        self.state.reset(owner)   # 새 세션: 이전 세션의 답·진행 상태는 쓰지 않는다
        self.state.answers.update({k: v for k, v in self.given.items() if k != "lock"})
        self.run.env["TT_LOCK_OWNER"] = owner
        self.locked = True
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
                        jira_origin=(plan.get("jira") or {}).get("origin"))
            if not self.state.data.get("pending_cleared"):
                pending = userconfig.home() / "pending-feedback"
                removed = [p.name for p in pending.glob(f"{self.key}-*.yaml")] if pending.is_dir() else []
                for name in removed:
                    (pending / name).unlink(missing_ok=True)
                info["pending_removed"] = len(removed)
                self.state.data["pending_cleared"] = True
                self.state.save()
        pending = userconfig.home() / "pending-feedback"
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
        meta_path = self.job / "jira_meta.json"
        if self.offline and a.jira_meta:
            meta = json.loads(Path(a.jira_meta).read_text(encoding="utf-8"))
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
            self.out["jira"] = {k: info[k] for k in ("origin", "occurred_at", "sw", "sim_slot")}
            self.out_failed_step()
            return info
        raw_default = self.job / "jira_raw.json"
        reuse = self.state.data.get("jira_done") and (self.job / "jira.json").is_file()
        if a.jira_raw and not Path(a.jira_raw).is_file() and reuse:
            source, origin = None, None    # 첫 실행이 --consume으로 지웠다
        elif a.jira_raw or a.jira_file:
            source, origin = Path(a.jira_raw or a.jira_file), "mcp" if a.jira_raw else "file"
        elif raw_default.is_file():
            source, origin = raw_default, "mcp"
        elif reuse:
            source, origin = None, None
        else:
            raise NeedsInput("jira", "Jira MCP로 이슈를 읽는다. 응답은 hook이 JOB/jira_raw.json에 저장하고 마스킹 요약만 보여준다. "
                                     "읽은 뒤 같은 명령을 다시 실행한다.", [],
                             tool=self.jira_tool("get_issue"), comments_tool=self.jira_tool("get_comments"),
                             save_to=str(raw_default))
        if source is not None:
            argv = ["extract", source, "--origin", origin, "--db", self.snap, "--meta-out", meta_path]
            if origin == "mcp":
                argv.append("--consume")   # 원문을 work_dir에 남기지 않는다 (08-safety.md §8.1)
            _, data, _ = self.run.call("2-jira", "jira_fields.py", argv)
            (self.job / "jira.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8", newline="\n")
            self.state.data["jira_done"] = True
            self.state.save()
        data = json.loads((self.job / "jira.json").read_text(encoding="utf-8"))
        if data.get("key") and data["key"] != self.key:
            raise Fail(USAGE, f"Jira 응답의 키({data['key']})가 {self.key}와 다르다.")
        self.apply_failed_step(data, meta_path)
        text = data.get("text") or {}
        info = {"key": self.key, "origin": data.get("origin"), "occurred_at": data.get("occurred_at"),
                "sw": (data.get("jira") or {}).get("sw"), "android_version": (data.get("jira") or {}).get("android_version"),
                "sim_slot": data.get("sim_slot"), "summary": text.get("summary") or "", "missing": data.get("missing") or [],
                "logcat": data.get("logcat") or {}, "jira_block": data.get("jira") or {}}
        self.out["jira"] = {"origin": info["origin"], "occurred_at": info["occurred_at"], "sw": info["sw"],
                            "android_version": info["android_version"], "sim_slot": info["sim_slot"],
                            "summary": _clip(info["summary"], 160),
                            "description": _clip(text.get("description"), 240),
                            "comments": len(text.get("comments") or []), "missing": info["missing"]}
        self.out_failed_step()
        return info

    # 실패 스텝(선택, 보조 정보) ----------------------------------------------------------------------

    def masker(self):
        try:
            allow = list((compat.load_db_config(self.snap).get("mask") or {}).get("allow_patterns") or [])
        except Exception:    # noqa: BLE001 — 호환성 문제는 compat 단계가 보고한다
            allow = []
        return masking.new_masker(allow_patterns=allow)

    def existing_record(self) -> None:
        _, data, _ = self.run.call("2-existing", "db_search.py", [self.key, "--db", self.snap, "--limit", SEARCH_LIMIT])
        record = next((r for r in (data or {}).get("results") or [] if r.get("kind") == "jira"), None)
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
                                                                  "--search", self.key, "--jira", self.key])
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
        parser = _module("parse_logcat")
        out, build = [], {}
        for p in resolved:
            if not parser._looks_like_bugreport(p):
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
        return out

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
        options = [{"value": c.get("name") or ",".join(f"{k}={v}" for k, v in (c.get("roots") or {}).items()),
                    "label": f"{c.get('name') or '최근'} Android {c.get('android_version') or '?'}"
                             + (" (추천)" if c.get("recommended") else "")}
                   for c in suggested.get("candidates") or []]
        options += [{"value": "<경로 또는 키=경로,…>", "label": "직접 입력"},
                    {"value": "skip", "label": "코드 분석 건너뛰기(로그 기반 분석만)"}]
        text = text or f"코드 경로를 고른다 (대상: Android {version or '?'})."
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
        profiles = {p.get("name") for p in self.cfg.get("code_profiles") or []}
        if choice not in profiles and not self.state.data.get("code_remembered"):
            self.run.call("2-1-code", "code_roots.py", ["remember", choice])
            self.state.data["code_remembered"] = True
            self.state.save()
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
        """앵커 구간 밖 Jira 발생 시각 근처의 오류 이벤트(근거·점수에 쓰지 않는다, 리포트 안내용).
        Jira 시각이 분석 구간 밖이고 로그 범위 안일 때만 마스킹 파싱을 한 번 더 한다(파일은 쓰지 않는다)."""
        jira_at = _parse_ts(info.get("occurred_at"))
        if not anchor or jira_at is None:
            return None
        start, end = _parse_ts(anchor["window"][0]), _parse_ts(anchor["window"][1])
        first, last = stepanchor._ts(cov.get("first_ts")), stepanchor._ts(cov.get("last_ts"))
        if start is None or end is None or (start <= jira_at <= end) or not (first and last and first <= jira_at <= last):
            return None
        data = self.parse(logs, info["occurred_at"], tz, year, None, step="3-parse-outside")
        errors = [self.error_row(e) for e in (data or {}).get("events") or []
                  if e.get("event") and ERROR_EVENT_RE.search(str(e["event"]))
                  and not ((t := _parse_ts(e.get("ts"))) and start <= t <= end)]    # 분석 범위 안의 이벤트는 이미 근거 후보다
        return {"at": info["occurred_at"], "total": len(errors), "rows": errors[:3]}

    def match(self, events: Path, meta: Path | None, out: Path, regress: bool = False) -> dict:
        argv = ["--db", self.snap, "--events", events, "--top", 0 if regress else TOP]
        if meta is not None:
            argv += ["--jira-meta", meta]
        if regress:
            argv.append("--regress")
        _, data, _ = self.run.call("4-match" if not regress else "2-time", "match_signatures.py", argv)
        out.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return data

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    # Step 4·5 --------------------------------------------------------------------------------------

    def cause_info(self, cause_id: str) -> dict:
        _, data, _ = self.run.call("4-db", "db_search.py", [cause_id, "--db", self.snap, "--limit", 1])
        entry = next((r for r in (data or {}).get("results") or [] if r.get("id") == cause_id), {})
        fix = entry.get("fix") or {}
        return {"resolution": _clip(entry.get("resolution"), 120),
                "resolution_verification": entry.get("resolution_verification"),
                "fix_status": fix.get("status"), "jira_count": entry.get("jira_count"),
                "jira_recent": (entry.get("jira") or [])[:3], "code_refs": entry.get("code_refs") or []}

    def resolve_code(self, code: dict | None, version: str | None, candidates: list[dict]) -> dict:
        if not code or code.get("skipped"):
            return {"skipped": True}
        resolved, moved = [], []
        for cand in candidates:
            for ref in cand.pop("_code_refs", []):
                versions = [str(v) for v in ref.get("android_versions") or []]
                if versions and version and str(version) not in versions:
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

    def explore(self, candidates: list[dict]) -> dict | None:
        """Step 5-2 탐색 분석 해당 여부: 후보 없음·원인 미확인이면 `{reason, when}`, 아니면 None.

        타임라인은 만들지 않는다(동의 뒤 `triage.py explore`가 `explore_input()`의 값으로 만든다). 판정은 하지 않는다(07-workflow.md §Step 5-2).
        """
        if candidates and candidates[0]["C"]:
            return None
        reason = "cause_unconfirmed" if candidates else "no_candidate"
        when = userconfig.get(self.cfg, "explore.when", "ask")
        if when not in EXPLORE_WHEN:
            self.warnings.append(f"explore.when 값이 잘못됐다({when}). ask로 본다")
            when = "ask"
        return {"reason": reason, "when": when}

    def explore_input(self, around: str | None, anchor: dict | None) -> dict:
        """`JOB/explore-input.json`의 내용(마스킹된 값만): 타임라인 머리·줄 수 상한. `core`에 들어가 캐시된다."""
        limit = userconfig.get(self.cfg, "explore.timeline_max_lines", EXPLORE_MAX_LINES)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 20 <= limit <= 1000:
            self.warnings.append(f"explore.timeline_max_lines 값이 잘못됐다({limit}). {EXPLORE_MAX_LINES}로 본다")
            limit = EXPLORE_MAX_LINES
        step = getattr(self, "failed_step", None)
        return {"around": around, "failed_step": step["text"] if step else None, "limit": limit,
                "anchor": {k: anchor.get(k) for k in ("source", "step", "start", "fail")} if anchor else None}

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

    def prepare(self) -> dict:
        """Step 0~2와 입력 정리(로그·코드·시간대·연도). 여기까지는 재사용 여부와 상관없이 항상 한다."""
        self.preflight_args()
        self.check_key()
        self.open_job()
        for name in (TIMELINE_FILE, EXPLORE_INPUT_FILE):    # 이전 실행의 탐색 산출물은 이번 결과가 아니다(타임라인은 동의 뒤 `explore`가 만든다)
            (self.job / name).unlink(missing_ok=True)
        if not self.offline:
            self.lock()
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
        version = info.get("android_version") or None
        code = self.code(version)
        tz = self.args.tz or (info.get("logcat") or {}).get("tz")
        year = self.year(info, logs)
        return {"info": info, "logs": logs, "version": version, "code": code, "tz": tz, "year": year}

    def write_meta(self, anchor: dict | None) -> Path | None:
        """`time` 답을 jira_meta.json에, 앵커가 있으면 match_meta.json(근접 중심 = 스텝 실패 시각)에 쓴다 → 매처에 줄 메타 경로."""
        meta_path = self.job / "jira_meta.json"
        if self.answer("time"):
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {"key": self.key}
            meta["occurred_at"] = self.answer("time")
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        match_meta = meta_path if meta_path.is_file() else None
        if anchor:      # 근접 보너스 중심을 스텝 실패 시각으로. jira_meta.json은 건드리지 않는다
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
        around = anchor["fail"] if anchor else self.occurred(info, logs, tz, year)
        events_path = self.job / "events.json"
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
                                  "_ref": _ref_label(e.get("line_ref"))}   # report.md 전용, analysis.json에는 안 나간다
                                 for e in _unique_evidence(c.get("evidence") or [])[:10]],
                    "fix_judgement": (c.get("fix_judgement") or {}).get("judgement"),
                    "fix_message": _clip((c.get("fix_judgement") or {}).get("message"), 100),
                    "related": [r.get("cause") for r in c.get("related") or []],
                    **({"clock_flags": c["clock_flags"]} if c.get("clock_flags") else {})}   # 표시 전용 (판정 불변)
            if c["cause"] is None and c["type"] in cause_unjudged:   # report.md 전용: 원인 미확인이 아니라 판정 불가
                cand["_cause_unjudged"] = True
            if c.get("version_match") is False:   # 표시 전용 (순위·score 무관)
                cand["_version_mismatch"] = c.get("android_versions")   # report.md 전용
            if c["cause"]:
                extra = self.cause_info(c["cause"])
                cand["_code_refs"] = extra.pop("code_refs")
                cand.update(extra)
            candidates.append(cand)
        no_candidate = None if candidates else self.no_candidate_hints(info, events)
        code_out = self.resolve_code(code, version, candidates)
        analyzer = self.analyzer(candidates)
        explore = self.explore(candidates)
        explore_input = self.explore_input(around, anchor) if explore and explore["when"] != "never" else None
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
        if cov.get("clock_anomalies"):
            extra_warnings.append("시계 이상(재부팅·NITZ 전 가능) — 증상 시각 스캔(--answer time=…)을 제안한다")
        member = self.steps_info()[3]
        self.steps_member = _clip(self.masker()(member), 120) if member else None
        return {
            "around": around, "anchor": anchor, "outside": outside, "candidates": candidates,
            "pending_causes": [{"cause": p["cause"], "title": _clip(p.get("title"), 50)}
                               for p in match.get("pending_causes") or []][:TOP],
            "no_candidate": no_candidate, "unjudged": unjudged, "code": code_out, "analyzer": analyzer, "explore": explore,
            "explore_input": explore_input,
            "logs": {"files": [p.name for p in logs], "window": (events.get("input") or {}).get("window"),
                     "range": [cov.get("first_ts"), cov.get("last_ts")], "in_range": cov.get("window_in_range"),
                     "clock_anomalies": len(cov.get("clock_anomalies") or []), "events": len(events.get("events") or []),
                     **({"uncollected_tags": uncollected} if uncollected else {})},
            "warnings_core": self.warnings[warn0:], "extra_warnings": extra_warnings,
            "attrs": {"clock": self.clock, "order_fail": self.order_fail, "order_evidence": self.order_evidence,
                      "focus": self.focus, "steps_member": self.steps_member},
        }

    def analyzer(self, candidates: list[dict]) -> dict | None:
        if not candidates:
            return None
        conf = (self.cfg.get("analyzers") or {}).get(candidates[0].get("category") or "")
        return {"skill": conf.get("skill"), "when": conf.get("when", "ask")} if conf else None

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
