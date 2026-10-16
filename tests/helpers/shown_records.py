"""표시 기록(L R, `<work_dir>/.shown/log.jsonl`) 테스트 도우미 — test_show_guard·test_skill_evals가 함께 쓴다.

show_guard는 스크립트가 남긴 기록을 transcript의 Bash 호출에 시각으로 고정한다. 옛 테스트 transcript(시각·기록 없음)를 그대로
쓰도록: `stamp`는 줄마다 `timestamp`(1초 간격)를 붙이고, `backfill`은 그 transcript가 실제였다면 스크립트가 남겼을 기록을 만든다
(명령 모양·출력은 채점기 추론 `shown_infer`로 읽는다 — 기록 형식은 contracts.md "표시 기록"). 기록 시각은 그 호출의 tool_use 시각 뒤
0.05초 간격(tool_result 시각 앞)이고, 한 명령 안 순서는 명령 글의 위치 순(`stage …; publish …`)이다. hook이 거부한 호출
(`not_run`)은 스크립트가 돌지 않았으므로 기록이 없다."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "skill_evals"))
import shown_infer as infer  # noqa: E402
from common import shown  # noqa: E402

T0 = datetime(2026, 10, 16, tzinfo=timezone.utc)


def iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp(rows, t0: datetime = T0, step: float = 1.0) -> list:
    """dict 줄마다 `timestamp`(t0부터 step초 간격). 문자열 줄(깨진 줄)은 그대로."""
    out, k = [], 0
    for r in rows:
        if isinstance(r, dict):
            r = {**r, "timestamp": iso(t0 + timedelta(seconds=k * step))}
            k += 1
        out.append(r)
    return out


def home(base: Path) -> dict:
    """`base/config.yaml`(work_dir = base/work)을 만들고 hook 환경 변수를 돌려준다."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.yaml").write_text(f"work_dir: {(base / 'work').as_posix()}\n", encoding="utf-8")
    return {"TELEPHONY_TRIAGE_HOME": str(base)}


def log_path(base: Path) -> Path:
    return base / "work" / shown.SHOWN_DIR / shown.LOG_NAME


def add_record(base: Path, script: str, kind: str, job: str, at, **fields) -> dict:
    rec = {"v": 1, "at": at if isinstance(at, str) else iso(at), "script": script, "kind": kind, "job": job, **fields}
    p = log_path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _json_in(text: str):
    a, b = text.find("{"), text.rfind("}")
    try:
        doc = json.loads(text[a:b + 1]) if 0 <= a < b else None
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _screen(rx, head, text: str):
    found = list(rx.finditer(text))
    if not found:
        return None
    block = found[-1].group(0)
    block = block[[m.start() for m in head.finditer(block)][-1]:]
    return block, block.rstrip().splitlines()[-1].split(":")[-1].strip()


def records_for(e) -> list[tuple[int, str, str, dict]]:
    """한 Bash 호출이 실제였다면 남겼을 기록 `(명령 글 위치, script, kind, fields)`(위치 순)."""
    if e.get("kind") != "tool" or e.get("name") != "Bash" or infer.not_run(e):
        return []
    cmd, res = infer.command_of(e), infer.tool_text(e)
    m = re.search(r"\b(MOCK-\d+)\b", cmd)
    job = m.group(1) if m else "MOCK-1"
    out = []
    for m in infer.STAGE.finditer(cmd):
        out.append((m.start(), "db_pr", "close", {"by": "stage"}))
    for m in infer.JOB_END.finditer(cmd):
        out.append((m.start(), "db_pr", "close", {"by": "lock" if "lock" in m.group(0) else "discard"}))
    for m in infer.PUSH_END.finditer(cmd):
        if m.group(1) == "publish":
            out.append((m.start(), "db_pr", "close", {"by": "publish"}))
    for m in infer.POST_END.finditer(cmd):
        out.append((m.start(), "issue_post", "close", {"by": "approve"}))
    made = [m.start() for rx in (infer.STAGE, infer.SUMMARY) for m in rx.finditer(cmd)]
    scr = _screen(infer.PUSH_SCREEN, infer.SCREEN_HEAD["push"], res) if made else None
    if scr:
        out.append((max(made) + 1, "db_pr", "push", {"key": f"push:{scr[1]}", "block": scr[0]}))
    made = [m.start() for m in infer.RENDER.finditer(cmd)]
    scr = _screen(infer.POST_SCREEN, infer.SCREEN_HEAD["post"], res) if made else None
    if scr:
        out.append((max(made) + 1, "issue_post", "post", {"key": f"post:{scr[1][:16]}", "block": scr[0]}))
    m = infer.DRAFT.search(cmd)
    rules = infer.draft_rules(res) if m else None
    if rules:
        tag = infer.plan_tag(e)
        out.append((m.start(), "db_verify", "draft",
                    {"key": shown.draft_key(tag, rules), "plan": tag.rsplit("/", 1)[-1], "rules": rules}))
    m = infer.TRIAGE_RUN.search(cmd)
    doc = _json_in(res) if m else None
    if doc and doc.get("status") == "ok":
        rep = (doc.get("files") or {}).get("report") if isinstance(doc.get("files"), dict) else None
        text = Path(rep).read_text(encoding="utf-8") if isinstance(rep, str) and Path(rep).is_file() else ""
        key = doc.get("key") or job
        must = doc.get("must_show")
        ana = Path(rep).with_name("analysis.json") if isinstance(rep, str) else None
        if must is None and ana and ana.is_file():     # run 출력에 없으면 분석 결과의 must_show(스크립트는 이것을 기록한다)
            must = (_json_in(ana.read_text(encoding="utf-8")) or {}).get("must_show")
        out.append((m.start(), "triage", "report", {"key": f"report:{key}#{doc.get('run') or 1}",
                                                     "lines": shown.report_core(text),
                                                     "must_show": [str(x) for x in must or []],
                                                     "path": rep}))
    return [(pos, script, kind, {"job": job, **f}) for pos, script, kind, f in sorted(out, key=lambda x: x[0])]


def backfill(rows, base: Path, extra: dict | None = None, replace: dict | None = None) -> int:
    """stamp한 transcript 줄(dict 또는 JSON 문자열)에서 기록을 만들어 `base`의 work_dir 기록을 새로 쓴다. 쓴 기록 수.
    extra = {tool_use id: [(script, kind, fields), …]}: 출력으로 알 수 없는 기록(리디렉션으로 숨긴 화면 등)을 그 호출 기록 뒤에 더한다.
    replace = 같은 모양: 그 호출의 추론 기록 대신 쓴다(출력을 잘라 찍어도 스크립트는 전체를 기록한다 등)."""
    p = log_path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    n = 0
    for e in shown.parse_events(rows):
        t = shown._epoch(e.get("ts"))
        if t is None or e.get("rts") is None:
            continue
        recs = [(script, kind, f) for _, script, kind, f in records_for(e)]
        if e.get("id") in (replace or {}):
            recs = [(script, kind, {"job": "MOCK-1", **f}) for script, kind, f in replace[e["id"]]]
        recs += [(script, kind, {"job": "MOCK-1", **f}) for script, kind, f in (extra or {}).get(e.get("id"), [])]
        for k, (script, kind, f) in enumerate(recs):
            f = dict(f)
            job = f.pop("job")
            add_record(base, script, kind, job, datetime.fromtimestamp(t + 0.05 * (k + 1), timezone.utc), **f)
            n += 1
    return n


def screen_record(block: str) -> tuple[str, str, dict]:
    """확인 화면 전문의 push 기록(extra용): key는 끝 줄 `approved_hash:`."""
    return "db_pr", "push", {"key": "push:" + block.rstrip().splitlines()[-1].split(":")[-1].strip(), "block": block}


def stamp_file(src: Path, dst: Path, base: Path, extra: dict | None = None) -> list[str]:
    """녹화 transcript(시각 없음)를 stamp해 dst에 쓰고 base 홈에 기록을 덧입힌다. 쓴 줄을 돌려준다."""
    rows = []
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            rows.append(line)
    rows = stamp(rows)
    lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in rows]
    Path(dst).write_text("\n".join(lines) + "\n", encoding="utf-8")
    home(base)
    backfill(rows, base, extra)
    return lines
