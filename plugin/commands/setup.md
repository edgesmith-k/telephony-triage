---
description: telephony-triage 사용자 설정 — config 생성, Jira MCP 도구 확인, 이슈 DB hook·읽기 스냅샷·캐시, gh 인증 확인
---

telephony-triage를 이 사용자 환경에 맞게 설정한다 (`02-config.md §4` setup 1~10).
스크립트는 모두 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`로 부른다. 결과는 JSON이다.
각 단계의 결과를 짧게 보여주고, **사용자 확인이 필요한 곳에서는 반드시 묻는다.**

어떤 스크립트든 종료 코드 2와 "사내 기본값 없음(S-3 미완료)"을 내면 **거기서 멈추고** 그 메시지를
그대로 보여준다(플러그인에 `site-defaults.yaml`이 없다. example 파일로 대신하지 않는다).

1. **config 만들기** — `config.py show`로 기존 config를 확인한다.
   - 없으면 아래 항목을 사용자에게 하나씩 묻는다(괄호 안 기본값은 `show`의 `effective`에 있다):
     GHE 아이디, 이슈 DB 로컬 clone 경로, 이슈 DB 원격 URL, base 브랜치, GHE 호스트, Jira 시각 타임존,
     logcat 시각 타임존, 연도 결정 방식(`jira | file-mtime | ask`), logcat 기본 탐색 경로(선택),
     작업 디렉토리. `code_profiles`는 건너뛸 수 있다.
   - 답을 JSON(`{"user.ghe_id": ..., "issue_db.path": ..., ...}`)으로 임시 파일에 쓰고
     `config.py init --answers <파일>`을 실행한다. 경로가 없으면 거부되므로(종료 코드 2) 그 항목만 다시 묻는다.
     홈(`~/.telephony-triage/`)과 작업 디렉토리는 권한 700으로 만들어진다.
   - 있으면 바꿀 항목만 `config.py set <키> <값>`으로 고친다.
2. **스크립트 경로** — `config.py sync-scripts-path`.
3. **이슈 DB clone** — `init` 결과의 `suggest_clone`이 있으면 그 `git clone` 명령을 제안하고, 사용자가 동의하면 실행한다.
4. **Jira MCP** — `config.py jira-candidates`로 이미 등록된 MCP 서버의 도구에서 후보를 고른다.
   - `usable`이 비어 있으면: "사용자 범위(user scope)로 사내 Jira MCP를 등록해야 한다(다른 프로젝트에만 등록돼
     있을 수 있음)"고 안내하고 **setup을 중단**한다.
   - 원격 서버라 `error`가 있으면, 이 세션에서 보이는 그 서버의 도구 이름을 `{"<server>": ["mcp__<server>__<tool>", ...]}`
     JSON으로 써서 `--tools-json <파일>`로 다시 부른다.
   - 서버를 고르고, `suggested`(팀 기본값이 먼저)의 `get_issue`(필수)·`search_issues`·`get_comments`를
     보여주고 **사용자 확인**을 받는다. 이어서 `read_tools` 후보를 보여주고 허용할 읽기 도구를 **확인**받는다.
   - `config.py set-jira --server <s> --get-issue <전체 이름> [--search-issues ..] [--get-comments ..] --read-tools <a,b,..>`.
     도구 이름은 항상 **전체 이름**(`mcp__<server>__<tool>`)이다. `jira.tools` 값은 `read_tools`에 자동으로 들어간다.
5. **git hook** — `config.py install-hooks`. 값이 정확히 `.githooks`가 아니면 실패한다(그대로 보고한다).
6. **읽기 스냅샷과 캐시** — `db_pr.py lock acquire setup --command setup`
   → `db_pr.py snapshot --job setup` → `db_build.py --cache-only --db <work_dir>/_snapshot`.
   - `lock acquire`가 종료 코드 2면 보유자(`holder`)를 보여주고 그 세션이 끝났는지 묻는다. 끝났으면
     `db_pr.py lock release <보유자 작업 키> --force` 후 다시 잡는다. 같은 작업 키(`setup`)가 10분 이내에
     갱신됐다면 사용자 확인 후 `--take-over`로 이어받는다.
   - `snapshot` 결과의 `pull_skipped_reason`이 있으면 그대로 알린다. **사용자 clone의 브랜치와 워킹 트리는 바꾸지 않는다.**
7. **호환성(스냅샷 기준)** — `config.py check --db <work_dir>/_snapshot --for dry-run`.
   `writable: false`면 `reasons`를 보여주고 "읽기 전용 — 이슈 DB 쓰기는 막힌다"고 알린 뒤 계속한다.
8. `db_pr.py lock release setup`. (1~8 중 어디서 멈추든 lock을 잡았다면 반드시 푼다.)
9. **gh 인증** — `config.py gh-status`. 종료 코드 2면 `message`(로그인 방법)를 보여주고
   "쓰기 불가(gh 인증 없음). 읽기 전용 분석과 `--dry-run` 연습은 된다"로 **setup을 끝낸다.**
10. 이슈 DB의 `docs/getting-started.md` 위치(`<issue_db.path>/docs/getting-started.md`)를 알려준다.

lock 획득·인계 결과의 `lock.owner`를 보관하고 이후 `db_pr`·`db_verify` 호출마다 `TT_LOCK_OWNER`로 전달한다. 현재 lock 파일에서 토큰을 다시 읽어 쓰지 않는다.
