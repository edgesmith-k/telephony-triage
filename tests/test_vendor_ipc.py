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
    msg = "[<DEV#1>][RX] SIT_DEMO_QUERY, RSP, token=0x0012, len=12, Error(RCM_E_DEMO_FAILURE)"
    assert vi.detect(msg) == [("builtin.common.vendor_ipc_error",
                               {"ipc": "SIT_DEMO_QUERY", "error": "RCM_E_DEMO_FAILURE"})]
    tx = "[<DEV#1>][TX] SIT_DIAL, RSP, Error( RCM_E_NO_SUCH_ELEMENT )"
    assert vi.detect(tx) == [(vi.IPC_ERROR, {"ipc": "SIT_DIAL", "error": "RCM_E_NO_SUCH_ELEMENT"})]


def test_ipc_success_and_non_rsp_are_not_events():
    assert vi.detect("[<DEV#1>][RX] SIT_DEMO_QUERY, RSP, token=0x0012, Error(RCM_E_SUCCESS)") == []
    assert vi.detect("[<DEV#1>][RX] SIT_DEMO_NOTICE, IND, len=8") == []
    assert vi.detect("[<DEV#1>][TX] SIT_DEMO_QUERY, REQ, token=0x0012") == []
    assert vi.detect("Error(RCM_E_DEMO_FAILURE) without channel") == []
    assert vi.detect("") == [] and vi.detect(None) == []


def test_request_complete_result():
    msg = "[IpcCtx_0] OnIpcComplete Request ID=27, result=2"
    assert vi.detect(msg) == [("builtin.common.vendor_request_failed", {"request_id": "27", "result": "2"})]
    assert vi.detect("[IpcCtx_1] OnIpcComplete Request ID=27, result=0") == []
    assert vi.detect("[IpcCtx_1] OnIpcComplete Request ID=27, result=-1")[0][1]["result"] == "-1"
    assert vi.detect("[IpcCtx_1] OnIpcComplete Request ID=27, result=10x") == []


def test_both_shapes_on_one_line_and_event_names():
    msg = ("[IpcCtx_0] OnIpcComplete Request ID=3, result=1 "
           "[<DEV#1>][RX] SIT_SIM_IO, RSP, Error(RCM_E_DEMO_FAILURE)")
    assert [e for e, _ in vi.detect(msg)] == [vi.IPC_ERROR, vi.REQUEST_FAILED]
    assert vi.EVENTS == ("builtin.common.vendor_ipc_error", "builtin.common.vendor_request_failed")
    assert all(e.split(".")[:2] == ["builtin", "common"] for e in vi.EVENTS)


def test_spec_injection():
    """요청 완료 줄의 문맥 접두어·완료 낱말은 spec(site-defaults `platform.vendor_ipc`·`platform.others.<p>.vendor_ipc`)에서 온다. 기본은 placeholder.
    IPC 오류 줄 모양은 spec과 무관하다."""
    spec = vi.Spec(context="SiteCtx_", complete="SiteDone")
    line = "[SiteCtx_2] SiteDone Request ID=5, result=3"
    assert vi.detect(line, spec) == [(vi.REQUEST_FAILED, {"request_id": "5", "result": "3"})]
    assert vi.detect(line) == []                                                   # 기본 spec은 사내 토큰을 모른다
    assert vi.detect("[IpcCtx_0] OnIpcComplete Request ID=5, result=3", spec) == []
    assert vi.detect("[SiteCtx_2] SiteDoneX Request ID=5, result=3", spec) == []   # 완료 낱말은 낱말 경계까지
    assert vi.detect("[SiteCtx_2] SiteDone Request ID=5, result=0", spec) == []
    err = "[<DEV#1>][RX] SIT_DIAL, RSP, Error(RCM_E_DEMO_FAILURE)"
    assert vi.detect(err, spec) == vi.detect(err) and len(vi.detect(err)) == 1
    assert vi.DEFAULT == vi.Spec() and (vi.DEFAULT.context, vi.DEFAULT.complete) == ("IpcCtx_", "OnIpcComplete")
    assert vi.KEYS == ("context", "complete")
