---
description: 이슈 DB 검색 — 유형, 원인, 해결책, 수정 상태, Jira (옛 ID → 새 ID 연결 포함)
argument-hint: <keyword|JIRA-KEY|ID>
---

이슈 DB를 검색한다 (`03-issue-db.md §5.5`, `09-commands.md` search). **읽기 전용**이라 세션 lock을 잡지 않는다.
스크립트: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`(결과 JSON). 종료 코드 2면 메시지를 그대로 보이고 멈춘다(예: 사내 기본값 없음 S-3).

인자: `$ARGUMENTS` (키워드, Jira 키, 유형 ID·원인 ID). 인자가 없으면 무엇을 찾는지 묻는다.

1. **검색** — `db_search.py --db <work_dir>/_snapshot "$ARGUMENTS"`. 스냅샷이 없으면(`sync`를 한 적이 없음)
   `--db`를 주지 않는다(cwd의 이슈 DB 또는 config의 clone). 이때는 "최신 main 기준이 아닐 수 있으니 `sync`를 권한다"고 알린다.
   `work_dir`는 `config.py show`의 값이다.
2. **보여주기** — `kind`(type-id / cause-id / jira / keyword)를 밝히고 `results[]`를 유형 > 원인 순으로 정리한다.
   원인마다 해결책과 `resolution_verification` 상태(미검증이면 그렇다고), 수정 상태(`fix.status`, `fixed_in`),
   연관(`related`), 다른 카테고리(`secondary_categories`), 최근 Jira(최대 5건)를 보여준다.
3. **ID 연결** — `links[]`가 있으면 `옛 ID → 새 ID`(`merged-into` 병합 / `renumbered` 사후 정리, 커밋·날짜)를 함께 보여준다.
   `current`(병합 체인의 끝)가 있으면 지금 봐야 할 ID를 알려준다.
4. **결과 없음** — 종료 코드 0에 `results`가 비면 "일치 없음"과 다른 검색어(유형 제목·태그·Jira 키)를 제안한다.
