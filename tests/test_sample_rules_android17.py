#!/usr/bin/env python3
"""샘플 DB 규칙의 Android 17 줄 모양 (결정 3·5, 2차 B 수정).

줄은 에뮬레이터(API 37) 캡처를 마스킹한 것(`# 캡처`)과 17 소스 문구로 만든 것(`# 소스`)이다. 캡처 줄은
threadtime(연도·uid 없음)으로 옮겼고, 망 이름이 든 꼬리는 잘랐다. 각 줄을 reference 백엔드로 읽어
샘플 `parser-rules`(태그 수집 → 마스킹 → extractor)를 거친 이벤트를 본다. 옛 규칙(17 이전 문구)으로는
아래 양성 줄이 모두 이벤트를 내지 못한다.

`pytest tests/test_sample_rules_android17.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import parse_logcat  # noqa: E402
from common import masking, parser_rules  # noqa: E402
from parser_backends import reference  # noqa: E402

RULES = REPO / "tests" / "fixtures" / "issue-db-sample" / "parser-rules"
APN = "<APN#1>"
DIAL = ("[0] useImsForCall=false, useOnlyDialedSimEccList=false, isEmergency=false, useImsForEmergency=false, "
        "useImsForUt=false, isUt={ut}, isSuppServiceCode=false, isPotentialUssdCode={ussd}, isWpsCall=false, "
        "allowWpsOverIms=true, imsPhone=Handler (com.android.internal.telephony.imsphone.ImsPhone) {{f8179f4}}, "
        "imsPhone.isVoiceOverCellularImsEnabled()=false, imsPhone.isVowifiEnabled()=false, "
        "imsPhone.isVideoEnabled()=false, imsPhone.getServiceState().getState()=1")
NRM = ("onRequestNetworkRegistrationInfoComplete result: 0, info: NetworkRegistrationInfo{{ domain={d} "
       "transportType=WWAN registrationState={s} networkRegistrationState={s} roamingType=NOT_ROAMING "
       "accessNetworkTechnology=NR rejectCause=0 emergencyEnabled=false availableServices=[]")
POLL = ("pollStateDone: hasRegistered = {r} hasDeregistered = {d} hasDataAttached = {{1=false, 2=false}} "
        "hasDataDetached = {{1=true, 2=false}} hasDataRegStateChanged = {{1=true, 2=false}}")

# (태그, 메시지, 기대 이벤트, 기대 필드 | None = 이벤트 없음)
CASES = [
    # 캡처 c04r-mo-accept
    ("UiccController", "Broadcasting intent ACTION_SIM_STATE_CHANGED READY reason null for phone: 0 sub: 1",
     "sim_state_changed", {"state": "READY"}),
    # 캡처 c04r-mo-accept / c11r-ussd-mmi(isUt=true: USSD·MMI 경로, 발신 아님)
    ("GsmCdmaPhone", DIAL.format(ut="false", ussd="false"), "ims_dial_attempt", {"ims": "false", "ims_state": "1"}),
    ("GsmCdmaPhone", DIAL.format(ut="true", ussd="true"), "ims_dial_attempt", None),
    # 캡처 d04r-denied (에뮬레이터는 DENIED에 rejectCause=0)
    ("NRM-C-0", NRM.format(d="PS", s="DENIED"), "network_registration_rejected", {"cause": "0", "domain": "PS"}),
    ("NRM-C-0", NRM.format(d="PS", s="NOT_REG_OR_SEARCHING"), "network_registration_rejected", None),
    # 캡처 d04r-denied(해제·등록) / c04r-mo-accept(바뀐 것 없음)
    ("SST-0", POLL.format(r="false", d="true"), "network_service_state", {"registered": "false", "deregistered": "true"}),
    ("SST-0", POLL.format(r="true", d="false"), "network_service_state", {"registered": "true", "deregistered": "false"}),
    ("SST-0", POLL.format(r="false", d="false"), "network_service_state", None),
    # 소스 RIL.java·LastCallFailCause.java (옛 모양도 맞는다)
    ("RILJ", "[0078]< LAST_CALL_FAIL_CAUSE com.android.internal.telephony.LastCallFailCause@5d3c2a1 causeCode: 17 "
     "vendorCause: null [PHONE0]", "call_fail_cause", {"cause": "17"}),
    ("RILJ", "[0078]< LAST_CALL_FAIL_CAUSE causeCode=17 [PHONE0]", "call_fail_cause", {"cause": "17"}),
    # 소스 UiccController.java — 예외 이름은 Rlog가 다음 줄에 찍는다(메시지는 "error"로 끝난다)
    ("UiccController", "Error getting ICC status. RIL_REQUEST_GET_ICC_STATUS should never return an error",
     "uicc_card_status_error", {}),
    # 소스 ImsPhone.java
    ("ImsPhone", "[0] handleImsRegistered: onImsMmTelConnected imsTransportType=WWAN", "ims_registered",
     {"transport": "WWAN"}),
    ("ImsPhone", "[0] handleImsUnregistered: onImsMmTelDisconnected imsReasonInfo=ImsReasonInfo :: "
     "{1000 : CODE_REGISTRATION_ERROR, 403, Forbidden}, suggestedAction=0, disconnectedRadioTech=0",
     "ims_registration_failed", {"code": "1000", "reason": "CODE_REGISTRATION_ERROR", "extra": "403"}),
    # 소스 ImsSmsDispatcher.java
    ("ImsSmsDispatcher [0]", "sendSms failed. Falling back to PSTN. Error: SMS_FORMAT_NOT_SUPPORTED",
     "sms_send_failed", {"result": "SMS_FORMAT_NOT_SUPPORTED"}),
    # 캡처 c04r-mo-accept(성공) / d31-enterprise-request(실패: 모뎀 cause는 이 줄에만)
    ("DN-100-C", "ConnectingState: onSetupResponse: resultCode=RESULT_SUCCESS, response=DataCallResponse: { cause=NONE(0x0) "
     "retry=-1 cid=27 linkStatus=2 protocolType=0 ifname=eth0", "data_setup_response",
     {"result": "RESULT_SUCCESS", "cause": "NONE"}),
    ("DN-133-C", "ConnectingState: onSetupResponse: resultCode=RESULT_ERROR_ILLEGAL_STATE, response=DataCallResponse: "
     "{ cause=MISSING_UNKNOWN_APN(0x1b) retry=10000 cid=-1 linkStatus=0", "data_setup_response",
     {"result": "RESULT_ERROR_ILLEGAL_STATE", "cause": "MISSING_UNKNOWN_APN"}),
    # 캡처 d31-eims-request
    ("DRM-0", "Scheduled data retry [DataSetupRetryEntry: delay=1000ms, retry time:17:04:04.749, null, transport=WWAN, "
     "retry type=BY_NETWORK_REQUESTS", "data_retry_scheduled", {"kind": "Setup", "delay": "1000"}),
    # 캡처 c15r-call-in-airplane(로컬 해제) / d20h-nw-radio-hal-kill(끊김: tearDownReason=NONE)
    ("DNC-0", f"onDataNetworkDisconnected: [DataNetwork: DN-100-C, {APN}, state=null], cause=LOST_CONNECTION(0x10004)(65540), "
     "tearDownReason=AIRPLANE_MODE_ON", "data_network_disconnected", {"cause": "LOST_CONNECTION", "reason": "AIRPLANE_MODE_ON"}),
    ("DNC-0", f"onDataNetworkDisconnected: [DataNetwork: DN-106-C, {APN}, state=null], cause=RADIO_NOT_AVAILABLE(0x10001)(65537), "
     "tearDownReason=NONE", "data_network_disconnected", {"cause": "RADIO_NOT_AVAILABLE", "reason": "NONE"}),
]


def _events(tag: str, msg: str) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="tt-a17-") as tmp:
        log = Path(tmp) / "one.log"
        log.write_text(f"11-10 23:02:17.214  2005  2005 D {tag}: {msg}\n", encoding="utf-8", newline="\n")
        raw = reference.BACKEND.parse([log], "UTC", 2026, None)
    text = f"{tag}: {msg}"
    return parse_logcat.postprocess(raw, parser_rules.load(RULES), masker=masking.new_masker(text, (), log_lines=True))


@pytest.mark.parametrize("tag,msg,event,fields", CASES, ids=[f"{c[2]}-{i}" for i, c in enumerate(CASES)])
def test_extractor_on_android17_line(tag, msg, event, fields) -> None:
    got = [e for e in _events(tag, msg) if e["event"] == event]
    if fields is None:
        assert got == [], got
    else:
        assert len(got) == 1, (tag, msg)
        assert got[0]["fields"] == fields


def test_removed_and_tag_rules() -> None:
    rules = parser_rules.load(RULES)
    assert "smsc-address-missing" not in {ex.id for ex in rules.extractors}   # 17 발신 경로는 SMSC를 찍지 않는다
    assert rules.tag_category("UiccSlot [0]") == rules.tag_category("UiccSlot") == "sim"   # 캡처 d20h-nw-radio-hal-kill
    assert rules.tag_category("GsmInboundSmsHandler") == "sms"                            # 캡처 x01r-mt
    assert rules.tag_category("InboundSmsHandler") is None                                # 17에 없는 태그
    assert rules.tag_category("GsmCdmaPhone") == "call"                                   # useImsForCall= 줄의 태그


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
