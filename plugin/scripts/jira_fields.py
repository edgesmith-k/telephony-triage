#!/usr/bin/env python3
"""jira_fields.py — Jira 응답에서 분석 항목 추출 (07-workflow.md §Step 0·2, 16-existing-assets.md §16.1, 08-safety.md §8.1).

    jira_fields.py check-key <KEY> [--db <path>]
        `jira_key_regex`(이슈 DB `issue-db.config.yaml`)로 키를 검사한다. 맞지 않으면 종료 코드 1.
        작업 키·경로·브랜치로 쓰기 전에 부른다(contracts.md §3.2 작업 키 검증).
    jira_fields.py extract <raw.json|raw.yaml> [--origin mcp|file] [--db <path>]
                           [--meta-out <file>] [--consume] [--comments all|last:<N>] [--comment-chars <N>]
        Jira MCP `get_issue` 응답(스킬이 파일로 저장) 또는 `--jira-file` YAML을 읽어
        `jira.field_map`(사용자 config > site-defaults)으로 구조화 필드를 뽑고, 텍스트 필드
        (요약·설명·코멘트 본문)는 **읽은 직후 마스킹**한다. 코멘트 작성자 같은 사람 이름 필드는 내지 않는다.

출력(JSON):
    {key, key_valid, origin,
     jira: {key, origin, model, sw, android_version, carrier, occurred_on},   # 계획 `jira` 블록 초안(date·note 제외)
     occurred_at: <UTC ISO | null>, occurred_at_local: <jira.timezone ISO | null>,
     logcat: {tz, year},                        # parse_logcat --tz/--year 값 (year_source: jira일 때 발생 연도)
     sim_slot, components[], text: {summary, description, comments[], comments_total},   # 마스킹됨
                                                # --comments last:N면 뒤에서 N개, --comment-chars면 하나당 N자
     missing[], meta_out}
선택 키(실패 스텝은 선택 값이라 **있을 때만** 나온다, 07-workflow.md §Step 2): `text.test_steps`(마스킹, ≤1000자),
`failed_step_auto {text, source}`(Jira에서 자동으로 얻은 값: field > description > test_steps),
`failed_step {text, source}`(`--failed-step`·`--steps-file`까지 반영한 최종 값, source는 cli|field|description|test_steps|steps_file),
`jira.failed_step`(그 값의 text), `warnings[]`. 보조 정보일 뿐이며 `missing`에 넣지 않는다.
`--failed-step <한 줄>`·`--steps-file <파일>`은 record 흐름이 쓴다(우선순위 cli > 자동 > steps-file, 모두 마스킹 후 정규화).
`--meta-out`이면 `match_signatures.py --jira-meta` 입력 `{key, occurred_at, sw, summary, description}`을 쓴다(`failed_step`·`android_version`은 있을 때만 더한다).
`--consume`이면 읽은 원본 파일을 지운다(원문을 work_dir에 남기지 않기 위해서다, 08-safety.md §8.1).

`field_map` 경로 표기: 점으로 잇고, 목록은 `[]`로 펼친다(`fields.components[].name`). 경로가 비었거나
값이 없으면 `missing[]`에 넣는다(스킬이 사용자에게 묻는다). 설정의 `summary`·`description`·`comments`
경로가 없으면 `fields.summary`, `fields.description`, `comments[].body`(또는 `fields.comment.comments[].body`)를 쓴다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import compat, dbpath, failedstep, masking, site_defaults, userconfig, yamlio  # noqa: E402
from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402

DEFAULT_KEY_RE = r"[A-Z][A-Z0-9]+-\d+"
STRUCTURED = ("model", "sw", "android_version", "carrier")
TEXT_DEFAULTS = {
    "summary": ["fields.summary", "summary"],
    "description": ["fields.description", "description"],
    "comments": ["comments[].body", "fields.comment.comments[].body"],
}


class UsageError(Exception):
    pass


def _db(arg: str | None) -> Path | None:
    try:
        return dbpath.resolve(arg)
    except dbpath.DbPathError:
        if arg:
            raise
        return None


def _db_cfg(db: Path | None) -> dict:
    return compat.load_db_config(db) if db else {}


def key_regex(db: Path | None) -> re.Pattern:
    return re.compile(str(_db_cfg(db).get("jira_key_regex") or DEFAULT_KEY_RE))


def lookup(node, path: str):
    """`a.b[].c` 경로 값. 목록 펼침이 있으면 목록, 없으면 값(없으면 None)."""
    if not path:
        return None
    values, spread = [node], False
    for part in path.split("."):
        many = part.endswith("[]")
        name = part[:-2] if many else part
        nxt = []
        for v in values:
            if isinstance(v, dict) and name in v:
                v = v[name]
            elif name:
                continue
            if many:
                spread = True
                nxt.extend(v if isinstance(v, list) else [])
            else:
                nxt.append(v)
        values = nxt
    if spread:
        return [v for v in values if v is not None]
    return values[0] if values else None


def _first(node, paths: list[str]):
    for p in paths:
        v = lookup(node, p)
        if v not in (None, "", []):
            return v
    return None


def _zone(name: str | None, what: str) -> ZoneInfo:
    if not name:
        raise UsageError(f"{what} 타임존이 설정에 없습니다 (setup 또는 site-defaults).")
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UsageError(f"{what} 타임존 {name}을 알 수 없습니다.") from exc


def parse_time(value, tz: ZoneInfo) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)  # +0900 → +09:00
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def comment_budget(spec: str) -> int | None:
    """`all` → None(전부), `last:N` → N. 결정적 절삭이다(뒤에서 N개)."""
    if spec == "all":
        return None
    m = re.fullmatch(r"last:(\d+)", spec or "")
    if not m:
        raise UsageError(f"--comments는 all 또는 last:<N>이다: {spec}")
    return int(m.group(1))


def _failed_step_part(raw, fmap, jira_cfg, text, masker, cli, steps_file, step_cfg=None) -> dict:
    """선택 키(`test_steps`·`failed_step_auto`·`failed_step`·`warnings`). 없으면 키를 만들지 않는다."""
    out: dict = {}
    patterns = jira_cfg.get("failed_step_patterns") or []
    steps_raw = lookup(raw, fmap["test_steps"]) if fmap.get("test_steps") else None
    steps = masker(_text(steps_raw)) if steps_raw not in (None, "", []) else ""
    field = lookup(raw, fmap["failed_step"]) if fmap.get("failed_step") else None
    if isinstance(field, list):
        field = " ".join(_text(v) for v in field)
    elif isinstance(field, dict):
        field = _text(field)
    auto, warnings = failedstep.auto_from(field, text["description"], steps, patterns, masker)
    final, more = failedstep.resolve(cli, auto, steps_file, patterns, masker, step_cfg)
    warnings += [w for w in more if w not in warnings]
    if steps:
        if len(steps) > failedstep.TEST_STEPS_MAX:
            steps = steps[: failedstep.TEST_STEPS_MAX - 1] + "…"
        out["test_steps"] = steps
    if auto:
        out["failed_step_auto"] = auto
    if final:
        out["failed_step"] = final
    if warnings:
        out["warnings"] = warnings
    return out


def extract(raw: dict, cfg: dict, db: Path | None, origin: str, last: int | None = None,
            chars: int = 0, failed_step: str | None = None, steps_file: str | None = None) -> dict:
    jira_cfg = cfg.get("jira") or {}
    fmap = jira_cfg.get("field_map") or {}
    jtz = _zone(jira_cfg.get("timezone"), "Jira")
    logcat_cfg = cfg.get("logcat") or {}
    ltz = _zone(logcat_cfg.get("timezone"), "logcat")

    key = str(raw.get("key") or lookup(raw, "issue.key") or "")
    kre = key_regex(db)
    missing: list[str] = []

    structured = {}
    for name in STRUCTURED:
        v = lookup(raw, fmap.get(name, "")) if fmap.get(name) else None
        if isinstance(v, list):
            v = ", ".join(map(str, v))
        structured[name] = None if v in (None, "") else str(v)
        if structured[name] is None and name != "carrier":
            missing.append(name)

    when = parse_time(lookup(raw, fmap.get("occurred_at", "")) if fmap.get("occurred_at") else None, jtz)
    if when is None:
        missing.append("occurred_at")

    allow = list((_db_cfg(db).get("mask") or {}).get("allow_patterns") or [])
    masker = masking.new_masker(allow_patterns=allow)

    def texts(name: str):
        paths = [fmap[name]] if fmap.get(name) else TEXT_DEFAULTS[name]
        return _first(raw, paths)

    comments = texts("comments") or []
    if not isinstance(comments, list):
        comments = [comments]
    comments = [c for c in comments if _text(c)]
    total = len(comments)
    if last is not None:
        comments = comments[-last:] if last else []
    masked = [masker(_text(c)) for c in comments]
    if chars:
        masked = [m if len(m) <= chars else m[: chars - 1] + "…" for m in masked]
    text = {
        "summary": masker(_text(texts("summary"))),
        "description": masker(_text(texts("description"))),
        "comments": masked,
        "comments_total": total,
    }

    slot = lookup(raw, fmap["sim_slot"]) if fmap.get("sim_slot") else None
    comps = lookup(raw, fmap.get("components") or "fields.components[].name") or []
    if not isinstance(comps, list):
        comps = [comps]

    optional = _failed_step_part(raw, fmap, jira_cfg, text, masker, failed_step, steps_file, cfg.get("failed_step"))

    local = when.astimezone(jtz) if when else None
    year = None
    if when and (logcat_cfg.get("year_source") or "jira") == "jira":
        year = when.astimezone(ltz).year
    jira_block = {"key": key, "origin": origin, **structured}
    if local:
        jira_block["occurred_on"] = local.date().isoformat()
    if optional.get("failed_step") or optional.get("failed_step_auto"):
        jira_block["failed_step"] = (optional.get("failed_step") or optional["failed_step_auto"])["text"]
    if "test_steps" in optional:
        text["test_steps"] = optional.pop("test_steps")
    result = {
        "key": key,
        "key_valid": bool(key and kre.fullmatch(key)),
        "origin": origin,
        "jira": jira_block,
        "occurred_at": when.astimezone(timezone.utc).isoformat() if when else None,
        "occurred_at_local": local.isoformat() if local else None,
        "logcat": {"tz": str(ltz.key), "year": year, "year_source": logcat_cfg.get("year_source") or "jira"},
        "sim_slot": None if slot in (None, "") else str(slot),
        "components": [str(c) for c in comps],
        "text": text,
        "missing": missing,
    }
    result.update(optional)
    return result


def _read(path: Path) -> dict:
    if not path.is_file():
        raise UsageError(f"파일이 없습니다: {path}")
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = yamlio.safe_load(raw)
    if isinstance(data, dict) and isinstance(data.get("issue"), dict) and "key" not in data:
        data = data["issue"]
    if not isinstance(data, dict):
        raise UsageError(f"Jira 응답 형식이 아닙니다(객체가 아님): {path}")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력 (항상 JSON)")
    common.add_argument("--plugin-root", default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-key", parents=[common])
    p.add_argument("key", metavar="KEY")
    p = sub.add_parser("extract", parents=[common])
    p.add_argument("raw", metavar="raw.json|yaml")
    p.add_argument("--origin", choices=["mcp", "file"], default="mcp")
    p.add_argument("--meta-out", metavar="file")
    p.add_argument("--consume", action="store_true")
    p.add_argument("--comments", metavar="all|last:N", default="all", help="코멘트 예산: all | last:<N> (뒤에서 N개)")
    p.add_argument("--comment-chars", metavar="N", type=int, default=0, help="코멘트 하나의 최대 글자 수 (0이면 자르지 않음)")
    p.add_argument("--failed-step", metavar="한 줄", help="실패 스텝 한 줄(선택, 마스킹 후 사용)")
    p.add_argument("--steps-file", metavar="파일", help="시험 절차 첨부 파일(txt/csv/html/zip, 선택). 읽지 못하면 경고만 내고 진행")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(getattr(args, "plugin_root", None))
    try:
        db = _db(getattr(args, "db", None))
        if args.cmd == "check-key":
            ok = bool(key_regex(db).fullmatch(args.key))
            result = {"key": args.key, "valid": ok, "regex": key_regex(db).pattern}
            print(json.dumps(result, ensure_ascii=False))
            return OK if ok else CHECK_FAILED
        path = Path(args.raw)
        raw = _read(path)
        if args.comment_chars < 0:
            raise UsageError("--comment-chars는 0 이상이다.")
        result = extract(raw, userconfig.merged(defaults), db, args.origin,
                         comment_budget(args.comments), args.comment_chars,
                         args.failed_step, args.steps_file)
        if args.meta_out:
            meta = {"key": result["key"], "sw": result["jira"].get("sw"),
                    "summary": result["text"]["summary"], "description": result["text"]["description"]}
            if result["jira"].get("android_version"):
                meta["android_version"] = result["jira"]["android_version"]
            if result["occurred_at"]:
                meta["occurred_at"] = result["occurred_at"]
            fs = result.get("failed_step") or result.get("failed_step_auto")
            if fs:
                meta["failed_step"] = fs["text"]
            out = Path(args.meta_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
            result["meta_out"] = str(out)
        else:
            result["meta_out"] = None
        if args.consume:
            path.unlink(missing_ok=True)
    except (UsageError, dbpath.DbPathError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
