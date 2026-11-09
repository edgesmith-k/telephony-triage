"""벤더 RIL IPC 결과 줄 → builtin 이벤트 (H C1+D R12, 두 플랫폼 공통·순수 함수).

벤더 RIL 줄 모양 둘(oFono `exynos-ril`, Android `RIL` 태그)을 이벤트로 바꾼다. 이름·모양은 placeholder이며
사내 RIL 버전에 따라 사내에서 조정한다(TODO(SITE:S9)).

| 줄 모양 | 이벤트 | fields |
|---|---|---|
| `[<장치>][RX] SIT_<X>, RSP, … Error(RCM_E_<Y>)` (`RCM_E_SUCCESS`는 뺀다) | `builtin.common.vendor_ipc_error` | `ipc`, `error` |
| `[RilContext_<n>] OnRequestComplete Request ID=<id>, result=<n≠0>` | `builtin.common.vendor_request_failed` | `request_id`, `result` |

배선(어느 태그·데몬의 줄에 부르는지)은 플랫폼 백엔드가 한다(oFono는 구성요소 설정 `vendor_ipc: true`인 ident, Android `VENDOR_IPC_TAGS = {"RIL"}`;
이슈 DB tags.yaml에 `ipc: vendor`가 하나라도 있으면 그 태그만 — 백엔드 `apply_rules`, 04-parser-matching §5.8 (2)).
값은 글(str)이다. 이 모듈은 태그 카테고리(tags.yaml 수집 여부)에 기대지 않는다 — 태그가 수집 대상이 아니어도 같은 이벤트가 나온다.
"""

from __future__ import annotations

import re

IPC_ERROR = "builtin.common.vendor_ipc_error"
REQUEST_FAILED = "builtin.common.vendor_request_failed"
EVENTS = (IPC_ERROR, REQUEST_FAILED)

IPC_ERROR_RE = re.compile(r"\[(?:RX|TX)\]\s*(?P<ipc>SIT_[A-Z0-9_]+)\s*,\s*RSP\b.*?\bError\(\s*(?P<error>RCM_E_[A-Z0-9_]+)\s*\)")
REQUEST_RE = re.compile(r"\[RilContext_\d+\]\s*OnRequestComplete\b.*?\bRequest ID\s*=\s*(?P<request_id>\d+)\s*,\s*"
                        r"result\s*=\s*(?P<result>-?\d+)\b")
SUCCESS = "RCM_E_SUCCESS"


def detect(msg: str) -> list[tuple[str, dict]]:
    """메시지 한 줄 → `[(이벤트 이름, fields)]`(없으면 빈 목록)."""
    out: list[tuple[str, dict]] = []
    if not msg:
        return out
    m = IPC_ERROR_RE.search(msg)
    if m and m.group("error") != SUCCESS:
        out.append((IPC_ERROR, {"ipc": m.group("ipc"), "error": m.group("error")}))
    m = REQUEST_RE.search(msg)
    if m and int(m.group("result")) != 0:
        out.append((REQUEST_FAILED, {"request_id": m.group("request_id"), "result": m.group("result")}))
    return out
