"""`triage.py check-output <KEY> --for deep|explore [--skipped <사유>] [--out <dir>]` — 5-1·5-2 출력 검사(B2 §6).

Claude가 쓴 `JOB/deep-output.md`·`JOB/explore-output.md`를 받아:
1. `mask_pii`와 같은 마스킹을 하고 마스킹한 글을 그 파일에 다시 쓴다(뒤 Step 7은 마스킹된 글만 본다).
2. 고정 칸과 UTF-8 바이트 한도를 본다(한 칸 768바이트 = 한글 약 250자).
3. 근거 원문 검사: 인용이 준 타임라인(모듈 뷰·`JOB/timeline.md`, 설치 스킬이면 events.json 전체 행)에 있는지.
4. report.md의 5-1·5-2 줄(과 `  - ` 아래 줄)을 쓴다 — `TODO(LLM)`이 남은 줄만 고친다. 모델은 그 줄을 고치지 않는다.

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
    data[purpose] = entry
    try:
        _write_atomic(path, (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    except OSError:
        print(f"경고: {RECORD}를 쓰지 못했다", file=sys.stderr)


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
    if not fields:
        return []
    if purpose == "explore":
        return [q for hyp in fields["hyps"] for q in hyp["로그로 확인"]]
    return list(fields.get("근거") or [])


def _parse(purpose: str, mode: str, text: str) -> dict | None:
    if purpose == "explore":
        return evidence.parse_explore(text)
    return evidence.parse_fields(text, evidence.FIELDS_DEEP if mode == "module" else evidence.FIELDS_SKILL)


# --- 그리기 ----------------------------------------------------------------------------------------------

def _head(current: str | None, prefix: str, default: str) -> str:
    if current and current.startswith(prefix) and "): " in current:
        return current[: current.index("): ") + 3]
    return default


def _one(text) -> str:
    return " ".join(str(text or "").split())


def _render(purpose: str, mode: str, head: str, fields: dict, sub: str) -> list[str]:
    if purpose == "explore":
        if not fields["hyps"]:
            return [f"{head}가설 없음: {_one(fields['none'])} / 다음 확인: {_one(fields['next'])}", sub]
        out = [f"{head}가설 {len(fields['hyps'])}개 — 점수·분류·검증에 쓰지 않는다"]
        for i, h in enumerate(fields["hyps"], 1):
            out.append(f"  - 가설 {i}: {_one(h['가설'])} / 로그로 확인: {' | '.join(_one(q) for q in h['로그로 확인'])} / "
                       f"코드로 추정: {_one(h['코드로 추정'])} / 반대 근거: {_one(h['반대 근거'])} / 다음 확인: {_one(h['다음 확인'])}")
        return out + [sub]
    quotes = " | ".join(_one(q) for q in fields["근거"])
    if mode == "module":
        first = (f"{head}원인 층 {_one(fields['원인 층'])} · 원인 데몬 {_one(fields['원인 데몬'])} / 분석 스킬 의견: "
                 f"{_one(fields['분석 스킬 의견'])}")
        return [first, f"  - 근거: {quotes}", f"  - 반대 근거: {_one(fields['반대 근거'])}", sub]
    return ([f"{head}{_one(fields['요약'])} / 분석 스킬 의견: {_one(fields['분석 스킬 의견'])}"]
            + ([f"  - 근거: {quotes}"] if fields["근거"] else []) + [sub])


def _evidence_sub(mode: str, res: dict | None, skipped: str | None) -> str:
    if mode == "skill":
        lead = "  - " + SKILL_LABEL + ": "
    else:
        lead = EVIDENCE_SUB.format(text="")
    if skipped:
        return f"{lead}건너뜀({skipped})"
    text = f"인용 {res['n']}개 중 원문에 없음 {res['fabricated']}"
    if res["weak"]:
        text += f" · 약함 {res['weak']}"
    if mode == "skill" and res["raw"]:
        text += f" · 원문 로그 인용 {res['raw']}개(검사 밖)"
    if res["fabricated"]:
        text += f" ({res['first']}…)"
    return lead + text


# --- 본체 ------------------------------------------------------------------------------------------------

def _rewrite(report: Path, prefix: str, lines: list[str], keep_sub: tuple[str, ...] = ()) -> bool:
    ok = rep.rewrite_line(report, prefix, lines, keep_sub=keep_sub, only_pending=True)
    if not ok:
        print(WARN_REWRITE, file=sys.stderr)
    return ok


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


def _preconditions(job: Path, purpose: str) -> dict:
    report = job / "report.md"
    current = rep.current_line(report, PREFIX[purpose])
    analysis = _load(job / "analysis.json")
    if not isinstance(analysis, dict):
        raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, "analysis.json이 없다")
    if not current or "TODO(LLM)" not in current:
        raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, "고칠 줄이 없다(이미 쓴 줄은 그대로 둔다)")
    if purpose == "deep":
        ana = analysis.get("analyzer")
        if not isinstance(ana, dict) or ana.get("error") or ana.get("when") == "never":
            raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, "심층 분석 해당 없음")
    elif _kind(job / EXPLORE_INPUT_FILE) != "file" or (analysis.get("explore") or {}).get("when") == "never":
        raise _Stop(USAGE, "작업 없음", NEXT_CHECK_NA, "탐색 분석 해당 없음")
    return analysis


def _fail(job: Path, purpose: str, env: dict, reason: str, label: str, sha: str | None, args) -> int:
    report = job / "report.md"
    _rewrite(report, PREFIX[purpose], [SKIPPED[purpose].format(reason=label)])
    _record(job, purpose, {"error": label, "at": _now(), "env": env, "output_sha256": sha})
    _obligation(args, job, purpose, [])
    print(label, file=sys.stderr)
    _emit({"reason": reason, "detail": label, "next": NEXT_CHECK_FAILED})
    return CHECK_FAILED


def _check(args, job: Path, purpose: str, env: dict) -> int:
    analysis = _preconditions(job, purpose)
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
    src_rel, src_text, src_skip = _source(job, purpose, mode, rec, events)

    # 1~3. 마스킹 → 다시 쓰기 → residual
    raw_bytes = out_path.read_bytes()
    raw = raw_bytes.decode("utf-8", "replace")
    masker = masking.new_masker(existing_text=src_text or "", allow_patterns=allow, log_lines=True)
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
    left = masking.residual(text, allow)
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
    res = None
    if not quotes:
        src_skip = "인용 없음"
    elif src_skip is None:
        source, tags = evidence.source_text(src_text)
        res = evidence.check_quotes(quotes, source, tags, raw_items=raw_items)
    sub = _evidence_sub(mode, res, src_skip)

    report, prefix = job / "report.md", PREFIX[purpose]
    current = rep.current_line(report, prefix)
    if purpose == "explore":
        default = f"{EXPLORE_PREFIX} (추정, {TIMELINE_FILE}): "
    elif mode == "module":
        default = f"{DEEP_PREFIX} (모듈 스킬 {rec.get('module')} @{str(rec.get('sha') or '')[:7]}): "
    else:
        name = (rec or {}).get("skill") or (analysis.get("analyzer") or {}).get("skill") or "-"
        default = f"{DEEP_PREFIX} ({name}): "
    lines = _render(purpose, mode, _head(current, prefix, default), fields, sub)
    _rewrite(report, prefix, lines, KEEP_SUB)

    counts = {k: (res or {}).get(k, 0) for k in ("fabricated", "weak", "raw")}
    n = (res or {}).get("n", 0)
    _record(job, purpose, {"mode": mode, "at": _now(), "env": env, "output_sha256": sha, "source": src_rel if res else None,
                           "quotes": n, **counts})
    head = masking.mask_brief(lines[0], 300)
    fab = [sub.lstrip()] if counts["fabricated"] else []
    # 심층 분석은 결과 줄(첫 줄)을 늘 보인다 — 탐색은 지어낸 인용이 있을 때만(B2-6)
    _obligation(args, job, purpose, [head.removesuffix("…")] + fab if purpose == "deep" else fab)
    _emit({"line": head, "evidence": sub.lstrip(), "quotes": n, **counts})
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
        trace_event(job, "checked", purpose=purpose, skipped=skipped, exit=code)
    return code
