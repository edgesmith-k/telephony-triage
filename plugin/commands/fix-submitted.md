---
description: 수정 CL 반영 기록 — fix.status를 fix-submitted로 바꾸는 fix-submit PR을 만든다
argument-hint: <원인 ID> --ref <CL> --fixed-in <branch>[:<build>]
---

먼저 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/verify.md`를 읽고 그 `fix-submitted` 흐름을 다음 인자로 실행한다: $ARGUMENTS
실행 규칙(스크립트 호출, 종료 코드 2·사내 기본값 없음 S-3이면 멈춤, lock, 마스킹)은 `SKILL.md` §실행 규칙을 따른다.
