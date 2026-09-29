#!/usr/bin/env python3
"""모의 data 심층 분석 스킬의 결정적 러너 (15-local-draft.md §15.2).

LLM 없이 `analyzers.data` 호출 경로만 확인한다. 같은 입력이면 항상 같은
출력을 낸다. 실제 분석은 사내 스킬이 한다 (`16-existing-assets.md §16.5`).

입력 JSON (analyze Step 5 뒤에 넘기는 것과 같은 항목):
    {"events_json": "<경로>", "log_paths": ["<경로>"],
     "top_candidates": [{"type": "DATA-001", "cause": "DATA-001-01",
                         "score": 1.0, "confidence": "high"}],
     "jira_summary": "<마스킹된 한두 줄>"}

출력 JSON:
    {"skill": "mock-data-analyzer", "summary": "<한 줄>",
     "detail": "<리포트에 붙일 텍스트>",
     "suggested_cause": "<원인 ID 또는 null>", "notes": [...]}
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SKILL = "mock-data-analyzer"


def analyze(payload: dict) -> dict:
    events = []
    events_path = payload.get("events_json")
    if events_path and Path(events_path).is_file():
        loaded = json.loads(Path(events_path).read_text(encoding="utf-8"))
        events = loaded.get("events", loaded) if isinstance(loaded, dict) else loaded

    names = Counter(e.get("event") for e in events if isinstance(e, dict) and e.get("event"))
    slots = sorted({e.get("phone_id") for e in events if isinstance(e, dict)} - {None})
    top = (payload.get("top_candidates") or [{}])[0]
    top_cause = top.get("cause")

    lines = [
        f"이벤트 {len(events)}건, 판별 이벤트 {sum(names.values())}건.",
        "슬롯: " + (", ".join(str(s) for s in slots) if slots else "표기 없음"),
    ]
    if names:
        lines.append(
            "빈도 상위: "
            + ", ".join(f"{name}×{count}" for name, count in names.most_common(3))
        )
    else:
        lines.append("판별 이벤트가 없어 추가로 해석할 것이 없습니다.")

    # 모의 규칙: 사용자 설정 꺼짐 이벤트(백엔드 내장 또는 extractor)가 있으면 그 원인을 의견으로 낸다.
    suggested = None
    setting_off = any(isinstance(e, dict) and e.get("event") == "data_setting_changed"
                      and str((e.get("fields") or {}).get("enabled")) == "false" for e in events)
    if ("builtin.data.user_data_disabled" in names or setting_off) and top_cause != "DATA-001-01":
        suggested = "DATA-001-01"
        lines.append("의견: 사용자 데이터 설정이 꺼진 흔적이 있습니다.")

    return {
        "skill": SKILL,
        "summary": lines[0],
        "detail": "\n".join(lines),
        "suggested_cause": suggested,
        "notes": [
            "모의 스킬이므로 실제 해석이 아닙니다.",
            "분류 후보·점수·확정에는 영향을 주지 않습니다 (16-existing-assets.md §16.5).",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__)
    parser.add_argument("--input", default="-", help="입력 JSON 경로 (기본: stdin)")
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    payload = json.loads(raw) if raw.strip() else {}
    print(json.dumps(analyze(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
