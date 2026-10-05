#!/usr/bin/env python3
"""parse_logcat.py — logcat 파서 엔진 (contracts.md §3.2, 04-parser-matching.md §5.8,
07-workflow.md §Step 3, 16-existing-assets.md §16.3).

서브커맨드
  parse <logcat...> (--around <ISO 시각> [--minutes 5] | --between <ISO 시작> <ISO 끝> | --full)
        --rules <db>/parser-rules [--tz <IANA>] [--year <YYYY>] [--mask] [--no-external]
      이벤트 JSON을 stdout으로 낸다. `--between`은 명시 구간(타임존 있는 ISO 둘, 시작 ≤ 끝)이다.
  markers <logcat...> --rules <db>/parser-rules [--tz <IANA>] [--year <YYYY>] [--step-events]
      시험 자동화의 스텝 마커 줄(`failed_step.marker_patterns`, site-defaults에서만 읽는다)을 모아
      `{schema, markers[{ts, step, status, tag, msg}], total, truncated, coverage, warnings}`로 낸다(상한 2000).
      `--step-events`: 이슈 DB `issue-db.config.yaml`의 `step_events` 규칙(스텝 이름은 인자로 받지 않는다)마다 로그에서
      그 흔적을 모아 `step_events[{rule, ts, seq, label}]`(규칙 번호·시각·줄 순번·이름 — 로그 본문 없음, (ts, seq, rule) 순)을
      더한다. 규칙당 1000개·전체 5000개 상한(넘으면 경고 `step-events-truncated`), 잘못된 규칙은 경고 `step-event-rule`.
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
import json
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import adapters  # noqa: E402
import parser_backends  # noqa: E402
from common import compat, masking, parser_rules, site_defaults, stepanchor  # noqa: E402
from common import events as evt  # noqa: E402
from common.patterns import DEFAULT_TIMEOUT_MS, PatternError, PatternRunner, PatternTimeout  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402
from platforms.android import bugreport, logcat  # noqa: E402

OUTPUT_SCHEMA = evt.SCHEMA_VERSION  # markers 출력도 같은 번호
DEFAULT_MINUTES = 5


class UsageError(Exception):
    """종료 코드 2로 끝낸다."""


# -- 공통 후처리 ------------------------------------------------------------


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
            out.append(evt.derived_event(rec, "ril_error", {**base_fields, "error": ann["error"]}))
        if ann["latency_ms"] is not None and ann["latency_ms"] > timeout:
            out.append(
                evt.derived_event(
                    rec,
                    "ril_timeout",
                    {**base_fields, "latency_ms": ann["latency_ms"], "timeout_ms": timeout},
                )
            )
    elif ann["paired_ts"] is None and last_ts is not None:
        # 파일이 요청 + timeout 이후까지 있는데 응답이 없을 때만 "응답 없음"이다.
        deadline = logcat.parse_ts(rec["ts"]) + timedelta(milliseconds=timeout)
        if logcat.parse_ts(last_ts) >= deadline:
            out.append(
                evt.derived_event(rec, "ril_no_response", {**base_fields, "timeout_ms": timeout})
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
                        found.append((i, evt.derived_event(lines[i], ex.event, fields)))
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
            rec.setdefault("line_ref", None)
            kept.append(_mask_record(rec, masker) if masker else rec)
        else:
            rec = dict(rec)
            rec.setdefault("line_ref", None)
            kept.append(_mask_record(rec, masker) if masker else rec)

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
    for file_index, path in enumerate(paths):
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
                evt.make_event(
                    ts=logcat.format_ts(dt),
                    pid=item.get("pid"),
                    tid=item.get("tid"),
                    level=item.get("level"),
                    tag=item.get("tag"),
                    msg=item.get("msg") or "",
                    phone_id=item.get("phone_id"),
                    category_hint=category,
                    event=name,
                    fields={k: str(v) for k, v in (item.get("fields") or {}).items() if v is not None},
                    source=f"{evt.EXTERNAL_PREFIX}{module.ADAPTER_NAME}",
                    # 외부 파서는 파일만 안다 (줄 번호 없음).
                    line_ref=evt.line_ref(file_index),
                )
            )
    if dropped:
        warnings.append(
            _ext_warn(category, f"이벤트 {dropped}개를 버렸습니다 (이름이 {prefix}* 이 아니거나 시각을 모름)")
        )
    return events, warnings


def _ext_warn(category: str, message: str) -> dict:
    return {"code": "external-parser-failed", "message": f"[{category}] {message}"}


# -- parse -------------------------------------------------------------------


def _window(args) -> tuple | None:
    if args.full:
        return None
    if args.between:
        try:
            start, end = logcat.parse_ts(args.between[0]), logcat.parse_ts(args.between[1])
        except ValueError as exc:
            raise UsageError(
                f"--between은 타임존이 있는 ISO 시각 둘이어야 합니다(예: 2026-09-20T14:32:00+09:00): {exc}"
            ) from exc
        if start > end:
            raise UsageError(f"--between의 시작이 끝보다 늦습니다: {args.between[0]} > {args.between[1]}")
        return (start, end)
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
            "mode": "full" if args.full else "between" if args.between else "around",
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


# -- markers -----------------------------------------------------------------


STEP_EVENT_PER_RULE = 1000
STEP_EVENT_TOTAL = 5000


def _step_event_rules(db_cfg: dict) -> tuple[list[dict | None], list[dict]]:
    """`step_events` → 규칙 번호 자리마다 `{kind, ...}`(관측 불가·잘못된 규칙은 None)와 경고.

    대상은 정확히 하나: `ril`(+`dir`), `match`(정규식), `event`(+`fields{이름: 정규식}`). 스텝 이름 패턴은 쓰지 않는다."""
    raw = db_cfg.get("step_events")
    if not isinstance(raw, list):
        return [], []
    out: list[dict | None] = []
    warnings: list[dict] = []

    def bad(i: int, why: str) -> None:
        warnings.append({"code": "step-event-rule", "message": f"step_events[{i}]: {why} — 건너뜀"})
        out.append(None)

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            bad(i, "매핑이 아님")
            continue
        targets = [k for k in ("event", "ril", "match") if k in item]
        if item.get("observable") is False:
            out.append(None)
            if targets:
                warnings.append({"code": "step-event-rule", "message": f"step_events[{i}]: observable: false에 대상이 있다 — 건너뜀"})
            continue
        if len(targets) != 1:
            bad(i, "event·ril·match 중 정확히 하나가 필요하다")
            continue
        kind = targets[0]
        value = item[kind]
        if not isinstance(value, str) or not value:
            bad(i, f"{kind}는 문자열이어야 한다")
            continue
        if kind == "ril":
            direction = item.get("dir") or ("unsol" if value.startswith("UNSOL_") else "req")
            if direction not in ("req", "resp", "unsol"):
                bad(i, f"dir이 req|resp|unsol이 아니다: {direction!r}")
                continue
            out.append({"kind": "ril", "name": value, "dir": direction})
        elif kind == "match":
            try:
                out.append({"kind": "match", "rx": re.compile(value), "pattern": value})
            except re.error as exc:
                bad(i, f"match 정규식 오류: {exc}")
        else:
            if value.startswith("ext."):
                bad(i, "ext.* 이벤트는 지원하지 않는다")
                continue
            fields = item.get("fields") or {}
            if not isinstance(fields, dict):
                bad(i, "fields는 매핑이어야 한다")
                continue
            try:
                compiled = {str(k): re.compile(str(v)) for k, v in fields.items()}
            except re.error as exc:
                bad(i, f"fields 정규식 오류: {exc}")
                continue
            out.append({"kind": "event", "name": value, "fields": compiled})
    return out, warnings


def _step_event_hits(raw: list[dict], specs: list[dict | None], paths: list[Path], rules_dir: Path,
                     db_cfg: dict, coverage: dict, timeout_ms: int, warnings: list[dict]) -> list[dict]:
    """규칙별 로그 흔적 `[{rule, ts, seq, label}]`(정렬 전). `seq`는 파서 출력 줄의 순번이다.

    `ril`: 원 레코드의 `ril`(요청 이름·방향) 그대로. `match`: 모든 `TAG: msg`를 한 마스커로 마스킹해 정규식 검색.
    `event`: `postprocess`(마스킹 포함) 이벤트 중 이름·필드 정규식이 맞는 것. 라벨은 이름뿐이다(본문 없음)."""
    hits: list[dict] = []
    masker = None
    if any(sp and sp["kind"] in ("match", "event") for sp in specs):
        masker = masking.new_masker(_read_texts(paths), _allow_patterns(db_cfg))
    line_idx = [i for i, r in enumerate(raw) if r.get("event") is None]

    for rule, sp in enumerate(specs):             # ril
        if sp and sp["kind"] == "ril":
            for i in line_idx:
                ann = raw[i].get("ril")
                if ann and ann.get("request") == sp["name"] and ann.get("dir") == sp["dir"]:
                    hits.append({"rule": rule, "ts": raw[i]["ts"], "seq": i, "label": sp["name"]})

    match_rules = [(rule, sp) for rule, sp in enumerate(specs) if sp and sp["kind"] == "match"]
    if match_rules:
        texts = [masker(f"{raw[i]['tag']}: {raw[i]['msg']}") for i in line_idx]
        with PatternRunner(texts, timeout_ms) as runner:
            for rule, sp in match_rules:
                try:
                    found = runner.search(sp["pattern"])
                except (PatternTimeout, PatternError) as exc:
                    warnings.append({"code": "step-event-rule", "message": f"step_events[{rule}]: match 건너뜀: {exc}"})
                    continue
                for k in found:
                    i = line_idx[k]
                    hits.append({"rule": rule, "ts": raw[i]["ts"], "seq": i, "label": str(raw[i]["tag"])[:40]})

    event_rules = [(rule, sp) for rule, sp in enumerate(specs) if sp and sp["kind"] == "event"]
    if event_rules:
        try:
            rules = parser_rules.load(rules_dir)
        except parser_rules.RulesError as exc:
            raise UsageError(f"파서 규칙 오류: {exc}") from exc
        errors: list[dict] = []
        out = postprocess(list(raw), rules, masker=masker, last_ts=coverage["last_ts"], timeout_ms=timeout_ms,
                          errors=errors)
        for error in errors:
            warnings.append({"code": "pattern-timeout", "message": f"extractor {error['extractor']}: {error['error']}"})
        # postprocess가 남긴 원 레코드(태그 매핑에 맞는 줄 + builtin 이벤트)의 원래 순번. 파생 이벤트는 그 줄 바로 뒤에 온다.
        kept = [i for i, r in enumerate(raw) if r.get("event") is not None or rules.tag_category(r["tag"]) is not None]
        pos, seq = 0, None
        for e in out:
            derived = e.get("event") is not None and e.get("source") == "rules"
            if not derived:
                seq = kept[pos] if pos < len(kept) else seq
                pos += 1
            if e.get("event") is None or seq is None:
                continue
            for rule, sp in event_rules:
                if e["event"] != sp["name"]:
                    continue
                fields = e.get("fields") or {}
                if all(name in fields and rx.search(str(fields[name])) for name, rx in sp["fields"].items()):
                    hits.append({"rule": rule, "ts": e["ts"], "seq": seq, "label": sp["name"]})
    return hits


def run_markers(args, defaults: dict) -> dict:
    """스텝 마커 줄을 모은다. 마커 태그는 `tags.yaml`에 없으므로 `parse` 출력을 쓰지 못하고 백엔드의 줄 레코드를 직접 본다.

    원문 줄에서 정규식이 맞는 줄만 골라(시간 상한 `matcher.pattern_timeout_ms`) 그 줄만 마스킹하고, 마스킹된 텍스트에서
    이름 그룹(`step`, `status`)을 다시 뽑는다 — 원문 값은 출력에 나가지 않는다. 마커 패턴은 `site-defaults.yaml`의
    `failed_step.marker_patterns`에서만 읽는다(사용자 config로 바꿀 수 없다). 패턴이 없으면 마커 없이 범위(`coverage`)만 낸다."""
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
    rules_dir = Path(args.rules)
    db_cfg = compat.load_db_config(rules_dir.parent)
    backend_name = (defaults.get("parser") or {}).get("backend")
    try:
        backend = parser_backends.load(backend_name)
    except parser_backends.BackendError as exc:
        raise UsageError(f"site-defaults.yaml parser.backend: {exc}") from exc

    conf = defaults.get("failed_step") or {}
    status_map = conf.get("marker_status") if isinstance(conf.get("marker_status"), dict) else None
    compiled, warn_texts = stepanchor.compile_markers(conf.get("marker_patterns") or [])
    warnings: list[dict] = [{"code": "marker-pattern", "message": w} for w in warn_texts]

    coverage = backend.coverage(paths, args.tz, args.year)
    coverage.pop("stats", None)
    coverage = {"first_ts": coverage["first_ts"], "last_ts": coverage["last_ts"]}
    markers: list[dict] = []
    total = 0
    timeout_ms = int((db_cfg.get("matcher") or {}).get("pattern_timeout_ms", DEFAULT_TIMEOUT_MS))
    step_specs, rule_warnings = _step_event_rules(db_cfg) if getattr(args, "step_events", False) else ([], [])
    warnings += rule_warnings
    raw_records = None
    if compiled or any(step_specs):
        raw_records = backend.parse(paths, args.tz, args.year, None)       # 한 번만 파싱한다
    if compiled:
        records = [r for r in raw_records if r.get("event") is None]
        texts = [f"{r['tag']}: {r['msg']}" for r in records]
        hits: dict[int, re.Pattern] = {}
        remaining = list(range(len(records)))
        with PatternRunner(texts, timeout_ms) as runner:
            for rx in compiled:
                if not remaining:
                    break
                try:
                    found = runner.search(rx.pattern, indices=remaining)
                except (PatternTimeout, PatternError) as exc:
                    warnings.append({"code": "marker-pattern", "message": f"마커 패턴 건너뜀: {exc}"})
                    continue
                for i in found:
                    hits[i] = rx
                done = set(found)
                remaining = [i for i in remaining if i not in done]
        if hits:
            masker = masking.new_masker(_read_texts(paths), _allow_patterns(db_cfg))
            for i in sorted(hits):
                masked = masker(texts[i])
                m = hits[i].search(masked)       # 이름 그룹은 마스킹된 텍스트에서만 뽑는다
                if not m:
                    continue
                state = stepanchor.status_of(m.group("status"), status_map)
                if state is None:
                    continue
                tag, _, msg = masked.partition(":")
                total += 1
                if len(markers) < stepanchor.MARKER_MAX:
                    markers.append({"ts": records[i]["ts"], "step": " ".join(str(m.group("step") or "").split())[:60],
                                    "status": state, "tag": tag.strip(), "msg": " ".join(msg.split())[:200]})
    truncated = total > len(markers)
    if truncated:
        warnings.append({"code": "markers-truncated",
                         "message": f"마커 {total}개 중 앞의 {len(markers)}개만 냈습니다."})
    result = {"schema": OUTPUT_SCHEMA, "markers": markers, "total": total, "truncated": truncated,
              "coverage": coverage, "warnings": warnings}
    if getattr(args, "step_events", False):
        hits = _step_event_hits(raw_records, step_specs, paths, rules_dir, db_cfg, coverage, timeout_ms, warnings) \
            if any(step_specs) else []
        by_rule: dict[int, int] = {}
        capped = []
        for hit in sorted(hits, key=lambda h: (h["ts"], h["seq"], h["rule"])):
            if by_rule.get(hit["rule"], 0) >= STEP_EVENT_PER_RULE:
                by_rule[hit["rule"]] = by_rule.get(hit["rule"], 0) + 1
                continue
            by_rule[hit["rule"]] = by_rule.get(hit["rule"], 0) + 1
            capped.append(hit)
        truncated_rules = {r for r, n in by_rule.items() if n > STEP_EVENT_PER_RULE}
        if len(capped) > STEP_EVENT_TOTAL:
            truncated_rules |= {h["rule"] for h in capped[STEP_EVENT_TOTAL:]}
            capped = capped[:STEP_EVENT_TOTAL]
        if truncated_rules:
            warnings.append({"code": "step-events-truncated", "truncated_rules": sorted(truncated_rules),
                             "message": f"step_events 규칙 {sorted(truncated_rules)}의 흔적이 상한"
                                        f"(규칙당 {STEP_EVENT_PER_RULE}, 전체 {STEP_EVENT_TOTAL})을 넘어 앞부분만 냈습니다."})
        result["step_events"] = capped
    return result


# -- extract-bugreport --------------------------------------------------------

# 구현은 `platforms/android/bugreport.py` (RF-3). 여기는 오류를 사용 오류로 바꾸는 래퍼다.
_looks_like_bugreport = bugreport.looks_like_bugreport


def run_extract_bugreport(args) -> dict:
    try:
        return bugreport.extract(Path(args.bugreport), Path(args.out))
    except bugreport.BugreportError as exc:
        raise UsageError(str(exc)) from exc


# -- cut ------------------------------------------------------------------------


def _cut_anchors(args, lines: list) -> tuple[set[int], dict, list[dict]]:
    """(앵커 줄의 전체 순번 집합, 앵커 방식별 근거 수, 경고).

    `--evidence`는 근거마다 `line_ref`(`match.json` 근거의 줄 위치)가 가리키는 줄을 앵커로 삼는다.
    그 줄이 입력에 있고 시각·태그가 근거와 같을 때만이다(입력 파일이 `events.json`의 `input.files`와
    같은 순서가 아니면 어긋난다). 아니면 그 근거만 예전처럼 `(ts, tag)`가 같은 모든 줄을 앵커로 삼고
    `line_ref`가 있었는데 못 쓴 경우 경고 `evidence-ref-mismatch`를 낸다 (04-parser-matching.md §5.8 (6))."""
    if args.around:
        try:
            center = logcat.parse_ts(args.around)
        except ValueError as exc:
            raise UsageError(f"--around는 타임존이 있는 ISO 시각이어야 합니다: {exc}") from exc
        span = timedelta(seconds=args.seconds)
        found = {i for i, (_, line, _) in enumerate(lines) if center - span <= line.dt <= center + span}
        return found, {"line_ref": 0, "ts_tag": 0}, []
    try:
        match = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"--evidence를 읽을 수 없습니다: {exc}") from exc
    candidates = match.get("candidates") or []
    evidence = candidates[0].get("evidence") if candidates else None
    if not evidence:
        raise UsageError("--evidence: 1위 후보에 근거가 없습니다.")
    position = {(fi, line.line_no): i for i, (fi, line, _) in enumerate(lines)}
    by_ts_tag: dict[tuple, list[int]] = {}
    for i, (_, line, _) in enumerate(lines):
        by_ts_tag.setdefault((logcat.format_ts(line.dt), line.tag), []).append(i)
    anchors: set[int] = set()
    by = {"line_ref": 0, "ts_tag": 0}
    mismatch = False
    for e in evidence:
        ref = e.get("line_ref") or {}
        key = (e["ts"], e.get("tag"))
        ref_pos = evt.ref_key(ref)
        i = position.get(ref_pos) if ref_pos else None
        if i is not None and (logcat.format_ts(lines[i][1].dt), lines[i][1].tag) == key:
            anchors.add(i)
            by["line_ref"] += 1
            continue
        anchors.update(by_ts_tag.get(key, []))
        by["ts_tag"] += 1
        mismatch = mismatch or ref_pos is not None
    warnings = []
    if mismatch:
        warnings.append({"code": "evidence-ref-mismatch",
                         "message": "근거의 줄 위치(line_ref)가 입력과 맞지 않아 (시각, 태그)로 앵커를 찾았습니다. "
                                    "parse에 준 로그를 같은 순서로 주세요 (events.json input.files 순서)."})
    return anchors, by, warnings


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
        # `read_file`과 같은 방식으로 줄을 센다(`splitlines`는 \x0c 등에서도 끊어 줄 번호가 어긋난다).
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            raw = [text.rstrip("\r\n") for text in fh]
        parsed, _ = logcat.read_file(path, index, args.tz, args.year)
        lines += [(index, line, raw[line.line_no - 1]) for line in parsed]
    anchors, anchors_by, warnings = _cut_anchors(args, lines)
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
        "anchors_by": anchors_by,
        "context": context,
        "masked": True,
        "replacements": dict(sorted(masker.counts.items())),
        "warnings": warnings,
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
    mode.add_argument("--between", nargs=2, metavar=("START", "END"),
                      help="명시 구간 (타임존 있는 ISO 둘, 시작 ≤ 끝)")
    mode.add_argument("--full", action="store_true", help="파일 전체")
    p.add_argument("--minutes", type=float, default=DEFAULT_MINUTES)
    p.add_argument("--rules", required=True, help="<db>/parser-rules")
    p.add_argument("--tz", default=None, help="연도 없는 logcat 시각의 타임존 (IANA)")
    p.add_argument("--year", type=int, default=None, help="첫 줄의 연도")
    p.add_argument("--mask", action="store_true", help="extractor 전에 줄 단위 마스킹")
    p.add_argument("--no-external", action="store_true", help="외부 파서 끔 (분석 디버그용)")

    k = sub.add_parser("markers", parents=[common], help="logcat → 스텝 마커 목록 (마스킹)")
    k.add_argument("logs", nargs="+")
    k.add_argument("--rules", required=True, help="<db>/parser-rules")
    k.add_argument("--tz", default=None, help="연도 없는 logcat 시각의 타임존 (IANA)")
    k.add_argument("--year", type=int, default=None, help="첫 줄의 연도")
    k.add_argument("--step-events", action="store_true",
                   help="이슈 DB step_events 규칙의 로그 흔적(step_events[{rule, ts, seq, label}])을 더한다")

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
        elif args.cmd == "markers":
            result = run_markers(args, defaults)
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
