#!/usr/bin/env python3
"""분석 정확도 기준값의 조합 로그·라벨셋(`tests/fixtures/accuracy/`)을 만든다 (분석 정확도 단계 1).

재료는 공개 근거뿐이다: 이슈 DB 시드 fixture(`templates/issue-db-seeds/android/<카테고리>/fixtures/*.log`, 합성 머리줄은 뺀다)의
줄과 합성 벤더 IPC 줄(`VIPC_` 꼴 — `common/ipcseq.py`의 기본 trace가 읽는 모양, 태그 `RIL`). 조각(segment)마다 첫 줄을
정한 시각으로 옮기고(조각 안 간격은 그대로) 이어 붙인다. 결정적이다.

만드는 것(커밋한다 — 이 스크립트는 다시 만들 때와 `--check`로 비교할 때 쓴다):
- `<사례>.log`: 조합 로그
- `labelset.yaml`: `tools/offline_eval.py` 라벨셋(조건별 실행 `conditions`, 정답 `expect`, 정답 실패 줄 `fail_line`·`fail_at`,
  기준 줄 `look_at`). 정답이 의도와 다르게 나와도 사례를 맞추지 않는다 — 지금 코드의 출력은 `baseline.json`이 기록한다.
- `issues/<KEY>.yaml`: 코멘트가 필요한 사례의 Jira 글(`triage.py --issue-file` 모의 티켓 형식). **지금 코드는 선별에서 코멘트를
  쓰지 않아 읽히지 않는다** — 단계 4가 쓸 입력을 미리 고정해 둔다.

`--seed-db DIR`: 시드 계획 다섯 개를 새 뼈대(`tools/make_db_skeleton.py`)에 `db_add.py apply`로 차례로 적용한 이슈 DB를 DIR에
만든다(git·검증 없이 — 라벨셋을 돌릴 DB. 커밋하지 않는다).

CLI:
    python3 tests/helpers/make_accuracy_fixtures.py [--check] [--seed-db DIR]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SEEDS = REPO / "templates" / "issue-db-seeds" / "android"
OUT = REPO / "tests" / "fixtures" / "accuracy"
YEAR, TZ, DAY = 2026, "+09:00", "11-14"
STAMP = re.compile(r"^(\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})(.*)$")
HEAD = "-- [합성] 분석 정확도 조합 로그. 시드 fixture 줄과 합성 VIPC_ 줄을 시각만 옮겨 이어 붙였다(tests/helpers/make_accuracy_fixtures.py)."
CONDITIONS = ["no_time", "time", "look_at"]


def seed(rel: str, keep=None) -> list[str]:
    """시드 fixture의 시각 있는 줄(합성 머리줄 제외). keep = 남길 줄 번호(0부터)."""
    lines = [x for x in (SEEDS / rel).read_text(encoding="utf-8").splitlines() if STAMP.match(x)]
    return [lines[i] for i in keep] if keep is not None else lines


def _at(sec: float) -> str:
    return (datetime(YEAR, 11, 14) + timedelta(seconds=sec)).strftime("%m-%d %H:%M:%S.%f")[:-3]


def vipc(sec: float, way: str, name: str, token: str, result: str | None = None, slot: int | None = None) -> str:
    """합성 벤더 IPC 줄(placeholder 기본 trace 모양). slot이 있으면 `ipc[<slot>]` 머리(단계 1.5가 슬롯으로 읽을 자리)."""
    kind = "REQ" if way == "TX" else "RSP"
    tail = f", len={24 if way == 'TX' else 8}" + (f", Error({result})" if result else "")
    head = f"ipc[{slot}]" if slot is not None else ""
    return f"{_at(sec)}   900   910 D RIL     : {head}[{way}] {name}, {kind}, token={token}{tail}"


# -- 조각 ---------------------------------------------------------------------------------------------
# M: 비행기 모드 켬(NETWORK-001-03) · OFF: 비행기 모드 끔 후 복구(후보 없음) · H: radio HAL 장애(NETWORK-001-08)
# X: DB에 없는 SETUP_DATA_CALL 실패(요청 뒤 RIL 오류 응답 — 응답 줄만 시드 줄 모양으로 새로 씀) · F: APN 없음 실패(DATA-003-01)
# OK: 정상 데이터 연결 · D12R: 비행기 모드로 데이터 해제(DATA-002-01) · C15: 비행기 모드 중 발신(CALL-001-02)
M = "network/fixtures/radio-off-airplane.log"
OFF = "network/fixtures/network-airplane-off-recovered.log"
H = "network/fixtures/radio-hal-died.log"
F = "data/fixtures/data-setup-missing-apn.log"
OK = "data/fixtures/data-normal-setup.log"
D12R = "data/fixtures/data-airplane-on.log"
C15 = "call/fixtures/mo-airplane.log"
X_ERROR = "[0410]< SETUP_DATA_CALL error 2 [PHONE0]"
X_DONE = "  2101  2141 D RILJ    : " + X_ERROR


def segment(kind, start: float, token: str | None = None, result: str = "VIPC_E_DEMO_FAILURE", slot: int | None = None) -> list[str]:
    """조각 하나를 start초(11-14 00:00 기준)로 옮긴다. kind가 "X"면 X 조각. token이 있으면 SETUP_DATA_CALL 요청 줄 뒤에
    IPC 요청·응답 줄을 끼운다(result: 실패 `VIPC_E_DEMO_FAILURE`, 성공 `VIPC_E_OK` — 성공은 OK 조각에 쓴다)."""
    if kind == "X":
        base = seed("data/fixtures/data-setup-missing-apn.log", keep=[0, 1, 2, 3])
        lines = base + [base[-1][:18] + X_DONE]          # 응답 줄(새로 씀): 시각은 아래 offsets(요청 +0.116초)
        offsets = [0.0, 0.5, 0.502, 0.504, 0.620]
    else:
        lines, offsets = seed(kind), None
    first = datetime.strptime(f"{YEAR}-{STAMP.match(lines[0]).group(1)}", "%Y-%m-%d %H:%M:%S.%f")
    out = []
    for i, line in enumerate(lines):
        t = STAMP.match(line)
        rel = offsets[i] if offsets else (datetime.strptime(f"{YEAR}-{t.group(1)}", "%Y-%m-%d %H:%M:%S.%f") - first).total_seconds()
        out.append(_at(start + rel) + t.group(2))
    if token is not None:       # IPC 줄: 요청 줄 뒤 +0.010초 TX, 응답(오류·성공) 앞 RX
        req = next(i for i, x in enumerate(out) if "> SETUP_DATA_CALL" in x)
        t0 = (datetime.strptime(f"{YEAR}-{STAMP.match(out[req]).group(1)}", "%Y-%m-%d %H:%M:%S.%f") - datetime(YEAR, 11, 14)).total_seconds()
        out.insert(req + 1, vipc(t0 + 0.010, "TX", "VIPC_SETUP_DATA", token, slot=slot))
        out.insert(req + 2, vipc(t0 + 0.090, "RX", "VIPC_SETUP_DATA", token, result, slot=slot))
    if slot:                    # 두 번째 SIM: 프레임워크 줄의 phone·컨트롤러 번호만 바꾼다
        out = [x.replace("[PHONE0]", f"[PHONE{slot}]").replace("DNC-0 ", f"DNC-{slot} ").replace("SST-0 ", f"SST-{slot} ")
               for x in out]
    return sorted(out, key=lambda x: STAMP.match(x).group(1))


def minute(m: float) -> float:
    return 10 * 3600 + m * 60     # 10:00 기준 분


# -- 사례 ---------------------------------------------------------------------------------------------
# 각 사례: 조각 목록, 정답(expect), 정답 실패 줄(fail: 그 줄에만 있는 글), 기준 줄(look: None이면 실패 줄 원문 그대로),
# 항목 추가 필드. token 사례의 기준 줄은 코멘트에 적히는 `<IPC 이름> (token=0x…)` 꼴이다.
TC_SEGMENTS = [(M, minute(0)), (OFF, minute(0.5)), ("X", minute(2)), (M, minute(3))]
CASES = [
    # Codex 2차 §5.4 조합(M 비행기 모드, X DB에 없는 실패, H radio HAL 장애)
    {"name": "mmx", "key": "MMX-1", "segs": [(M, minute(0)), (M, minute(2)), ("X", minute(4))], "expect": "unresolved",
     "fail": X_ERROR, "summary": "데이터 연결 실패"},
    {"name": "xm", "key": "XM-1", "segs": [("X", minute(0)), (M, minute(2))], "expect": "unresolved", "fail": X_ERROR,
     "summary": "데이터 연결 실패"},
    {"name": "mxm", "key": "MXM-1", "segs": [(M, minute(0)), ("X", minute(2)), (M, minute(4))], "expect": "unresolved",
     "fail": X_ERROR, "summary": "데이터 연결 실패"},
    {"name": "mmh", "key": "MMH-1", "segs": [(M, minute(0)), (M, minute(2)), (H, minute(4))], "expect": "NETWORK-001-08",
     "fail": "Service MODEM has died.", "summary": "서비스 없음"},
    # 대조군: 비행기 모드가 실제 원인(M 단독·d12r·c15 유형), radio HAL 단독(d20h 유형)
    {"name": "ctl-m", "key": "CTLM-1", "segs": [(M, minute(0))], "expect": "NETWORK-001-03", "fail": "set service state as POWER_OFF",
     "summary": "서비스 없음"},
    {"name": "ctl-d12r", "key": "D12R-1", "segs": [(D12R, minute(0))], "expect": "DATA-002-01",
     "fail": "onDataNetworkDisconnected:", "summary": "데이터 끊김"},
    {"name": "ctl-c15", "key": "C15-1", "segs": [(C15, minute(0))], "expect": "CALL-001-02",
     "fail": "CreateConnectionProcessor: Connection failed:", "summary": "발신 실패",
     "look": "CreateConnectionProcessor: Connection failed: (DisconnectCause [ Code: (ERROR) Label: (Radio off)"},   # 원문은 300자 넘음
    {"name": "ctl-h", "key": "HAL-1", "segs": [(H, minute(0))], "expect": "NETWORK-001-08", "fail": "Service MODEM has died.",
     "summary": "서비스 없음"},
    # TC 모양(11/17 오답 유형): 시작에 비행기 모드 켬·끔 → 실패 → 끝에 비행기 모드 켬
    {"name": "tc-shape", "key": "TC-1", "segs": TC_SEGMENTS, "expect": "unresolved", "fail": X_ERROR,
     "summary": "데이터 연결 실패", "failed_step": "Step 5 데이터 연결 확인 FAIL"},
    # 실패 뒤 복구(U3 반례): 등록된 실패 뒤 정상 연결이 이어진다
    {"name": "recover", "key": "RECOVER-1", "segs": [(F, minute(0)), (OK, minute(0.5))], "expect": "DATA-003-01",
     "fail": "onDataNetworkSetupDataFailed:", "summary": "데이터 연결 실패"},
    # token 기준(R3·R7): 실패 지점에 IPC 줄. 같은 로그에 코멘트만 다르다(이름 같음 / 이름 다르고 token만 같음)
    {"name": "token", "key": "TOKSAME-1", "segs": [(M, minute(0)), (OK, minute(1), "0x0dd", "VIPC_E_OK"),
                                                    ("X", minute(2), "0x0de"), (M, minute(3))],
     "expect": "unresolved", "fail": "token=0x0de, len=8, Error(VIPC_E_DEMO_FAILURE)", "look": "VIPC_SETUP_DATA (token=0x0de)",
     "summary": "데이터 연결 실패", "comment": "CP 확인: VIPC_SETUP_DATA (token=0x0de) 에서 망 거절로 실패했습니다."},
    {"name": "token", "key": "TOKNAME-1", "expect": "unresolved", "fail": "token=0x0de, len=8, Error(VIPC_E_DEMO_FAILURE)",
     "look": "VIPC_SETUP_DATA (token=0x0de)", "summary": "데이터 연결 실패",
     "comment": "CP 확인: VIPC_PDN_CONNECT (token=0x0de) 실패입니다."},
    # 이름만 있고 token 없음 — 같은 이름이 로그에 여러 번(성공 둘, 실패 하나)
    {"name": "token-nameonly", "key": "TOKONLY-1",
     "segs": [(M, minute(0)), (OK, minute(1), "0x0d1", "VIPC_E_OK"), ("X", minute(2), "0x0d2"), (OK, minute(3), "0x0d3", "VIPC_E_OK"),
              (M, minute(4))],
     "expect": "unresolved", "fail": "token=0x0d2, len=8, Error(VIPC_E_DEMO_FAILURE)", "look": "VIPC_SETUP_DATA (token=0x0d2)",
     "summary": "데이터 연결 실패", "comment": "CP 확인: VIPC_SETUP_DATA 실패입니다."},
    # 듀얼 SIM(A292): 같은 token이 두 슬롯에 — 슬롯 0은 성공, Jira 슬롯 1이 실패
    {"name": "dual-sim", "key": "DUAL-1", "segs": [(OK, minute(0), "0x0de", "VIPC_E_OK", 0), ("X", minute(1), "0x0de", "VIPC_E_DEMO_FAILURE", 1)],
     "expect": "unresolved", "fail": "ipc[1][RX] VIPC_SETUP_DATA, RSP, token=0x0de", "look": "VIPC_SETUP_DATA (token=0x0de)",
     "summary": "SIM2 데이터 연결 실패", "sim_slot": "1", "comment": "CP 확인: SIM2 VIPC_SETUP_DATA (token=0x0de) 실패."},
    # 재시험(U4): 올린 로그는 마지막 시험 것, 앞 코멘트의 token(0x0de)은 이 로그에 없음 / 우연히 다른 곳에 있음
    {"name": "retest", "key": "RETEST-1", "segs": [(M, minute(0)), ("X", minute(2), "0x1a2"), (M, minute(3))],
     "expect": "unresolved", "fail": "token=0x1a2, len=8, Error(VIPC_E_DEMO_FAILURE)", "look": "VIPC_SETUP_DATA (token=0x1a2)",
     "summary": "데이터 연결 실패(재시험)", "comment": "1차 시험: VIPC_SETUP_DATA (token=0x0de) 실패. 재시험 요청합니다."},
    {"name": "retest-elsewhere", "key": "RETESTX-1",
     "segs": [(M, minute(0)), (OK, minute(1), "0x0de", "VIPC_E_OK"), ("X", minute(2), "0x1a2"), (M, minute(3))],
     "expect": "unresolved", "fail": "token=0x1a2, len=8, Error(VIPC_E_DEMO_FAILURE)", "look": "VIPC_SETUP_DATA (token=0x1a2)",
     "summary": "데이터 연결 실패(재시험)", "comment": "1차 시험: VIPC_SETUP_DATA (token=0x0de) 실패. 재시험 요청합니다."},
    # pass 짝(단계 6용): 같은 흐름(비행기 모드 켬·끔 → 데이터 연결)의 fail 로그와 pass 로그
    {"name": "pair-fail", "key": "PAIRFAIL-1", "segs": [(M, minute(0)), (OFF, minute(0.5)), (F, minute(2))], "expect": "DATA-003-01",
     "fail": "onDataNetworkSetupDataFailed:", "summary": "데이터 연결 실패", "pair": "PAIRPASS-1"},
    {"name": "pair-pass", "key": "PAIRPASS-1", "segs": [(M, minute(0)), (OFF, minute(0.5)), (OK, minute(2))], "expect": "unresolved",
     "fail": None, "occurred": minute(2), "summary": "같은 TC의 pass 로그", "pair": "PAIRFAIL-1"},
    # 첫 분석(R5): 단서 없음 — 제목·실패 증상 한 줄만(시각·기준 줄 없이 no_time만)
    {"name": "tc-shape", "key": "FIRSTTC-1", "expect": "unresolved", "fail": X_ERROR, "first": True,
     "summary": "데이터 연결 실패", "failed_step": "데이터 연결 FAIL"},
    {"name": "mmh", "key": "FIRSTH-1", "expect": "NETWORK-001-08", "fail": "Service MODEM has died.", "first": True,
     "summary": "서비스 없음", "failed_step": "망 등록 FAIL"},
]


def build_log(segs) -> list[str]:
    lines = []
    for seg in segs:
        kind, start, *rest = seg
        lines += segment(kind, start, *rest)
    return sorted(lines, key=lambda x: STAMP.match(x).group(1))


def _iso(stamp: str) -> str:
    return f"{YEAR}-{stamp[:5]}T{stamp[6:]}{TZ}"


def build(out: Path) -> list[Path]:
    """조합 로그·코멘트·라벨셋을 out 아래에 쓰고 쓴 파일 목록을 낸다."""
    logs: dict[str, list[str]] = {}
    items = []
    for case in CASES:
        if case.get("segs"):
            logs[case["name"]] = build_log(case["segs"])
        lines = logs[case["name"]]
        item = {"key": case["key"], "logs": [f"{case['name']}.log"], "expect": case["expect"], "summary": case["summary"]}
        if case.get("fail"):
            hits = [x for x in lines if case["fail"] in x]
            assert len(hits) == 1, f"{case['key']}: 실패 줄 {case['fail']!r}이 {len(hits)}번"
            stamp = STAMP.match(hits[0]).group(1)
            item["fail_line"] = hits[0]
            item["fail_at"] = _iso(stamp)
            if not case.get("first"):
                item["occurred_at"] = _iso(stamp)[:19] + TZ     # Jira 발생 시각(초 단위)
                item["look_at"] = case.get("look") or hits[0]  # 기준 줄: 실패 줄 원문(붙여 넣은 AP 줄) 또는 IPC 이름+token
        elif case.get("occurred") is not None:
            item["occurred_at"] = _iso(_at(case["occurred"]))[:19] + TZ
        for k in ("failed_step", "sim_slot", "pair"):
            if case.get(k):
                item[k] = case[k]
        if case.get("first"):
            item["first_analysis"] = True
        if case.get("comment"):
            item["issue_file"] = f"issues/{case['key']}.yaml"
        items.append((item, case))
    written = []
    out.mkdir(parents=True, exist_ok=True)
    for name, lines in logs.items():
        path = out / f"{name}.log"
        path.write_text("\n".join([HEAD, *lines]) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    for item, case in items:
        if not case.get("comment"):
            continue
        ticket = {"key": item["key"], "fields": {"summary": item["summary"], "description": "시험 중 데이터 연결이 실패했습니다.",
                                                 "customfield_10001": item.get("occurred_at", "").replace("+09:00", "+0900"),
                                                 "customfield_10006": item.get("sim_slot", "0")},
                  "comments": [{"author": "mock.tester", "created": "2026-11-14T11:00:00+0900", "body": "로그 첨부했습니다."},
                               {"author": "mock.cp", "created": "2026-11-14T13:00:00+0900", "body": case["comment"]}]}
        path = out / item["issue_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(ticket, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
        written.append(path)
    doc = {"tz": "Asia/Seoul", "year": YEAR, "conditions": CONDITIONS, "items": [i for i, _ in items]}
    path = out / "labelset.yaml"
    path.write_text("# 생성 파일 — tests/helpers/make_accuracy_fixtures.py. 손으로 고치지 않는다.\n"
                    "# db는 적지 않는다: 시드 DB(--seed-db)를 --db로 준다. 규칙 동작 확인용 표본 안 자료(정확도 수치가 아님).\n"
                    + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8", newline="\n")
    written.append(path)
    return written


def build_seed_db(dest: Path, root: Path) -> Path:
    """시드 계획 다섯 개를 새 뼈대에 `db_add.py apply`로 적용한 이슈 DB(검증·git 없이)."""
    subprocess.run([sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(dest)], check=True, capture_output=True)
    for plan in sorted(SEEDS.glob("*/plan.json")):
        proc = subprocess.run([sys.executable, str(root / "scripts" / "db_add.py"), "apply", str(plan), "--db", str(dest),
                               "--plugin-root", str(root), "--user", "mock-user1"], capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise SystemExit(f"{plan.parent.name} 시드 적용 실패({proc.returncode}): {proc.stdout[-500:]} {proc.stderr[-500:]}")
    return dest


def run(check: bool = False) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="tt-accuracy-"))
    try:
        made = build(tmp)
        if not check:
            for p in made:
                target = OUT / p.relative_to(tmp)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, target)
            return {"written": [str(OUT / p.relative_to(tmp)) for p in made], "mismatched": [], "missing": []}
        missing = [str(p.relative_to(tmp)) for p in made if not (OUT / p.relative_to(tmp)).is_file()]
        mismatched = [str(p.relative_to(tmp)) for p in made
                      if (OUT / p.relative_to(tmp)).is_file() and (OUT / p.relative_to(tmp)).read_bytes() != p.read_bytes()]
        return {"written": [], "mismatched": mismatched, "missing": missing}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_accuracy_fixtures.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="쓰지 않고 커밋된 내용과 비교")
    parser.add_argument("--seed-db", metavar="DIR", help="시드 DB를 DIR에 만든다(비어 있거나 없는 경로)")
    args = parser.parse_args(argv)
    if args.seed_db:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import make_plugin_root
        root = make_plugin_root.make()
        try:
            print(build_seed_db(Path(args.seed_db), root))
        finally:
            shutil.rmtree(root, ignore_errors=True)
        return 0
    result = run(check=args.check)
    for p in result["missing"]:
        print(f"없음: {p}")
    for p in result["mismatched"]:
        print(f"다름: {p}")
    for p in result["written"]:
        print(p)
    return 1 if result["missing"] or result["mismatched"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
