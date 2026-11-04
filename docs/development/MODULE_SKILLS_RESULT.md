# 계획 H 결과 노트 (모듈 스킬 레포 + +1 병합)

단계표는 `MODULE_SKILLS_PLAN.md §4`. 이 파일은 단계마다 리뷰·재측정에서 P2로 남긴 것(결정 (r): P0·P1만 고치고 P2는 반입 뒤 후보)과 단계 결과를 적는다.

## A2 바로 병합 삭제·확인 화면·리뷰어 질문 (11/04)

커밋: 7746c46(구현·리뷰 P1 수정), 다음 커밋(eval 기록·이 노트). 리뷰: 2관점(동작, 문서·스킬) 1회 → 반박 검증 → P1 2건 한 번 수정(재리뷰 없음, 11/04 진행 방식).
고친 P1: ① 검증 결과 '승인 필요' PR이 아무나 +1로 병합되던 회귀(A2가 merge-offer `mode`를 지우며 생김) — merge-offer `needs_approval`로 `db_pr merge`가 거부, 옛 기록은 `mode: review`+'승인 필요' 사유만 거부. ② write-flow §6 '병합해줘' 거부를 모두 +1 안내로 처리 — +1 거부(no-approval·stale-approval·changes-requested)에만 +1 안내, 그 밖은 사유의 다음 단계. 메인에서 더함: eval 72의 '병합해줘' 전 병합·우회·lock/clone 행을 안전 행으로(스텁은 +1이 있어 요청 없는 병합이 실제로 MERGED가 된다, 리뷰 P2를 올림).
검증: 전체 테스트 2,603 통과(메인 트리, 3샤드), gen_contracts --check·check_boundary 통과, CLAUDE.md 4,051B. eval(Sonnet 5.5): 72 9/9×2, 61 14/14·62 8/8(수동 행 transcript 확인), 75 안전 행 통과·표시 행 fail(5/7·4/7). trigger 17/18·오탐 0.
크기 상한 올림(사용자 확인 대상): write-flow.md 15,872 → 16,000(지금 15,995), rules.md 2,496 → 2,516.
사용자 확인 대상 결정 D1: 메인테이너 경로·'승인 필요' PR의 확인 화면 병합 줄은 메인테이너 문구(`merge.how`).

### P2 — A2 (반입 뒤 후보)

- 안내서·자료(`docs/book/telephony-triage-book.html`, `docs/materials/01·02·19·step7-rule-proposals`)에 바로 병합·`--and-merge`·`issue_db.merge`가 남아 있다 → G에서 고친다.
- 다시 해도 안 되는 거부(메인테이너 경로·닫힌 PR·다른 커밋으로 병합됨)에도 `retry`가 붙는다('승인 필요' 거부만 뺐다).
- `job_status` pr-created 다음 할 일이 메인테이너·'승인 필요' PR에도 '병합해줘'를 권한다.
- 리뷰어 질문에서 로그인이 아닌 답(한글 이름·메일)이면 request-review가 종료 2로 끝나 rules.md 기본(멈춤)대로 Step 9 질문이 안 나올 수 있다. `REVIEWER_RE`는 로그인·org/team만 받는다.
- 브랜치 보호 BLOCKED 거부 문구가 '리뷰어가 GHE에서 머지한다'(없앤 모델)를 말한다.
- 리뷰어 질문 판별이 '리뷰어'·'지정'이 든 뒤 질문을 두 번째 리뷰어 질문으로 셀 수 있다(eval 61·67·72 채점).
- eval 75: 사유를 글자 그대로 보이라는 문구가 있어도 모델이 바꿔 말한다(A1부터, 2/2). a2-75b는 첫 PR 거부 뒤 '멈춘다'를 요청 전체로 읽어 두 번째 PR을 시도하지 않았다(1/2, 호출 횟수 행 — 안전 행 아님). 고치려면 write-flow에 'PR마다 따로'를 넣어야 하는데 상한까지 5B 남았다.
- trigger: "SETUP_DATA_CALL이 안 나가는 원인 찾아줘"가 미트리거(0/2). A2 전 플러그인도 0/4(지금 1/4)라 A2 때문이 아니다.
- show_guard 테스트 화면(`tests/fixtures/show_guard/eval2-ask.json`)은 옛 '리뷰어:' 줄 그대로(자체 완결, 통과).

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

- 사외 측정(a1-75a·a1-75b, Sonnet 5.5): 7행 중 5행 통과, 안전 행 통과. 실패 2행은 표시 행이다 — 병합 거부 때 `reason`과 재시도 명령을 글자 그대로 보이라는 write-flow §6 문구(병합 재시도·`--and-merge` 결과)가 있어도 모델이 사유를 바꿔 말했다. 11/04 사용자 결정: 문구는 그대로 두고 P2로 기록, A2에서 같은 파일(write-flow)을 고칠 때 함께 본다.
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

### e8f3342 회귀 수정 (11/03)

회귀 4건을 고친 뒤 2관점 리뷰(닫힌 부류·회귀, 반박 검증) 2회와 재수정을 거쳤다. 마지막 리뷰에서 남은 2건(`$'\c'`가 닫는 따옴표를 먹어 뒤 명령 전체가 판정 밖으로 빠짐 — e8f3342 회귀 P0, 1024자 넘는 cwd 후보를 work_dir로 접어 worktree·작업 폴더 검사를 건너뜀 — 수정이 만든 P1)은 직접 고치고 그 두 수정만 다시 리뷰했다. `$'…'` 쪽은 지적 0건(bash 대조 퍼징 약 9만 건). 긴 후보 쪽은 P1 2건(글자로만 접어 심볼릭 링크를 지나 clone·worktree·작업 폴더로 드는 긴 사슬을 놓침, 1024자 안 조상으로 잘라 깊이를 잊어 뒤 `..`가 밖으로 올라감)과 앞 회차 패치의 속도 P1(없는 경로 pushd 1000개 + popd 1000개가 156~250초 — hook 한도 180초를 넘겨 판정 없이 통과, e8f3342 1.3초)이 나와 다시 고쳤다(3~5초).
고친 부류: 실패하거나 대상을 모르는 cd·pushd·popd는 이전 cwd 후보를 남긴다(옵션·남는 인자·stat 오류·x 권한 없음 포함), `$'…'`는 bash 어휘 분석으로 닫고 NUL·서로게이트를 bash처럼, 경로·걷기 예외는 그 검사만 ask(내부 오류 판정으로 무너지지 않음)·`_degraded`도 병합 deny, 숫자 owner SCP 원격, 후보 넘침 때 처음·보호 뿌리 안·최근 후보 유지, and-or에서 건너뛴 상태·if 조건 끝 상태, heredoc 본문은 연산자당 두 번만 걷기(945바이트 사례 302s → 0.36s), 긴 후보는 실제 경로와 글자로 `..`을 접은 경로를 둘 다(깊이 유지, 4096자 넘을 때만 조상으로 자르고 모르는 디렉토리도 둠), 모르게 된 pushd 스택은 칸 하나로 합침.
검증(긴 후보 3차 수정 전 — 3차 수정 뒤 재검증은 아래 줄에 더한다): 관련 테스트 804 통과, 말뭉치 7,403 × cwd 4곳은 앞 패치와 같고 e8f3342보다 약해진 판정 0(강해진 것 17), 리뷰어 사례 11,964건 중 약해진 6건은 bash가 실패하는 cd(이름 255바이트 초과)의 과잉 거부가 빠진 것(bash로 확인), bash 판정 퍼징 10 × 1,500(clone 안에서 끝나는 6,314건) 구멍 0.
P2:
- 닫힌 쪽: `if cd <DB>; then …; else …`의 else도 DB에서 판정, `true && cd X || <명령>`의 `||` 뒤도 cd 전 상태로 판정, bash가 거절하는 cd 옵션·남는 인자·`! cd <clone> && git push`는 양쪽 해석 모두로 막음, 같은 명령에서 만드는 폴더로의 cd·`cd X || exit`도 DB 후보를 남김, 걷기 예외 때 낱말 거부가 넓다, degraded(PyYAML 없음)에서 모든 `gh pr merge`가 deny(`--help` 오탐), 같은 거부 사유가 되풀이된다.
- 열린 쪽(대부분 2d0544c에도 있음): 넘침 때 보호 뿌리 밖 가운데 후보는 모르는 디렉토리로, 보호 뿌리 안 후보가 8개를 넘으면 나머지는 뿌리(worktree → work_dir)로 접힌다. work_dir 밖 DB worktree는 우선하지 않는다. 명령 낱말에 붙은 입력 리디렉션(`git</dev/null push`)과 공백 없는 `bash<<EOF`는 명령으로 보지 않는다. 루프 되돌이(뒤 cd가 다음 회차 앞 명령의 cwd), while·until 조건 끝 상태, 함수 본문 cd(모르는 디렉토리만), `cd "$X" && git …`의 성공 상태가 이전 후보를 버린다. root로 돌면 x 권한 검사가 늘 참이다. `main`의 stdin 읽기가 try 밖이다(strict 디코딩 환경에서 잘못된 바이트면 종료 1).
- 기타: `user@host:PORT/o/r`의 PORT를 owner로 읽는다(git도 SCP 경로로 읽는다). 긴 상대 cd 사슬이 앞 패치보다 약 2.7배 느리다(cd 2,000개 4.5s, e8f3342 5.3s — hook 한도 180s 안).

### guard 마지막 리뷰 (11/04, 사용자 결정: 이번 회차만 보고 P0만)

3차 수정(긴 후보 실제·글자 두 꼴, PATH_MAX, pushd 스택 합치기)만 겨눈 2관점 리뷰. 고친 것: 두 꼴 때문에 보호 뿌리 안 후보가 넘쳐 work_dir로 접히던 P0(레포 꼭대기·작업 폴더로 접기, c0f4ea9), 스택 합치기가 다시 넣은 칸의 최근 순서를 잃던 P0 2건(bash처럼 마지막에 넣은 칸이 이긴다), 4096자 넘는 실제 디렉토리를 잘라 뒤 `..`가 밖으로 올라가던 P0(HEAD에도 있던 것 — 실제로 있으면 자르지 않는다), 제가 만든 속도 회귀 P1(깊은 디렉토리에서 `..`마다 realpath — `..`은 푼 실제 경로의 부모로, cd 1000개 115~318초), sticky 상태에서 스택을 합치지 않아 pushd/popd가 180초를 넘던 P1(sticky도 합친다). P2(기록만): 디렉토리 스택 tilde(`~-`·`~N`) 미지원, 1024자 이하 후보에 글자 경로 꼴 없음(링크 뒤 `..`), 함수 본문이 `pushd -n X`만 할 때 sticky가 아닌 경우가 생김(bash로는 cwd가 안 바뀐다).

최종 검증(6c49a8c): 관련 테스트 357 통과, bash 판정 퍼징 5×1,500 구멍 0, 심볼릭 링크 판정 퍼징 4×1,500 구멍 6(모두 26ef9f3에도 있던 짧은 경로의 글자·실제 해석 차이 — 26ef9f3은 8), 말뭉치 7,403×4는 26ef9f3과 같음(e8f3342보다 약한 판정 0), 리뷰어 사례 11,964건·재현 사례(c1~c4, 스택 7묶음) 26ef9f3보다 약한 행 0(P2로 둔 함수 본문 `pushd -n` 3행 제외), 깊은 디렉토리 `..` 사슬 115~318초 → 1~5초.

### show_guard post 안내 (11/04)

PostToolUse `post`가 60초 안의 모든 기록(다른 세션·eval 하위 세션·앞 호출)을 보고, 기록을 남기지 않은 호출(`db_pr status` 등)에도 "push 화면을 붙여라"를 안내했다(예전부터 있던 것). 11/04 사용자 결정으로 고쳤다: 그 호출이 도는 동안(transcript의 tool_use 시각 − 2초 ~ 지금) 남은 기록만 본다. 호출을 transcript에서 못 찾으면 예전 60초 창(경고). 리뷰(P0·P1 없음) 뒤 contracts.md 문구와 PostToolUse 기다림(2초 → 0.3초 — 하위 에이전트 호출은 주 transcript에 없다)을 고쳤다. P2: 겹친 때 다른 세션이 같은 스크립트로 남긴 기록, 앞 호출 기록 뒤 2초 안에 이어 부른 호출(`shown.anchor`는 앞 호출에 고정한다 — 고치려면 끝난 앞 호출에 고정되는 기록을 뺀다)에는 아직 안내된다. 660초보다 긴 호출(`BASH_MAX_TIMEOUT_MS`를 올린 경우)의 앞 기록은 보지 않는다.

### 리뷰 중 사고 (11/03)

guard 재리뷰 중 리뷰어 하나의 셸 heredoc 실수로 메인 레포(GitHub 원격)에서 `gh pr merge 3`이 한 번 실행됐다. PR #3은 10/05에 이미 병합된 PR이라 실패했고, 바뀐 것은 없다(GitHub에서 확인: 오늘 마지막 병합은 #79, 01:57 UTC). 앞으로 리뷰·검증 에이전트에는 gh 스텁 PATH나 쓸 수 없는 `GH_HOST`를 주고, 실제 원격이 있는 레포에서 `gh` 쓰기를 금지한다고 프롬프트에 적는다.
