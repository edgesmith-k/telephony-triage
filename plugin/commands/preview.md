---
description: 이슈 DB 생성 파일(README, STATS, CHANGELOG) 미리보기 — 워킹 트리를 바꾸지 않는다
---

생성 결과를 임시 디렉토리에만 만들어 보여준다 (`03-issue-db.md §5.6`, `09-commands.md` preview). **읽기 전용**이다.
스크립트는 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/db_build.py"`로 부른다.
종료 코드 2와 "사내 기본값 없음(S-3 미완료)"이면 거기서 멈추고 메시지를 그대로 보여준다.

1. **대상 정하기** — cwd가 이슈 DB 레포(또는 worktree) 안이면 그 트리, 아니면 config의 clone이 대상이다(`--db`를 주지 않는다).
2. **미리보기 만들기** — 임시 디렉토리(`<work_dir>/preview-<YYYYMMDD-HHMM>`)에
   `db_build.py --preview <임시 디렉토리>`를 실행한다. 대상 이슈 DB의 워킹 트리와 git 상태는 바뀌지 않아야 한다.
3. **보여주기** — 만들어진 파일 목록과, 현재 커밋된 생성 파일과 다른 부분의 요약(`diff -ru`)을 보여준다.
   차이가 없으면 "생성 파일이 최신"이라고 알린다.
4. **정리** — 임시 디렉토리는 사용자에게 알리고 남겨 두거나(요청 시) 지운다. 생성 파일은 직접 편집하지 않고
   `db_build.py --write`로만 만든다고 안내한다.
