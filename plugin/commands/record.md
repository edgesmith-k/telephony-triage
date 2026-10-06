---
description: 수동 기록 — 스스로 해결한 이슈를 분석·매칭 없이 이슈 DB 히스토리에 남긴다
argument-hint: <JIRA-KEY> [--cause <원인 ID> | --new-cause <유형 ID> | --new-type <category> | --unresolved <유형 ID>] [--fixture <logcat>] [--resolved-fixture <logcat>] [--dry-run] [--jira-file <yaml>] [--failed-step <한 줄>] [--steps-file <파일>]
---

먼저 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/record.md`를 읽고 그 `record` 흐름을 다음 인자로 실행한다: $ARGUMENTS
실행 규칙(종료 코드 2·사내 기본값 없음 S-3이면 멈춤 등)은 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/rules.md`를 따른다.
스텝 목록을 붙여넣으면 `WD/<KEY>/steps-pasted.txt`에 쓰고 `--steps-file`로 넘긴다(도구가 읽을 때 마스킹, 작업이 끝나면 discard·release가 지운다).
