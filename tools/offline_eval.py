#!/usr/bin/env python3
"""오프라인 재현 평가 (11-phases.md Phase 12, 15-local-draft.md §15.5 S-5).

라벨셋의 항목마다 analyze와 같은 드라이버(`plugin/scripts/triage.py run --offline-db`: 파서 → 매처)를
스크립트로만 돌려 1위 정확도, 상위 3 포함률, 오탐률을 표로 낸다. 스킬(LLM)은 부르지 않는다.

라벨셋 형식 (경로는 라벨셋 파일 위치 기준 상대 경로):

    db: ../issue-db-sample        # 선택. --db가 우선
    tz: Asia/Seoul                # 선택. 연도 없는 logcat 시각의 타임존
    year: 2026                    # 선택. 없으면 항목의 occurred_at 현지 연도(tz 기준). 문서 year는 모든 항목이 같은 해일 때만
    minutes: 5                    # 선택. 발생 시각 앞뒤 분
    items:
      - key: MOCK-1
        logs: [logs/a.log]        # logcat 파일 (원문은 파서가 --mask로 마스킹한다)
        occurred_at: "2026-09-20T14:32:10+09:00"   # 타임존 있는 ISO
        sw: ""                    # 선택
        summary: ""               # 선택
        description: ""           # 선택
        year: 2026                # 선택. 항목별 연도·tz (문서 값보다 우선)
        tz: Asia/Seoul            # 선택
        failed_step: ""           # 선택. 실패 스텝 한 줄(보조 정보, 후보 동점 정렬의 키워드 보너스·후보 없음 힌트에만 쓴다)
        expect: DATA-001-01       # 정답 원인 ID 또는 unresolved

지표:
  - 1위 정확도: 정답이 원인 ID인 항목 중 1위 후보가 정답인 비율
  - 상위 3 포함률: 정답이 원인 ID인 항목 중 상위 3 후보에 정답이 있는 비율
  - 오탐률: 정답이 unresolved인 항목 중 후보를 낸 비율
  로그 범위 밖(`logs.in_range` false)이거나 이벤트가 0인 항목은 오류로 빼고(분모 제외) 따로 센다.

플러그인 루트: `--plugin-root`, 없으면 `plugin/site-defaults.yaml`이 있을 때 `plugin/`,
없으면 테스트 헬퍼 루트(`tests/helpers/make_plugin_root.py`)를 임시로 만든다.
`--json`의 `meta`(텍스트는 머리 한 줄): `plugin_repo`(이 도구가 들어 있는 레포의 git SHA·dirty), `db`(DB의 git SHA·dirty),
`plugin_root`(실제 실행 루트 경로·임시 여부), `site_defaults_sha256`, `labelset_sha256`, Python 버전, 실행 인자 — 결과를 어느
코드·DB·설정·라벨셋으로 냈는지 식별한다(비밀값·원문 없음). 항목에는 `logs_sha256`(입력 로그 해시)과 `backend`·`external`
(`events.json`의 파서 백엔드·외부 파서, 못 읽으면 null)을 더한다.
종료 코드: 0 = 실행 완료, 2 = 사용 오류.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

REPO = Path(__file__).resolve().parents[1]
UNRESOLVED = "unresolved"

sys.path.insert(0, str(REPO / "plugin" / "scripts"))
from common import history  # noqa: E402


class EvalError(Exception):
    pass


def _git_state(path: Path) -> dict:
    """git 최상위 레포면 {sha, dirty}, 아니면 둘 다 None (상위 레포 SHA를 DB 것으로 적지 않는다)."""
    if not history.is_repo(path):
        return {"sha": None, "dirty": None}
    return {"sha": (history._git(path, "rev-parse", "HEAD") or "").strip() or None,
            "dirty": bool((history._git(path, "--no-optional-locks", "status", "--porcelain") or "").strip())}


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
    """analyze와 같은 드라이버(`triage.py run --offline-db`)로 파서 → 매처를 돌린다."""
    key = str(item["key"])
    logs = [str((base / p).resolve()) for p in item["logs"]]
    job = work / f"{len(list(work.iterdir())):03d}-{key}"
    job.mkdir(parents=True)
    meta = {"key": key, "occurred_at": str(item["occurred_at"]), "sw": item.get("sw", ""),
            "summary": item.get("summary", ""), "description": item.get("description", "")}
    if item.get("failed_step"):
        meta["failed_step"] = str(item["failed_step"])
    meta_path = job / "jira_input.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    args = ["run", key, "--offline-db", str(db), "--out", str(job), "--logs", *logs, "--jira-meta", str(meta_path)]
    minutes = item.get("minutes", doc.get("minutes"))
    if minutes:
        args += ["--minutes", str(minutes)]
    tz = item.get("tz", doc.get("tz"))
    if tz:
        args += ["--tz", str(tz)]
    result = {"key": key, "expect": str(item["expect"]), "top": None, "top3": [], "error": None,
              "logs_sha256": [hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else None for p in logs],
              "backend": None, "external": None}
    try:
        year = item.get("year") or doc.get("year")
        if not year:
            occurred = datetime.fromisoformat(str(item["occurred_at"]))
            year = (occurred.astimezone(ZoneInfo(str(tz))) if tz and occurred.tzinfo else occurred).year
    except (ValueError, ZoneInfoNotFoundError) as exc:
        result["error"] = f"occurred_at·tz 해석 실패: {exc}"
        return result
    args += ["--year", str(year)]
    proc = _script(root, "triage.py", args)
    if proc.returncode != 0:
        result["error"] = f"triage 종료 {proc.returncode}: {proc.stderr.strip()[:200]}"
        return result
    analysis = json.loads(proc.stdout)
    try:    # 작업 디렉터리를 지우기 전에 파서 백엔드·외부 파서를 events.json에서 읽어 둔다
        events = json.loads((job / "events.json").read_text(encoding="utf-8"))
        result["backend"], result["external"] = events.get("backend"), events.get("external")
    except (OSError, ValueError, AttributeError):
        pass
    if analysis.get("status") != "ok":
        result["error"] = f"triage {analysis.get('status')}: {(analysis.get('needs_input') or {}).get('kind')}"
        return result
    logs = analysis.get("logs") or {}
    if logs.get("in_range") is False or not logs.get("events"):
        result["error"] = (f"로그 범위 밖 또는 이벤트 0 (in_range={logs.get('in_range')}, "
                           f"events={logs.get('events')}) — year·tz 확인")
        return result
    candidates = analysis.get("candidates") or []
    result["top3"] = [c["cause"] for c in candidates[:3]]
    result["top"] = result["top3"][0] if result["top3"] else None
    return result


def summarize(results: list[dict]) -> dict:
    scored = [r for r in results if not r["error"]]
    positive = [r for r in scored if r["expect"] != UNRESOLVED]
    negative = [r for r in scored if r["expect"] == UNRESOLVED]
    for r in scored:
        if r["expect"] == UNRESOLVED:
            r["verdict"] = "오탐" if any(c is not None for c in r["top3"]) else "정답"   # cause: null(유형만)은 오탐 아님
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
        "evaluated": len(scored),
        "errors": len(results) - len(scored),
        "error_rate": rate(len(results) - len(scored), len(results)),
        "type_only": sum(bool(r["top3"]) and all(c is None for c in r["top3"]) for r in negative),
        "positive": len(positive),
        "negative": len(negative),
        "top1_accuracy": rate(sum(r["top"] == r["expect"] for r in positive), len(positive)),
        "top3_inclusion": rate(sum(r["expect"] in r["top3"] for r in positive), len(positive)),
        "false_positive_rate": rate(sum(r["verdict"] == "오탐" for r in negative), len(negative)),
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
        f"평가 {summary['evaluated']}/전체 {summary['total']}",
        f"항목 {summary['total']}건 (원인 정답 {summary['positive']}, "
        f"unresolved 정답 {summary['negative']}, 오류 {summary['errors']})",
        f"1위 정확도    {_pct(summary['top1_accuracy'])}",
        f"상위 3 포함률 {_pct(summary['top3_inclusion'])}",
        f"오탐률        {_pct(summary['false_positive_rate'])} (원인 후보 기준, 유형만 {summary['type_only']}건 제외)",
        f"오류율        {_pct(summary['error_rate'])} ({summary['errors']}/{summary['total']}, 평가에서 제외됨)",
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
        site_yaml = root / "site-defaults.yaml"
        meta = {"plugin_repo": _git_state(REPO), "db": _git_state(db),
                "plugin_root": {"path": str(root), "temporary": made},
                "site_defaults_sha256": hashlib.sha256(site_yaml.read_bytes()).hexdigest() if site_yaml.is_file() else None,
                "labelset_sha256": hashlib.sha256(label_path.read_bytes()).hexdigest(),
                "python": platform.python_version(),
                "argv": list(sys.argv[1:] if argv is None else argv)}
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
        print(json.dumps({"meta": meta, "summary": summary, "items": results}, ensure_ascii=False, indent=1))
    else:
        def s(g: dict) -> str:
            return "-" if not g["sha"] else g["sha"][:12] + ("+dirty" if g["dirty"] else "")

        pr = meta["plugin_root"]
        print(f"meta: 플러그인 {s(meta['plugin_repo'])} · DB {s(meta['db'])} · 플러그인 루트 {pr['path']}"
              f"{'(임시)' if pr['temporary'] else ''} · 라벨셋 sha256 {meta['labelset_sha256'][:12]} · Python {meta['python']}")
        print(render(results, summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
