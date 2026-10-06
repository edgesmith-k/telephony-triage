---
description: 이슈 DB 검색 — 증상 문장·키워드·Jira 키·ID (원인, 해결책, 수정 상태, 이슈 번호, 옛 ID → 새 ID 연결)
argument-hint: <증상 문장|keyword|JIRA-KEY|ID>
---

먼저 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/search.md`(단일 원본)를 읽고 그 절차를 다음 인자로 실행한다: $ARGUMENTS
인자가 없으면 무엇을 찾는지 묻는다. 읽기 전용, lock 없음.
스크립트: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`(결과 JSON). 종료 코드 2면 메시지를 그대로 보이고 멈춘다(예: 사내 기본값 없음 S-3).
