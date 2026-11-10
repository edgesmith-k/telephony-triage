"""벤더 RIL IPC 결과 줄 → builtin 이벤트 (H C1+D R12, 두 플랫폼 공통·순수 함수).

벤더 RIL 줄 모양 둘(oFono 벤더 RIL 데몬 `vrild`, Android `RIL` 태그)을 이벤트로 바꾼다. 이름·모양은 placeholder이며
사내 RIL 버전에 따라 사내에서 조정한다(TODO(SITE:S9)).

| 줄 모양 | 이벤트 | fields |
|---|---|---|
| `[<장치>][RX] <request_prefix><X>, RSP, … Error(<error_prefix><Y>)` (`<success>`는 뺀다) | `builtin.common.vendor_ipc_error` | `ipc`, `error` |
| `[<context><n>] <complete> Request ID=<id>, result=<n≠0>` | `builtin.common.vendor_request_failed` | `request_id`, `result` |

다섯 토큰(`context`·`complete`·`request_prefix`·`error_prefix`·`success`)은 site-defaults `platform.vendor_ipc`(기본 플랫폼)·
`platform.others.<p>.vendor_ipc`(`Spec`, 17-platforms §9-1)에서 온다. 기본은 누가 봐도 지어낸 placeholder
(`IpcCtx_`·`OnIpcComplete`·`VIPC_`·`VIPC_E_`·`VIPC_E_OK`)라 사내 줄은 사내 설정이 있어야 잡힌다(TODO(SITE:S9)).
백엔드 `configure(profile)`가 spec을 들고 `detect(msg, spec)`에 넘긴다.

배선(어느 태그·데몬의 줄에 부르는지)은 플랫폼 백엔드가 한다(oFono는 구성요소 설정 `vendor_ipc: true`인 ident, Android `VENDOR_IPC_TAGS = {"RIL"}`;
이슈 DB tags.yaml에 `ipc: vendor`가 하나라도 있으면 그 태그만 — 백엔드 `apply_rules`, 04-parser-matching §5.8 (2)).
값은 글(str)이다. 이 모듈은 태그 카테고리(tags.yaml 수집 여부)에 기대지 않는다 — 태그가 수집 대상이 아니어도 같은 이벤트가 나온다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property

IPC_ERROR = "builtin.common.vendor_ipc_error"
REQUEST_FAILED = "builtin.common.vendor_request_failed"
EVENTS = (IPC_ERROR, REQUEST_FAILED)

# `platform[.others.<p>].vendor_ipc` 키 (값은 식별자 모양 글). 블록을 쓰면 다섯 키 모두
KEYS = ("context", "complete", "request_prefix", "error_prefix", "success")
VALUE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Spec:
    """벤더 IPC 줄의 사내 토큰. 기본값은 placeholder — 사내 값은 site-defaults에만 둔다(TODO(SITE:S9))."""
    context: str = "IpcCtx_"                     # `[<context><n>]` 문맥 접두어
    complete: str = "OnIpcComplete"              # 완료 낱말
    request_prefix: str = "VIPC_"                # IPC 메시지 이름 접두어(`[RX] <prefix><X>, RSP`)
    error_prefix: str = "VIPC_E_"                # 결과 값 접두어(`Error(<prefix><Y>)`)
    success: str = "VIPC_E_OK"                   # 성공 결과 값 전체(error_prefix로 시작, 이벤트로 내지 않는다)

    @cached_property
    def request_re(self) -> re.Pattern:
        return re.compile(rf"\[{re.escape(self.context)}\d+\]\s*{re.escape(self.complete)}\b.*?\bRequest ID\s*=\s*"
                          r"(?P<request_id>\d+)\s*,\s*result\s*=\s*(?P<result>-?\d+)\b")

    @cached_property
    def error_re(self) -> re.Pattern:
        return re.compile(rf"\[(?:RX|TX)\]\s*(?P<ipc>{re.escape(self.request_prefix)}[A-Z0-9_]+)\s*,\s*RSP\b.*?"
                          rf"\bError\(\s*(?P<error>{re.escape(self.error_prefix)}[A-Z0-9_]+)\s*\)")


DEFAULT = Spec()


def detect(msg: str, spec: Spec = DEFAULT) -> list[tuple[str, dict]]:
    """메시지 한 줄 → `[(이벤트 이름, fields)]`(없으면 빈 목록)."""
    out: list[tuple[str, dict]] = []
    if not msg:
        return out
    m = spec.error_re.search(msg)
    if m and m.group("error") != spec.success:
        out.append((IPC_ERROR, {"ipc": m.group("ipc"), "error": m.group("error")}))
    m = spec.request_re.search(msg)
    if m and int(m.group("result")) != 0:
        out.append((REQUEST_FAILED, {"request_id": m.group("request_id"), "result": m.group("result")}))
    return out
