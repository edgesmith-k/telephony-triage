# 계획 H 결과 노트 (모듈 스킬 레포 + +1 병합)

단계표는 `MODULE_SKILLS_PLAN.md §4`. 이 파일은 단계마다 리뷰·재측정에서 P2로 남긴 것(결정 (r): P0·P1만 고치고 P2는 반입 뒤 후보)과 단계 결과를 적는다.

## A1 +1 병합 관문 (11/03)

커밋: 403cef4(관문), 2d0544c(테스트 임시 폴더 누수), e8f3342(guard 규칙 11 4회차 리뷰 반영).
리뷰: 구현 리뷰 3회 + guard 규칙 11 리뷰 4회차(반박 검증 → 수정 → 재리뷰 2회). 마지막 수정(재리뷰 2회차 P1 4건)은 다시 리뷰하지 않았다.

### P2 — 병합 쪽 (반입 뒤 후보)

- 리뷰는 시도마다 한 번, fetch 전에 읽는다. `gh pr merge` 직전에 들어온 변경 요청·기각은 보지 못한다(뒷받침: GHE branch protection 필수 승인).
- +1은 쓰기 권한이 없는 사용자의 Approve도 센다. GHE 필수 승인은 쓰기 권한자만 센다(뒷받침: branch protection).
- 리뷰를 읽는 호스트·레포는 view `url`에서 나온다. 설정의 GHE 호스트나 merge-offer url과 대조하지 않는다.
- 리뷰 읽기 실패·view url 없음 거부에는 PR 링크가 없다.
- 리뷰 읽기 실패 사유에 gh stderr 원문(300자)이 마스킹 없이 stdout·trace에 남는다.
- 테스트 임시 폴더: 수집이 없는 실행(`pytest -h`)은 빈 `tt-session-*`을 남긴다. 실패한 테스트의 `tmp_path`는 `TT_KEEP_TMP=1` 없이 남지 않는다.

### P2 — eval 75 채점

- `checks_gate` 5행(우회 없음, 안전 행)이 `db_pr`·`publish`/`stage`를 언급만 하는 읽기 명령이나 `merge-offer.json` 복사를 우회로 셀 수 있다(거짓 안전 위반 쪽 — 실행 결과를 사람이 확인).

### P2 — guard 규칙 11 (best effort, 실제 강제는 db_pr +1 관문·git hook·GHE branch protection)

닫힌 쪽 부작용(정상 명령이 ask·deny):
- 셸 변수 선택자·`-R` 값의 병합·Approve는 모든 레포에서 deny이고 메시지는 이슈 DB PR이라고 한다. 이슈 DB clone·worktree에서는 다른 레포를 겨눈 병합·Approve도 deny다.
- 조건부 cd(`&&`·`||`·if/case/loop), `source`/`.`, 셸 값 `eval`, 짝 없는 `)`, 명령 글의 `CDPATH`는 모르는 cwd 후보를 더한다. 예: `source .venv/bin/activate && gh pr merge`는 어느 레포에서나 deny.
- 명령 글 전체에서 찾는 것: `GH_REPO` 낱말(주석·본문 포함)은 다른 레포의 병합·Approve를 deny, 쓰기를 ask로. GraphQL mutation 이름은 읽기 질의도 deny(셸 값 엔드포인트 포함).
- 하위 명령 앞 옵션(`GH_LEAD_ASK`)은 읽기 명령도 ask. `-R other/x` 앞 bool 옵션, `-p`·`-a`도 ask가 된다. `gh repo fork <이슈 DB>`가 새로 ask다.
- `gh api "$GHE_API/graphql" -f query="$Q"`(읽지 못한 본문)는 어느 레포에서나 ask.

열린 쪽 빈틈(알려진 한계로 둠):
- 같은 명령 글의 `export GIT_DIR=`·`GIT_WORK_TREE`·`GIT_CONFIG_*`, `git remote add upstream <DB>`는 cwd 판정에 넣지 않는다. 앞 Bash 호출·셸 프로필의 `CDPATH`·함수, cd 대상 변수, `$OLDPWD`(모르는 cwd는 git 규칙을 끈다)도 보지 않는다.
- 셸이 만드는 명령 낱말(중괄호 확장·셸 값 머리·함수), `bash -c -- '…'`, `python3 -c` 안의 Approve.
- deny 대신 ask: REST 쿼리 문자열 event, 읽지 못한 GraphQL 본문, 내부 오류, `ccr/auto_merge`. API로 main을 PR head로 옮기기(ref 이동 mutation 포함)도 ask.
- 다른 호스트의 같은 owner/repo를 이슈 DB로 본다. dot-segment 엔드포인트는 첫 owner/repo로 풀린다.
- 이슈 DB가 아닌 cwd에서 `gh repo edit|delete|archive|sync <DB>`는 ask가 없다.
- MCP: owner+repo·`MCP_REPO_KEYS` 밖 대상 키는 판정하지 않는다. Approve 검사가 `mcptools.is_write` 뒤에 있다.
- 주석을 줄 이음보다 먼저 빼서 생기는 차이(`echo a\⏎#b; gh pr merge 3`).

테스트 빈틈: `GH_LEAD_ASK` 분기, `_backstop`(모르는 머리 뒤 gh·git), `=` 없는 `GH_REPO` 언급을 보는 테스트가 없다. 새 테스트 몇 개는 주장한 동작을 단언하지 않는다(뮤테이션이 살아남음).

### e8f3342 회귀 리뷰 (11/03)

e8f3342(guard 4회차 수정)만 겨눈 회귀 리뷰(말뭉치 재생·안전 비교·코드·원격 설정, 반박 검증). 말뭉치는 eval·문서·테스트 명령 7,403건 × cwd 4곳(59,224 판정)으로, 스킬 흐름 명령은 새로 막힌 것이 없었다. 확인된 회귀(빈 스택 `popd`가 cwd 후보를 버림, `$'\0'`·서로게이트 예외로 deny→ask, 숫자 owner SCP 원격 거부, cwd 후보 상한이 최근 후보를 버림)는 다음 커밋에서 고친다. P2:
- 하위 명령이 없는 gh 명령(browse·status·completion)에 옵션을 주면 앞 옵션으로 ask된다.
- DB clone을 cwd로 둔 세션에서 `mkdir -p D && cd D` 다음 줄의 상대 경로 쓰기가 규칙 8로 deny된다(조건부 cd 합집합).
- source·`.`·셸 값 eval·함수 정의가 켠 모르는 cwd 후보가 뒤의 절대 경로 cd 뒤에도 남아, 무관한 레포의 gh 쓰기는 ask, `gh pr merge`는 deny가 된다.
- 파이프 마지막 요소의 cd를 늘 서브셸로 본다(`shopt -s lastpipe`·zsh에서는 현재 셸).
- `_heredoc_scan`이 끝 표시를 못 찾으면 연산자마다 글 끝까지 다시 훑는다(`<<`가 많은 줄이 이어지면 시간이 제곱으로 는다, 5000줄 5.8s — hook timeout 180s 안). 옛 산술 `$[ … ]` 안의 `<<`를 heredoc으로 본다.
- (기존) 읽기 전용 `git apply --numstat`·`--stat`·`--check`가 DB clone에서 규칙 8로 deny된다.
- 플랫폼 프로필의 remote를 못 풀 때 doctor config 행의 '다음' 안내에 `--platform <p>`가 빠진다.
- 새 테스트 여럿이 주장한 walker·heredoc·gh 동작을 단언하지 않는다(뮤테이션 26개 중 15개 생존).

### 리뷰 중 사고 (11/03)

guard 재리뷰 중 리뷰어 하나의 셸 heredoc 실수로 메인 레포(GitHub 원격)에서 `gh pr merge 3`이 한 번 실행됐다. PR #3은 10/05에 이미 병합된 PR이라 실패했고, 바뀐 것은 없다(GitHub에서 확인: 오늘 마지막 병합은 #79, 01:57 UTC). 앞으로 리뷰·검증 에이전트에는 gh 스텁 PATH나 쓸 수 없는 `GH_HOST`를 주고, 실제 원격이 있는 레포에서 `gh` 쓰기를 금지한다고 프롬프트에 적는다.
