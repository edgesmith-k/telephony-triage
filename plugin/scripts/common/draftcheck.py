"""초안 검증 기록: 시그니처·파서 규칙·새 원인·유형을 만드는 계획은 stage 전에 `db_verify ... --plan --draft`로
초안 트리를 검증해 사용자에게 보였어야 한다(SKILL Step 7). db_verify가 기록을 남기고 `db_pr stage`가 대조한다.

지문은 작성 op만 본다 — note·verification처럼 초안 검증 뒤에 붙는 op는 바꿔도 다시 검증하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

AUTHORING_OPS = ("new-type", "new-cause", "update-signature", "add-parser-rule", "update-parser-rule")
RECORD = "draft-verify.json"


# fixture 중 작성 단계에서 넣는 것(새 원인 positive·negative, chose-other extra). verify 흐름이 판정 뒤 붙이는
# resolved·fixed·recurrence는 뺀다 — 넣으면 `db_verify fix --plan --draft` 기록 뒤 지문이 늘 바뀐다
AUTHORING_FIXTURES = ("positive", "negative", "extra")


def _authoring(op) -> bool:
    return isinstance(op, dict) and (op.get("op") in AUTHORING_OPS
                                     or (op.get("op") == "add-fixture" and op.get("kind") in AUTHORING_FIXTURES))


def fingerprint(plan: dict) -> str | None:
    """작성 op의 지문. 작성 op가 없으면 None(초안 검증 불필요)."""
    ops = [op for op in plan.get("operations") or [] if _authoring(op)]
    if not ops:
        return None
    return hashlib.sha256(json.dumps(ops, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def record(job_dir: Path, plan: dict, code: int, command: str) -> None:
    """초안 검증을 마쳤다는 기록(결과 코드와 무관하게 — 실패면 사용자가 계획을 고치고 지문이 바뀐다)."""
    fp = fingerprint(plan)
    if fp is None or not Path(job_dir).is_dir():
        return
    data = {"fingerprint": fp, "code": code, "command": command,
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    (Path(job_dir) / RECORD).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def missing(job_dir: Path, plan: dict) -> str | None:
    """stage 전 대조. 필요 없거나 기록이 지금 계획과 맞으면 None, 아니면 이유."""
    fp = fingerprint(plan)
    if fp is None:
        return None
    try:
        data = json.loads((Path(job_dir) / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "초안 검증 기록 없음"
    if not isinstance(data, dict) or data.get("fingerprint") != fp:
        return "초안 검증 뒤 계획의 작성 op(시그니처·파서 규칙·새 원인·유형)가 바뀜"
    return None
