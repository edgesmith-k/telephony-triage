"""`similar`: 제목·증상 시그니처가 비슷한 유형 상위 3개."""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from common import issuedb
from common.exitcodes import OK
from common.typedoc import id_key

from .core import UsageError, _db


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z0-9_]{2,}|[가-힣]{2,}", text or "")}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    ratio = difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()
    return round(max(jac, ratio), 3)


def cmd_similar(args, defaults: dict) -> tuple[dict, int]:
    db = _db(args)
    try:
        idb = issuedb.load(db)
    except issuedb.IssueDbError as exc:
        raise UsageError(str(exc)) from exc
    symptoms = None
    if args.symptom_json:
        symptoms = json.loads(Path(args.symptom_json).read_text(encoding="utf-8"))
    rows = []
    for t in idb.types:
        same = symptoms is not None and t.raw.get("symptom_signatures") == symptoms
        score = similarity(args.title, t.title)
        rows.append({"type": t.id, "title": t.title, "category": t.category, "status": t.status,
                     "score": 1.0 if same else score, "same_symptom": same,
                     "same_category": args.category is not None and t.category == args.category})
    rows.sort(key=lambda r: (-r["score"], id_key(r["type"])))
    return {"title": args.title, "top": rows[:3]}, OK
