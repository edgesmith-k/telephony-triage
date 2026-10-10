"""상태 파일(`State`)과 분석 캐시·재사용·JOB 보관 (`CacheMixin`)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from common import compat, compiled, userconfig

from .core import (ANSWER_KEYS, CACHE_FILE, CACHE_FILES, CACHE_FORMAT, PART_KEYS, RUNS_DIR, RUNS_KEEP, RUN_DIRS_KEEP,
                   SCRIPTS, STATE_SCHEMA, _now)
from .report import _top_label


def _digest(obj) -> str:
    """JSON으로 직렬화한 값의 sha256 앞 16자리(키 정렬)."""
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


# -- 상태 ----------------------------------------------------------------------------------------


class State:
    def __init__(self, path: Path | None):
        self.path = path
        self.data: dict = {}
        if path is not None and path.is_file():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.data = {}
            if not isinstance(self.data, dict):
                self.data = {}
            if self.data.get("schema") != STATE_SCHEMA:
                self.data.pop("job", None)     # 스키마 1(표시 없음) 파일: 재사용 이력 없이 첫 실행으로 본다

    def reset(self, owner: str | None) -> None:
        answers = self.data.get("answers") or {}
        # 새 세션: 답·진행 상태는 버리고 `job`(로그·실행 이력·캐시 요약)만 남긴다 — 세션이 바뀌어도 같은 입력이면 재사용한다
        self.data = {"owner": owner, "answers": answers if self.data.get("owner") == owner else {},
                     "job": self.data.get("job") or {}}

    @property
    def answers(self) -> dict:
        return self.data.setdefault("answers", {})

    @property
    def job(self) -> dict:
        return self.data.setdefault("job", {})

    def save(self) -> None:
        if self.path is None:
            return
        # lock 답(이어받기·강제 해제)은 그 실행에만 쓴다. 다음 실행에서 상황이 달라도 저절로 적용되지 않게 남기지 않는다.
        data = {**self.data, "schema": STATE_SCHEMA, "answers": {k: v for k, v in self.answers.items() if k != "lock"}}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, self.path)


class CacheMixin:
    # 입력 재사용 (RF-7) ---------------------------------------------------------------------------------

    def inputs(self, ctx: dict) -> dict:
        """결과를 정하는 입력의 부분별 해시(각 16자리 hex). 바뀐 부분 이름을 알려 주는 데 쓴다. mode·dry-run은 넣지 않는다."""
        a = self.args
        jira_path = self.job / "jira.json"
        user = dict(userconfig.load_user() or {})
        user.pop("recent_code_roots", None)      # 코드 경로를 처음 쓸 때 도구가 기록한다 — 결과와 무관
        code = ctx["code"] or {}
        steps_file = getattr(a, "steps_file", None)
        steps_sha = None
        if steps_file:
            try:
                steps_sha = _file_sha(Path(steps_file).expanduser())
            except OSError:
                steps_sha = "missing"
        scripts = sorted(p for p in SCRIPTS.rglob("*.py") if "__pycache__" not in p.parts)
        plugin_json = SCRIPTS.parent / ".claude-plugin" / "plugin.json"
        try:
            version = json.loads(plugin_json.read_text(encoding="utf-8")).get("version")
        except (OSError, json.JSONDecodeError, AttributeError):
            version = None
        plugin = [version, CACHE_FORMAT] + [[p.relative_to(SCRIPTS).as_posix(), _file_sha(p)] for p in scripts]
        return {
            "logs": _digest([{"name": f["name"], "sha": f["sha"]} for f in self.log_inputs]),
            "jira": _file_sha(jira_path) if jira_path.is_file() else None,
            "db": compiled.source_hash(self.snap, compat.load_db_config(self.snap), compiled.environment(self.defaults))[:16],
            "config": _digest({"site": self.defaults, "user": user}),
            "plugin": _digest(plugin),
            "args": _digest({"tz": ctx["tz"], "year": ctx["year"], "minutes": a.minutes,
                             "code": {k: code.get(k) for k in ("skipped", "roots", "tree_version")},
                             "clock_offset_sec": self.clock_offset, "steps_file_sha": steps_sha,
                             "answers": {k: v for k, v in sorted(self.state.answers.items()) if k in ANSWER_KEYS}}),
        }

    def reuse_check(self, parts: dict, request_hash: str) -> dict | None:
        """저장된 core가 이번 입력에 그대로 쓸 수 있으면 돌려주고(적중), 아니면 None. 결정은 `self.reuse`와 trace에 남긴다."""
        prev = self.state.job.get("cache")
        if not prev:
            return None       # 첫 실행(또는 스키마 1 상태): 재사용 정보가 없다
        base = {"hit": False, "prev_run": prev.get("run")}
        cached = None
        if self.args.refresh:
            base["reason"] = "refresh"
        elif prev.get("request_hash") == request_hash:
            cached, why = self.load_cache(request_hash)
            if cached is None:
                base.update({"changed": ["code"]} if why == "code" else {"reason": "cache-missing"})
        else:
            old = prev.get("parts") or {}
            base["changed"] = [k for k in PART_KEYS if parts.get(k) != old.get(k)]
        if cached is not None:
            self.reuse = {"hit": True, "run": cached["run"]}
            self.run.note("reuse", hit=True, run=cached["run"])
            return cached["core"]
        self.reuse = base
        self.run.note("reuse", hit=False, **{k: v for k, v in base.items() if k in ("changed", "reason")})
        return None

    def load_cache(self, request_hash: str) -> tuple[dict | None, str | None]:
        """`analysis-cache.json`이 쓸 만한가 → (캐시, None) | (None, 사유 `cache-missing`·`code`)."""
        try:
            doc = json.loads((self.job / CACHE_FILE).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, "cache-missing"
        core = doc.get("core") if isinstance(doc, dict) else None
        if (not isinstance(core, dict) or doc.get("format") != CACHE_FORMAT or doc.get("request_hash") != request_hash
                or not isinstance(doc.get("run"), int)):
            return None, "cache-missing"
        files = doc.get("files") or {}
        for name in ("events", "match"):        # 파서·매처 출력이 그대로 있어야 같은 결과다(손으로 고치거나 지웠으면 다시 계산)
            try:
                st = (self.job / CACHE_FILES[name]).stat()
            except OSError:
                return None, "cache-missing"
            if files.get(name) != [st.st_size, st.st_mtime_ns]:
                return None, "cache-missing"
        for ref in (core.get("code") or {}).get("resolved") or []:
            if not Path(str(ref.get("path"))).exists():     # 코드 트리가 옮겨졌다 — 열 파일 목록이 달라진다
                return None, "code"
        return doc, None

    def restore(self, core: dict) -> None:
        """적중: core가 계산하며 남기던 상태를 되살린다(리포트·analysis.json이 같게 나오도록). 싼 파일 쓰기는 그대로 한다."""
        attrs = core.get("attrs") or {}
        self.clock = attrs.get("clock")
        self.order_fail = attrs.get("order_fail")
        self.order_evidence = [tuple(x) for x in attrs.get("order_evidence") or []]
        self.focus = list(attrs.get("focus") or [])
        self.steps_member = attrs.get("steps_member")
        self.warnings += core.get("warnings_core") or []
        self.write_meta(core.get("anchor"))

    def archive_previous(self, request_hash: str) -> None:
        """새로 계산한 결과가 이전 실행과 입력이 다르면, 덮어쓰기 전에 이전 `analysis.json`·`report.md`를 `JOB/runs/<n>/`에
        보관한다(n = 이전 실행 번호, 최근 `RUN_DIRS_KEEP`개만 둔다). 마스킹된 결과만이고 `events.json`·`match.json`은 보관하지 않는다."""
        runs = self.state.job.get("runs") or []
        if not runs or runs[-1].get("request_hash") == request_hash:
            return
        dest_root = self.job / RUNS_DIR
        dest = dest_root / str(runs[-1]["n"])
        copied = False
        for name in ("analysis.json", "report.md"):
            src = self.job / name
            if src.is_file():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest / name)
                copied = True
        if copied:
            self.run.note("archive", run=runs[-1]["n"])
        numbered = sorted((int(d.name) for d in dest_root.iterdir() if d.is_dir() and d.name.isdigit()), reverse=True) \
            if dest_root.is_dir() else []
        for n in numbered[RUN_DIRS_KEEP:]:
            shutil.rmtree(dest_root / str(n), ignore_errors=True)

    def reuse_out(self, candidates: list[dict], parts: dict, runs: list) -> dict:
        """analysis.json의 `reuse`: 적중이면 `{hit, run}`, 다시 계산했으면 무엇이 바뀌었고 1위가 달라졌는지."""
        r = dict(self.reuse)
        if r["hit"]:
            return r
        prev_top = runs[-1].get("top") if runs else None
        prev_label = (prev_top or {}).get("cause") or (prev_top or {}).get("type")
        label = _top_label(candidates)
        if "logs" in (r.get("changed") or []):
            old = {f.get("name") for f in (self.state.job.get("logs") or [])}    # 이전 실행의 로그 이름
            added = [f["name"] for f in self.log_inputs if f["name"] not in old]
            if added:
                r["added_logs"] = added[:5]
        if prev_label:
            r["prev_top"] = prev_label
        r["top_changed"] = prev_label != label
        return r

    def save_job(self, core: dict, parts: dict, request_hash: str, run_no: int, seq: int, hit: bool, candidates: list) -> None:
        """계산한 실행이면(판정 불가 유형·시그니처 오류가 없을 때만) `analysis-cache.json`을, 모든 성공 실행이면 state의 `job` 절(실행 이력)을 갱신한다. 마스킹된 값·경로·sha만."""
        job = self.state.job
        if not hit and core.get("unjudged"):   # 시그니처 시간 초과·오류(비결정적)가 있는 결과는 재사용하지 않는다
            self.run.note("cache-skipped", unjudged=core["unjudged"].get("count"))
        elif not hit:
            files = {}
            for name in ("events", "match"):
                st = (self.job / CACHE_FILES[name]).stat()
                files[name] = [st.st_size, st.st_mtime_ns]
            doc = {"format": CACHE_FORMAT, "request_hash": request_hash, "run": run_no, "parts": parts,
                   "core": core, "files": files}
            tmp = (self.job / CACHE_FILE).with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            os.replace(tmp, self.job / CACHE_FILE)
            job["cache"] = {"request_hash": request_hash, "parts": parts, "run": run_no}
        top = candidates[0] if candidates else None
        runs = list(job.get("runs") or [])
        runs.append({"n": seq, "at": _now(), "request_hash": request_hash, "mode": self.out.get("mode"),
                     "logs": [f["name"] for f in self.log_inputs],
                     "top": {k: top[k] for k in ("type", "cause", "score", "S", "C")} if top else None, "reused": hit})
        job["runs"] = runs[-RUNS_KEEP:]
        job["logs"] = self.log_inputs
        self.state.save()

    def request_hash(self, logs: list[Path], around: str | None, anchor: dict | None = None) -> str:
        h = hashlib.sha256()
        for p in logs:
            h.update(hashlib.sha256(p.read_bytes()).hexdigest().encode())
        parts = [around, (self.out.get("snapshot") or {}).get("sha"), self.args.code, sorted(self.state.answers.items())]
        if self.failed_step:
            parts.append(self.failed_step["text"])
        if anchor:
            parts.append([anchor["source"], list(anchor["window"])])
        h.update(json.dumps(parts, ensure_ascii=False).encode())
        return h.hexdigest()[:16]
