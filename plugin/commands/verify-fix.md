---
description: 코드 수정 검증 — 수정 패치 적용 빌드 logcat으로 판정하고 verify-fix PR을 만든다(AP 패치는 fixed_in 비교 안 함)
argument-hint: <원인 ID> <수정 빌드 logcat...> [--issue <검증 Jira 키>] [--bundle <CI/CD 번들 번호>]
---

먼저 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/verify.md`를 읽고 그 `verify-fix` 흐름(판정 규칙 `05-verification.md §5.12 (2)`)을 다음 인자로 실행한다: $ARGUMENTS
스크립트: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"` = `S/`(이 절대 경로를 그대로 쓴다).
실행 규칙(종료 코드 2·사내 기본값 없음 S-3이면 멈춤·플랫폼 `--platform` 등)은 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/rules.md`를 따른다.
