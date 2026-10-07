---
description: 수정 CL 반영 기록 — fix.status를 fix-submitted로 바꾸는 fix-submit PR을 만든다
argument-hint: <원인 ID> --ref <CL> --fixed-in <branch>[:<build>]
---

먼저 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/verify.md`를 읽고 그 `fix-submitted` 흐름을 다음 인자로 실행한다: $ARGUMENTS
스크립트: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"` = `S/`(이 절대 경로를 그대로 쓴다).
실행 규칙(종료 코드 2·사내 기본값 없음 S-3이면 멈춤 등)은 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/rules.md`를 따른다.
