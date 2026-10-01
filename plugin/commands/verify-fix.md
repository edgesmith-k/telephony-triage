---
description: 코드 수정 검증 — 수정 빌드 logcat으로 판정하고 verify-fix PR을 만든다
argument-hint: <원인 ID> <수정 빌드 logcat...> [--jira <검증 Jira 키>]
---

먼저 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/verify.md`를 읽고 그 `verify-fix` 흐름(판정 규칙 `05-verification.md §5.12 (2)`)을 다음 인자로 실행한다: $ARGUMENTS
실행 규칙(스크립트 호출, 종료 코드 2·사내 기본값 없음 S-3이면 멈춤, lock, 마스킹)은 `SKILL.md` §실행 규칙을 따른다.
