---
description: Jira 이슈와 logcat으로 telephony 이슈 분석 및 이슈 DB 분류
argument-hint: <JIRA-KEY> [logcat 경로...] [--code <프로필|경로>] [--dry-run | --analysis-only] [--more-logs <로그...>] [--jira-file <yaml>] [--failed-step <한 줄>] [--steps-file <파일>] [--clock-offset <±시간>] [--analyzer | --no-analyzer] [--explore | --no-explore]
---

`${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/SKILL.md`(telephony-triage 스킬)의 analyze를 다음 인자로 실행한다: $ARGUMENTS
실행 규칙(종료 코드 2·사내 기본값 없음 S-3이면 멈춤 등)은 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/rules.md`를 따른다.
스텝 목록을 붙여넣으면 `WD/<KEY>/steps-pasted.txt`에 쓰고 `--steps-file`로 넘긴다(도구가 읽을 때 마스킹, 작업이 끝나면 discard·release가 지운다).
