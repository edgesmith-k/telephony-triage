#!/usr/bin/env python3
"""parse_logcat.py — logcat 파서 엔진 (contracts.md §3.2, 04-parser-matching.md §5.8,
07-workflow.md §Step 3, 16-existing-assets.md §16.3).

서브커맨드
  parse <logcat...> (--around <ISO 시각> [--minutes 5] | --full) --rules <db>/parser-rules
        [--tz <IANA>] [--year <YYYY>] [--mask] [--no-external]
      이벤트 JSON을 stdout으로 낸다.
  extract-bugreport <zip|txt> --out <dir>
      bugreport에서 logcat 섹션(system/radio/main)과 빌드 정보(build.json)만 꺼낸다.
  cut <logcat...> (--evidence <match.json> | --around <ISO 시각> [--seconds 30]) --out <file>
      [--context 20] [--max-lines 100] [--tz <IANA>] [--year <YYYY>] [--rules <db>/parser-rules]
      판별 근거 주변 최소 구간을 마스킹된 상태로만 쓴다(fixture용).

설정 읽기: 사용자 config를 읽지 않는다(시각은 `--tz`/`--year`). 파서 백엔드와
외부 파서 설정은 플러그인 `site-defaults.yaml`에서만 읽는다. 이슈 DB 쪽 고정값
(`parser_backend`, `external_parsers`)은 `--rules`의 상위 디렉토리
`issue-db.config.yaml`에서 읽고 다르면 경고한다(분석은 계속한다).

처리 순서 (parse)
  1. 백엔드(`parser.backend`): 포맷·시각(UTC)·RIL 페어링·윈도우, builtin 판별
  2. 태그 → 카테고리 매핑(`tags.yaml`). 목록에 없는 태그의 줄은 버린다
  3. 마스킹(`--mask`) — extractor보다 **먼저**, 한 번의 파싱에 마스커 하나(같은 값 = 같은 번호)
  4. RIL 파생 이벤트(`ril.yaml` timeout): `ril_error`, `ril_timeout`, `ril_no_response`
  5. extractor(`extractors.yaml`). 패턴마다 시간 상한 `matcher.pattern_timeout_ms`
     (넘기면 그 extractor 이벤트를 버리고 `errors`·경고 `pattern-timeout`)
  6. 외부 파서(`external_parsers`, `--no-external`이면 건너뜀)
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import zipfile
from datetime import timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import adapters  # noqa: E402
import parser_backends  # noqa: E402
from common import compat, masking, parser_rules, site_defaults  # noqa: E402
from common.patterns import DEFAULT_TIMEOUT_MS, PatternError, PatternRunner, PatternTimeout  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402
from parser_backends import logcat  # noqa: E402

OUTPUT_SCHEMA = 1
DEFAULT_MINUTES = 5


class UsageError(Exception):
    """종료 코드 2로 끝낸다."""


# -- 공통 후처리 ------------------------------------------------------------


def _derived(base: dict, event: str, fields: dict, source: str) -> dict:
    return {
        "ts": base["ts"],
        "pid": base.get("pid"),
        "tid": base.get("tid"),
        "level": base.get("level"),
        "tag": base.get("tag"),
        "msg": base.get("msg"),
        "phone_id": base.get("phone_id"),
        "category_hint": base.get("category_hint"),
        "ril": None,
        "event": event,
        "fields": {k: str(v) for k, v in fields.items()},
        "source": source,
    }


def _ril_events(rec: dict, rules: parser_rules.Rules, last_ts: str | None) -> list[dict]:
    ann = rec.get("ril")
    if not ann or ann["dir"] not in ("req", "resp"):
        return []
    # A different buffer/device/restart cannot extend this request's observation.
    last_ts = ann.get("observed_until", rec["ts"])
    rule = rules.requests.get(ann["request"])
    if not rule:
        return []
    timeout = int(rule["timeout_ms"])
    base_fields = {"request": ann["request"], "serial": ann["serial"]}
    out = []
    if ann["dir"] == "resp":
        if ann["error"] not in (None, "NONE"):
            out.append(_derived(rec, "ril_error", {**base_fields, "error": ann["error"]}, "rules"))
        if ann["latency_ms"] is not None and ann["latency_ms"] > timeout:
            out.append(
                _derived(
                    rec,
                    "ril_timeout",
                    {**base_fields, "latency_ms": ann["latency_ms"], "timeout_ms": timeout},
                    "rules",
                )
            )
    elif ann["paired_ts"] is None and last_ts is not None:
        # 파일이 요청 + timeout 이후까지 있는데 응답이 없을 때만 "응답 없음"이다.
        deadline = logcat.parse_ts(rec["ts"]) + timedelta(milliseconds=timeout)
        if logcat.parse_ts(last_ts) >= deadline:
            out.append(
                _derived(rec, "ril_no_response", {**base_fields, "timeout_ms": timeout}, "rules")
            )
    return out


def _run_extractors(lines: list[dict], rules: parser_rules.Rules, timeout_ms: int | None,
                    errors: list[dict]) -> list[list[dict]]:
    """줄 레코드 목록에 extractor를 돌려 줄마다 파생 이벤트 목록을 준다(규칙 순서).

    패턴은 시간 상한(`matcher.pattern_timeout_ms`)을 지키는 실행기에서 돈다. 넘기면 그
    extractor의 이벤트를 모두 버리고 `errors`에 남긴다(분석은 계속, 04 §5.8 (4)).
    """
    derived: list[list[dict]] = [[] for _ in lines]
    msgs = [rec["msg"] for rec in lines]
    with PatternRunner(msgs, timeout_ms) as runner:
        for ex in rules.extractors:
            remaining = [i for i, rec in enumerate(lines) if ex.tag_matches(rec["tag"])]
            found: list[tuple[int, dict]] = []
            try:
                for pattern in ex.patterns:
                    if not remaining:
                        break
                    hits = runner.search(pattern.pattern, indices=remaining)
                    hit_set = set(hits)
                    for i in hits:
                        groups = pattern.search(msgs[i]).groupdict()
                        fields = {f: groups[f] for f in ex.fields if groups.get(f) is not None}
                        found.append((i, _derived(lines[i], ex.event, fields, "rules")))
                    remaining = [i for i in remaining if i not in hit_set]
            except (PatternTimeout, PatternError) as exc:
                errors.append({"extractor": ex.id, "error": str(exc)})
                continue
            for i, rec in sorted(found, key=lambda item: item[0]):
                derived[i].append(rec)
    return derived


def _mask_record(rec: dict, masker) -> dict:
    rec = dict(rec)
    if isinstance(rec.get("msg"), str):
        rec["msg"] = masker(rec["msg"])
    # 필드 값은 같은 마스커의 번호 대응을 쓴다: 줄에서 본 원래 값이면 같은 토큰이 된다
    # (문맥 없는 값도 마스킹된다, 08-safety.md §8).
    mask_value = getattr(masker, "mask_value", masker)
    rec["fields"] = {
        k: mask_value(v) if isinstance(v, str) else v for k, v in (rec.get("fields") or {}).items()
    }
    return rec


def postprocess(
    events: list[dict],
    rules: parser_rules.Rules,
    *,
    masker=None,
    last_ts: str | None = None,
    timeout_ms: int | None = None,
    errors: list[dict] | None = None,
) -> list[dict]:
    """백엔드 출력에 태그 매핑 → 마스킹 → RIL 파생 이벤트 → extractor를 적용한다.

    줄 레코드(`event: None`)는 `tags.yaml`에 없는 태그면 버린다. builtin 레코드는
    그대로 두고(마스킹만) 줄 레코드와 함께 낸다. 파생 이벤트는 그 줄 바로 뒤에 온다
    (RIL 파생 이벤트, 그다음 extractor 이벤트를 규칙 순서로).
    """
    errors = [] if errors is None else errors
    kept: list[dict] = []
    for rec in events:
        if rec.get("event") is None:
            category = rules.tag_category(rec["tag"])
            if category is None:
                continue
            ann = rec.get("ril")
            if ann:
                category = rules.ril_category(ann["request"]) or category
            rec = dict(rec, category_hint=category)
            kept.append(_mask_record(rec, masker) if masker else rec)
        else:
            kept.append(_mask_record(rec, masker) if masker else dict(rec))

    line_pos = [i for i, rec in enumerate(kept) if rec.get("event") is None]
    extracted = _run_extractors([kept[i] for i in line_pos], rules, timeout_ms, errors)
    by_pos = dict(zip(line_pos, extracted))

    out: list[dict] = []
    for i, rec in enumerate(kept):
        out.append(rec)
        if i in by_pos:
            out.extend(_ril_events(rec, rules, last_ts))
            out.extend(by_pos[i])
    return out


# -- 외부 파서 ---------------------------------------------------------------


def _external_configs(defaults: dict) -> dict[str, dict]:
    raw = defaults.get("external_parsers") or {}
    if not isinstance(raw, dict):
        raise UsageError("site-defaults.yaml: external_parsers는 매핑이어야 합니다.")
    return raw


def _external_status(configs: dict[str, dict]) -> tuple[dict, dict, list[dict]]:
    """카테고리별 어댑터 모듈과 현재 환경 정보 `{adapter, version, available}`."""
    modules, status, warnings = {}, {}, []
    for category, conf in sorted(configs.items()):
        conf = conf or {}
        name = conf.get("adapter")
        info = {"adapter": name, "version": conf.get("version"), "available": False}
        try:
            module = adapters.load(name)
        except adapters.AdapterError as exc:
            warnings.append({"code": "external-parser-failed", "message": f"[{category}] {exc}"})
        else:
            modules[category] = module
            info["available"] = True
            if info["version"] is None:
                info["version"] = module.VERSION
        status[category] = info
    return modules, status, warnings


def _run_external(
    category: str,
    conf: dict,
    module,
    paths: list[Path],
    plugin_root: Path,
    tz: str | None,
    year: int | None,
    window,
) -> tuple[list[dict], list[dict]]:
    command = conf.get("command")
    if not isinstance(command, list) or not command:
        return [], [_ext_warn(category, "command가 비어 있습니다")]
    timeout = float(conf.get("timeout_sec", 120))
    prefix = f"ext.{category}."
    events, warnings = [], []
    dropped = 0
    for path in paths:
        argv = [
            str(a).replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root)).replace("{log}", str(path))
            for a in command
        ]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            warnings.append(_ext_warn(category, f"실행 실패({path.name}): {exc}"))
            continue
        if proc.returncode != 0:
            warnings.append(_ext_warn(category, f"종료 코드 {proc.returncode}({path.name})"))
            continue
        try:
            raw = json.loads(proc.stdout) if conf.get("output", "json") == "json" else proc.stdout
            converted = module.convert(raw, {"log": str(path), "category": category, "tz": tz, "year": year})
            converted = list(converted or [])
            if any(not isinstance(item, dict) or not isinstance(item.get("fields") or {}, dict)
                   for item in converted):
                raise ValueError("어댑터 이벤트 형식 오류")
        except Exception as exc:  # noqa: BLE001 — 외부 코드. 분석은 계속한다.
            warnings.append(_ext_warn(category, f"출력 변환 실패({path.name}): {exc}"))
            continue
        for item in converted or []:
            name = item.get("event")
            if name is not None and not str(name).startswith(prefix):
                dropped += 1
                continue
            dt = logcat.normalize_ts(item.get("ts"), tz, year)
            if dt is None:
                dropped += 1
                continue
            if window and not (window[0] <= dt <= window[1]):
                continue
            events.append(
                {
                    "ts": logcat.format_ts(dt),
                    "pid": item.get("pid"),
                    "tid": item.get("tid"),
                    "level": item.get("level"),
                    "tag": item.get("tag"),
                    "msg": item.get("msg") or "",
                    "phone_id": item.get("phone_id"),
                    "category_hint": category,
                    "ril": None,
                    "event": name,
                    "fields": {k: str(v) for k, v in (item.get("fields") or {}).items() if v is not None},
                    "source": f"external:{module.ADAPTER_NAME}",
                }
            )
    if dropped:
        warnings.append(
            _ext_warn(category, f"이벤트 {dropped}개를 버렸습니다 (이름이 {prefix}* 이 아니거나 시각을 모름)")
        )
    return events, warnings


def _ext_warn(category: str, message: str) -> dict:
    return {"code": "external-parser-failed", "message": f"[{category}] {message}"}


# -- parse -------------------------------------------------------------------


def _looks_like_bugreport(path: Path) -> bool:
    if path.suffix.lower() == ".zip":
        return True
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            head = [fh.readline() for _ in range(5)]
    except OSError:
        return False
    return any(line.startswith("== dumpstate") for line in head)


def _window(args) -> tuple | None:
    if args.full:
        return None
    try:
        center = logcat.parse_ts(args.around)
    except ValueError as exc:
        raise UsageError(
            f"--around는 타임존이 있는 ISO 시각이어야 합니다(예: 2026-09-20T14:32:10+09:00): {exc}"
        ) from exc
    minutes = timedelta(minutes=args.minutes)
    return (center - minutes, center + minutes)


def _in_range(window, coverage: dict) -> bool | str:
    if window is None:
        return True
    if not coverage["first_ts"]:
        return False
    first, last = logcat.parse_ts(coverage["first_ts"]), logcat.parse_ts(coverage["last_ts"])
    start, end = window
    if end < first or start > last:
        return False
    if start >= first and end <= last:
        return True
    return "partial"


def _read_texts(paths: list[Path]) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in paths)


def _allow_patterns(db_cfg: dict) -> list[str]:
    return list((db_cfg.get("mask") or {}).get("allow_patterns") or [])


def run_parse(args, plugin_root: Path, defaults: dict) -> dict:
    paths = [Path(p) for p in args.logs]
    for path in paths:
        if not path.is_file():
            raise UsageError(f"로그 파일이 없습니다: {path}")
        if _looks_like_bugreport(path):
            raise UsageError(
                f"{path.name}은(는) bugreport입니다. 먼저 extract-bugreport로 logcat 섹션을 꺼내세요."
            )
    try:
        logcat.get_tz(args.tz)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    window = _window(args)

    rules_dir = Path(args.rules)
    try:
        rules = parser_rules.load(rules_dir)
    except parser_rules.RulesError as exc:
        raise UsageError(f"파서 규칙 오류: {exc}") from exc
    db_cfg = compat.load_db_config(rules_dir.parent)

    backend_name = (defaults.get("parser") or {}).get("backend")
    try:
        backend = parser_backends.load(backend_name)
    except parser_backends.BackendError as exc:
        raise UsageError(f"site-defaults.yaml parser.backend: {exc}") from exc

    masker = None
    if args.mask:
        # 입력에 이미 있는 토큰의 다음 번호부터 준다 (부분 마스킹된 로그, fixture 재파싱).
        masker = masking.new_masker(_read_texts(paths), _allow_patterns(db_cfg))

    warnings: list[dict] = []
    warnings += compat.check_parser_backend(db_cfg, backend.name, backend.version())

    coverage = backend.coverage(paths, args.tz, args.year)
    stats = coverage.pop("stats", {})
    if stats.get("missing_zone"):
        warnings.append({"code": "tz_assumed_utc", "message": "--tz가 없어 logcat 시각을 UTC로 해석했습니다."})
    if stats.get("missing_year"):
        warnings.append(
            {"code": "year_assumed", "message": f"--year가 없어 연도를 {logcat.DEFAULT_YEAR}로 해석했습니다."}
        )
    if stats.get("unparsed"):
        warnings.append(
            {"code": "unparsed-lines", "message": f"형식을 모르는 줄 {stats['unparsed']}개를 건너뛰었습니다."}
        )
    if not stats.get("lines"):
        warnings.append({"code": "no-lines-parsed", "message": "해석한 logcat 줄이 없습니다."})
    coverage = {
        "first_ts": coverage["first_ts"],
        "last_ts": coverage["last_ts"],
        "window_in_range": _in_range(window, coverage),
        "clock_anomalies": coverage["clock_anomalies"],
    }

    timeout_ms = int((db_cfg.get("matcher") or {}).get("pattern_timeout_ms", DEFAULT_TIMEOUT_MS))
    errors: list[dict] = []
    events = backend.parse(paths, args.tz, args.year, window)
    events = postprocess(events, rules, masker=masker, last_ts=coverage["last_ts"],
                         timeout_ms=timeout_ms, errors=errors)
    for error in errors:
        warnings.append({"code": "pattern-timeout",
                         "message": f"extractor {error['extractor']}: {error['error']}"})

    configs = _external_configs(defaults)
    external_info = []
    if not args.no_external and configs:
        modules, status, ext_warn = _external_status(configs)
        warnings += ext_warn
        warnings += compat.check_external(db_cfg, status)
        for category, conf in sorted(configs.items()):
            if category not in modules:
                continue
            ext_events, w = _run_external(
                category, conf, modules[category], paths, plugin_root, args.tz, args.year, window
            )
            warnings += w
            mode = conf.get("mode", "merge")
            if mode == "replace" and not w:
                events = [
                    e
                    for e in events
                    if not (e["category_hint"] == category and e["source"].startswith("backend:"))
                ]
            else:
                ext_events = [e for e in ext_events if e["event"] is not None]
            if masker:
                ext_events = [_mask_record(e, masker) for e in ext_events]
            events += ext_events
            external_info.append(
                {"category": category, "adapter": status[category]["adapter"],
                 "version": status[category]["version"], "mode": mode}
            )
        events.sort(key=lambda e: e["ts"])  # 안정 정렬: 같은 시각이면 백엔드 레코드가 먼저
    elif not args.no_external:
        warnings += compat.check_external(db_cfg, {})

    return {
        "schema": OUTPUT_SCHEMA,
        "backend": {"name": backend.name, "version": backend.version()},
        "external": external_info,
        "external_disabled": bool(args.no_external),
        "complete": not args.no_external and not observation_errors({"warnings": warnings}),
        "rules": {"path": str(rules_dir), **rules.summary()},
        "input": {
            "files": [str(p) for p in paths],
            "tz": args.tz,
            "year": args.year,
            "mode": "full" if args.full else "around",
            "window": None if window is None else {
                "start": logcat.format_ts(window[0]),
                "end": logcat.format_ts(window[1]),
            },
        },
        "coverage": coverage,
        "masked": masker is not None,
        "warnings": warnings,
        "errors": errors,
        "events": events,
    }


def observation_errors(doc: dict) -> list[dict]:
    """Missing observations cannot establish absence of a cause."""
    codes = {"external-parser-failed", "external-parser-mismatch", "parser-backend-mismatch"}
    errors = [{"error": w["message"], "code": w["code"]} for w in doc.get("warnings", [])
              if w.get("code") in codes]
    if (doc.get("external_disabled") or doc.get("complete") is False) and not errors:
        errors.append({"error": "파서 관측 불완전", "code": "incomplete-observation"})
    return errors


# -- extract-bugreport --------------------------------------------------------

# bugreport 섹션 헤더 — TODO(SITE:S21) 사내 실제 문자열로 확인한다.
# 예: "------ RADIO LOG (logcat -b radio -v threadtime -d *:v) ------"
SECTION_RE = re.compile(r"^------ (?P<title>.+?) \((?P<cmd>logcat\b[^)]*)\) ------\s*$")
SECTION_BOUNDARY_RE = re.compile(r"^------ .* ------\s*$")
BUFFER_RE = re.compile(r"-b\s+(?P<buf>[a-z]+)")
BUILD_RE = re.compile(r"^Build:\s*(?P<v>.+?)\s*$")
FINGERPRINT_RE = re.compile(r"^Build fingerprint:\s*'?(?P<v>[^']+?)'?\s*$")
WANTED_BUFFERS = ("system", "radio", "main")


def _open_bugreport(path: Path) -> tuple[io.TextIOBase, list]:
    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        members = [
            info for info in zf.infolist()
            if info.filename.lower().endswith(".txt")
            and Path(info.filename).name.lower().startswith("bugreport")
        ]
        if not members:
            zf.close()
            raise UsageError(f"{path.name}: bugreport 본문(bugreport-*.txt)이 zip 안에 없습니다.")
        member = max(members, key=lambda i: i.file_size)
        return io.TextIOWrapper(zf.open(member), encoding="utf-8", errors="replace"), [zf]
    return path.open(encoding="utf-8", errors="replace"), []


def run_extract_bugreport(args) -> dict:
    src = Path(args.bugreport)
    if not src.is_file():
        raise UsageError(f"bugreport 파일이 없습니다: {src}")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    build = {"build": None, "fingerprint": None}
    writers: dict[str, io.TextIOBase] = {}
    counts: dict[str, int] = {}
    current = None
    in_header = True
    stream, closers = _open_bugreport(src)
    try:
        for raw in stream:
            line = raw.rstrip("\r\n")
            if SECTION_BOUNDARY_RE.match(line):
                in_header = False
                current = None
                hit = SECTION_RE.match(line)
                if hit:
                    buf = BUFFER_RE.search(hit.group("cmd"))
                    if buf and buf.group("buf") in WANTED_BUFFERS:
                        current = buf.group("buf")
                        if current not in writers:
                            writers[current] = (out_dir / f"logcat-{current}.txt").open(
                                "w", encoding="utf-8", newline="\n"
                            )
                            counts[current] = 0
                continue
            if in_header:
                hit = BUILD_RE.match(line)
                if hit and build["build"] is None:
                    build["build"] = hit.group("v")
                hit = FINGERPRINT_RE.match(line)
                if hit and build["fingerprint"] is None:
                    build["fingerprint"] = hit.group("v")
                continue
            if current is not None:
                writers[current].write(line + "\n")
                counts[current] += 1
    finally:
        stream.close()
        for closer in closers:
            closer.close()
        for writer in writers.values():
            writer.close()

    if not writers:
        raise UsageError(
            f"{src.name}: logcat 섹션(system/radio/main)을 찾지 못했습니다. "
            "섹션 헤더 형식이 다를 수 있습니다 (S21)."
        )
    warnings = []
    if build["fingerprint"] is None:
        warnings.append({"code": "no-fingerprint", "message": "헤더에 Build fingerprint가 없습니다."})
    build_json = out_dir / "build.json"
    build_json.write_text(
        json.dumps({**build, "source": src.name}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "files": [
            {"buffer": name, "path": str(out_dir / f"logcat-{name}.txt"), "lines": counts[name]}
            for name in WANTED_BUFFERS
            if name in writers
        ],
        "build_json": str(build_json),
        "build": build,
        "warnings": warnings,
    }


# -- cut ------------------------------------------------------------------------


def _cut_anchors(args, lines: list) -> set[int]:
    """앵커 줄의 전체 순번 집합."""
    if args.around:
        try:
            center = logcat.parse_ts(args.around)
        except ValueError as exc:
            raise UsageError(f"--around는 타임존이 있는 ISO 시각이어야 합니다: {exc}") from exc
        span = timedelta(seconds=args.seconds)
        return {i for i, (_, line, _) in enumerate(lines) if center - span <= line.dt <= center + span}
    try:
        match = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"--evidence를 읽을 수 없습니다: {exc}") from exc
    candidates = match.get("candidates") or []
    evidence = candidates[0].get("evidence") if candidates else None
    if not evidence:
        raise UsageError("--evidence: 1위 후보에 근거가 없습니다.")
    wanted = {(e["ts"], e.get("tag")) for e in evidence}
    return {i for i, (_, line, _) in enumerate(lines) if (logcat.format_ts(line.dt), line.tag) in wanted}


def run_cut(args) -> dict:
    """판별 근거(또는 지정 시각) 주변 최소 구간을 **마스킹해서** 파일로 쓴다.

    앵커 줄 앞뒤 `--context` 줄(파일 순서)을 합치고, `--max-lines`를 넘으면 context를
    줄인다. 앵커만으로도 넘으면 종료 코드 2. 여러 파일이면 시각 순으로 합친다.
    """
    paths = [Path(p) for p in args.logs]
    for path in paths:
        if not path.is_file():
            raise UsageError(f"로그 파일이 없습니다: {path}")
    try:
        logcat.get_tz(args.tz)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    lines = []  # (파일 순번, LogLine, 원문 줄)
    for index, path in enumerate(paths):
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
        parsed, _ = logcat.read_file(path, index, args.tz, args.year)
        lines += [(index, line, raw[line.line_no - 1]) for line in parsed]
    anchors = _cut_anchors(args, lines)
    if not anchors:
        raise UsageError("앵커 줄이 없습니다 (시각·근거가 로그 범위 밖이거나 --tz/--year가 다름).")

    def select(context: int) -> list[int]:
        chosen: set[int] = set()
        for i in anchors:
            file_index = lines[i][0]
            for j in range(max(0, i - context), min(len(lines), i + context + 1)):
                if lines[j][0] == file_index:
                    chosen.add(j)
        return sorted(chosen, key=lambda j: (lines[j][1].dt, lines[j][0], lines[j][1].line_no))

    context = max(0, args.context)
    chosen = select(context)
    while len(chosen) > args.max_lines and context > 0:
        context -= 1
        chosen = select(context)
    if len(chosen) > args.max_lines:
        raise UsageError(f"근거 줄만 {len(chosen)}줄이라 --max-lines {args.max_lines}를 넘습니다.")

    allow = []
    if args.rules:
        allow = _allow_patterns(compat.load_db_config(Path(args.rules).parent))
    texts = [lines[j][2] for j in chosen]
    masker = masking.new_masker("\n".join(texts), allow)
    masked = [masker(text) for text in texts]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(masked) + "\n", encoding="utf-8", newline="\n")
    return {
        "out": str(out),
        "lines": len(masked),
        "anchors": len(anchors),
        "context": context,
        "masked": True,
        "replacements": dict(sorted(masker.counts.items())),
        "warnings": [],
    }


# -- main ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="JSON 출력 (parse·extract-bugreport는 항상 JSON)")
    common.add_argument("--plugin-root", default=argparse.SUPPRESS,
                        help="플러그인 루트 (기본: ${CLAUDE_PLUGIN_ROOT})")

    parser = argparse.ArgumentParser(prog="parse_logcat.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse", parents=[common], help="logcat → 이벤트 JSON")
    p.add_argument("logs", nargs="+")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--around", help="발생 시각 (타임존 있는 ISO)")
    mode.add_argument("--full", action="store_true", help="파일 전체")
    p.add_argument("--minutes", type=float, default=DEFAULT_MINUTES)
    p.add_argument("--rules", required=True, help="<db>/parser-rules")
    p.add_argument("--tz", default=None, help="연도 없는 logcat 시각의 타임존 (IANA)")
    p.add_argument("--year", type=int, default=None, help="첫 줄의 연도")
    p.add_argument("--mask", action="store_true", help="extractor 전에 줄 단위 마스킹")
    p.add_argument("--no-external", action="store_true", help="외부 파서 끔 (분석 디버그용)")

    b = sub.add_parser("extract-bugreport", parents=[common], help="bugreport → logcat 섹션")
    b.add_argument("bugreport")
    b.add_argument("--out", required=True)

    c = sub.add_parser("cut", parents=[common], help="판별 근거 주변 최소 구간 (마스킹해서 쓴다)")
    c.add_argument("logs", nargs="+")
    anchor = c.add_mutually_exclusive_group(required=True)
    anchor.add_argument("--evidence", help="match_signatures.py 출력 (1위 후보의 근거)")
    anchor.add_argument("--around", help="지정 시각 (타임존 있는 ISO)")
    c.add_argument("--seconds", type=float, default=30, help="--around 앞뒤 초")
    c.add_argument("--out", required=True)
    c.add_argument("--rules", default=None, help="<db>/parser-rules (mask.allow_patterns를 읽는다)")
    c.add_argument("--context", type=int, default=20)
    c.add_argument("--max-lines", type=int, default=100)
    c.add_argument("--tz")
    c.add_argument("--year", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    root_opt = getattr(args, "plugin_root", None)
    defaults = site_defaults.load_or_exit(root_opt)
    plugin_root = Path(root_opt) if root_opt else site_defaults.plugin_root()

    try:
        if args.cmd == "parse":
            result = run_parse(args, plugin_root, defaults)
        elif args.cmd == "extract-bugreport":
            result = run_extract_bugreport(args)
        else:
            result = run_cut(args)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    for warning in result.get("warnings", []):
        print(f"경고[{warning['code']}]: {warning['message']}", file=sys.stderr)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
