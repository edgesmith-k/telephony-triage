---
description: 수동 기록 — 스스로 해결한 이슈를 분석·매칭 없이 이슈 DB 히스토리에 남긴다
argument-hint: <JIRA-KEY> [--cause <원인 ID> | --new-cause <유형 ID> | --new-type <category> | --unresolved <유형 ID>] [--fixture <logcat>] [--resolved-fixture <logcat>] [--dry-run] [--jira-file <yaml>]
---

먼저 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/record.md`를 읽고, 그 `record` 흐름(원본 `07-workflow.md §record`)을 다음 인자로 실행한다: $ARGUMENTS
적용 이후는 `reference/write-flow.md`, 새 원인·유형·시그니처는 `reference/db-authoring.md`. SKILL.md의 analyze 절차는 읽지 않는다.
스크립트는 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`로 호출한다.
어떤 스크립트든 종료 코드 2와 "사내 기본값 없음(S-3 미완료)"을 내면 거기서 멈추고 메시지를 그대로 보여준다.

- 로그·코드 분석과 매칭은 건너뛰고, 쓰기 경로와 검증은 analyze Step 8과 같다. 확인 화면과 PR에 "구분: 수동 기록 (record)"을 밝힌다.
- 옵션이 없으면 유사 유형(`db_search.py`, `db_add.py similar`)을 보여주고 대화형으로 묻는다.
- `fixed`는 기록할 수 없다(`fix-submitted`까지). "검증까지 끝났다"고 해도 `fixed`는 `verify-fix`로만 한다고 안내한다.
- 시작할 때 세션 lock(`db_pr lock acquire <JIRA-KEY>`)을 잡고 끝나는 모든 경로에서 푼다. record는 쓰기만 하는 흐름이라 쓰기 불가면 이유를 보여주고 lock을 풀고 멈춘다. `--dry-run`은 `--for dry-run`으로 확인 화면까지 간다.
