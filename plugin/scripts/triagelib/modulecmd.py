"""`triage.py module <KEY> --for deep|explore` (B1 §4, B2 §5): 모듈 스킬 문서 받기·모듈 타임라인·5-1/5-2 리포트 줄.

    module KEY --for deep [--also] [--out dir]
    module KEY --for explore [--module p/dir | --choose top|dir] [--at ISO] [--out dir]

- deep: 1위 후보 카테고리의 출처(`userconfig.deep_source`)가 `skill`이면 설치 스킬 `SKILL.md`를 찾아(`skillpath.resolve`)
  `skill-input.json`·타임라인을 쓰고 `{skill, read, base, input, timeline}`(못 찾으면 종료 1 `설치 스킬 못 찾음`).
  `module`이면 관리 clone에서 받아 `JOB/module-skill/deep/`·`deep-input.json`·`module-skill.json`을 쓴다.
- explore: `--module`이 없으면 모듈 후보를 세어(IMPL §2.3 규칙 1~4) 하나면 고르고, 둘 이상이면 `pick: null`과 질문을 낸다.
  `--at`은 받은 사본으로 타임라인 중심만 다시 잡는다(받기·lock 없음).

stdout은 언제나 JSON 한 줄(≤ 4,096B), 실패면 `{"reason", "next", …}`와 stderr `<reason>: <detail>` 한 줄. 원격 URL은 내지 않는다.
리포트 줄(`- 심층 분석`/`- 탐색 분석`)은 스크립트가 고친다(성공은 늘, 실패는 `TODO(LLM)` 줄만, B2-17). 세션 lock·trace는 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from common import masking, moduleskills, userconfig
from common.exitcodes import OK

from triagelib import core, report
from triagelib.core import EXPLORE_INPUT_FILE, EXPLORE_MAX_LINES, TIMELINE_FILE, _now

RECORD = "module-skill.json"
FOLDER = "module-skill"
DEEP_INPUT = "deep-input.json"
SKILL_INPUT = "skill-input.json"
OUT_MAX = 4096
VIEW_CAPS = {"explore": (150, 20480), "deep": (None, 24576)}
NAME_OK = re.compile(r"^[A-Za-z0-9._/-]{1,40}$")
MODULE_ARG = re.compile(r"^([a-z][a-z0-9_]*)/([a-z]+)$")
FORBIDDEN_ASK = re.compile(r"탐색|explore|심층|analyzer|Step 5|할까요|실행할까|진행할까|할지|하시겠|할래요|\.md|--for")
FETCH_LABELS = moduleskills.REASONS + ("git 버전",)
# 종료 표(B2 §5.7). EXIT_TABLE 시험이 이 목록과 맞춘다(`레포에 <p>/<dir> 없음`은 틀 이름)
REASONS = ("설정 없음", "설치 스킬 못 찾음", "분석 후보 없음", "모듈 후보 없음", "레포에 <p>/<dir> 없음", "사용 오류", "설정 오류",
           "작업 없음", "작업 디렉토리 이상", "git 버전", "마스킹 점검 실패") + moduleskills.REASONS


class Exit(Exception):
    """한 번에 내는 결과: stdout JSON·stderr 한 줄·리포트 줄 고치기(lock 밖에서)."""

    def __init__(self, code: int, out: dict, detail: str = "", rewrite: tuple | None = None):
        super().__init__(out.get("reason", ""))
        self.code, self.out, self.detail, self.rewrite = code, out, detail, rewrite


def C(name: str):
    """`core`의 줄·next 상수(B2 §7.2). 부를 때 읽는다."""
    return getattr(core, name)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _brief(text, limit: int = 160) -> str:
    return masking.mask_brief(text, limit)


# -- 실패 분류 -------------------------------------------------------------------------------------


def _next(purpose: str, reason: str) -> str:
    if reason == "사용 오류":
        return C("NEXT_FIX_CALL")
    if purpose == "deep":
        return C("NEXT_SKILL_MISSING") if reason == "설치 스킬 못 찾음" else C("NEXT_CONTINUE")
    if reason in ("설정 없음", "모듈 후보 없음") or reason.startswith("레포에 "):
        return C("NEXT_BUILTIN")
    if reason in ("설정 오류", "작업 없음", "작업 디렉토리 이상"):
        return C("NEXT_EXPLORE_SKIPPED")
    return C("NEXT_ASK_BUILTIN")


def _fail_line(purpose: str, reason: str, detail: str, ctx: dict):
    """실패 때 쓸 리포트 줄(B2 §5.5). None = 고치지 않는다."""
    if reason in ("사용 오류", "설치 스킬 못 찾음"):
        return None
    if purpose == "deep":
        if reason.startswith("레포에 "):
            return C("DEEP_REPO_MISSING").format(module=ctx.get("missing") or "?", sha7=(ctx.get("sha") or "")[:7])
        if reason in ("설정 없음", "분석 후보 없음"):
            return C("DEEP_SKIPPED").format(reason=reason)
        if reason == "설정 오류":
            return C("DEEP_CONFIG_ERROR").format(problem=_brief(detail, 120))
        if reason in ("작업 없음", "작업 디렉토리 이상", "마스킹 점검 실패"):
            return C("DEEP_SKIPPED").format(reason=f"{reason}({_brief(detail, 60)})")
        return C("DEEP_FETCH_FAILED").format(reason=reason)
    if reason in ("설정 오류", "작업 없음", "작업 디렉토리 이상") or "lines" not in ctx:
        return C("EXPLORE_SKIPPED").format(reason=reason)
    why = ("모듈 스킬 레포 설정 없음" if reason == "설정 없음" else reason if reason == "모듈 후보 없음" or reason.startswith("레포에 ")
           else f"받기 실패({reason})")
    return C("EXPLORE_MODULE_NONE").format(lines=ctx["lines"], total=ctx["total"], reason=why)


def _fail(purpose: str, code: int, reason: str, detail: str = "", ctx: dict | None = None, **extra) -> Exit:
    ctx = ctx or {}
    out = {"reason": reason, **extra, "next": _next(purpose, reason)}
    line = _fail_line(purpose, reason, detail, ctx) if ctx.get("job") else None
    return Exit(code, out, detail, (ctx["job"], purpose, [line], True) if line else None)


def _module_error(purpose: str, exc: moduleskills.ModuleError, ctx: dict) -> Exit:
    extra = {}
    if exc.code == 1 and exc.extra.get("module"):
        extra = {"module": exc.extra["module"], "sha": exc.extra.get("sha")}
        ctx = {**ctx, "missing": exc.extra["module"], "sha": exc.extra.get("sha")}
    return _fail(purpose, exc.code, exc.reason, exc.detail, ctx, **extra)


# -- JOB 파일 쓰기 ---------------------------------------------------------------------------------


def _record_paths(job: Path, purpose: str) -> list[Path]:
    return [job / FOLDER, job / FOLDER / purpose, job / RECORD, job / DEEP_INPUT, job / SKILL_INPUT]


def _paths_ok(job: Path, purpose: str) -> bool:
    paths = _record_paths(job, purpose)
    if any(os.path.islink(p) for p in paths):
        return False
    return not (os.path.lexists(paths[0]) and not paths[0].is_dir())


def _write_new(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _atomic(path: Path, data: bytes) -> None:
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    _write_new(tmp, data)
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _json_bytes(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def _read_record(job: Path) -> dict:
    try:
        data = json.loads((job / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _set_record(job: Path, purpose: str, value: dict | None) -> None:
    obj = _read_record(job)
    if value is None:
        if purpose not in obj:
            return
        obj.pop(purpose)
    else:
        obj[purpose] = value
    _atomic(job / RECORD, _json_bytes(obj))


def _clean_stale(job: Path, purpose: str) -> None:
    folder = job / FOLDER
    if not folder.is_dir() or folder.is_symlink():
        return
    for p in folder.iterdir():
        if p.name.startswith((f".{purpose}.tmp-", f".{purpose}.old-")) and not p.is_symlink() and p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


def _stage(job: Path, purpose: str, files: dict[str, bytes]) -> Path:
    folder = job / FOLDER
    if not folder.exists():
        os.mkdir(folder, 0o700)
    stage = folder / f".{purpose}.tmp-{os.getpid()}-{time.time_ns()}"
    os.mkdir(stage, 0o700)
    for rel, data in files.items():
        path = stage / rel
        for parent in reversed(path.relative_to(stage).parents[:-1]):
            d = stage / parent
            if not d.exists():
                os.mkdir(d, 0o700)
        _write_new(path, data)
    return stage


def _swap(job: Path, purpose: str, stage: Path) -> None:
    dest = job / FOLDER / purpose
    old = None
    if os.path.lexists(dest):
        old = job / FOLDER / f".{purpose}.old-{os.getpid()}-{time.time_ns()}"
        os.replace(dest, old)
    try:
        os.replace(stage, dest)
    except OSError:
        if old is not None:          # 옛 사본을 되돌린다(기록에는 이미 이 purpose가 없다)
            os.replace(old, dest)
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def _write_set(job: Path, purpose: str, files: dict[str, bytes], record: dict, deep_input: dict | None = None,
               skill_input: dict | None = None) -> None:
    """B1 §4.5 쓰기 순서: 묵은 stage 지우기 → stage → 기록에서 purpose 빼기 → 바꿔 넣기 → 입력 JSON → 기록(마지막)."""
    _clean_stale(job, purpose)
    stage = _stage(job, purpose, files)
    try:
        _set_record(job, purpose, None)
        _swap(job, purpose, stage)
    except OSError:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    if deep_input is not None:
        _atomic(job / DEEP_INPUT, _json_bytes(deep_input))
    if skill_input is not None:
        _atomic(job / SKILL_INPUT, _json_bytes(skill_input))
    _set_record(job, purpose, record)


def _files_meta(purpose: str, files: dict[str, bytes]) -> list[dict]:
    return [{"path": f"{FOLDER}/{purpose}/{rel}", "sha256": _sha256(data)} for rel, data in files.items()]


def _rewrite(job: Path, purpose: str, lines: list[str], only_pending: bool) -> bool:
    prefix = "- 심층 분석" if purpose == "deep" else "- 탐색 분석"
    path = job / "report.md"
    if not path.is_file() or path.is_symlink():
        return True
    try:
        return bool(report.rewrite_line(path, prefix, lines, (), only_pending)) or only_pending
    except Exception:  # noqa: BLE001 — 리포트 줄은 보조. 종료 코드를 바꾸지 않는다
        return False


# -- 입력 ----------------------------------------------------------------------------------------


def _load(path: Path) -> tuple[object, bytes]:
    data = path.read_bytes()
    return json.loads(data.decode("utf-8")), data


def _limit(cfg: dict) -> int:
    limit = userconfig.get(cfg, "explore.timeline_max_lines", EXPLORE_MAX_LINES)
    return limit if isinstance(limit, int) and not isinstance(limit, bool) and 20 <= limit <= 1000 else EXPLORE_MAX_LINES


def _around(job: Path, analysis: dict):
    issue = analysis.get("issue") or {}
    meta = {}
    try:
        if (job / "issue_meta.json").is_file():
            meta = json.loads((job / "issue_meta.json").read_text("utf-8"))
    except (OSError, ValueError):
        meta = {}
    return issue.get("occurred_at") or (meta.get("occurred_at") if isinstance(meta, dict) else None)


def _generic_timeline(key: str, events: dict, around, limit: int) -> tuple[str, int, int]:
    text, kept, total = report.timeline(key, events, around, limit, None, None)
    return masking.redact(text, events.get("mask_allow") or [])[0], kept, total


def _parse_iso(value: str):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _filter(lib, payload: dict) -> dict:
    res = lib.child(payload)
    if not isinstance(res, dict):
        return {"error": "crash", "detail": "결과 형식"}
    return res


def _view_or_fail(purpose: str, res: dict, ctx: dict) -> dict:
    err = res.get("error")
    if err == "mask":
        kinds = res.get("kinds") or {}
        raise _fail(purpose, 2, "마스킹 점검 실패", ", ".join(f"{k} {n}건" for k, n in kinds.items()) or "가림 뒤 남음", ctx)
    if err == "timeout":
        raise _fail(purpose, 2, "modules.yaml", "정규식 시간 초과(20초)", ctx)
    if err:
        raise _fail(purpose, 2, "modules.yaml", _brief(res.get("detail") or "필터 실패", 120), ctx)
    return res


def _has_filter(doc: dict, platform: str) -> bool:
    block = ((doc.get("platforms") or {}).get(platform) or {})
    return "filter" in (block.get("common") or {})


def _modem_dir(doc: dict, platform: str) -> str | None:
    mods = ((doc.get("platforms") or {}).get(platform) or {}).get("modules") or {}
    hits = [d for d, b in mods.items() if isinstance(b, dict) and b.get("db_category") == "common"]
    return hits[0] if len(hits) == 1 else None


def _sub_line(stats: dict) -> str:
    names = [n for n in (stats.get("uncollected") or [])[:5] if isinstance(n, str) and NAME_OK.fullmatch(n)]
    return C("MODULE_TIMELINE_SUB").format(kept=stats.get("kept", 0), pool=stats.get("pool", 0), noise=stats.get("noise", 0),
                                           collapsed=stats.get("collapsed", 0),
                                           uncollected=(", 미수집 " + "·".join(names)) if names else "")


def _why_label(key, n) -> str:
    kind, _, name = str(key).partition(":")
    if not NAME_OK.fullmatch(name or ""):
        return f"기타 태그 {n}줄"
    return {"tag": f"{name} {n}줄", "ril": f"RIL {name} {n}줄", "file": f"ofonod {name} {n}줄"}.get(kind, f"기타 태그 {n}줄")


def _env(defaults: dict) -> dict:
    try:
        return importlib.import_module("common.provenance").env_info(cfg=defaults)
    except Exception:  # noqa: BLE001 — 출처 기록은 보조
        return {"runtime": "모름", "model": "모름", "model_defaults": {}, "gateway": "none", "label": None}


# -- 명령 ----------------------------------------------------------------------------------------


def cmd_module(args, defaults: dict) -> int:
    try:
        code, out, warn, rewrite = _run(args, defaults)
        _emit(out)
        if warn:
            print(warn, file=sys.stderr)
        if rewrite and not _rewrite(*rewrite):
            print("경고: report.md 줄을 고치지 못했다", file=sys.stderr)
        return code
    except Exit as exc:
        _emit(exc.out)
        print(f"{exc.out.get('reason')}: {_brief(exc.detail) or '-'}", file=sys.stderr)
        if exc.rewrite:
            job, purpose, lines, pending = exc.rewrite
            if not _rewrite(job, purpose, lines, pending):
                print("경고: report.md 줄을 고치지 못했다", file=sys.stderr)
        return exc.code


def _emit(out: dict) -> None:
    text = report.dumps(out)
    if len(text.encode("utf-8")) > OUT_MAX:
        for key in ("candidates", "also_why", "missing", "hints_unmapped"):
            if key in out:
                out = {**out, key: out[key][:1]}
        text = report.dumps(out)
    print(text)


def _run(args, defaults: dict):
    import platforms
    import triage as T  # _work_key·_find_job·_job_platform (triage.py가 CLI를 둔다)
    from common import yamlio
    from platforms import session as platform_session

    purpose = args.purpose
    use = lambda msg: _fail(purpose, 2, "사용 오류", msg)
    cfg = args.platform_cfg
    key = (args.key if re.fullmatch(r"[A-Za-z0-9._-]+", args.key) else None) if args.out else T._work_key(cfg, args.key)
    if key is None:
        raise use(f"Jira 키 형식이 아니다: {args.key}")
    args.key = key
    if purpose == "deep":
        if args.module or args.choose or args.at:
            raise use("--for deep은 --module·--choose·--at을 받지 않는다(1위 후보 카테고리로 고른다)")
    else:
        if args.also:
            raise use("--also는 --for deep에만 쓴다")
        if args.choose and args.module:
            raise use("--choose와 --module은 함께 못 쓴다")
        if args.at and not args.module:
            raise use("--at은 --module과 함께 쓴다")
        if args.choose and args.choose != "top" and not re.fullmatch(r"[a-z]+", args.choose):
            raise use("--choose는 top 또는 모듈 디렉토리 이름")
    if not args.out:
        T._find_job(args, defaults, key)
        cfg = args.platform_cfg
    job = Path(args.out).expanduser().resolve() if args.out else Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / key
    if not job.is_dir():
        raise _fail(purpose, 2, "작업 없음", f"작업 디렉토리가 없다: {key}")
    ctx = {"job": job}
    nojob = lambda msg: _fail(purpose, 2, "작업 없음", msg, ctx)
    inputs: dict[str, str | None] = {}
    try:
        analysis, raw = _load(job / "analysis.json")
        if not isinstance(analysis, dict):
            raise ValueError
        inputs["analysis.json"] = _sha256(raw)
        events, raw = _load(job / "events.json")
        if not isinstance(events, dict):
            raise ValueError
        inputs["events.json"] = _sha256(raw)
    except (OSError, ValueError):
        raise nojob("analysis.json·events.json을 읽지 못했다 — /telephony-triage:analyze를 다시") from None
    candidates = [c for c in (analysis.get("candidates") or []) if isinstance(c, dict)]
    explore = None
    if purpose == "deep":
        if not candidates:
            raise _fail(purpose, 1, "분석 후보 없음", "1위 후보가 없다", ctx)
        match_raw = (job / "match.json").read_bytes() if (job / "match.json").is_file() else None
        inputs["match.json"] = _sha256(match_raw) if match_raw is not None else None
    else:
        explore = _explore_inputs(job, key, events, inputs, nojob)
        ctx.update(lines=explore["kept"], total=explore["total"])
    p = T._job_platform(job, args.platform_name)
    if p != args.platform_name:
        try:
            cfg = platform_session.resolve(defaults, p)[1]
        except (platforms.PlatformConfigError, yamlio.YamlFileError) as exc:
            raise _fail(purpose, 2, "설정 오류", str(exc), ctx) from None
    user = userconfig.load_user()
    env = _env(defaults)
    if purpose == "deep":
        cand0 = candidates[0]
        src = userconfig.deep_source(cfg, cand0.get("category"))
        if src.get("source") == "skill":
            probs = userconfig.analyzer_problems(defaults, user, platform=p)
            if probs:
                raise _fail(purpose, 2, "설정 오류", probs[0], ctx)
            return _deep_skill(job, key, cfg, analysis, events, candidates, src, inputs, env)
        probs = userconfig.module_skills_problems(defaults, user) + userconfig.analyzer_problems(defaults, user, platform=p)
        if probs:
            raise _fail(purpose, 2, "설정 오류", probs[0], ctx)
        if src.get("source") == "none":
            raise _fail(purpose, 1, "설정 없음", "1위 카테고리에 모듈 스킬·분석 스킬 설정이 없다", ctx)
        if src.get("source") == "error":
            raise _fail(purpose, 2, "설정 오류", userconfig.deep_source_problem(cfg, cand0.get("category")) or "prefer", ctx)
    else:
        probs = userconfig.module_skills_problems(defaults, user)
        if probs:
            raise _fail(purpose, 2, "설정 오류", probs[0], ctx)
        if args.module:
            m = MODULE_ARG.fullmatch(args.module)
            if not m or m.group(1) != p:
                raise _fail(purpose, 2, "사용 오류", f"--module은 {p}/<모듈>: {args.module}")
        if args.at:
            return _explore_at(args, job, key, p, events, explore, inputs, env, ctx)
    ms = userconfig.module_skills(cfg)
    if ms is None:
        _drop_explore(job, purpose)
        raise _fail(purpose, 1, "설정 없음", "module_skills.remote가 없다", ctx)
    work = Path(str(userconfig.get(cfg, "work_dir"))).expanduser()
    ver = moduleskills.git_version()
    if ver is None or ver < moduleskills.MIN_GIT:
        _drop_explore(job, purpose)
        raise _fail(purpose, 2, "git 버전", f"git {'.'.join(map(str, ver)) if ver else '없음'} — 2.25 이상 필요", ctx)
    if not _paths_ok(job, purpose):
        raise _fail(purpose, 2, "작업 디렉토리 이상", "모듈 기록 경로가 링크이거나 디렉토리가 아니다", ctx)
    try:
        userconfig.ensure_private_dir(work)
        with moduleskills.clone_lock(work) as lk:
            state = moduleskills.prepare(work, ms["remote"], ms["base_branch"], lock=lk, platform=p)
            if purpose == "deep":
                return _deep_module(args, job, key, p, cfg, analysis, events, candidates, state, inputs, env, ctx)
            return _explore_module(args, job, key, p, cfg, analysis, events, explore, state, inputs, env, ctx)
    except moduleskills.ModuleError as exc:
        _drop_explore(job, purpose)
        raise _module_error(purpose, exc, ctx) from None
    except Exit as exc:
        if purpose == "explore" and exc.out.get("reason") != "사용 오류":
            _drop_explore(job, purpose)
        raise
    except OSError as exc:
        _drop_explore(job, purpose)
        raise _fail(purpose, 2, "작업 디렉토리 이상", exc.strerror or type(exc).__name__, ctx) from None


def _drop_explore(job: Path, purpose: str) -> None:
    """E8b: 실패한 explore는 이전 고른 것의 기록을 지운다(check-output이 옛 view로 채점하지 않게)."""
    if purpose != "explore" or not _paths_ok(job, purpose):
        return
    try:
        _set_record(job, "explore", None)
    except OSError:
        pass


def _explore_inputs(job: Path, key: str, events: dict, inputs: dict, nojob) -> dict:
    """E1: 네 입력을 읽고 `timeline.md`를 다시 계산해 바이트로 맞춘다."""
    try:
        spec, raw = _load(job / EXPLORE_INPUT_FILE)
        limit = spec.get("limit") if isinstance(spec, dict) else None
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError
        inputs[EXPLORE_INPUT_FILE] = _sha256(raw)
        tl = (job / TIMELINE_FILE).read_bytes()
    except (OSError, ValueError, AttributeError):
        raise nojob(f"{EXPLORE_INPUT_FILE}·{TIMELINE_FILE}을 읽지 못했다 — triage.py explore를 먼저") from None
    inputs[TIMELINE_FILE] = _sha256(tl)
    allow = events.get("mask_allow") or []
    rows = report.merge_rows(events)
    items, total = report.select_rows(rows, spec.get("around"), limit)
    text = report.render_timeline(key, events, items, total, spec.get("around"), limit, spec.get("failed_step"),
                                  spec.get("anchor"))
    text = masking.redact(text, allow)[0]
    if text.encode("utf-8") != tl:
        raise nojob(f"{TIMELINE_FILE}가 events.json과 맞지 않는다 — triage.py explore를 다시")
    anchor = spec.get("anchor") or {}
    center = anchor.get("fail") or spec.get("around")
    pins = [{"ts": r.get("ts"), "tag": r.get("tag"), "msg": r.get("msg")} for r in rows
            if anchor.get("fail") and r.get("ts") == anchor.get("fail")][:5]
    return {"spec": spec, "items": items, "kept": len(items), "total": total, "center": center,
            "center_source": "실패 스텝" if anchor.get("fail") else "발생 시각", "pins": pins, "allow": allow}


# -- deep ------------------------------------------------------------------------------------------


def _top3(candidates: list[dict]) -> list[dict]:
    return [{k: c.get(k) for k in ("type", "cause", "score", "confidence")} for c in candidates[:3]]


def _log_paths(events: dict) -> list[str]:
    return [f for f in (events.get("input") or {}).get("files") or [] if isinstance(f, str)]


def _deep_skill(job, key, cfg, analysis, events, candidates, src, inputs, env):
    """B2 §5.4 S: 설치 스킬 SKILL.md(받기·lock·git 없음). 못 찾아도 입력 파일·타임라인·기록은 쓴다."""
    purpose, cand0 = "deep", candidates[0]
    ctx = {"job": job}
    if not _paths_ok(job, purpose):
        raise _fail(purpose, 2, "작업 디렉토리 이상", "모듈 기록 경로가 링크이거나 디렉토리가 아니다", ctx)
    try:
        r = importlib.import_module("common.skillpath").resolve(cfg, cand0.get("category"))
    except ImportError:
        r = {"path": None, "base": None, "why": "skillpath 없음"}
    name = src.get("skill")
    around = _around(job, analysis)
    text, kept, total = _generic_timeline(key, events, around, _limit(cfg))
    data = text.encode("utf-8")
    tl_rel = f"{FOLDER}/deep/{TIMELINE_FILE}"
    timeline = {"path": tl_rel, "sha256": _sha256(data), "lines": kept, "total": total}
    skill_input = {"events_json": str(job / "events.json"), "log_paths": _log_paths(events), "top_candidates": _top3(candidates),
                   "issue_summary": (analysis.get("issue") or {}).get("summary"), "timeline": str(job / tl_rel)}
    record = {"skill": name, "path": r.get("path"), "at": _now(), "timeline": timeline,
              "inputs": inputs, "env": env}
    if r.get("path"):
        try:
            record["sha256"] = _sha256(Path(r["path"]).read_bytes())
        except OSError:
            r = {"path": None, "base": None, "why": "SKILL.md를 읽지 못했다"}
            record["path"] = None
    if not r.get("path"):
        record["why"] = _brief(r.get("why"), 160)
    try:
        _write_set(job, purpose, {TIMELINE_FILE: data}, record, skill_input=skill_input)
    except OSError as exc:
        raise _fail(purpose, 2, "작업 디렉토리 이상", exc.strerror or type(exc).__name__, ctx) from None
    tl_out = {"path": str(job / tl_rel), "lines": kept, "total": total, "view": False}
    if not r.get("path"):
        raise Exit(1, {"reason": "설치 스킬 못 찾음", "skill": name, "input": str(job / SKILL_INPUT),
                       "next": _next(purpose, "설치 스킬 못 찾음")}, r.get("why") or "")
    return OK, {"skill": name, "read": [r["path"]], "base": r.get("base") or str(Path(r["path"]).parent),
                "input": str(job / SKILL_INPUT), "timeline": tl_out}, "", None


def _deep_module(args, job, key, p, cfg, analysis, events, candidates, state, inputs, env, ctx):
    purpose, cand0 = "deep", candidates[0]
    fetched = moduleskills.materialise(state, purpose="deep", category=cand0.get("category"), type_id=cand0.get("type"),
                                       also=args.also)
    allow = events.get("mask_allow") or []
    limit = _limit(cfg)
    around = _around(job, analysis)
    view = _has_filter(fetched.doc, p)
    modem = _modem_dir(fetched.doc, p)
    lib = importlib.import_module("common.modulefilter") if view or (modem and not args.also) else None
    ev = None
    if lib is not None:
        try:
            match = json.loads((job / "match.json").read_text("utf-8")) if inputs.get("match.json") else {}
        except (OSError, ValueError):
            match = {}
        ev = lib.deep_evidence(match if isinstance(match, dict) else {}, cand0) or list(cand0.get("evidence") or [])
    stats = None
    if view:
        res = _view_or_fail(purpose, _filter(lib, {
            "op": "view", "mode": "deep", "events": str(job / "events.json"), "key": key, "module": fetched.module,
            "center": None, "center_source": "근거", "evidence": ev, "pins": ev, "allow": allow, "cap_rows": limit,
            "cap_bytes": VIEW_CAPS["deep"][1], "with_modem": bool(args.also), "modules": fetched.doc, "platform": p}), ctx)
        text, stats = res["text"], res.get("stats") or {}
        kept, total, center = stats.get("kept", 0), stats.get("pool", 0), stats.get("center")
    else:
        text, kept, total = _generic_timeline(key, events, around, limit)
        center = around
    also, also_why, ask_also = [], [], None
    if lib is not None and not args.also and modem and modem != fetched.module and f"{p}/{modem}/SKILL.md" in fetched.tree:
        sig = _filter(lib, {"op": "also", "events": str(job / "events.json"), "evidence": ev, "module": fetched.module,
                            "modules": fetched.doc, "platform": p})
        if not sig.get("error") and int(sig.get("rows") or 0) >= 1:
            also = [f"{p}/{modem}"]
            also_why = [_why_label(k, n) for k, n in (sig.get("why") or [])[:3]]
            ask_also = {"question": f"모뎀 모듈 문서도 함께 볼까요? (모뎀 신호: {', '.join(also_why) or str(sig['rows']) + '줄'})",
                        "options": ["아니오(기본)", "예"]}
    data = text.encode("utf-8")
    files = dict(fetched.files)
    files["modules.yaml"] = fetched.modules_yaml
    files[TIMELINE_FILE] = data
    tl_rel = f"{FOLDER}/deep/{TIMELINE_FILE}"
    module = f"{p}/{fetched.module}"
    deep_input = {"schema_version": 1, "key": analysis.get("key"), "platform": p, "module": module, "sha": fetched.sha,
                  "type_id": cand0.get("type"), "top_candidates": _top3(candidates),
                  "issue_summary": (analysis.get("issue") or {}).get("summary"), "occurred_at": around,
                  "events": "events.json", "timeline": tl_rel, "log_paths": _log_paths(events)}
    record = {"module": module, "sha": fetched.sha, "at": _now(),
              "files": [m for m in _files_meta(purpose, files) if not m["path"].endswith("/" + TIMELINE_FILE)],
              "timeline": {"path": tl_rel, "sha256": _sha256(data), "lines": kept, "total": total},
              "inputs": inputs, "center": center, "with": [f"{p}/{fetched.with_modem}"] if fetched.with_modem else [],
              "env": env, "warnings": fetched.warnings,
              "checks": {"passed": list(moduleskills.CHECKS_PASSED), "skipped": dict(moduleskills.CHECKS_SKIPPED)}}
    _locked_write(state, job, purpose, files, record, deep_input=deep_input)
    read = [str(job / FOLDER / "deep" / rel) for rel, _ in fetched.files]
    out = {"module": module, "sha": fetched.sha, "read": read, "also": also, "input": str(job / DEEP_INPUT),
           "timeline": {"path": str(job / tl_rel), "lines": kept, "total": total, "view": bool(view)}}
    if fetched.with_modem:
        out["with"] = [f"{p}/{fetched.with_modem}"]
    if also:
        out.update(also_why=also_why, ask_also=ask_also)
    line = C("DEEP_MODULE_FETCHED").format(module=module + ("+modem" if fetched.with_modem else ""), sha7=fetched.sha[:7])
    lines = [line] + ([_sub_line(stats)] if stats is not None else [])
    return _success(job, purpose, out, lines, fetched.warnings)


def _locked_write(state, job, purpose, files, record, **kw) -> None:
    state.lock.check()
    if not _paths_ok(job, purpose):
        raise _fail(purpose, 2, "작업 디렉토리 이상", "모듈 기록 경로가 링크이거나 디렉토리가 아니다", {"job": job})
    _write_set(job, purpose, files, record, **kw)


def _success(job, purpose, out, lines, warnings):
    """lock을 놓은 뒤 리포트 줄을 고친다(cmd_module이 출력한다)."""
    warn = ("경고: " + _brief("; ".join(warnings), 300)) if warnings else ""
    return OK, out, warn, (job, purpose, lines, False)


# -- explore ---------------------------------------------------------------------------------------


def _hints(job: Path, cfg: dict, analysis: dict, by_cat: dict[str, str]) -> tuple[list[tuple[str, str]], list[str]]:
    """IMPL §2.3 규칙 4 → [(dir, label)], hints_unmapped(≤3)."""
    cands = [c for c in analysis.get("candidates") or [] if isinstance(c, dict)]
    found: list[tuple[str, str]] = []
    if (analysis.get("explore") or {}).get("reason") == "cause_unconfirmed" and cands and cands[0].get("type"):
        found.append((str(cands[0]["type"]), f"1위 유형 {cands[0]['type']}(원인 미확인)"))
    try:
        match = json.loads((job / "match.json").read_text("utf-8")) if (job / "match.json").is_file() else {}
    except (OSError, ValueError):
        match = {}
    for t in ((match.get("step_focus") or {}).get("types") or []) if isinstance(match, dict) else []:
        if isinstance(t, str):
            found.append((t, f"실패 스텝 유형 {t}"))
    for h in ((analysis.get("no_candidate") or {}).get("search_hits") or []):
        if isinstance(h, dict) and h.get("kind") in ("type", "cause") and isinstance(h.get("id"), str):
            t = re.sub(r"-\d{2}$", "", h["id"]) if h["kind"] == "cause" else h["id"]
            found.append((t, f"요약 유형 {t}"))
    prefixes = _id_prefixes(cfg, analysis)
    cats = set(by_cat)
    out, unmapped, seen = [], [], set()
    for t, label in found:
        cat = next((c.get("category") for c in cands if c.get("type") == t and c.get("category")), None)
        pre = t.split("-", 1)[0]
        if cat is None:
            cat = prefixes.get(pre)
        if cat is None and pre.lower() in cats:
            cat = pre.lower()
        d = by_cat.get(cat) if cat else None
        if d is None:
            if NAME_OK.fullmatch(t) and t not in unmapped:
                unmapped.append(t)
            continue
        if (d, label) not in seen:
            seen.add((d, label))
            out.append((d, label))
    return out, unmapped[:3]


def _id_prefixes(cfg: dict, analysis: dict) -> dict[str, str]:
    if not analysis.get("snapshot"):
        return {}
    path = Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / core.SNAPSHOT_DIR / "issue-db.config.yaml"
    try:
        from common import yamlio
        doc = yamlio.load(path)
    except Exception:  # noqa: BLE001 — 힌트는 도움일 뿐
        return {}
    out = {}
    for c in (doc or {}).get("categories") or []:
        if isinstance(c, dict) and isinstance(c.get("id_prefix"), str) and isinstance(c.get("key"), str):
            out[c["id_prefix"]] = c["key"]
    return out


def rank(counts: dict, hints: list[tuple[str, str]], order: list[str], tree, platform: str) -> tuple[list[dict], list[str]]:
    """E6–E7: 후보(줄 수 > 0 ∪ 힌트) 중 explore.md가 있는 것, 줄 수 내림 → 힌트 먼저 → modules.yaml 순서, 3개.
    3위 안에 힌트가 없고 힌트 후보가 있으면 가장 좋은 힌트가 3위를 대신한다."""
    hint_label: dict[str, str] = {}
    for d, label in hints:
        hint_label.setdefault(d, label)
    dirs = [d for d in order if (counts.get(d) or {}).get("lines", 0) > 0 or d in hint_label]
    dirs += [d for d in list(counts) + list(hint_label) if d not in dirs and ((counts.get(d) or {}).get("lines", 0) > 0
                                                                            or d in hint_label)]
    present = [d for d in dirs if f"{platform}/{d}/explore.md" in tree]
    missing = [f"{platform}/{d}" for d in dirs if d not in present]
    pos = {d: i for i, d in enumerate(order)}
    present.sort(key=lambda d: (-(counts.get(d) or {}).get("lines", 0), d not in hint_label, pos.get(d, len(pos)), d))
    top = present[:3]
    if top and len(present) > 3 and not any(d in hint_label for d in top):
        best = next((d for d in present[3:] if d in hint_label), None)
        if best:
            top[2] = best
    out = []
    for d in top:
        c = counts.get(d) or {}
        why = [_why_label(k, n) for k, n in (c.get("why") or [])[:3]]
        if d in hint_label:
            why = (why + [hint_label[d]])[:3] if len(why) < 3 else why[:2] + [hint_label[d]]
        out.append({"module": f"{platform}/{d}", "lines": int(c.get("lines", 0)), "why": why, "hint": d in hint_label})
    return out, missing


def ask_text(cands: list[dict]) -> dict:
    counts = " · ".join(f"{c['module'].split('/', 1)[1]} {c['lines']}" for c in cands)
    return {"question": f"어느 모듈 문서로 볼까요? (모듈 신호 줄 수: {counts})",
            "options": [f"{c['module'].split('/', 1)[1]} — {c['lines']}줄" + (" (요약과 맞음)" if c["hint"] else "")
                        for c in cands[:3]]}


def _explore_module(args, job, key, p, cfg, analysis, events, explore, state, inputs, env, ctx):
    purpose = "explore"
    doc = state.doc
    mods = ((doc.get("platforms") or {}).get(p) or {}).get("modules") or {}
    cands_out: list[dict] = []
    if args.module:
        d, by = args.module.split("/", 1)[1], "user"
    else:
        lib = importlib.import_module("common.modulefilter")
        res = _filter(lib, {"op": "candidates", "modules": doc, "platform": p,
                            "items": [{k: r.get(k) for k in ("tag", "msg", "cat", "ril", "level", "marks")}
                                      for r in explore["items"]]})
        if res.get("error") == "timeout":
            raise _fail(purpose, 2, "modules.yaml", "정규식 시간 초과(20초)", ctx)
        if res.get("error"):
            raise _fail(purpose, 2, "modules.yaml", _brief(res.get("detail") or "필터 실패", 120), ctx)
        by_cat = {b.get("db_category"): name for name, b in mods.items() if isinstance(b, dict)}
        hints, unmapped = _hints(job, cfg, analysis, by_cat)
        cands_out, missing = rank(res.get("counts") or {}, hints, list(mods), state.tree, p)
        if args.choose == "top":
            if not cands_out:
                raise _fail(purpose, 1, "모듈 후보 없음", "모듈 신호 줄도 요약 힌트도 없다", ctx)
            d, by = cands_out[0]["module"].split("/", 1)[1], "choose"
        elif args.choose:
            if f"{p}/{args.choose}/explore.md" not in state.tree:
                ctx2 = {**ctx, "missing": f"{p}/{args.choose}", "sha": state.sha}
                raise _fail(purpose, 1, f"레포에 {p}/{args.choose} 없음", "explore.md 없음", ctx2,
                            module=f"{p}/{args.choose}", sha=state.sha)
            d, by = args.choose, "choose"
        elif not cands_out:
            raise _fail(purpose, 1, "모듈 후보 없음", "모듈 신호 줄도 요약 힌트도 없다", ctx)
        elif len(cands_out) == 1:
            d, by = cands_out[0]["module"].split("/", 1)[1], "auto"
        else:
            return OK, {"pick": None, "sha": state.sha, "candidates": cands_out, "missing": missing[:5],
                        "hints_unmapped": unmapped, "ask": ask_text(cands_out),
                        "timeline": {"lines": explore["kept"], "total": explore["total"]}}, "", None
    fetched = moduleskills.materialise(state, purpose="explore", module=d)
    view = _has_filter(fetched.doc, p)
    stats = None
    files = {rel: blob for rel, blob in fetched.files}
    files["modules.yaml"] = fetched.modules_yaml
    read = [str(job / FOLDER / "explore" / rel) for rel, _ in fetched.files]
    tl_record = None
    if view:
        lib = importlib.import_module("common.modulefilter")
        res = _view_or_fail(purpose, _filter(lib, _explore_view_payload(job, key, p, d, explore, fetched.doc)), ctx)
        data = res["text"].encode("utf-8")
        stats = res.get("stats") or {}
        files[TIMELINE_FILE] = data
        tl_path = job / FOLDER / "explore" / TIMELINE_FILE
        kept, total = stats.get("kept", 0), stats.get("pool", 0)
        tl_record = {"path": f"{FOLDER}/explore/{TIMELINE_FILE}", "sha256": _sha256(data), "lines": kept, "total": total}
    else:
        tl_path = job / TIMELINE_FILE
        kept, total = explore["kept"], explore["total"]
    read.append(str(tl_path))
    module = f"{p}/{d}"
    record = {"module": module, "sha": fetched.sha, "at": _now(),
              "files": [m for m in _files_meta(purpose, files) if not m["path"].endswith("/" + TIMELINE_FILE)],
              "inputs": inputs, "center": explore["center"], "pick": {"by": by}, "env": env, "warnings": fetched.warnings,
              "checks": {"passed": list(moduleskills.CHECKS_PASSED), "skipped": dict(moduleskills.CHECKS_SKIPPED)}}
    if tl_record:
        record["timeline"] = tl_record
    _locked_write(state, job, purpose, files, record)
    out = {"module": module, "sha": fetched.sha, "read": read, "also": [], "pick": {"by": by}}
    if cands_out:
        out["candidates"] = cands_out
    out["timeline"] = {"path": str(tl_path), "lines": kept, "total": total, "view": bool(view)}
    if stats and stats.get("weak"):
        out["ask_switch"] = _ask_switch(d, stats, cands_out, tree=state.tree, platform=p)
    return _success(job, purpose, out, _explore_lines(module, fetched.sha, kept, total, stats), fetched.warnings)


def _explore_view_payload(job, key, p, d, explore, doc, center=None, source=None) -> dict:
    cap_rows, cap_bytes = VIEW_CAPS["explore"]
    return {"op": "view", "mode": "explore", "events": str(job / "events.json"), "key": key, "module": d,
            "center": center or explore["center"], "center_source": source or explore["center_source"], "evidence": [],
            "pins": explore["pins"], "allow": explore["allow"], "cap_rows": cap_rows, "cap_bytes": cap_bytes,
            "with_modem": False, "modules": doc, "platform": p}


def _explore_lines(module, sha, kept, total, stats) -> list[str]:
    line = C("EXPLORE_MODULE_DONE").format(lines=kept, total=total, module=module, sha7=sha[:7])
    return [line] + ([_sub_line(stats)] if stats is not None else [])


def _ask_switch(d: str, stats: dict, cands: list[dict], tree=None, platform: str | None = None) -> dict:
    """약한 신호일 때 바꿀 모듈 질문. `tree`(받은 레포 트리)를 주면 `<p>/<m>/explore.md`가 있는 모듈만 권한다(H C1+D R40)."""
    hot = sorted(((k, v) for k, v in (stats.get("hot_modules") or {}).items() if k != d and NAME_OK.fullmatch(str(k))
                  and (tree is None or f"{platform}/{k}/explore.md" in tree)),
                 key=lambda kv: (-kv[1], kv[0]))
    shown = " · ".join(f"{k} {v}" for k, v in hot[:3])
    others = [f"{k} — {v}줄" for k, v in hot[:2]]
    return {"question": f"고른 모듈 문서의 신호가 약합니다. 다른 모듈 문서로 바꿀까요? (모듈 신호 줄 수: {shown})",
            "options": [f"그대로 {d}"] + others}


def _explore_at(args, job, key, p, events, explore, inputs, env, ctx):
    """X2: 받은 사본으로 중심만 다시 잡는다(lock·받기 없음)."""
    purpose = "explore"
    rec = _read_record(job).get("explore")
    stale = _fail(purpose, 2, "작업 없음", "기록이 이전 분석 것이거나 사본이 바뀌었다 — --at 없이 다시", ctx)
    if not isinstance(rec, dict) or rec.get("module") != args.module or rec.get("inputs") != inputs:
        raise stale
    for f in rec.get("files") or []:
        try:
            if _sha256((job / f["path"]).read_bytes()) != f["sha256"]:
                raise stale
        except (OSError, KeyError, TypeError):
            raise stale from None
    t = _parse_iso(args.at)
    window = (events.get("input") or {}).get("window") or {}
    lo, hi = _parse_iso(window.get("start") or ""), _parse_iso(window.get("end") or "")
    try:
        outside = t is not None and ((lo and t < lo) or (hi and t > hi))
    except TypeError:
        outside = True
    if t is None or outside:
        raise _fail(purpose, 2, "사용 오류", f"--at은 분석 범위 안의 ISO 시각: {args.at}")
    if not _paths_ok(job, purpose):
        raise _fail(purpose, 2, "작업 디렉토리 이상", "모듈 기록 경로가 링크이거나 디렉토리가 아니다", ctx)
    folder = job / FOLDER / "explore"
    try:
        from common import skillcheck
        doc = skillcheck.strip_unknown(skillcheck.load_modules_yaml((folder / "modules.yaml").read_bytes()))
    except Exception:  # noqa: BLE001
        raise stale from None
    d = args.module.split("/", 1)[1]
    if not _has_filter(doc, p):
        raise _fail(purpose, 2, "사용 오류", "--at은 modules.yaml에 filter가 있을 때만 쓴다")
    lib = importlib.import_module("common.modulefilter")
    res = _view_or_fail(purpose, _filter(lib, _explore_view_payload(job, key, p, d, explore, doc, args.at, "--at")), ctx)
    data, stats = res["text"].encode("utf-8"), res.get("stats") or {}
    files = {}
    for path in folder.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.name != TIMELINE_FILE:
            files[path.relative_to(folder).as_posix()] = path.read_bytes()
    files[TIMELINE_FILE] = data
    kept, total = stats.get("kept", 0), stats.get("pool", 0)
    record = dict(rec, at=_now(), center=args.at, env=env,
                  timeline={"path": f"{FOLDER}/explore/{TIMELINE_FILE}", "sha256": _sha256(data), "lines": kept,
                            "total": total})
    try:
        _write_set(job, purpose, files, record)
    except OSError as exc:
        raise _fail(purpose, 2, "작업 디렉토리 이상", exc.strerror or type(exc).__name__, ctx) from None
    read = [str(folder / rel) for rel in (f["path"].split("/", 2)[2] for f in rec.get("files") or [])
            if rel != "modules.yaml"] + [str(folder / TIMELINE_FILE)]
    out = {"module": args.module, "sha": rec.get("sha"), "read": read, "also": [], "pick": rec.get("pick") or {"by": "user"},
           "timeline": {"path": str(folder / TIMELINE_FILE), "lines": kept, "total": total, "view": True}, "at": args.at}
    if stats.get("weak"):
        out["ask_switch"] = _ask_switch(d, stats, [])
    return _success(job, purpose, out, _explore_lines(args.module, rec.get("sha") or "", kept, total, stats), [])
