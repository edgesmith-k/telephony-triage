---
description: 코드 수정 검증 — 수정 빌드 logcat으로 판정하고 verify-fix PR을 만든다
argument-hint: <원인 ID> <수정 빌드 logcat...> [--jira <검증 Jira 키>]
---

telephony-triage 스킬의 `verify-fix` 흐름(`reference/verify.md`, 원본 `07-workflow.md §verify-fix`, 판정 규칙 `05-verification.md §5.12 (2)`)을
다음 인자로 실행한다: $ARGUMENTS
스크립트는 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`로 호출한다.
어떤 스크립트든 종료 코드 2와 "사내 기본값 없음(S-3 미완료)"을 내면 거기서 멈추고 메시지를 그대로 보여준다.

- 작업 키 `verify-fix-<원인 ID>-<build>`로 세션 lock을 잡고, 판정 결과를 기록하지 않고 끝나는 경로(판단 불가, 중단, 취소)를 포함해
  끝나는 모든 경로에서 푼다.
- `fix.status`가 `fix-submitted`(재검증이면 `fixed`)가 아니거나, `signatures_pending` 원인이거나, `fixed_in`에 빌드가 없거나,
  시나리오·회복 시그니처가 없으면 중단하고 필요한 조치를 안내한다.
- 판정은 `db_verify.py fix`의 출력으로 한다(스킬이나 사용자 확인으로 대신하지 않는다). 시나리오 흔적이 없으면 판단 불가다.
- 브랜치는 `verify-fix/<원인 ID>-<build>`. push 전에는 확인 화면(판정 근거 로그와 시나리오 흔적, 마스킹) 승인 후에만 한다.
