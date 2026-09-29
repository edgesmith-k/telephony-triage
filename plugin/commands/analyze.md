---
description: Jira 이슈와 logcat으로 telephony 이슈 분석 및 이슈 DB 분류
argument-hint: <JIRA-KEY> [logcat 경로...] [--code <프로필|경로>] [--dry-run] [--jira-file <yaml>] [--analyzer | --no-analyzer]
---

telephony-triage 스킬의 워크플로우(Step 0~8)를 다음 인자로 실행한다: $ARGUMENTS
스크립트는 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`로 호출한다 (`07-workflow.md §analyze`, `09-commands.md`).
어떤 스크립트든 종료 코드 2와 "사내 기본값 없음(S-3 미완료)"을 내면 거기서 멈추고 메시지를 그대로 보여준다.

- logcat 경로가 없으면 config의 `log_dir`에서 후보를 보여주고 선택받는다. bugreport(`.zip`/txt)를 주면 logcat 섹션만 추출해서 쓴다(Step 3).
- `--code`가 없으면 Step 2-1에 따라 코드 경로를 묻는다.
- `--jira-file`은 `--dry-run`과 함께만 받는다. 없이 주면 거절하고 이유를 알린다.
- 카테고리 분석 스킬(Step 5-1)은 기본으로 호출 여부를 묻고, `--analyzer`면 묻지 않고 호출, `--no-analyzer`면 호출하지 않는다.
- 시작할 때 세션 lock(`db_pr lock acquire <JIRA-KEY>`)을 잡고 끝나는 모든 경로에서 푼다. 이어서 `config.py check --db <work_dir>/_snapshot`으로 쓰기 가능 여부를 확인하고, 불가면 이유를 보여주고 읽기 전용으로 계속한다. `--dry-run`은 `--for dry-run`으로 gh 인증 없이 확인 화면까지 간다.
- 분류 확정, 새 유형·원인 생성, 시그니처·파서 규칙 추가는 항상 사용자 확인 후, push 전에는 확인 화면 승인 후에만 한다.
