#!/usr/bin/env python3
"""오프라인 재현 평가 (11-phases.md Phase 12, 15-local-draft.md §15.5 S-5).

라벨셋의 항목마다 `analyze --dry-run`과 같은 경로(파서 → 매처)를 스크립트로만 돌려
1위 정확도, 상위 3 포함률, 오탐률을 표로 낸다. 스킬(LLM)은 부르지 않는다.

라벨셋 형식 (경로는 라벨셋 파일 위치 기준 상대 경로):

    db: ../issue-db-sample        # 선택. --db가 우선
    tz: Asia/Seoul                # 선택. 연도 없는 logcat 시각의 타임존
    year: 2026                    # 선택
    minutes: 5                    # 선택. 발생 시각 앞뒤 분
    items:
      - key: MOCK-1
        logs: [logs/a.log]        # logcat 파일 (원문은 파서가 --mask로 마스킹한다)
        occurred_at: "2026-09-20T14:32:10+09:00"   # 타임존 있는 ISO
        sw: ""                    # 선택
        summary: ""               # 선택
        description: ""           # 선택
        expect: DATA-001-01       # 정답 원인 ID 또는 unresolved

지표:
  - 1위 정확도: 정답이 원인 ID인 항목 중 1위 후보가 정답인 비율
  - 상위 3 포함률: 정답이 원인 ID인 항목 중 상위 3 후보에 정답이 있는 비율
  - 오탐률: 정답이 unresolved인 항목 중 후보를 낸 비율

플러그인 루트: `--plugin-root`, 없으면 `plugin/site-defaults.yaml`이 있을 때 `plugin/`,
없으면 테스트 헬퍼 루트(`tests/helpers/make_plugin_root.py`)를 임시로 만든다.
종료 코드: 0 = 실행 완료, 2 = 사용 오류.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
UNRESOLVED = "unresolved"


class EvalError(Exception):
    pass


def _plugin_root(explicit: str | None) -> tuple[Path, bool]:
    """(루트, 임시로 만들었는가)."""
    if explicit:
        return Path(explicit), False
    plugin = REPO / "plugin"
    if (plugin / "site-defaults.yaml").is_file():
        return plugin, False
    sys.path.insert(0, str(REPO / "tests" / "helpers"))
    import make_plugin_root  # noqa: E402

    return make_plugin_root.make(), True


def _script(root: Path, name: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / name), *args, "--plugin-root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def load_labelset(path: Path) -> dict:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EvalError(f"라벨셋을 읽을 수 없습니다: {path} ({exc})")
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list) or not doc["items"]:
        raise EvalError("라벨셋에 items 목록이 필요합니다.")
    for i, item in enumerate(doc["items"], 1):
        for field in ("key", "logs", "occurred_at", "expect"):
            if not item.get(field):
                raise EvalError(f"items[{i}]에 {field}가 없습니다.")
        if not isinstance(item["logs"], list):
            raise EvalError(f"items[{i}].logs는 목록이어야 합니다.")
    return doc


def evaluate_item(root: Path, db: Path, base: Path, doc: dict, item: dict, work: Path) -> dict:
    key = str(item["key"])
    logs = [str((base / p).resolve()) for p in item["logs"]]
    parse_args = ["parse", *logs, "--around", str(item["occurred_at"]),
                  "--rules", str(db / "parser-rules"), "--mask"]
    minutes = item.get("minutes", doc.get("minutes"))
    if minutes:
        parse_args += ["--minutes", str(minutes)]
    if doc.get("tz"):
        parse_args += ["--tz", str(doc["tz"])]
    if doc.get("year"):
        parse_args += ["--year", str(doc["year"])]
    result = {"key": key, "expect": str(item["expect"]), "top": None, "top3": [], "error": None}
    proc = _script(root, "parse_logcat.py", parse_args)
    if proc.returncode != 0:
        result["error"] = f"파서 종료 {proc.returncode}: {proc.stderr.strip()[:200]}"
        return result
    events = work / f"{key}.events.json"
    events.write_text(proc.stdout, encoding="utf-8")
    meta = {"key": key, "occurred_at": str(item["occurred_at"]), "sw": item.get("sw", ""),
            "summary": item.get("summary", ""), "description": item.get("description", "")}
    meta_path = work / f"{key}.jira.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    proc = _script(root, "match_signatures.py", ["--db", str(db), "--events", str(events),
                                                 "--jira-meta", str(meta_path), "--top", "3"])
    if proc.returncode != 0:
        result["error"] = f"매처 종료 {proc.returncode}: {proc.stderr.strip()[:200]}"
        return result
    candidates = json.loads(proc.stdout).get("candidates") or []
    result["top3"] = [c["cause"] for c in candidates[:3]]
    result["top"] = result["top3"][0] if result["top3"] else None
    return result


def summarize(results: list[dict]) -> dict:
    scored = [r for r in results if not r["error"]]
    positive = [r for r in scored if r["expect"] != UNRESOLVED]
    negative = [r for r in scored if r["expect"] == UNRESOLVED]
    for r in scored:
        if r["expect"] == UNRESOLVED:
            r["verdict"] = "오탐" if r["top3"] else "정답"
        elif r["top"] == r["expect"]:
            r["verdict"] = "1위"
        elif r["expect"] in r["top3"]:
            r["verdict"] = "상위3"
        else:
            r["verdict"] = "미스"

    def rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    return {
        "total": len(results),
        "errors": len(results) - len(scored),
        "positive": len(positive),
        "negative": len(negative),
        "top1_accuracy": rate(sum(r["top"] == r["expect"] for r in positive), len(positive)),
        "top3_inclusion": rate(sum(r["expect"] in r["top3"] for r in positive), len(positive)),
        "false_positive_rate": rate(sum(bool(r["top3"]) for r in negative), len(negative)),
    }


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def render(results: list[dict], summary: dict) -> str:
    rows = [("키", "정답", "1위", "판정")]
    for r in results:
        rows.append((r["key"], r["expect"], r["top"] or "-", "오류" if r["error"] else r["verdict"]))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    for r in results:
        if r["error"]:
            lines.append(f"오류 {r['key']}: {r['error']}")
    lines += [
        "",
        f"항목 {summary['total']}건 (원인 정답 {summary['positive']}, "
        f"unresolved 정답 {summary['negative']}, 오류 {summary['errors']})",
        f"1위 정확도    {_pct(summary['top1_accuracy'])}",
        f"상위 3 포함률 {_pct(summary['top3_inclusion'])}",
        f"오탐률        {_pct(summary['false_positive_rate'])}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="오프라인 재현 평가 (라벨셋 → 파서 → 매처 → 정확도 표)")
    parser.add_argument("labelset")
    parser.add_argument("--db", default=None, help="이슈 DB 경로 (없으면 라벨셋의 db)")
    parser.add_argument("--plugin-root", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    label_path = Path(args.labelset).resolve()
    temp_root = None
    try:
        doc = load_labelset(label_path)
        base = label_path.parent
        if args.db:
            db = Path(args.db)
        elif doc.get("db"):
            db = base / str(doc["db"])
        else:
            raise EvalError("--db 또는 라벨셋의 db가 필요합니다.")
        db = db.resolve()
        if not (db / "issue-db.config.yaml").is_file():
            raise EvalError(f"이슈 DB가 아닙니다: {db}")
        root, made = _plugin_root(args.plugin_root)
        temp_root = root if made else None
        work = Path(tempfile.mkdtemp(prefix="tt-offline-eval-"))
        try:
            results = [evaluate_item(root, db, base, doc, item, work) for item in doc["items"]]
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except EvalError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)

    summary = summarize(results)
    if args.json:
        print(json.dumps({"summary": summary, "items": results}, ensure_ascii=False, indent=1))
    else:
        print(render(results, summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
