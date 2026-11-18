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
        negative_control: true    # 선택. 대조군(일부러 틀린 라벨 등): 돌리고 판정은 보이되 지표의 분모·분자에서 뺀다
        steps_file: tc.html       # 선택. --steps-file로 넘긴다(라벨셋 기준 상대 경로)
        sim_slot: "1"             # 선택. 이슈 메타의 SIM 슬롯(--issue-meta sim_slot)

조건별 실행(선택, 분석 정확도 단계 1): 문서에 `conditions: [no_time, time, look_at]`가 있으면 항목마다 그 조건을 따로 돌린다.
항목이 가진 조건만 돈다 — `no_time`(시각 없음: `occurred_at`도 `--answer`도 넘기지 않는다. 포털의 첫 선별·analyze 기본처럼
플러그인이 묻지 않고 증상 시각 스캔으로 로그 전체를 본다)은 늘, `time`(발생 시각만)은 `occurred_at`이 있을 때, `look_at`(정답 기준
줄을 `--look-at`으로, 시각·답 없이 — 단계 4가 자동으로 찾아야 할 것을 사람이 넣은 경우)은 항목 `look_at`이 있을 때. 이때
`occurred_at`은 필수가 아니고 연도는 `year`(항목·문서) 또는 `occurred_at`에서 온다. 항목 필드 더: `look_at`(기준 줄), `fail_at`(정답
실패 줄의 시각, 타임존 있는 ISO — 기준 위치 정답 판정), `fail_line`(그 줄 원문, 기록용 — 표·JSON에 내지 않는다), `first_analysis: true`
(첫 분석 — 단서 없음 사례), 그 밖(`issue_file`·`pair`)은 읽지 않는 기록용. `conditions`가 없으면 예전처럼 항목마다 한 번
(`occurred_at` 필수) 돈다. 포털 선별과 다른 입력: 이 도구는 `--issue-meta`(실패 스텝은 메타의 `failed_step` 칸)로 주고, 포털은
`--issue-file`(Jira 필드)·`--failed-step=`(CLI)·`--platform android`로 준다 — 단계 4에서 코멘트를 읽게 되면 `issue_file`로 도는
조건이 따로 필요하다.
조건이 있을 때 `--json`의 `summary`는 모든 조건의 실행을 합친 값(종료 코드 판단용)이라 S-5 게이트(`site_checks` s5)에 쓰지 않는다 —
조건별 값은 `by_condition`.

채택(단계 사이 비교용 정의): `analysis.json`에 `decision`이 있으면 `state: accepted`일 때 `selected.cause`, 없으면 1위 후보가
원인을 갖고 C=1일 때 그 원인. 채택 지표(대조군·표본내·오류 제외, 조건별): 맞는 채택·틀린 채택·보류·답변률(채택÷평가)·옳은 보류
(정답 unresolved인데 보류)·보류 사유별 수(`held_reasons`: `decision.reason`, decision 없으면 `top`)·보류 중 raw 1위가 정답이던 수·기준 위치 정답(기준(`step_anchor.source`가 look_at·log_marker·
steps_file·step_order)을 쓴 실행에서 잡힌 실패 시각 = `fail_at`. 시각을 읽지 못하면 판정 없음과 항목 경고)·기준 못 잡음
(`anchor_missed`: look_at 조건이나 `steps_file`로 기준을 요청했는데 기준 없이 돈 실행)·첫 분석 보류율.
`--portal <dir>`(선택): `<dir>/portal/screener.py`(포털 소스 — 체크아웃이 아니라 `git archive`로 푼 사본)의 `classify`와 실제 카드가
거치는 `result_of`(대표 원인·주의 줄 거르기·표시 전 검사), `confident_match`를 그대로 불러 실행마다 포털 카드 판정·대표 원인·확실한
일치를 열로 낸다(포털 규칙을 복제하지 않는다). `meta.portal`에 `screener.py` sha256을 남긴다. 없으면 그 열은 "미측정".

지표(대조군 제외 — `negative_control: true` 항목은 `controls`로 따로 세고 표에 `대조군(<판정>)`으로 보인다. **표본내**
항목 — 로그가 그 이슈 DB의 `*/fixtures/` 아래 파일(시그니처를 만들 때 쓴 fixture 자체)이거나, 항목 `key`가 그 DB에 이미
기록된 이슈(`<카테고리>/<유형>/issues/<KEY>.yaml`의 파일 이름, Jira 키 기준)이면 자기 일치라 정확도 지표가 아니다 —
도 자동으로 `in_sample`로 세고(사유는 항목 `in_sample_reason`: `fixture` 우선, 아니면 `db-record`) 표에 `표본내(<판정>)`로
보이며 지표에서 뺀다. 도구 동작 확인(합성 샘플)에는 `--include-in-sample`. 기록 없이 시드(import fixture)에만 쓴 Jira는
도구가 못 가린다 — 사내 S-5는 시그니처 작성에 쓰지 않은 로그만 넣는다):
  - 1위 정확도: 정답이 원인 ID인 항목 중 1위 후보가 정답인 비율
  - 상위 3 포함률: 정답이 원인 ID인 항목 중 상위 3 후보에 정답이 있는 비율
  - 오탐률: 정답이 unresolved인 항목 중 후보를 낸 비율
  로그 범위 밖(`logs.in_range` false)이거나 이벤트가 0인 항목은 오류로 빼고(분모 제외) 따로 센다.
  판정 불완전(`unjudged`의 `count`·`cause_count` > 0: 시그니처 시간 초과·오류로 S/C null인 유형·원인이 있음)이면:
    - 정답이 unresolved이고 상위 3에 원인(`cause`가 null 아님) 후보가 이미 있으면 판정 불완전과 무관하게 오탐이 확정이므로
      평가하고(판정 오탐) 항목 `warning`에 판정 불완전을 남긴다.
    - 그 밖(unresolved인데 원인 후보 없음, 정답이 원인 ID인 항목 전부 — 1위가 정답이어도 판정 못 한 유형이 앞설 수 있다)은
      오류 "판정 불가(…)"로 뺀다(분모 제외, `errors`·`error_rate`에 들어가고 `unjudged_errors`로 따로 센다).
  S/C에 영향 없는 시그니처 오류만 있으면(`errors`만, `count` 0) 평가하고 항목 `warning`에 남긴다.
  항목 `unjudged`는 `{count, cause_count}`(판정 불가가 없으면 null). 오류 항목의 `top`·`top3`는 비운다.

플러그인 루트: `--plugin-root`, 없으면 `plugin/site-defaults.yaml`이 있을 때 `plugin/`,
없으면 테스트 헬퍼 루트(`tests/helpers/make_plugin_root.py`)를 임시로 만든다.
`--json`의 `meta`(텍스트는 머리 한 줄): `plugin_repo`(이 도구가 들어 있는 레포의 git SHA·dirty), `db`(DB의 git SHA·dirty),
`plugin_root`(실제 실행 루트 경로·임시 여부), `site_defaults_sha256`, `labelset_sha256`, Python 버전, 실행 인자 — 결과를 어느
코드·DB·설정·라벨셋으로 냈는지 식별한다(비밀값·원문 없음). 항목에는 `logs_sha256`(입력 로그 해시)과 `backend`·`external`
(`events.json`의 파서 백엔드·외부 파서, 못 읽으면 null)을 더한다.
종료 코드: 0 = 실행 완료, 1 = 평가 가능한 항목 없음(전부 오류·대조군·표본내 — 통과로 보지 않는다), 2 = 사용 오류.
"""

from __future__ import annotations

import argparse
from collections import Counter
import functools
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
CONDITIONS = ("no_time", "time", "look_at")
ANCHORED = ("look_at", "log_marker", "steps_file", "step_order")    # 기준이 있는 `step_anchor.source`
HEADER = ("규칙 동작 확인용 — 조합 로그는 시드 줄로 만든 표본 안 자료, 정확도 수치가 아님. 표본내 자동 제외(DB fixtures/ 자체·"
          "DB에 기록된 키)는 이 조합 로그를 가리지 못한다(로그가 DB 밖 사본이고 키가 DB에 없다).\n"
          "look_at의 기준 위치 정답은 token 사례 말고는 넣은 줄(실패 줄 원문)을 다시 찾은 것이다.")
PORTAL_NOTE = ("포털 열: 포털 classify·result_of·confident_match 그대로. 실제 카드와 다를 수 있는 곳 — 입력 인자(--issue-meta, "
               "포털은 --issue-file·--failed-step=), 이해 카드·타임라인은 만들지 않음(입력 버전 없음).")

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
    conds = doc.get("conditions")
    if conds is not None and (not isinstance(conds, list) or not conds or set(conds) - set(CONDITIONS)):
        raise EvalError(f"conditions는 {', '.join(CONDITIONS)} 중 하나 이상의 목록이어야 합니다.")
    for i, item in enumerate(doc["items"], 1):
        for field in ("key", "logs", "expect") + (() if conds else ("occurred_at",)):
            if not item.get(field):
                raise EvalError(f"items[{i}]에 {field}가 없습니다.")
        if not isinstance(item["logs"], list):
            raise EvalError(f"items[{i}].logs는 목록이어야 합니다.")
    return doc


def _under_fixtures(log: Path, db: Path) -> bool:
    """로그가 그 이슈 DB의 `<카테고리>/<유형>/fixtures/` 아래 파일인가(시그니처 작성 fixture 자체 = 표본내)."""
    try:
        rel = log.resolve().relative_to(Path(db).resolve())
    except (ValueError, OSError):
        return False
    return "fixtures" in rel.parts[:-1]


@functools.cache
def _recorded_keys(db: Path) -> frozenset[str]:
    """이슈 DB에 이미 기록된 이슈 키(`common/issuedb.py`: `<유형 디렉토리>/issues/<KEY>.yaml`). 라벨셋 key는 외부 입력이라
    glob에 넣지 않고 파일 이름(stem)과 비교한다. DB당 한 번만 훑는다."""
    return frozenset(p.stem for p in Path(db).glob("*/*/issues/*.yaml"))


def _same_instant(a, b) -> bool | None:
    """같은 시각인가. 읽지 못하거나 타임존이 없으면 None(판정 없음 — 틀림으로 세지 않는다). `Z`는 3.10도 읽게 바꾼다
    (`logtime.parse_ts`와 같은 방식)."""
    try:
        x, y = (datetime.fromisoformat(str(v).replace("Z", "+00:00")) for v in (a, b))
    except (TypeError, ValueError):
        return None
    return None if x.tzinfo is None or y.tzinfo is None else x == y


def _adopted(analysis: dict) -> tuple[str | None, str]:
    """(채택한 원인 | None, 근거): `decision`이 있으면 그 값(단계 2부터), 없으면 1위 후보가 원인을 갖고 C=1."""
    dec = analysis.get("decision")
    if isinstance(dec, dict):
        return ((dec.get("selected") or {}).get("cause") if dec.get("state") == "accepted" else None), "decision"
    top = (analysis.get("candidates") or [{}])[0]
    return (top.get("cause") if top.get("cause") and top.get("C") == 1 else None), "top"


def _portal_column(screener, proc, root: Path, db: Path, job: Path, key: str) -> dict:
    """포털 카드를 실제와 같은 함수로 만든다: 선별 분류(`classify`) → 카드(`result_of` — 대표 원인 이슈 DB 조회·주의 줄 거르기·
    표시 전 검사, 입력 버전이 없어 이해 카드·타임라인은 없음) → 확실한 일치(`confident_match`). job = 그 실행의 `--out`."""
    try:
        c = screener.classify(proc.returncode, proc.stdout.encode("utf-8"), False)
        cfg = {"plugin_root": str(root), "screen_db": str(db), "data_dir": str(job.parent), "secret_vars": []}
        res = screener.result_of(cfg, key, job, c, [])
        return {"verdict": res["verdict"], "reason": res["reason"], "primary": (res["primary"] or {}).get("cause"),
                "confident": screener.confident_match(res), "errors": res["errors"],
                "hidden": res.get("evidence_hidden") or res.get("report_hidden")}
    except Exception as exc:     # 포털 코드가 이 환경에서 못 도는 것은 열에 그대로 남긴다(통과로 보이지 않게)
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


def evaluate_item(root: Path, db: Path, base: Path, doc: dict, item: dict, work: Path,
                  condition: str | None = None, screener=None) -> dict:
    """analyze와 같은 드라이버(`triage.py run --offline-db`)로 파서 → 매처를 돌린다. condition이 None이면 예전 실행(발생 시각)."""
    key = str(item["key"])
    logs = [str((base / p).resolve()) for p in item["logs"]]
    job = work / f"{len(list(work.iterdir())):03d}-{key}"
    job.mkdir(parents=True)
    meta = {"key": key, "sw": item.get("sw", ""),
            "summary": item.get("summary", ""), "description": item.get("description", "")}
    if condition in (None, "time"):
        meta["occurred_at"] = str(item["occurred_at"])
    if item.get("failed_step"):
        meta["failed_step"] = str(item["failed_step"])
    if item.get("sim_slot") not in (None, ""):
        meta["sim_slot"] = str(item["sim_slot"])
    meta_path = job / "issue_input.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    args = ["run", key, "--offline-db", str(db), "--out", str(job), "--logs", *logs, "--issue-meta", str(meta_path)]
    if condition == "look_at":
        args += ["--look-at", str(item["look_at"])]
    if item.get("steps_file"):
        args += ["--steps-file", str((base / str(item["steps_file"])).resolve())]
    minutes = item.get("minutes", doc.get("minutes"))
    if minutes:
        args += ["--minutes", str(minutes)]
    tz = item.get("tz", doc.get("tz"))
    if tz:
        args += ["--tz", str(tz)]
    in_fixture = any(_under_fixtures(Path(p), db) for p in logs)
    in_db = key in _recorded_keys(db)
    result = {"key": key, "expect": str(item["expect"]), "top": None, "top3": [], "error": None, "warning": None, "unjudged": None, "observation": None,
              "control": bool(item.get("negative_control")),
              "in_sample": in_fixture or in_db,
              "in_sample_reason": "fixture" if in_fixture else "db-record" if in_db else None,
              "logs_sha256": [hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else None for p in logs],
              "backend": None, "external": None,
              "condition": condition, "adopted": None, "adopted_from": None, "anchor": None, "anchor_ok": None, "anchor_missed": False,
              "first_analysis": bool(item.get("first_analysis")), "portal": None}
    try:
        year = item.get("year") or doc.get("year")
        if not year:
            if not item.get("occurred_at"):
                raise ValueError("year도 occurred_at도 없다")
            occurred = datetime.fromisoformat(str(item["occurred_at"]))
            year = (occurred.astimezone(ZoneInfo(str(tz))) if tz and occurred.tzinfo else occurred).year
    except (ValueError, ZoneInfoNotFoundError) as exc:
        result["error"] = f"occurred_at·tz 해석 실패: {exc}"
        return result
    args += ["--year", str(year)]
    proc = _script(root, "triage.py", args)
    if screener is not None:
        result["portal"] = _portal_column(screener, proc, root, db, job, key)
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
    result["adopted"], result["adopted_from"] = _adopted(analysis)
    dec = analysis.get("decision")
    if isinstance(dec, dict) and dec.get("state") == "held":
        result["held_reason"] = dec.get("reason")
    sa = analysis.get("step_anchor") or {}
    if sa:
        result["anchor"] = {"source": sa.get("source"), "fail": (sa.get("span") or [None, None])[-1]}
    anchor_note = None
    if sa.get("source") in ANCHORED and item.get("fail_at"):
        result["anchor_ok"] = _same_instant(result["anchor"]["fail"], item["fail_at"])
        if result["anchor_ok"] is None:
            anchor_note = f"기준 위치 판정 없음(시각 해석 실패·타임존 없음: {result['anchor']['fail']} / {item['fail_at']})"
    elif item.get("fail_at") and (condition == "look_at" or item.get("steps_file")):
        result["anchor_missed"] = True      # 기준을 요청했는데 기준 없이 돌았다(못 찾음)
    # 정답·미스를 단정하지 못하는 이유 [(오류 문구, 오탐 확정 때 경고 문구)]: 판정 불가 유형·원인(unjudged)과 관측 불완전
    # (observation). 둘 다 있으면 둘 다 기록한다
    unsure: list[tuple[str, str]] = []
    notes: list[str] = [anchor_note] if anchor_note else []
    u = analysis.get("unjudged") or {}
    if u:
        first = (u.get("errors") or [{}])[0]
        why = f" — {first.get('signature')}: {first.get('error')}" if first.get("signature") else ""
        if not (u.get("count") or u.get("cause_count")):   # 충족된 유형의 다른 시그니처만 오류(S/C 영향 없음): 평가는 하고 알린다
            notes.append(f"시그니처 오류(S/C 영향 없음){why}")
        else:
            result["unjudged"] = {"count": u.get("count", 0), "cause_count": u.get("cause_count", 0)}
            what = f"유형 {result['unjudged']['count']}·원인 {result['unjudged']['cause_count']}{why}"
            unsure.append((f"판정 불가(시그니처 시간 초과·오류): {what}", f"판정 불완전(시그니처 시간 초과·오류): {what}"))
    obs = analysis.get("observation")
    if obs:     # 관측 불완전(extractor 오류·파일 해석 실패 등): 못 본 이벤트가 1위·후보를 바꿀 수 있다
        result["observation"] = {"count": obs.get("count", 0), "extractor": obs.get("extractor", 0)}
        example = next((e["error"] for e in obs.get("errors") or [] if e.get("error")), None)
        text = (f"관측 불완전(extractor 오류 {result['observation']['extractor']}·전체 {result['observation']['count']})"
                + (f" — {example}" if example else ""))
        unsure.append((text, text))
    if unsure and result["expect"] == UNRESOLVED and any(c is not None for c in result["top3"]):
        # 원인 후보가 이미 나왔으면 판정 못 한 항목·못 본 이벤트와 무관하게 오탐이 확정이다
        notes.append("; ".join(w for _, w in unsure) + " — 원인 후보가 있어 오탐은 확정")
    elif unsure:   # 판정 못 한 유형·원인, 못 본 이벤트가 1위·후보를 바꿀 수 있다 → 정답·미스를 단정하지 않는다(분모 제외)
        result["error"] = "; ".join(e for e, _ in unsure)
        result["top"], result["top3"], result["adopted"] = None, [], None
    if notes:
        result["warning"] = "; ".join(notes)
    return result


def _excluded(r: dict, include_in_sample: bool) -> bool:
    return bool(r.get("control")) or (bool(r.get("in_sample")) and not include_in_sample)


def summarize(results: list[dict], include_in_sample: bool = False) -> dict:
    """대조군(`control`)과 표본내(`in_sample`, `--include-in-sample`이 아니면)는 판정은 매기되(`대조군(<판정>)`·`표본내(<판정>)`)
    지표·분모 어디에도 넣지 않는다 — 일부러 틀린 라벨·자기 일치가 '정확도'로 읽히지 않게."""
    controls = [r for r in results if r.get("control")]
    in_sample = [r for r in results if r.get("in_sample") and not r.get("control")]
    graded = [r for r in results if not r["error"]]
    scored = [r for r in graded if not _excluded(r, include_in_sample)]
    positive = [r for r in scored if r["expect"] != UNRESOLVED]
    negative = [r for r in scored if r["expect"] == UNRESOLVED]
    for r in graded:
        if r["expect"] == UNRESOLVED:
            r["verdict"] = "오탐" if any(c is not None for c in r["top3"]) else "정답"   # cause: null(유형만)은 오탐 아님
        elif r["top"] == r["expect"]:
            r["verdict"] = "1위"
        elif r["expect"] in r["top3"]:
            r["verdict"] = "상위3"
        else:
            r["verdict"] = "미스"
        if r.get("control"):
            r["verdict"] = f"대조군({r['verdict']})"
        elif r.get("in_sample") and not include_in_sample:
            r["verdict"] = f"표본내({r['verdict']})"

    def rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    counted = [r for r in results if not _excluded(r, include_in_sample)]
    adopted = [r for r in scored if r.get("adopted")]
    first = [r for r in scored if r.get("first_analysis")]
    return {
        "total": len(results),
        "controls": len(controls),          # 지표 제외(돌리기는 한다)
        "in_sample": len(in_sample),        # fixture 자체·DB에 기록된 키인 항목 수(--include-in-sample이 아니면 지표 제외)
        "include_in_sample": include_in_sample,
        "evaluated": len(scored),
        "errors": len(counted) - len(scored),
        "unjudged_errors": sum(bool(r["error"]) and bool(r.get("unjudged")) for r in counted),
        "observation_errors": sum(bool(r["error"]) and bool(r.get("observation")) for r in counted),
        "error_rate": rate(len(counted) - len(scored), len(counted)),
        "type_only": sum(bool(r["top3"]) and all(c is None for c in r["top3"]) for r in negative),
        "positive": len(positive),          # 평가된(오류 아닌) 항목만
        "negative": len(negative),
        "positive_total": sum(r["expect"] != UNRESOLVED for r in counted),     # 오류 포함, 대조군 제외
        "negative_total": sum(r["expect"] == UNRESOLVED for r in counted),
        "top1_accuracy": rate(sum(r["top"] == r["expect"] for r in positive), len(positive)),
        "top3_inclusion": rate(sum(r["expect"] in r["top3"] for r in positive), len(positive)),
        "false_positive_rate": rate(sum(r["verdict"] == "오탐" for r in negative), len(negative)),
        # 채택 지표(머리말 "채택"): 평가된 것(scored) 기준
        "accepted_correct": sum(r["adopted"] == r["expect"] for r in adopted),
        "accepted_wrong": sum(r["adopted"] != r["expect"] for r in adopted),
        "held": len(scored) - len(adopted),
        # 보류 사유(decision.reason)별 수 — decision 없는 결과(1위 기준 채택)의 보류는 `top`
        "held_reasons": dict(sorted(Counter(r.get("held_reason") or "top" for r in scored if not r.get("adopted")).items())),
        "answer_rate": rate(len(adopted), len(scored)),
        "correct_hold": sum(not r.get("adopted") and r["expect"] == UNRESOLVED for r in scored),
        "held_top_right": sum(not r.get("adopted") and r["expect"] != UNRESOLVED and r["top"] == r["expect"] for r in scored),
        "anchor_runs": sum(r.get("anchor_ok") is not None for r in scored),
        "anchor_correct": sum(r.get("anchor_ok") is True for r in scored),
        "anchor_missed": sum(bool(r.get("anchor_missed")) for r in scored),
        "first_total": len(first),
        "first_hold_rate": rate(sum(not r.get("adopted") for r in first), len(first)),
    }


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _table(rows: list[tuple]) -> list[str]:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return lines


def _notes(results: list[dict]) -> list[str]:
    tag = lambda r: r["key"] + (f"[{r['condition']}]" if r.get("condition") else "")    # noqa: E731
    return ([f"오류 {tag(r)}: {r['error']}" for r in results if r["error"]]
            + [f"경고 {tag(r)}: {r['warning']}" for r in results if r.get("warning")])


def _portal_cells(p: dict | None) -> tuple[str, str, str]:
    if p is None:
        return "미측정", "미측정", "미측정"
    if p.get("error"):
        return "오류", "오류", "오류"
    # 평가 PC의 환경 문제(포털 쪽 마스킹 호출 실패·이슈 DB 조회 실패)는 카드 판정처럼 보이지 않게 표시하고 확실한 일치는 판정 불가
    env = ((["가림 실패"] if "mask-error" in str(p.get("hidden") or "") else [])
           + (["DB 조회 실패"] if "db_search" in (p.get("errors") or []) else []))
    verdict = p["verdict"] + (f"({p['reason']})" if p.get("reason") else "") + (f"({'·'.join(env)})" if env else "")
    return verdict, p.get("primary") or "-", "판정 불가" if env else "예" if p["confident"] else "아니오"


def render_conditions(results: list[dict], by_condition: dict) -> str:
    """조건별 표(사례마다 한 줄)와 채택 지표. 포털 열은 --portal이 없으면 "미측정"."""
    lines = [HEADER] + ([PORTAL_NOTE] if any(r.get("portal") is not None for r in results) else [])
    for cond, s in by_condition.items():
        rows = [("키", "정답", "raw 1위", "채택", "판정", "기준 위치", "포털 판정", "포털 대표 원인", "확실한 일치")]
        runs = [r for r in results if r.get("condition") == cond]
        for r in runs:
            where = ("못 찾음" if r.get("anchor_missed") else "-" if r.get("anchor_ok") is None
                     else "맞음" if r["anchor_ok"] else "틀림")
            rows.append((r["key"], r["expect"], r["top"] or "-", r.get("adopted") or "보류",
                         "오류" if r["error"] else r["verdict"], where, *_portal_cells(r.get("portal"))))
        lines += ["", f"[조건 {cond}] 평가 {s['evaluated']}/전체 {s['total']}, 오류 {s['errors']}", *_table(rows), *_notes(runs),
                  f"채택: 맞음 {s['accepted_correct']} · 틀림 {s['accepted_wrong']} · 보류 {s['held']} · 답변률 {_pct(s['answer_rate'])}",
                  f"보류: 옳은 보류(정답 unresolved) {s['correct_hold']} · 보류 중 raw 1위가 정답 {s['held_top_right']} · 사유 "
                  + (", ".join(f"{k} {n}" for k, n in s["held_reasons"].items()) or "-"),
                  f"기준 위치 정답 {s['anchor_correct']}/{s['anchor_runs']}(기준을 쓴 실행) · 기준 못 잡음 {s['anchor_missed']} · 첫 분석 보류율 "
                  f"{_pct(s['first_hold_rate'])}({s['first_total']}건)",
                  f"raw: 1위 정확도 {_pct(s['top1_accuracy'])} · 상위 3 포함률 {_pct(s['top3_inclusion'])} · "
                  f"오탐률 {_pct(s['false_positive_rate'])}"]
    return "\n".join(lines)


def render(results: list[dict], summary: dict) -> str:
    rows = [("키", "정답", "1위", "판정")]
    for r in results:
        rows.append((r["key"], r["expect"], r["top"] or "-", "오류" if r["error"] else r["verdict"]))
    lines = _table(rows) + _notes(results)
    lines += [
        "",
        f"평가 {summary['evaluated']}/전체 {summary['total']}"
        + (f" (대조군 {summary['controls']}건은 지표에서 뺌)" if summary.get("controls") else "")
        + (f" (표본내 — 시그니처 fixture 자체·이슈 DB에 이미 기록된 이슈 — {summary['in_sample']}건은 지표에서 뺌; 도구 동작 확인용이면 --include-in-sample)"
           if summary.get("in_sample") and not summary.get("include_in_sample")
           else f" (표본내 {summary['in_sample']}건 포함 — 정확도 지표 아님)" if summary.get("in_sample") else ""),
        f"항목 {summary['total'] - summary.get('controls', 0) - (0 if summary.get('include_in_sample') else summary.get('in_sample', 0))}건 "
        f"(정답 원인 ID {summary['positive_total']}·unresolved "
        f"{summary['negative_total']}, 평가된 것 원인 {summary['positive']}·unresolved {summary['negative']}, 오류 {summary['errors']})",
        f"1위 정확도    {_pct(summary['top1_accuracy'])}",
        f"상위 3 포함률 {_pct(summary['top3_inclusion'])}",
        f"오탐률        {_pct(summary['false_positive_rate'])} (원인 후보 기준, 유형만 {summary['type_only']}건 제외)",
        f"오류율        {_pct(summary['error_rate'])} ({summary['errors']}/{summary['total']}, 평가에서 제외됨, "
        f"그중 판정 불가 {summary['unjudged_errors']}건·관측 불완전 {summary['observation_errors']}건)",
    ]
    if not summary["evaluated"]:
        lines.append("평가 가능한 항목 없음 — 전부 오류·대조군·표본내(지표 없음, 통과 아님)")
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
    parser.add_argument("--portal", metavar="dir", default=None,
                        help="포털 소스 사본(<dir>/portal/screener.py, git archive로 푼 것) — 실행마다 포털 카드 판정 열을 낸다")
    parser.add_argument("--include-in-sample", action="store_true",
                        help="표본내 항목(로그가 이슈 DB fixtures/ 자체이거나 키가 DB에 기록된 이슈)도 지표에 넣는다 — 도구 동작 확인용, 정확도 측정 아님")
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
        screener = None
        if args.portal:
            sys.path.insert(0, str(Path(args.portal).resolve()))
            try:
                from portal import screener     # noqa: E402 — 포털 판정 규칙을 복제하지 않고 그대로 부른다
            except Exception as exc:            # 다른 의존성 때문에 안 되면 우회하지 않고 멈춘다
                raise EvalError(f"포털 소스를 불러올 수 없습니다: {args.portal} ({type(exc).__name__}: {exc})")
            meta["portal"] = {"path": str(Path(args.portal).resolve()),
                              "screener_sha256": hashlib.sha256(Path(screener.__file__).read_bytes()).hexdigest()}
        conds = doc.get("conditions")
        has = {"no_time": lambda i: True, "time": lambda i: bool(i.get("occurred_at")), "look_at": lambda i: bool(i.get("look_at"))}
        work = Path(tempfile.mkdtemp(prefix="tt-offline-eval-"))
        try:
            if conds:
                results = [evaluate_item(root, db, base, doc, item, work, c, screener)
                           for item in doc["items"] for c in conds if has[c](item)]
            else:
                results = [evaluate_item(root, db, base, doc, item, work, screener=screener) for item in doc["items"]]
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except EvalError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)

    summary = summarize(results, include_in_sample=args.include_in_sample)
    by_condition = {c: summarize([r for r in results if r["condition"] == c], include_in_sample=args.include_in_sample)
                    for c in conds or []}
    if args.json:
        out = {"meta": meta, "summary": summary, "items": results}
        if conds:       # 조건별 지표. summary는 모든 실행을 합친 것(종료 코드 판단용)
            out["by_condition"] = by_condition
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        def s(g: dict) -> str:
            return "-" if not g["sha"] else g["sha"][:12] + ("+dirty" if g["dirty"] else "")

        pr = meta["plugin_root"]
        print(f"meta: 플러그인 {s(meta['plugin_repo'])} · DB {s(meta['db'])} · 플러그인 루트 {pr['path']}"
              f"{'(임시)' if pr['temporary'] else ''} · 라벨셋 sha256 {meta['labelset_sha256'][:12]} · Python {meta['python']}")
        print(render_conditions(results, by_condition) if conds else render(results, summary))
    if not summary["evaluated"]:     # 전부 오류인 평가를 정상 완료(0)로 보이지 않는다
        print("평가 가능한 항목 없음 — 전부 오류·대조군·표본내(지표 없음, 통과 아님)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
