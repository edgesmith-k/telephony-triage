"""`common/vendor_ipc.py`(벤더 RIL IPC 결과 → builtin 이벤트, H C1+D R12): 실제 모양을 본뜬 합성 줄과 반례.

배선(oFono 구성요소 `vendor_ipc: true`, Android `RIL`)은 각 백엔드 시험이 본다. `pytest tests/test_vendor_ipc.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import vendor_ipc as vi


def test_ipc_error_rsp():
    msg = "[<DEV#1>][RX] VIPC_DEMO_QUERY, RSP, token=0x0012, len=12, Error(VIPC_E_DEMO_FAILURE)"
    assert vi.detect(msg) == [("builtin.common.vendor_ipc_error",
                               {"ipc": "VIPC_DEMO_QUERY", "error": "VIPC_E_DEMO_FAILURE"})]
    tx = "[<DEV#1>][TX] VIPC_DIAL, RSP, Error( VIPC_E_NO_SUCH_ELEMENT )"
    assert vi.detect(tx) == [(vi.IPC_ERROR, {"ipc": "VIPC_DIAL", "error": "VIPC_E_NO_SUCH_ELEMENT"})]


def test_ipc_success_and_non_rsp_are_not_events():
    assert vi.detect("[<DEV#1>][RX] VIPC_DEMO_QUERY, RSP, token=0x0012, Error(VIPC_OK)") == []
    assert vi.detect("[<DEV#1>][RX] VIPC_DEMO_NOTICE, IND, len=8") == []
    assert vi.detect("[<DEV#1>][TX] VIPC_DEMO_QUERY, REQ, token=0x0012") == []
    assert vi.detect("Error(VIPC_E_DEMO_FAILURE) without channel") == []
    assert vi.detect("") == [] and vi.detect(None) == []


def test_request_complete_result():
    msg = "[IpcCtx_0] OnIpcComplete Request ID=27, result=2"
    assert vi.detect(msg) == [("builtin.common.vendor_request_failed", {"request_id": "27", "result": "2"})]
    assert vi.detect("[IpcCtx_1] OnIpcComplete Request ID=27, result=0") == []
    assert vi.detect("[IpcCtx_1] OnIpcComplete Request ID=27, result=-1")[0][1]["result"] == "-1"
    assert vi.detect("[IpcCtx_1] OnIpcComplete Request ID=27, result=10x") == []


def test_both_shapes_on_one_line_and_event_names():
    msg = ("[IpcCtx_0] OnIpcComplete Request ID=3, result=1 "
           "[<DEV#1>][RX] VIPC_SIM_IO, RSP, Error(VIPC_E_DEMO_FAILURE)")
    assert [e for e, _ in vi.detect(msg)] == [vi.IPC_ERROR, vi.REQUEST_FAILED]
    assert vi.EVENTS == ("builtin.common.vendor_ipc_error", "builtin.common.vendor_request_failed")
    assert all(e.split(".")[:2] == ["builtin", "common"] for e in vi.EVENTS)


def test_spec_injection():
    """요청 완료 줄의 문맥 접두어·완료 낱말은 spec(site-defaults `platform.vendor_ipc`·`platform.others.<p>.vendor_ipc`)에서 온다. 기본은 placeholder."""
    spec = vi.Spec(context="SiteCtx_", complete="SiteDone")
    line = "[SiteCtx_2] SiteDone Request ID=5, result=3"
    assert vi.detect(line, spec) == [(vi.REQUEST_FAILED, {"request_id": "5", "result": "3"})]
    assert vi.detect(line) == []                                                   # 기본 spec은 사내 토큰을 모른다
    assert vi.detect("[IpcCtx_0] OnIpcComplete Request ID=5, result=3", spec) == []
    assert vi.detect("[SiteCtx_2] SiteDoneX Request ID=5, result=3", spec) == []   # 완료 낱말은 낱말 경계까지
    assert vi.detect("[SiteCtx_2] SiteDone Request ID=5, result=0", spec) == []
    err = "[<DEV#1>][RX] VIPC_DIAL, RSP, Error(VIPC_E_DEMO_FAILURE)"
    assert vi.detect(err, spec) == vi.detect(err) and len(vi.detect(err)) == 1          # 오류 줄 토큰은 따로(기본 그대로)
    assert vi.DEFAULT == vi.Spec() and (vi.DEFAULT.context, vi.DEFAULT.complete) == ("IpcCtx_", "OnIpcComplete")
    assert vi.KEYS == ("context", "complete", "request_prefix", "error_prefix", "success")


def test_error_line_tokens_from_spec():
    """IPC 오류 줄의 메시지 이름 접두어·결과 값 접두어·성공 값도 spec에서 온다(기본 placeholder `VIPC_`·`VIPC_E_`·`VIPC_OK`).
    사내 값을 넣으면 placeholder 줄은 잡지 않는다."""
    spec = vi.Spec(request_prefix="SMSG_", error_prefix="SRES_", success="SRES_DONE")
    line = "[<DEV#1>][RX] SMSG_DIAL, RSP, token=0x1, Error(SRES_BUSY)"
    assert vi.detect(line, spec) == [(vi.IPC_ERROR, {"ipc": "SMSG_DIAL", "error": "SRES_BUSY"})]
    assert vi.detect(line) == []                                                     # 기본 spec은 사내 접두어를 모른다
    assert vi.detect("[<DEV#1>][RX] SMSG_DIAL, RSP, Error(SRES_DONE)", spec) == []   # 사내 성공 값은 이벤트가 아님
    assert vi.detect("[<DEV#1>][RX] SMSG_DIAL, RSP, Error(VIPC_OK)", spec) == []     # 접두어가 다르면 오류 줄이 아님
    assert vi.detect("[<DEV#1>][RX] VIPC_DIAL, RSP, Error(VIPC_E_X)", spec) == []
    assert (vi.DEFAULT.request_prefix, vi.DEFAULT.error_prefix, vi.DEFAULT.success) == ("VIPC_", "VIPC_E_", "VIPC_OK")
