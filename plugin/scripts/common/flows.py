"""성공 흐름 점검 (04-parser-matching.md §5.13) — 표시 전용, S/C·점수·회귀 판정에 관여하지 않는다.

흐름 = 시작 줄 + 끝 줄 + 순서 있는 단계(`<category>/flows/<id>.yaml`, 스키마 `flow.schema.json`). 입력은 백엔드의 **모든**
줄 레코드와 그 `TAG: msg`(가리지 않은 글 — 판정은 마스킹과 무관하고, 흐름 패턴은 마스킹 토큰을 쓰지 않는다: db_lint `flow-token`).
패턴마다 `PatternRunner.search`를 한 번 돌려 맞은 줄 집합을 구하고 그 위에서 상태 기계를 돈다. 출력에 글자가 나가는 줄
(`notes`·`show`)만 `mask(줄 순번)`으로 가린 뒤 거기서 다시 뽑는다(스텝 마커와 같은 방식, 가린 줄에 안 맞으면 내지 않는다).

- 인스턴스 열쇠 = (시작 줄 pid, 시작 줄 태그). 열린 인스턴스에 같은 열쇠의 시작 줄이 또 오면 합친다(`restarts`만 센다).
  끝 줄로 닫힌 뒤의 시작만 새 인스턴스다. 끝 줄 `as: discard`는 아직 충족된 단계가 없으면 인스턴스를 버리고, 있으면 무시한다.
- 단계·끝·메모 줄은 시작 줄 pid의 줄만 본다. scope `own`은 태그 = 열쇠, `named`는 `name_template`(`{key}` = re.escape(태그)),
  `any`는 슬롯(`phone_id`)이 다르면 뺀다(`None`은 와일드카드). 한 줄은 같은 흐름의 한 인스턴스만 단계 충족에 쓴다(먼저 연 것).
- 닫힘: 끝 줄(라벨), 시작 태그가 다른 pid로 나옴(`프로세스 재시작`), 시계 이상·재부팅 줄(`로그 경계`). 시계 역행(T, d<0)은
  시각순 정렬에서 두 시계의 줄이 섞이는 구간 `[T, T+|d|]`이라 T에 열려 있던 인스턴스와 그 구간에서 연 인스턴스(T+|d|에서)를 닫는다.
- 단계는 순서대로만 찾는다. 단계가 충족되면 같은 시각(ms)의 이미 지난 **다른 파일** 줄도 한 번 다음 단계로 본다(버퍼별 파일의 같은 ms 순서).
- 판정 `ok`(+그 전 이상 값 n회) / `값이상` / `없음`(끝난 사유) / `로그끝`(뒤 로그 < log_end_sec, 판정 불가) / `-`(앞에서 벗어남,
  또는 `optional` 단계에 맞는 줄이 하나도 없음 — 설명 `OPTIONAL_NONE`, 벗어남이 아니다).
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

from . import logtime, yamlio
from .patterns import PatternError, PatternRunner, PatternTimeout

FLOW_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "flow.schema.json"
LOG_END_SEC = 10.0          # TODO(SITE) 뒤 로그가 이보다 짧으면 판정 불가(`로그끝`)
INSTANCES_MAX = 1000        # 흐름당 출력 인스턴스 상한(넘으면 뒤쪽만 남기고 truncated)
NOTES_MAX = 5
RESTART, BOUNDARY = "프로세스 재시작", "로그 경계"
OPTIONAL_NONE = "줄 없음(선택 단계)"
FIXTURE_RE = re.compile(r"^(?P<id>[a-z0-9]+(?:-[a-z0-9]+)*)\.normal\.(?P<n>[1-9]\d*)\.log$")   # 정상 fixture `flows/fixtures/<id>.normal.<n>.log`


def version_match(versions, platform_version) -> bool | None:
    """`match_signatures._version_match`와 같은 비교: 목록이 비거나 이슈 버전을 숫자로 못 읽으면 None."""
    versions = [str(v).strip().split(".")[0] for v in versions or []]
    found = re.fullmatch(r"\s*(\d+)(?:\.\d+)*\s*", str(platform_version or ""))
    return (found.group(1) in versions) if versions and found else None


def log_end_sec(config: dict) -> float:
    value = ((config or {}).get("flows") or {}).get("log_end_sec", LOG_END_SEC)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else LOG_END_SEC


def files(root: Path, config: dict) -> list[Path]:
    """`<category>/flows/*.yaml`(fixture 제외) — 엔진 입력이자 분석 재사용 해시 입력(`compiled.source_files`)."""
    out = []
    for category in (config or {}).get("categories") or []:
        key = category.get("key") if isinstance(category, dict) else None
        if key:
            out += sorted((Path(root) / key / "flows").glob("*.yaml"))
    return out


def load(root: Path, config: dict) -> tuple[list[dict], list[dict]]:
    """흐름 정의 `[{...yaml, ref: "<cat>/<id>", category}]`와 경고. 스키마·`id` = 파일 이름이 안 맞는 파일은 건너뛴다(db_lint가 막는다)."""
    import jsonschema

    validator = jsonschema.Draft202012Validator(json.loads(FLOW_SCHEMA.read_text(encoding="utf-8")))
    flows, warnings = [], []
    for path in files(root, config):
        rel = f"{path.parent.parent.name}/flows/{path.name}"
        try:
            data = yamlio.load(path)
        except yamlio.YamlFileError as exc:
            warnings.append({"code": "flow-invalid", "message": f"{rel}: YAML 오류 — 건너뜀 ({exc.problem})"})
            continue
        error = next(iter(sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))), None)
        if error is None and data["id"] != path.stem:
            error = "id가 파일 이름과 다르다"
        if error is not None:
            where = getattr(error, "message", error)
            warnings.append({"code": "flow-invalid", "message": f"{rel}: {where} — 건너뜀"})
            continue
        flows.append({**data, "category": path.parent.parent.name, "ref": f"{path.parent.parent.name}/{data['id']}"})
    return flows, warnings


def check(flows: list[dict], records: list[dict], texts: list[str], *, timeout_ms: int | None = None,
          log_end: float = LOG_END_SEC, anomalies: list[dict] = (), breaks: set = frozenset(),
          mask=None) -> tuple[list[dict], list[dict]]:
    """줄 레코드(`event: None`, 파서 순서)와 같은 순서의 `TAG: msg` → (`flow.json flows[]`, 경고).

    `mask`: 줄 순번 → 가린 `TAG: msg`(출력에 글자가 나가는 줄에만 부른다). 없으면 `texts`가 이미 가린 글이라고 본다.

    `anomalies`: `coverage.clock_anomalies[]`(`{ts, kind, delta_sec}`), `breaks`: 재부팅 줄의 레코드 순번 — 둘 다 열린 인스턴스를 닫는다."""
    dts = [logtime.parse_ts(r["ts"]) for r in records]
    cuts = []           # (T, 구간 끝): 역행은 [T, T+|d|], 점프는 T 한 점
    for a in anomalies:
        t = logtime.parse_ts(a["ts"])
        cuts.append((t, t + timedelta(seconds=abs(float(a.get("delta_sec") or 0))) if a.get("kind") == "backward" else t))
    cuts.sort()
    last = max(dts) if dts else None
    warnings, runs = [], {}
    with PatternRunner(texts, timeout_ms) as runner:
        for flow in flows:
            try:
                insts = _run(flow, records, texts, dts, runner, cuts, set(breaks), mask or texts.__getitem__)
            except (PatternTimeout, PatternError) as exc:
                warnings.append({"code": "flow-pattern", "message": f"흐름 {flow['ref']}: 건너뜀 — {exc}"})
                continue
            for inst in insts:
                inst["verdicts"] = _judge(flow, inst, dts, last, log_end)
            runs[flow["ref"]] = (flow, insts)
    out = []
    for ref, (flow, insts) in runs.items():
        target = _then_ref(flow)
        nxt = runs.get(target, (None, []))[1][-INSTANCES_MAX:]
        last_id = flow["steps"][-1]["id"]
        rows = []
        for inst in insts[-INSTANCES_MAX:]:
            row = _row(flow, inst, records)
            hit = inst["ok"].get(last_id)
            k = next((k for k, t in enumerate(nxt) if hit in t["starts"]), None) if hit is not None else None
            if k is not None:      # 마지막 단계 줄이 다음 흐름 인스턴스의 시작 줄(합친 시작 포함)
                row["then"] = {"flow": target, "index": k, "key": nxt[k]["tag"], "start_ts": records[nxt[k]["start"]]["ts"]}
            rows.append(row)
        out.append({"flow": ref, "title": flow["title"], "platform_versions": list(flow["platform_versions"]),
                    "steps": [{"id": s["id"], "title": s["title"], "suspect": s["suspect"]} for s in flow["steps"]],
                    "then": target if target in runs else None, "instances": rows,
                    "truncated": len(insts) > INSTANCES_MAX})
    return out, warnings


def _then_ref(flow: dict) -> str | None:
    target = flow.get("then")
    if not target:
        return None
    return target if "/" in target else f"{flow['category']}/{target}"


def _run(flow, records, texts, dts, runner, cuts, breaks, shown) -> list[dict]:
    tags = sorted({r["tag"] for r in records})
    key_tags = {tags[i] for i in runner.search(flow["start"]["tag_regex"], texts=tags)}
    tag_lines = [i for i, r in enumerate(records) if r["tag"] in key_tags]
    starts = set(runner.search(flow["start"]["pattern"], indices=tag_lines))
    ends = [(e, set(runner.search(e["pattern"]))) for e in flow.get("end") or []]
    notes = [(n, set(runner.search(n["pattern"]))) for n in flow.get("notes") or []]
    steps = []
    for s in flow["steps"]:
        hits = set()
        for p in s["patterns"]:
            hits.update(runner.search(p))
        oks = [(o, set(runner.search(o["pattern"], indices=sorted(hits)))) for o in s.get("ok") or []]
        steps.append((s, hits, oks))
    named: dict = {}
    used: set = set()       # 시작·단계 충족에 쓴 줄(흐름 전체 — 한 줄은 한 인스턴스만)

    def in_scope(item, hits, inst, i) -> bool:
        rec = records[i]
        if rec["pid"] != inst["pid"]:
            return False
        if item["scope"] == "own":
            return rec["tag"] == inst["tag"]
        if item["scope"] == "named":
            cache = (id(item), inst["tag"])
            if cache not in named:
                rx = item.get("name_template", "").replace("{key}", re.escape(inst["tag"]))
                named[cache] = set(runner.search(rx, indices=sorted(hits))) if rx else set()
            return i in named[cache]
        a, b = rec.get("phone_id"), inst["phone"]
        return a is None or b is None or a == b

    def feed(inst, i) -> bool:
        s, hits, oks = steps[inst["n"]]
        if i not in hits or i in used or not in_scope(s, hits, inst, i):
            return False
        failed = [o for o, good in oks if i not in good]
        if failed:
            inst["bad"].setdefault(s["id"], []).append((i, [o["why"] for o in failed]))
            return False
        inst["ok"][s["id"]] = i
        used.add(i)
        inst["n"] += 1
        return True

    def fidx(i):
        return (records[i].get("line_ref") or {}).get("file_index")

    def lookback(inst, bucket, i) -> None:
        """W-3: 같은 ms의 이미 지난 줄 중 줄 i와 **다른 파일**의 줄을 다음 단계로 한 번 더 본다(충족될 때마다 다시).
        한 파일 안의 순서는 실제 순서라 되돌아보지 않는다. 파일 순번이 없으면 되돌아보지 않는다."""
        here = fidx(i)
        others = [j for j in bucket if here is not None and fidx(j) not in (None, here)]
        moved = bool(others)
        while moved and inst["n"] < len(steps):
            moved = any(feed(inst, j) for j in others)

    out: list[dict] = []
    opened: dict[tuple, dict] = {}

    def close(inst, label, dt) -> None:
        inst["end"] = (label, dt)
        opened.pop((inst["pid"], inst["tag"]), None)

    relevant = set(starts) | set(tag_lines) | breaks
    for _, h in ends + notes:
        relevant |= h
    for _, h, _ in steps:
        relevant |= h
    cut, exits, bucket, bucket_dt = 0, [], [], None
    for i in sorted(relevant):
        rec, dt = records[i], dts[i]
        if dt != bucket_dt:
            bucket, bucket_dt = [], dt
        for hi in sorted(h for h in exits if dt > h):      # 역행 구간을 지남: 그 안에서 연 인스턴스도 닫는다
            for inst in list(opened.values()):
                close(inst, BOUNDARY, hi)
            exits.remove(hi)
        while cut < len(cuts) and dt >= cuts[cut][0]:
            for inst in list(opened.values()):
                close(inst, BOUNDARY, cuts[cut][0])
            if cuts[cut][0] < cuts[cut][1] and dt <= cuts[cut][1]:     # 이미 구간 끝을 넘은 줄이면 그 뒤 인스턴스는 구간 밖이다
                exits.append(cuts[cut][1])
            cut += 1
        if i in breaks:
            for inst in list(opened.values()):
                close(inst, BOUNDARY, dt)
            continue
        if rec["tag"] in key_tags:
            for inst in [v for k, v in opened.items() if k[1] == rec["tag"] and k[0] != rec["pid"]]:
                close(inst, RESTART, dt)
        if i in starts:
            key = (rec["pid"], rec["tag"])
            if key in opened:
                opened[key]["restarts"] += 1
                opened[key]["starts"].add(i)
            else:
                inst = {"pid": rec["pid"], "tag": rec["tag"], "phone": rec.get("phone_id"), "start": i, "starts": {i},
                        "restarts": 0, "n": 0, "ok": {}, "bad": {}, "notes": [], "end": None}
                used.add(i)
                opened[key] = inst
                out.append(inst)
                lookback(inst, bucket, i)
            bucket.append(i)
            continue
        for inst in list(opened.values()):
            if rec["pid"] != inst["pid"]:
                continue
            end = next((e for e, h in ends if i in h and in_scope(e, h, inst, i)), None)
            if end and end.get("as") == "discard":     # 예: 이미 켜짐 — 충족된 단계도 이상 값도 없으면 인스턴스가 아니다, 있으면 무시
                if inst["n"] == 0 and not inst["bad"]:
                    opened.pop((inst["pid"], inst["tag"]), None)
                    out.remove(inst)
                continue
            if end:
                close(inst, end["label"], dt)
                continue
            for n, h in notes:
                if i in h and in_scope(n, h, inst, i) and len(inst["notes"]) < NOTES_MAX:
                    m = re.search(n["pattern"], shown(i))
                    if m and m.group(0) not in inst["notes"]:
                        inst["notes"].append(m.group(0)[:60])
            if inst["n"] < len(steps) and feed(inst, i):
                lookback(inst, bucket, i)
        bucket.append(i)
    for hi in sorted(exits):        # 역행 구간 뒤에 볼 줄이 없음: 그 안에서 연 인스턴스도 닫는다
        for inst in list(opened.values()):
            close(inst, BOUNDARY, hi)
    for inst in out:      # 값이상일 때 보일 값: 멈춘 단계의 마지막 이상 줄에서 show 패턴이 맞은 글자
        bad = inst["bad"].get(flow["steps"][inst["n"]]["id"]) if inst["n"] < len(steps) else None
        shows = (flow["steps"][inst["n"]].get("show") or []) if bad else []
        j = bad[-1][0] if bad else None
        line = shown(j) if shows else ""
        inst["show"] = [m.group(0)[:60] for p in shows if runner.search(p, indices=[j]) and (m := re.search(p, line))]
    return out


def _judge(flow, inst, dts, last, log_end) -> list[tuple[str, str]]:
    """단계마다 (판정, 설명)."""
    res, broken = [], False
    prev = dts[inst["start"]]
    end_dt = inst["end"][1] if inst["end"] else None
    for s in flow["steps"]:
        if broken:
            res.append(("-", ""))
            continue
        hit = inst["ok"].get(s["id"])
        bad = inst["bad"].get(s["id"]) or []
        if hit is not None:
            res.append(("ok", f"{(dts[hit] - prev).total_seconds():.3f}s" + (f", 그 전 이상 값 {len(bad)}회" if bad else "")))
            prev = dts[hit]
            continue
        tail = ((end_dt or last) - prev).total_seconds()
        settled = end_dt is not None or tail >= log_end
        if inst["end"] and inst["end"][0] in (RESTART, BOUNDARY):     # 흐름 밖 사유로 끊김: 남은 단계는 판정하지 않는다(V-2)
            res.append(("-", f"{_ro(inst['end'][0])} 끝남"))
        elif not bad and settled and s.get("optional"):      # 선택 단계: 줄이 하나도 없으면 벗어남이 아니다(남은 단계도 -)
            res.append(("-", OPTIONAL_NONE))
        elif bad and settled:
            whys = "·".join(dict.fromkeys(bad[-1][1]))
            vals = ", ".join(inst["show"])
            res.append(("값이상", whys + (f": {vals}" if vals else "") + (f" ×{len(bad)}" if len(bad) > 1 else "")))
        elif bad:
            res.append(("로그끝", f"마지막 값 이상, 뒤 로그 {tail:.1f}s"))
        elif settled:
            res.append(("없음", f"{_ro(inst['end'][0])} 끝남" if end_dt is not None else f"뒤 로그 {tail:.0f}s"))
        else:
            res.append(("로그끝", f"뒤 로그 {tail:.1f}s"))
        broken = True
    return res


def _ro(word: str) -> str:
    """`연결 해제로`·`무선 끔으로` — 받침(ㄹ 빼고)이 있으면 `으로`."""
    jong = (ord(word[-1]) - 0xAC00) % 28 if "가" <= word[-1] <= "힣" else 0
    return word + ("으로" if jong not in (0, 8) else "로")


def _row(flow, inst, records) -> dict:
    steps = []
    for s, (verdict, detail) in zip(flow["steps"], inst["verdicts"]):
        bad = inst["bad"].get(s["id"]) or []
        at = inst["ok"].get(s["id"], bad[-1][0] if bad else None)
        steps.append({"id": s["id"], "verdict": verdict, "detail": detail,
                      "line_ref": records[at].get("line_ref") if at is not None else None, "bad_count": len(bad)})
    return {"key": inst["tag"], "start_ts": records[inst["start"]]["ts"], "line_ref": records[inst["start"]].get("line_ref"),
            "restarts": inst["restarts"],
            "end": {"label": inst["end"][0], "ts": logtime.format_ts(inst["end"][1])} if inst["end"] else None,
            "steps": steps, "notes": inst["notes"], "then": None}
