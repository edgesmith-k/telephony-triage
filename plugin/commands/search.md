---
description: 이슈 DB 검색 — 증상 문장·키워드·Jira 키·ID (원인, 해결책, 수정 상태, 이슈 번호, 옛 ID → 새 ID 연결)
argument-hint: <증상 문장|keyword|JIRA-KEY|ID>
---

먼저 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/search.md`(단일 원본)를 읽고 그 절차를 다음 인자로 실행한다: $ARGUMENTS
인자가 없으면 무엇을 찾는지 묻는다. 읽기 전용, lock 없음.
스크립트: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"` = `S/`(결과 JSON). 종료 코드 2면 메시지를 그대로 보이고 멈춘다(예: 사내 기본값 없음 S-3).
플랫폼: 사용자가 플랫폼을 말했으면(`--platform <이름>`, 예: oFono) `triage`·`config`·`issue_post`·`code_roots`·`db_pr`·`db_verify`·`db_add`·`db_search`·`db_review` 호출에 `--platform <이름>`을 붙이고, 그 밖 스크립트에는 붙이지 않는다. 그 밖 스크립트의 `--db`에는 그 플랫폼의 `SNAP`(읽기, `<work_dir>/_snapshot`) 또는 clone(`issue_db.path`)을 준다(`config.py show --platform <이름> --keys work_dir,issue_db.path`).
