#!/usr/bin/env python3
"""분석 정확도 기준값의 조합 로그·라벨셋(`tests/fixtures/accuracy/`)을 만든다 (분석 정확도 단계 1).

재료는 공개 근거뿐이다: 이슈 DB 시드 fixture(`templates/issue-db-seeds/android/<카테고리>/fixtures/*.log`, 합성 머리줄은 뺀다)의
줄과 합성 벤더 IPC 줄(`VIPC_` 꼴 — `common/ipcseq.py`의 기본 trace가 읽는 모양, 태그 `RIL`). 조각(segment)마다 첫 줄을
정한 시각으로 옮기고(조각 안 간격은 그대로) 이어 붙인다. 결정적이다.

만드는 것(커밋한다 — 이 스크립트는 다시 만들 때와 `--check`로 비교할 때 쓴다):
- `<사례>.log`: 조합 로그
- `labelset.yaml`: `tools/offline_eval.py` 라벨셋(조건별 실행 `conditions`, 정답 `expect`, 정답 실패 줄 `fail_line`·`fail_at`,
  기준 줄 `look_at`). 정답이 의도와 다르게 나와도 사례를 맞추지 않는다 — 지금 코드의 출력은 `baseline.json`이 기록한다.
- `problems/<KEY>.json`: 문제 파악 결과의 **정답 입력**(라벨에서 손으로 쓴 problem.json 모양 — 모델 출력 아님, 단계 5-2 조건
  `problem`·`look_at+problem`의 "정답 입력일 때의 상한"). 입력 해시(`source_sha256`)는 `offline_eval.py`가 실행 때 찍는다.
- `y10/<사례>.log`·`y10/y10.json`: 자격 검사 합성 6건(단계 5)과 기준·기대 결과 — 라벨셋 밖, `tests/test_eligibility.py`가 돈다
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
CONDITIONS = ["no_time", "time", "look_at", "problem", "look_at+problem"]
NOT_GENERATED = {"baseline.json"}     # 이 폴더에 있지만 생성기가 만들지 않는 것(tests/test_accuracy_baseline.py --update)


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
    # 단계 5 새 양성(자격 검사가 채택해야 할 것, 시제품 11/19): token 점(응답 뒤 2초 안 DATA-003) · 이름만(요청 하나 = REQ·RSP 한 곳) ·
    # AP 줄 인용(실패 줄이 아님 — problem.json 없는 5-1은 근처 보류, 5-2 문제 파악 유형이면 채택) · 코멘트 단서만(기준 줄 없음 — 5-2)
    {"name": "tokpos", "key": "TOKPOS-1",
     "segs": [(M, minute(0)), (OK, minute(1), "0x0dd", "VIPC_E_OK"), (F, minute(2), "0x0e1"), (M, minute(3))],
     "expect": "DATA-003-01", "fail": "onDataNetworkSetupDataFailed:", "look": "VIPC_SETUP_DATA (token=0x0e1)",
     "summary": "데이터 연결 실패", "comment": "CP 확인: VIPC_SETUP_DATA (token=0x0e1) 에서 실패했습니다."},
    {"name": "tokonlypos", "key": "TOKONLYPOS-1", "segs": [(M, minute(0)), (F, minute(2), "0x0e2"), (M, minute(3))],
     "expect": "DATA-003-01", "fail": "onDataNetworkSetupDataFailed:", "look": "VIPC_SETUP_DATA", "summary": "데이터 연결 실패",
     "comment": "CP 확인: VIPC_SETUP_DATA 실패입니다."},
    {"name": "nearpos", "key": "NEARPOS-1", "segs": [(M, minute(0)), (OFF, minute(0.5)), (F, minute(2)), (M, minute(3))],
     "expect": "DATA-003-01", "fail": "onDataNetworkSetupDataFailed:",
     "look": "ConnectingState: setupData: accessNetwork=EUTRAN, isSatellite=false", "summary": "데이터 연결 실패"},
    {"name": "cluepos", "key": "CLUEPOS-1", "segs": [(M, minute(0)), (F, minute(2), "0x0e3"), (OK, minute(3), "0x0e4", "VIPC_E_OK")],
     "expect": "DATA-003-01", "fail": "onDataNetworkSetupDataFailed:", "no_look": True, "summary": "데이터 연결 실패",
     "comment": "CP 확인: VIPC_SETUP_DATA (token=0x0e3) 실패입니다."},
]
# 문제 파악 정답 입력(시제품 11/19 `problems/`와 같은 값): 키 → (증상 유형, 단서 [(코멘트 번호, 종류, 이름, token, stale)]).
# 단서 인용(quote)은 그 사례 코멘트 글. RETEST·RETESTX의 단서는 앞 회차 코멘트(stale) — 자격 검사가 쓰지 않아야 한다.
_D3, _N1 = ["DATA-003"], ["NETWORK-001"]
PROBLEMS = {
    "MMX-1": (_D3, []), "XM-1": (_D3, []), "MXM-1": (_D3, []), "MMH-1": (_N1, []), "CTLM-1": (_N1, []),
    "D12R-1": (["DATA-002"], []), "C15-1": (["CALL-001"], []), "HAL-1": (_N1, []), "TC-1": (_D3, []), "RECOVER-1": (_D3, []),
    "TOKSAME-1": (_D3, [(2, "ipc", "VIPC_SETUP_DATA", "0x0de", False)]),
    "TOKNAME-1": (_D3, [(2, "ipc", "VIPC_PDN_CONNECT", "0x0de", False)]),
    "TOKONLY-1": (_D3, [(2, "ipc_name", "VIPC_SETUP_DATA", None, False)]),
    "DUAL-1": (_D3, [(2, "ipc", "VIPC_SETUP_DATA", "0x0de", False)]),
    "RETEST-1": (_D3, [(2, "ipc", "VIPC_SETUP_DATA", "0x0de", True)]),
    "RETESTX-1": (_D3, [(2, "ipc", "VIPC_SETUP_DATA", "0x0de", True)]),
    "PAIRFAIL-1": (_D3, []), "PAIRPASS-1": (_D3, []), "FIRSTTC-1": (_D3, []), "FIRSTH-1": (_N1, []),
    "TOKPOS-1": (_D3, [(2, "ipc", "VIPC_SETUP_DATA", "0x0e1", False)]),
    "TOKONLYPOS-1": (_D3, [(2, "ipc_name", "VIPC_SETUP_DATA", None, False)]),
    "NEARPOS-1": (_D3, []),
    "CLUEPOS-1": (_D3, [(2, "ipc", "VIPC_SETUP_DATA", "0x0e3", False)]),
}


def problem_doc(case: dict) -> dict:
    """정답 입력 problem.json(`triagelib/problem.py` 결과 모양 중 자격 검사가 읽는 칸 + 출처 표시)."""
    types, clues = PROBLEMS[case["key"]]
    return {"schema_version": 1, "key": case["key"], "origin": "정답 입력",
            "symptom": {"text": case["summary"], "types": types, "not_in_db": not types},
            "clues": [{"comment": n, "kind": kind, "name": name, "token": token, "quote": case["comment"], "side": "cp",
                       "stale": stale} for n, kind, name, token, stale in clues]}


AUTH = "data/fixtures/data-setup-auth-failure.log"
DROP = "call/fixtures/drop-airplane.log"


def _shift(lines: list[str], needle: str, sec: float) -> list[str]:
    """needle이 든 줄의 시각을 sec초 옮긴다(원인 근거를 사건 뒤로)."""
    out = []
    for x in lines:
        if needle in x:
            t = STAMP.match(x)
            x = (datetime.strptime(f"{YEAR}-{t.group(1)}", "%Y-%m-%d %H:%M:%S.%f") + timedelta(seconds=sec)).strftime(
                "%m-%d %H:%M:%S.%f")[:-3] + t.group(2)
        out.append(x)
    return sorted(out, key=lambda x: STAMP.match(x).group(1))


def _rename(lines: list[str], serial: str, dn: str) -> list[str]:
    """다른 요청으로: RIL serial·DataNetwork 이름만 바꾼다."""
    return [x.replace("[0410]", f"[{serial}]").replace("DN-120-C", dn) for x in lines]


def _retimed(lines: list[str], needle: str, starts: list[float]) -> list[str]:
    """needle이 든 첫 줄을 starts 시각마다 한 줄씩(시각만 바꾼 사본)."""
    tail = STAMP.match(next(x for x in lines if needle in x)).group(2)
    return [_at(s) + tail for s in starts]


TOKPOS = [(M, minute(0)), (OK, minute(1), "0x0dd", "VIPC_E_OK"), (F, minute(2), "0x0e1"), (M, minute(3))]


def _first_fail_logs() -> dict[str, list[str]]:
    """R1(첫 세는 실패) 기준값 사례: 음성 — 기준 IPC 요청이 DB에 없는 오류(RILJ `error 2`)로 실패하고 0.9초 뒤 다른 요청(serial
    0411·token 0x0df)이 인증 실패(DATA-003-02, 슬롯 없는 DN 줄)로 실패(`cp-typeless`, 듀얼 SIM 변형 `cp-dualsim` — X는 SIM2, IPC 줄은
    슬롯 없음). 양성 — tokpos 변형: RILJ `error 44` 응답 바로 뒤 DNC 실패(`tp-rerr`, 흡수), 평가 줄 "Data disallowed"가 실패 앞뒤에
    (`tp-eval`, 추출기 파생 이벤트는 세지 않음), 벤더 완료 줄 `OnIpcComplete … result=2`(`tp-vrf`, 벤더 IPC 이벤트는 세지 않음)."""
    t2 = minute(2)
    auth = _rename(segment(AUTH, t2 + 0.9, "0x0df"), "0411", "DN-121-C")
    x1 = [x.replace("[PHONE0]", "[PHONE1]") for x in segment("X", t2, "0x0de")]
    tok = build_log(TOKPOS)
    now = [x.startswith(_at(t2)[:11]) for x in tok]     # 10:02 실패 조각 줄만 바꾼다
    rerr = [x[:18] + "  2101  2141 D RILJ    : [0410]< SETUP_DATA_CALL error 44 [PHONE0]" if n and "< SETUP_DATA_CALL" in x
            else x.replace("resultCode=RESULT_SUCCESS", "resultCode=RESULT_ERROR_ILLEGAL_STATE") if n else x
            for x, n in zip(tok, now)]
    ok = segment(OK, minute(1))
    ev = _retimed(ok, "Data disallowed reasons", [t2 + 0.002, t2 + 0.700]) + _retimed(ok, "Data allowed reason", [t2 + 0.003])
    vrf = [f"{_at(t2 + 0.596)}   900   910 D RIL     : [IpcCtx_0] OnIpcComplete Request ID=17, result=2"]
    srt = lambda lines: sorted(lines, key=lambda x: STAMP.match(x).group(1))  # noqa: E731
    return {"cp-typeless": srt(segment(M, minute(0)) + segment("X", t2, "0x0de") + auth),
            "cp-dualsim": srt(segment(M, minute(0)) + x1 + auth),
            "tp-rerr": rerr, "tp-eval": srt(tok + ev), "tp-vrf": srt(tok + vrf)}


CASES += [
    {"name": "cp-typeless", "key": "CPX-1", "expect": "unresolved", "fail": "token=0x0de, len=8, Error(VIPC_E_DEMO_FAILURE)",
     "look": "VIPC_SETUP_DATA (token=0x0de)", "summary": "데이터 연결 실패"},
    {"name": "cp-dualsim", "key": "CPXD-1", "expect": "unresolved", "fail": "token=0x0de, len=8, Error(VIPC_E_DEMO_FAILURE)",
     "look": "VIPC_SETUP_DATA (token=0x0de)", "summary": "SIM2 데이터 연결 실패"},
    {"name": "tp-rerr", "key": "TPRERR-1", "expect": "DATA-003-01", "fail": "onDataNetworkSetupDataFailed:",
     "look": "VIPC_SETUP_DATA (token=0x0e1)", "summary": "데이터 연결 실패"},
    {"name": "tp-eval", "key": "TPEVAL-1", "expect": "DATA-003-01", "fail": "onDataNetworkSetupDataFailed:",
     "look": "VIPC_SETUP_DATA (token=0x0e1)", "summary": "데이터 연결 실패"},
    {"name": "tp-vrf", "key": "TPVRF-1", "expect": "DATA-003-01", "fail": "onDataNetworkSetupDataFailed:",
     "look": "VIPC_SETUP_DATA (token=0x0e1)", "summary": "데이터 연결 실패"},
]


def y10_cases() -> list[tuple[str, list[str], dict]]:
    """자격 검사 합성 6건(Y10, 시제품 11/19) `(이름, 로그 줄, {ref, expect})`. ref = ["text", 기준 줄] | ["range", START초, FAIL초]
    (로그 FAIL 마커 구간, 11-14 00:00 기준). expect = [state, reason, 채택이면 원인·보류면 check.why] — problem.json 없는 5-1 기준
    (RECOVER는 5-2가 문제 파악 유형을 읽으면 symptom_not_found/no_allowed_event_near로 바뀐다)."""
    drop = [x for x in segment(DROP, minute(5)) if "DIALING -> ACTIVE" not in x]     # 짧은 로그(< 창 10초)
    return [
        ("Y10-LOGEND", drop, {"ref": ["text", "Call: setState ACTIVE -> DISCONNECTED"],
                              "expect": ["held", "ineligible", "absence_unverified"]}),
        ("Y10-RECOVER", build_log([(F, minute(2)), (OK, minute(2.5))]),
         {"ref": ["text", "Internet data state changed from DISCONNECTED to CONNECTED."],
          "expect": ["held", "ineligible", "near_without_symptom"]}),
        ("Y10-SAMETOKEN", build_log([(OK, minute(1), "0x0e5", "VIPC_E_OK"), (F, minute(2), "0x0e5")]),
         {"ref": ["text", "VIPC_SETUP_DATA (token=0x0e5)"], "expect": ["held", "ambiguous", "locations"]}),
        ("Y10-SAMECAUSE", build_log([(M, minute(0)), (F, minute(2)), (F, minute(2.5))]),
         {"ref": ["range", minute(1.5), minute(3)], "expect": ["accepted", "anchored_top", "DATA-003-01"]}),
        ("Y10-DIFFCAUSE", build_log([(M, minute(0)), (F, minute(2)), (AUTH, minute(2.5))]),
         {"ref": ["range", minute(1.5), minute(3)], "expect": ["held", "ambiguous", "multiple_events"]}),
        ("Y10-AFTER", _shift(segment(M, minute(1)), "setRadioPower power false", 0.6),
         {"ref": ["text", "pollStateDone: hasRegistered = false hasDeregistered = true"],
          "expect": ["held", "cause_unconfirmed", "cause_after_event"]}),
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
    built = _first_fail_logs()
    for case in CASES:
        if case.get("segs"):
            logs[case["name"]] = build_log(case["segs"])
        elif case["name"] in built:
            logs[case["name"]] = built[case["name"]]
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
            if not case.get("first") and not case.get("no_look"):
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
        if case["key"] in PROBLEMS:
            item["problem"] = f"problems/{case['key']}.json"
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
    for item, case in items:
        if item.get("problem"):
            path = out / item["problem"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(problem_doc(case), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
            written.append(path)
    y10 = {}
    for name, lines, spec in y10_cases():      # 자격 검사 합성 6건: 라벨셋 밖(tests/test_eligibility.py가 기준을 직접 넘겨 돈다)
        path = out / "y10" / f"{name}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([HEAD, *lines]) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
        y10[name] = spec
    path = out / "y10" / "y10.json"
    path.write_text(json.dumps(y10, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
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
        # 남은 옛 파일(사례를 지웠는데 남은 로그·코멘트): 폴더의 파일 = 만든 파일 + 생성 대상이 아닌 기준값 스냅샷
        made_rel = {p.relative_to(tmp).as_posix() for p in made}
        stale = sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file()
                       and p.relative_to(OUT).as_posix() not in made_rel | NOT_GENERATED)
        return {"written": [], "mismatched": mismatched + [f"{x} (만든 목록에 없음)" for x in stale], "missing": missing}
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
