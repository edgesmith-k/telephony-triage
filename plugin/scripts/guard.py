#!/usr/bin/env python3
"""guard.py — Claude Code PreToolUse hook 판정 (08-safety.md §9, contracts.md §3.2).

    stdin: hook 입력 JSON ({tool_name, tool_input, cwd, ...})
    stdout: 권한 결정 JSON {"hookSpecificOutput": {"hookEventName": "PreToolUse",
            "permissionDecision": "deny"|"ask", "permissionDecisionReason": "..."}}
            판정할 것이 없으면 아무것도 내지 않는다(평소 권한 흐름). 종료 코드는 항상 0.

`hooks/hooks.json`의 matcher는 도구 이름까지만 거른다. 명령 내용·서버 판정은 여기서 한다.

TODO(SITE:S1) hook 입력 필드(`tool_name`, `tool_input.command|file_path|notebook_path`, `cwd`)와 권한 결정 출력
형식(`hookSpecificOutput.permissionDecision`)을 사내 Claude Code 버전에서 확인한다 (사외 빈 플러그인 실험도 미확인).
TODO(SITE:S3) 플러그인 hook에 보이는 MCP 도구 이름이 `mcp__<server>__<tool>`이고 `<server>`가 config
`tracker.mcp_server`를 `[^A-Za-z0-9_-]`→`_`로 바꾼 문자열인지 확인한다 (치환 규칙은 관측 기반 추정, `mcptools.server_segment`).

| # | 규칙 | 대상 |
|---|---|---|
| 2 | 트래커(Jira) 쓰기 차단: 트래커 서버(`tracker.mcp_server`와 `tracker.tools` 도구 이름의 서버 접두사, 이름 정규화) 도구 중 `tracker.read_tools`(전체 이름, 정규화 비교)에 없는 것은 거부. **예외 1종**: `tracker.write_tools.add_comment.tool`(승인 코멘트, `common/issuepost.write_spec` 조건)은 `read_tools`보다 먼저 판정해 `<work_dir>/<KEY>/post.approved.json`과 대조(인자 집합·이슈 키·도구·정규화 본문 sha256·30분 만료·1회용, 키 인자 모양은 트래커 어댑터)하고 맞으면 ask, 아니면·설정 오류·판정 예외면 거부. 설정되지 않은 서버라도 이름에 설치된 모든 트래커의 서버 단어(`trackers.all_server_words`, jira·atlassian, 레지스트리 실패 시 내장 jira·atlassian)가 들면 쓰기형 도구 거부. 옛 설정 키(`jira:` 등, `userconfig.legacy_problems`)가 남아 있거나 `tracker.kind`가 잘못됐으면(모르는 트래커) 모든 MCP 호출 거부. **S1 확인 전**(site-defaults `tracker.isolation_confirmed`가 참이 아님)에는 read_tools 호출도 ask — 규칙 9의 원문 격리(`updatedToolOutput` 대체)가 미확인이라 원문이 모델 문맥에 남을 수 있음을 사람이 보고 허용한다(OpenCode 어댑터 `TT_OC_ADAPTER` 환경은 자체 관문·대체가 있어 묻지 않는다) | `mcp__.*` |
| 2 | 같은 규칙: `<work_dir>/<KEY>/post.approved.json`·`post.result.json`을 파일 도구나 Bash 파일 쓰기(규칙 8과 같은 판별)로 쓰거나 지우면 거부(approve·jira_bridge만 쓴다) | Write/Edit/MultiEdit/NotebookEdit, Bash |
| 3 | PII 검사: `git commit`이면 `mask_pii --check --staged` | Bash, 이슈 DB |
| 4 | 생성 파일 정합성: `git commit`이면 `db_build --verify --staged`(`actions-build`면 생성 파일 staged 거부), `.cache/` staged 거부 | Bash, 이슈 DB |
| 5 | hook 우회 차단: 커밋의 `--no-verify`·`-n`, push의 `--no-verify`, `-c core.hooksPath=…`(모든 git 명령), 유효 `core.hooksPath`가 정확히 `.githooks`가 아니면 커밋 거부, `core.hooksPath`를 바꾸거나 해제하는 `git config` 거부(정확히 `.githooks`로 설정은 허용), `GIT_CONFIG_*`·`GIT_INDEX_FILE` 대입이 붙은 commit·push·config 거부. 그 clone `origin/<base>`의 `issue-db.config.yaml` `ci_mode`가 `actions`로 확인되면(작업 트리 파일은 보지 않는다 — `_ci_actions`. 이슈 DB 레포(본체·worktree, `-C`·`--git-dir` 포함)에서 그 ref를 바꿀 수 있는 git은 거부 — `REMOTE_REF_MSG`: `refs/remotes/**`·`refs/replace/**`를 쓰는 `update-ref`(`--stdin`)·`symbolic-ref`, `git replace` 쓰기(`_ci_actions`는 `--no-replace-objects`), dst가 `refs/remotes/**`인 refspec·`--refmap`의 fetch·pull·push, origin 밖 원격·URL·경로(`.`)·`--all`·`--stdin`의 fetch·pull, `-c`·`GIT_CONFIG_*`로 origin URL·refspec을 바꾼 fetch·pull, origin을 바꾸는 `git remote`·`remote update`, `remote.origin.*`·`url.*`·`include*` 키를 쓰는 `git config`, 다른 레포에서 경로로 이슈 DB에 하는 push. `.git/**`·worktree `.git` 파일 쓰기도 거부 — `GIT_META_MSG`. 허용: `git fetch`·`git fetch origin [<브랜치>]`·`git pull [origin]`)(서버 CI `db-check`가 마스킹·생성 파일 검사를 다시 한다) 거부 대신 ask하고 커밋 검사(3·4)를 이어 간다 — `GIT_INDEX_FILE` 커밋만은 커밋 검사가 그 index를 보지 못하므로 늘 거부. local·없음·읽지 못함·오류면 거부(닫힌 쪽, `_rule5`) | Bash, 이슈 DB |
| 6 | base 브랜치 push: 따로 거부하지 않는다 — 이슈 DB push는 refspec·`--all`·`--mirror`와 무관하게 규칙 7 ask. main 직접 push는 서버 브랜치 보호(필수 PR·force push·삭제 금지·관리자 포함)가 막는다(전제: site_checks `s4a.protection_guard`). 관리 clone·skill-wt의 push는 규칙 12 (a)가 모두 거부 | Bash, 이슈 DB |
| 7 | push 확인 강제: 이슈 DB `git push`(refspec과 무관 — base 브랜치 push도, 규칙 6)와 `db_pr.py publish`는 `ask` (옵션 `--commit`·`--and-discard`와 무관: `publish` 토큰만 본다). publish는 명령 글의 낱말 그물(`word_net`: 이름 `db_pr`와 낱말 `publish`가 함께 든다, 글 명령만인 줄은 뺀다 — 아래 "명령 파싱")로 본다. 같은 그물로 `db_pr.py merge`(+1 병합 — 사용자가 병합을 요청한 뒤에만, 스크립트가 +1·승인 커밋·검사를 대조)와 `db_pr.py request-review`(리뷰어 요청 — push 뒤 리뷰어 질문에서 사용자가 고른 뒤에만, 매번)도 `ask`. 같은 그물(이름 `module_eval` + 낱말 `module`)로 `module_eval.py`(모듈 eval — 자식 `claude -p`를 띄워 비용이 든다, `--dry-run`·`--probe-restricted` 포함 모든 호출. dry-run 결과를 보이고 사용자가 실행을 승인한 뒤에만)도 `ask`. 병합 기록 `<work_dir>/<KEY>/merge-offer.json`을 파일 도구·Bash 파일 쓰기로 쓰거나 지우면 거부(db_pr만 쓴다) | Bash |
| 8 | 사용자 clone 직접 편집 차단: 대상 파일이 `issue_db.path` 안이면 거부(`work_dir` 아래는 제외) | Write/Edit/MultiEdit/NotebookEdit |
| 8 | 같은 규칙, Bash: clone 본체에서 브랜치·파일을 바꾸는 git·`gh pr checkout`, clone 안으로의 파일 쓰기(리디렉션·tee·cp·rm·`sed -i` 등, 플러그인 스크립트 출력 인자 `--out`·`--preview`·`--meta-out`·`mask_pii --in-place`·`jira_fields extract --consume` — `_script_out_targets`) 거부. migrate 브랜치 생성(깨끗한 트리)과 clone을 고치는 `db_build.py --write`(`--db` 값이 clone 안이거나 `--db` 없이 cwd가 clone 본체)는 ask. 인터프리터 인라인 코드(`python3 -c`·`perl -e`·`python3 - <<EOF` 본문)에 clone 안 경로 낱말이 있거나 `ln`의 원본이 clone 안이면 ask(셸 파서는 코드 안 쓰기를 보지 못한다 — `check_inline_code`. `/` 없는 상대 이름은 보지 않는다) | Bash, clone 본체 |
| 10 | 로그 원문 통독 차단: cat·tac·nl·less·more·bat·strings·zcat·zless·bzcat·xzcat, `head/tail -c`, `unzip -p/-c`가 로그 원문·zip·bugreport·`events*.json`·`issue_raw.json`·`match.json`을 통째로 읽으면 거부(`fixtures/`·`draft/` 제외, 사용자 config와 무관). 인터프리터 인라인 코드가 그 파일 경로를 담으면 ask(`check_inline_code`) | Bash |
| 11 | 원격 쓰기 확인(거친 판정 — 대상 레포를 풀지 않는다: `-R`·`GH_REPO`·URL·cwd 원격을 보지 않으므로 이슈 DB가 아닌 레포의 gh 병합·쓰기도 ask): **병합 계열**(`gh pr merge`, REST `…/merge`·`…/merges`, GraphQL `mergePullRequest`·`enqueuePullRequest`·`mergeBranch`, 병합 별칭 `gh alias set|import`, MCP 단어 속 `merge`·입력 `action`·`method` merge…)는 ask(`GH_MERGE_ASK`·`MCP_MERGE_ASK` — 병합은 서버 브랜치 보호가 승인 1을 강제한다, 전제 site_checks `s4a.protection_guard`). 그 밖 gh 쓰기(`pr` 읽기 목록 밖 동작, 그룹의 읽기 목록 밖 동작, 모르는 그룹 — 이미 만든 별칭 실행 포함, `api`의 GET 아닌 메서드·필드·`--input`, GraphQL `mutation`·못 읽은 본문)와 비트래커 MCP 쓰기형 도구(`mcptools.is_write`)는 ask. **Claude Approve·리뷰 기각은 거부**(서버가 막지 못한다 — 낱말 수준, `_gh_kind`): 따옴표를 뗀 명령 글·argv·gh가 읽는 파일(`@파일`·`--input`·`$(cat 파일)`·heredoc stdin)에 `approve`·`dismiss`(상태 값 `APPROVED`·`DISMISSED`는 아니다), `gh pr review`의 `-a`·`-a=`·`--approve`·셸 값 옵션(`_gh_review_approves`), REST 리뷰 엔드포인트의 `event=@…`·셸 값·못 읽은 본문, GraphQL 리뷰 mutation의 변수 `event`와 셸 값·못 읽은 본문, MCP 단어 속 approve·dismiss와 동작 칸(`event`·`action`·`method`·`*event`). 그것일 수 있는 꼴도 거부: 셸이 정하는 그룹·`pr`·`alias` 동작·api 엔드포인트 끝 칸, 리뷰·Approve·기각 별칭과 못 읽은 별칭 파일·셸 값·자리 표시(`$1`·`$@`)·셸 별칭(`-s`·`--shell`·`!…`). `GH_JSON_DEPTH_MAX`(64)보다 깊이 중첩한 JSON 본문은 못 읽은 본문이다(Python 판마다 다른 RecursionError에 기대지 않는다). heredoc 본문은 끝 표시를 인용했거나 `$`·백틱·`\\`가 없고 명령 글의 `<<` 수가 찾은 heredoc 수와 같을 때만, stdin(`-`·`@-`)은 그 호출 자신의 heredoc일 때만 읽은 것이다(`_heredoc_known`·`_gh_stdin_known`). 서버 브랜치 보호·ruleset 바꾸기(`…/branches/<b>/protection…`(브랜치에 `/`가 들어도)·`…/rulesets`의 쓰기, 레포 설정 쓰기(REST `repos/<o>/<r>`·`repositories/<id>`)의 `allow_auto_merge`·`delete_branch_on_merge` 켜기(거짓 `false`·`0` 밖 모든 값, `-f`·`-F`·`--input`·JSON 이스케이프), GraphQL `create|update|delete` + `BranchProtectionRule|RepositoryRuleset`)와 `gh repo edit --enable-auto-merge`·`--delete-branch-on-merge`도 거부(`PROTECTION_DENY` — 4-c 뒤 서버 보호가 유일한 병합 장치). PR 자동 병합 켜기(`gh pr merge --auto`·선택자 뒤 따옴표 밖 셸 값, GraphQL `enablePullRequestAutoMerge`, `--auto` 병합 별칭, MCP 단어 속 auto+merge)도 거부(`AUTO_MERGE_DENY` — 원칙 12: 병합은 +1 뒤 요청 시 `db_pr merge`로만 한다. 자동 병합은 +1이 붙는 즉시 승인 SHA 대조·메인테이너 경로 거부 없이 병합한다). approve·dismiss 낱말이 든 gh 호출은 본문·검색어라도 거부된다(`GH_WORD_NOTE`). `pr checkout`·`gh co`(그룹·`pr` 동작 자리)는 clone 본체에서 규칙 8 거부. 동작 별칭(`new`·`ls`·`co`·`remove`)은 풀어 본다. 적용 조건: issue_db.remote·module_skills.remote 원격 값이 있으면(owner/repo로 못 풀어도 — setup 전엔 보지 않는다) | Bash, `mcp__.*` |
| 12 | 모듈 스킬 관리 clone·기록 보호, 분석 스킬 소스 확인: (a) 관리 clone `<work_dir>/_module-skills/**`·lock `<work_dir>/_module-skills.lock`(경로 조각 `_module-skills`이거나 `_module-skills.`로 시작하면 설정과 무관하게 — `.lock`·`.tmp-*` 포함)과 `<work_dir>/<KEY>/skill-wt/**`(모든 프로필 work_dir — 이름이 잘못된 프로필 포함 — 과 켠 플랫폼의 기본 work_dir)를 파일 도구·Bash 파일 쓰기(규칙 8과 같은 판별 + `mv`·`ln`·`rsync --remove-source-files`의 원본)로 바꾸면 거부. 어디서 돌든 git 경로 옵션(`--output`·`-o`·`--output-directory`·config `--file`·`--git-dir`·`--work-tree`·`--separate-git-dir`)이 그 안이나 (b) 기록을 가리키면 거부. git 작업 디렉토리·`--git-dir`·`GIT_DIR`·`--work-tree` 중 하나라도 그 안이면 읽기 목록(`MODULE_GIT_READ`, `branch`·`remote`·`config`·`sparse-checkout`·`worktree`·`stash`는 읽기 꼴만)만 통과하고(`--output*`·`-O`·`--open-files-in-pager`·`--ext-diff`·`--textconv`는 읽기라도 거부) `-c` 덮어쓰기와 나머지(commit·push·stash·reset·checkout·sparse-checkout set·worktree add·fetch·remote set-url·config 쓰기 등)는 거부, 대상이 그 안인 `git clone`·`init`도 거부(이슈 DB 설정과 무관, 받기·갱신은 `triage.py module`만). (b) 스크립트 기록 `<work_dir>/<KEY>/module-skill.json`·`module-skill/**`·`deep-input.json`·`skill-input.json`·`check-output.json`(triage.py만 — `deep-output.md`·`explore-output.md`는 Claude가 쓴다)과 `skill-suggestions/<이름>.patch`·`.meta.json`(skill_patch.py만)을 파일 도구·Bash 파일 쓰기로 쓰거나 지우면 거부(사본 `skill-suggestions/<이름>/**`는 허용). 상대 경로는 hook 입력 `cwd` 기준. `skill_patch.py --apply`(낱말 그물: 이름 `skill_patch`와 낱말 `apply`)는 `ask`. config `analyzers.<카테고리>.source`(절대 경로, site-defaults·사용자 config의 최상위와 모든 `platforms.<p>.analyzers` 것) 안을 파일 도구·Bash 파일 쓰기(규칙 8과 같은 판별)·파일을 바꾸는 git(`CLONE_GIT_SUBS`·commit·push·stash)으로 바꾸면 `ask`(적용은 `skill_patch.py --apply`로만) | Bash, Write/Edit/MultiEdit/NotebookEdit |

(1번은 SessionStart의 `config.py sync-scripts-path`다.)

**레포 판별**: git 규칙은 명령의 작업 디렉토리(cwd, `cd <dir>`, `git -C <dir>`)에서
`git rev-parse --git-common-dir`를 구해 config `issue_db.path`의 것과 같을 때만(그 worktree·읽기 스냅샷 포함) 적용한다.

**명령 파싱은 최선 노력**이다: `;`/`&&`/`||`/`|`/줄바꿈으로 이은 명령, `cd <dir>`(`cd -`·`pushd`·`popd`는 이 명령 글 안에서 따라간다.
bash 범위대로 — 서브셸·`$( )`·파이프 요소·`&` 백그라운드의 cd는 밖에 남지 않고, `&&`·`||` 뒤·분기·루프 안 cd는 전후 cwd를 모두
본다, 함수 본문 안 cd·짝 없는 `)`·`source`·셸 값 `eval`·`CDPATH`는 모르는 cwd를 더한다 — `_Walk`, H-A1 r6. 실패할 수 있거나
대상을 모르는 이동(빈 스택 popd·없는 경로·셸이 풀 경로 등)은 이전 cwd 후보를 버리지 않는다 — 모르는 디렉토리는 git 규칙이 판정하지
못하는 후보다, 회귀 수정 R1),
명령 앞의 셸 예약어(`if`·`then`·`do`·`{`·`!`·`function NAME`·`coproc`)·리디렉션(대상째 — `_strip_prefix`, H-A1 r5), 작은따옴표 밖
줄 이음(`\\` + 줄바꿈, bash처럼 지운다)·`$'…'`(풀어 읽는다 — `_shell_prep`, NUL 뒤는 버린다·서로게이트는 U+FFFD), 앞의 환경변수 대입(`GIT_DIR`·`GIT_WORK_TREE` 등은
레포 판별에 반영)과 래퍼(`WRAPPERS`: env·timeout·nice·ionice·stdbuf·sudo·setsid·time·exec·nohup·command·xargs(정적 인자만)),
`sh -c`/`bash -c`/`eval` 안쪽(중첩 한도 있음), `VAR=값` 대입 값 안의 `$( )`·백틱 본문, 셸(`SHELLS`)이 읽는 heredoc
본문(`bash <<EOF`·`cat <<EOF | sh`), 그 밖의 heredoc 본문 제외(heredoc은 인용·주석·산술 밖의 `<<`·`<<-`만, 끝 표시는 줄 전체가
같을 때만, 끝 표시가 없으면 빼지 않는다 — `_heredoc_scan`, H-A1 r6), 주석(인용 밖 단어 첫머리 `#`부터 줄 끝, 줄바꿈은 남김 —
`_strip_comments`) 제외. 변수 치환·별칭·인자 안의 `$( )`·백틱·`xargs -I{}` 항목·표 밖 래퍼·스크립트 파일 안의 git 호출은
보지 못한다.
규칙 7 publish는 낱말 그물 하나로 넓게 본다(ask 오판은 싸다, `word_net`): 명령 글 전체(heredoc 밖 줄 이음은 bash처럼 잇고 heredoc 본문 포함)에
이름 `db_pr`와 낱말 `publish`가 함께 있으면 ask다 — 인터프리터·`python3 -m`·변수·별칭·`$( )`·`-c`·heredoc과 무관. 검색·출력·
파일 받기(`NET_TEXT_CMDS`, git·gh는 아님 — 별칭·pager로 글을 실행한다)만인 줄과 그 줄이 연 heredoc 본문은 글로 보고 뺀다(그 줄에 `$( )`·백틱이 있거나 셸로 넘기면
(`echo "…" | bash`) 빼지 않음). 남는 한계: 낱말을 변수로 만들어 쓴 호출(`${P}lish`·`X=db; …/${X}_pr.py`)·인코딩, 스크립트 파일 안 호출(`bash push.sh`
— eval 채점기는 결과의 `"published": true`로도 센다), 사용자 셸 프로필의 별칭·함수. 반대로 db_pr 소스·문서를 sed·python으로
다루는 명령에 두 낱말이 함께 들면 ask 오판이다.
gh·MCP(규칙 11)는 cwd·대상 레포를 보지 않는 낱말 수준 판정이라 cd 따라가기와 무관하다(4-c — 병합 계열은 ask, Approve·기각은 거부).
진짜 강제는 git hook(pre-commit·pre-push)과 GHE 브랜치 보호다(모듈 스킬 레포도 브랜치 보호 승인 1, MODULE_SKILLS_PLAN_IMPL §4.5).

**설정 없음**: 사용자 config가 없거나 `issue_db.path`로 레포를 판별할 수 없으면 git·파일 규칙은 적용하지 않는다.
`issue_db.remote`가 없으면 11번을 적용하지 않는다. 있는데 owner/repo로 못 풀면(`userconfig.repo_slug`) 그 프로필의 11번이
꺼지므로 매번 경고한다(H-A1 r6 — `config.py init`·`set`은 거부, doctor `config` 행은 fail).
`tracker.mcp_server`와 `tracker.tools`가 모두 비어 있으면 설정 서버 규칙은 적용하지 않고 경고만 한다(이름 기반 거부는 적용). `tracker.read_tools`가 비어 있으면 그 서버 도구는
모두 거부한다. `tracker.write_tools`가 없으면 코멘트 예외가 없다(모든 Jira 쓰기 거부). 사용자 config가 없으면 승인 기록을 찾을 수
없으므로 코멘트 도구도 거부한다. hook은 모든 도구 호출에 걸리므로, `site-defaults.yaml`이 없어도 guard는 멈추지 않고 사용자 config만으로
판정한다(경고). 이때 커밋 검사(3·4번)가 부르는 스크립트는 종료 코드 2를 내므로 이슈 DB 커밋은 거부된다.
12번 (a)의 경로 조각 판정과 관리 clone git 판정은 사용자 config·issue_db.path가 없어도 적용한다. module_skills.remote가
owner/repo로 풀리지 않으면(file:// 제외) 매번 경고한다.

**의존성 없음**(`_degraded`): import 실패면 MCP는 거부, gh 호출마다 `_gh_kind`(설정·PyYAML 없이 돈다)의
거부 종류(Approve·기각·셸이 정한 동작·리뷰 별칭·보호 바꾸기 — `_gh_judged_deny`, `_gh_kind`가 예외면 `guard 내부 오류` 거부)와, 명령 걷기가 예외면 낱말 수준(따옴표를 뗀 명령 글에
`gh`와 `approve`·`dismiss`·`review … -…a`·보호·ruleset 쓰기·`--enable-auto-merge`·`--delete-branch-on-merge`·`allow_auto_merge`·`delete_branch_on_merge`·`enablePullRequestAutoMerge`·`merge … --auto` — `_text_unjudged_deny`)은 거부, 병합 계열과 Bash의 git·gh·`db_pr.py publish`·`merge`·
`request-review`·`module_eval.py`·`skill_patch.py --apply`(규칙 7·12와 같은 `word_net`)와 파일 도구는 ask, 그 밖의 Bash는 통과 + 경고.
degraded에서도 경로 조각 `_module-skills`(·`_module-skills.`로 시작) 파일 도구·Bash 쓰기는 ask가 아니라 deny.
**설정 읽기 오류**(사용자 config·site-defaults YAML 오류 — `Config`)도 의존성 없음과 같은 판정이다(설정을 고치는 Write·doctor를
막지 않게). **판정 중 예외**(검사 하나 — `_checked`, `_gh_kind`·`_json_obj`, 명령 걷기, `judge` 자체 — `RecursionError` 포함)는 그 호출을
거부한다(사유 `guard 내부 오류` — `INTERNAL_ERROR`, 4-c. 검사 예외면 다른 검사는 사유를 남기도록 이어 간다).
종료 코드는 그래도 0이다(2는 설치 명령까지 모든 Bash를 막는다). 출력은 ASCII JSON이고 판정·직렬화가 실패해도 거부를 낸다.
"""

from __future__ import annotations

import argparse
import bisect
import functools
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

# 의존성(PyYAML 등)이 없으면 import가 터진다. 종료 1(비차단 오류)로 끝나지 않게 받아 두고 `_degraded`로 판정한다.
try:
    from common import checks, mcptools, site_defaults, userconfig  # noqa: E402
    from common import issuepost  # noqa: E402
    import trackers  # noqa: E402
    IMPORT_ERROR: Exception | None = None
except ImportError as _exc:   # noqa: BLE001
    checks = mcptools = site_defaults = userconfig = issuepost = trackers = None   # type: ignore[assignment]
    IMPORT_ERROR = _exc

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
HOOKS_PATH_KEY = "core.hookspath"
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n", "|&", ";;"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
MAX_DEPTH = 3
# 다른 명령을 실행하는 앞 래퍼: 이름 → (값을 다음 토큰으로 받는 옵션, 옵션 뒤 건너뛸 위치 인자 수).
# 값이 붙은 옵션(`-oL`, `--signal=KILL`, `nice -5`)은 한 칸. 표 밖 래퍼(watch·flock 등)는 보지 못한다.
# xargs는 정적 인자만 본다(입력 항목은 모른다: `xargs -I{} git -C {} …`의 대상은 판정하지 못한다).
WRAPPERS = {
    "env": ({"-u", "--unset", "-C", "--chdir"}, 0), "command": (set(), 0), "builtin": (set(), 0),
    "nohup": (set(), 0), "setsid": (set(), 0), "exec": ({"-a"}, 0),
    "time": ({"-f", "--format", "-o", "--output"}, 0),
    "timeout": ({"-s", "--signal", "-k", "--kill-after"}, 1), "nice": ({"-n", "--adjustment"}, 0),
    "ionice": ({"-c", "--class", "-n", "--classdata"}, 0),
    "stdbuf": ({"-i", "-o", "-e", "--input", "--output", "--error"}, 0),
    "sudo": ({"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "--user", "--group", "--host",
              "--prompt", "--chdir"}, 0),
    # `-i`·`-l`·`-e`·`--replace`·`--eof`는 값을 붙여서만 받는다(다음 토큰을 먹지 않는다)
    "xargs": ({"-I", "-n", "-L", "-P", "-d", "-s", "-a", "-E", "--max-args", "--max-lines", "--max-procs",
               "--delimiter", "--arg-file", "--max-chars"}, 0),
}
CHDIR_OPTS = {"env": {"-C", "--chdir"}, "sudo": {"-D", "--chdir"}}
# 명령 낱말 찾기(H-A1 r5, 부류로 닫기): bash는 명령 앞의 예약어·리디렉션을 떼고 명령을 찾는다. `function NAME`·`coproc NAME {`는
# 이름까지 뗀다(`_strip_prefix`). `for`·`case`·`select` 머리는 명령이 아니다(`do`·`)` 뒤가 명령이다)
SHELL_RESERVED = {"if", "then", "elif", "else", "fi", "do", "done", "while", "until", "!", "{", "}", "esac"}
SHELL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# 리디렉션 토큰(`_tokens` 뒤): `>`·`>>`·`2>`·`2>&`·`>&2`·`&>`·`>|`·`<`·`<file`·`<<EOF`·`<<<w`·`{fd}>` … 대상이 붙었으면 1칸, 아니면
# 다음 토큰까지 2칸(`_redir_len`)
REDIR_RE = re.compile(r"^(?:(?:\{[A-Za-z_]\w*\}|\d+)?(?:<<<|<<-|<<|<>|<&|<|>>|>&|>\||>)|&>>|&>)(.*)$", re.DOTALL)
# 입력 쪽 리디렉션 토큰(연산자, 붙은 대상): `<`는 파일을 읽고, `<>`는 파일을 읽고 쓰기로 연다(O_RDWR|O_CREAT — 입력 파일이자 쓰기
# 대상), `<<`·`<<-`(heredoc 끝 표시)·`<<<`(here-string)·`<&`(fd 복제)는 파일이 아니다
IN_REDIR_RE = re.compile(r"^(?:\{[A-Za-z_]\w*\}|\d+)?(<<<|<<-|<<|<>|<&|<)(.*)$", re.DOTALL)
HERESTRING_RE = re.compile(r"^(?:\{[A-Za-z_]\w*\}|\d+)?<<<(.*)$", re.DOTALL)
# `_tokens`가 shlex 앞에 끼우고 뒤에서 되돌리는 표시: 셸이 풀지 않는 `$`·백틱(작은따옴표·`\` 안), 따옴표 밖 확장, 따옴표 밖
# 낱말 첫머리의 `~`(tilde 접두에 인용이 없다 — bash가 tilde로 푼다), 리디렉션 연산자에 공백 없이 붙은 fd(`2>`·`0<`·`{fd}<`),
# 따옴표 밖 `<<-`의 `-`(연산자 글자로 두어 `<<-`를 한 연산자로 읽는다 — `-`는 낱말 글자라 `<<`와 `-TAG`로 갈라졌다)
# `>&`·`<&` 바로 뒤 따옴표 밖 낱말 첫머리의 `-`(fd 닫기 — `>&-`는 한 연산자, 뒤 낱말은 복제 대상이 아니라 별도 인자다, `DUP_DASH`)
# 대입꼴 낱말(`NAME=`·`NAME+=` — 이름은 따옴표 없는 유효 이름) 값의 첫머리나 따옴표 밖 `:` 바로 뒤의 `~`(bash가 인자에서도 푼다:
# `env GIT_DIR=~-/.git`·`a=x:~-`. `--opt=~-`·`"a"=~-`·`a=x=~-`는 풀지 않는다, `TILDE_EQ` → `Word.atilde`)
# 인용(`'…'`·`"…"`·`$'…'`·따옴표 밖 `\\`) 안의 연산자 글자(`;&|()<>`) 앞에는 `QOP`(`'<pw>'`·`'<<'`·`\\<`는 연산자가 아니다 —
# `Word.op` 거짓. 토큰 나누기는 예전과 같다)
LIT_DOLLAR, LIT_TICK, BARE, TILDE_AT, FD_AT, HD_DASH, DUP_DASH, TILDE_EQ, QOP = (
    "\ue024", "\ue060", "\ue000", "\ue07e", "\ue03c", "\ue02d", "\ue02e", "\ue03d", "\ue03e")
QUOTED_OPS = ";&|()<>"
ASSIGN_HEAD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
# 공백 없이 리디렉션 연산자에 붙어 bash가 fd로 읽는 `{이름}`(bash 4.1+ — fd를 잡아 그 변수에 넣는다, `read_token_word`)
FD_NAME_RE = re.compile(r"^\{[A-Za-z_][A-Za-z0-9_]*\}$")
# `>&`·`<&`(앞 fd·`{이름}` 포함)만인 리디렉션 연산자(복제·닫기). 뒤 따옴표 밖 `-`(`DUP_DASH`)면 닫기이고 그 `-`는 연산자에 붙는다
DUP_OP_RE = re.compile(r"^(?:\{[A-Za-z_]\w*\}|\d*)(?:>&|<&)$")
ANSI_C = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
          "\\": "\\", "'": "'", '"': '"', "?": "?"}
# 짝 없는 서로게이트: 경로(`os.path.realpath`·`open`·subprocess)와 출력 인코딩이 예외를 낸다. 명령 글과 `$'…'` 해석 결과에서
# U+FFFD로 바꾼다(UTF-8 인코더가 셸에 넘길 때와 같다 — 회귀 수정 R2)
SURROGATE_RE = re.compile(r"[\ud800-\udfff]")

# 규칙 10: 로그 원문 통독 차단
RAW_ALWAYS_CMDS = {"cat", "tac", "nl", "less", "more", "bat", "strings", "zcat", "zless", "bzcat", "xzcat"}
RAW_NAMES = {"events.json", "events-full.json", "issue_raw.json", "match.json"}
# 개명 전 작업 파일(jira_raw.json 등)이 개발 PC의 옛 JOB에 남아 있을 수 있다 — 읽기 코드가 아니라 방어 목록이다
LEGACY_RAW_NAMES = {"jira_raw.json"}   # 개명 전 원문 파일만(jira.json·jira_meta.json은 마스킹본이라 새 이름처럼 대상 아님)
RAW_NAMES |= LEGACY_RAW_NAMES
RAW_EXEMPT_DIRS = {"fixtures", "draft"}
RAW_GLOB_MAX = 20
RAW_SNIFF_BYTES = 8192
RAW_SNIFF_LINES = 30
# 출력 리디렉션 토큰(`_tokens` 뒤 — 앞 fd는 숫자나 `{이름}`: `2>`·`{fd}>`·`>&2`·`&>>`·`>|` …)과 붙은 대상
REDIRECT_RE = re.compile(r"^(?:(?:\{[A-Za-z_]\w*\}|\d*)>&|&>>?|(?:\{[A-Za-z_]\w*\}|\d*)>>?\|?)(.*)$")
# 따옴표 밖 연산자 묶음(`>>`, `2>&`, `>|`, `&&`, `<<<`, `<<-`(`<<` + `HD_DASH`), `<(` …)을 하나씩 나눈다
PUNCT = ";&|()<>" + HD_DASH
OPS_RE = re.compile(rf">>\||>>|>&|>\||&>>|&>|<<<|<<{HD_DASH}|<<|<>|<&|\|\||&&|\|&|;;|[{re.escape(PUNCT)}]")
OP_CHARS = set(PUNCT)

# git 전역 옵션 중 값을 받는 것 (값이 다음 토큰)
GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                       "--super-prefix", "--list-cmds", "--attr-source"}
# git commit 옵션 중 값을 다음 토큰으로 받는 것
COMMIT_LONG_WITH_ARG = {"--message", "--file", "--author", "--date", "--template", "--reuse-message",
                        "--reedit-message", "--fixup", "--squash", "--cleanup", "--trailer", "--pathspec-from-file"}
COMMIT_SHORT_WITH_ARG = set("mFCct")
CONFIG_WITH_ARG = {"--file", "-f", "--blob", "--type", "--default", "--comment", "--value", "--fixed-value"}
CONFIG_READ_ACTIONS = {"get", "get-all", "get-regexp", "get-urlmatch", "get-color", "get-colorbool", "list",
                       "name-only", "show-origin", "show-scope"}
CONFIG_SUBCOMMANDS = {"get", "set", "unset", "list", "edit", "rename-section", "remove-section"}
GIT_CONFIG_ENV = {"GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL",
                  "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG"}


# -- 결정 --------------------------------------------------------------------------------


class Decision:
    def __init__(self):
        self.deny: list[str] = []
        self.ask: list[str] = []
        self.warn: list[str] = []

    def output(self) -> dict | None:
        if self.deny:
            return _decision("deny", "\n".join(dict.fromkeys(self.deny)))
        if self.ask:
            return _decision("ask", "\n".join(dict.fromkeys(self.ask)))
        return None


def _decision(kind: str, reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": kind,
                                   "permissionDecisionReason": f"[telephony-triage] {reason}"}}


# -- 설정 --------------------------------------------------------------------------------


def _c_text(s: str) -> str:
    """OS·셸이 보는 글: NUL 앞까지(C 문자열), 짝 없는 서로게이트는 U+FFFD."""
    return SURROGATE_RE.sub("\ufffd", s.split("\0", 1)[0])


def _norm(p: Path | str) -> str:
    """정규화한 실제 경로. NUL·인코딩할 수 없는 글자가 있으면(ValueError — UnicodeError 포함) OS가 보는 글(`_c_text`)로 정규화한다:
    예외 하나로 판정 전체가 내부 오류로 무너지지 않게(회귀 수정 R2 — 판정은 그 경로로 이어 간다)."""
    try:
        return os.path.normcase(os.path.realpath(str(p)))
    except ValueError:
        return os.path.normcase(os.path.realpath(_c_text(str(p))))


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


class GuardProfile:
    """플랫폼 경로 프로필 하나(17-platforms): clone·work_dir·base·원격. 사용자 config의 **모든** 프로필을 보호한다
    (`platform.enabled`·선택 플랫폼과 무관 — 플러그인을 두 벌 설치해도 서로 보호된다)."""

    def __init__(self, name: str, cfg: dict, has_user: bool):
        self.name = name
        self.clone = None
        self.clone_common = None
        self.work_dir = None
        self.exempt = None          # 규칙 8 제외 근거로 쓸 work_dir(절대 경로이고 어떤 clone도 포함하지 않을 때만, Config가 정한다)
        if has_user:
            db = cfg.get("issue_db") if isinstance(cfg.get("issue_db"), dict) else {}
            clone = db.get("path")
            if isinstance(clone, str) and clone.strip() and Path(clone).expanduser().is_dir():
                self.clone = Path(clone).expanduser()
                self.clone_common = _common_dir(self.clone)
            self.work_dir = Path(str(userconfig.get(cfg, "work_dir"))).expanduser()
        self.base = str(userconfig.get(cfg, "issue_db.base_branch") or "main")
        remote = userconfig.get(cfg, "issue_db.remote") if has_user else None
        self.has_remote = bool(str(remote or "").strip())     # 규칙 11 적용 조건(값만 본다 — owner/repo로 못 풀어도, 4-c)
        self._clone_git_dir: str | None = None

    def is_clone_body(self, cwd: Path) -> bool:
        """cwd가 이 프로필 clone 본체(작업 worktree·`_snapshot`이 아닌)인가. git dir(`<clone>/.git`)로 비교한다 —
        worktree의 git dir은 `<clone>/.git/worktrees/<이름>`이라 다르다."""
        if self.clone is None:
            return False
        if self._clone_git_dir is None:
            self._clone_git_dir = _git_dir(self.clone) or ""
        return bool(self._clone_git_dir) and _git_dir(cwd) == self._clone_git_dir


class Config:
    def __init__(self, plugin_root: str | None = None):
        self.warnings: list[str] = []
        try:
            defaults = site_defaults.load(Path(plugin_root) if plugin_root else None)
        except site_defaults.SiteDefaultsMissing:
            defaults = {}
            self.warnings.append("site-defaults.yaml이 없다 (S-3 미완료). 사용자 config만으로 판정한다.")
        self.plugin_root = plugin_root
        self._raw_sniffers: list | None = None
        self.raw_names, self.raw_exempt = self._raw_read(defaults)
        self.user = userconfig.load_user()
        self.cfg = userconfig.merged(defaults, self.user or {})
        cfgs = userconfig.profiles(defaults, self.user, invalid_names=True) if self.user else {userconfig.TOP_PROFILE: self.cfg}
        self.profiles = [GuardProfile(name, cfg, bool(self.user)) for name, cfg in cfgs.items()]
        # 잘못된 프로필도 보호 대상에는 넣는다. 다만 잘못된 work_dir(상대·빈 값·clone을 포함)은 규칙 8 제외 근거로 쓰지 않는다
        clones = [_norm(p.clone) for p in self.profiles if p.clone is not None]
        for p in self.profiles:
            raw = userconfig.get(cfgs[p.name], "work_dir")
            ok = isinstance(raw, str) and raw.strip() and os.path.isabs(os.path.expanduser(raw))
            if ok and not any(_inside(c, _norm(p.work_dir)) for c in clones):
                p.exempt = p.work_dir
        # 옛 설정 키(jira: 등)가 남아 있으면 규칙 2의 설정 서버가 비어 보인다 → check_mcp가 모든 MCP를 거부한다(fail-closed)
        self.legacy = userconfig.legacy_problems(defaults, self.user)
        # tracker.kind 오류(모르는 트래커·형식 오류·트래커 모듈을 못 불러옴)면 어느 트래커 규칙을 쓸지 모른다 → check_mcp가
        # 모든 MCP를 거부한다(fail-closed). 어떤 예외든 여기서 받는다: Config가 깨지면 파일·Bash 규칙까지 degraded(ask)로 약해진다
        self.tracker_error: str | None = None
        for c in [self.cfg, *cfgs.values()]:
            try:
                trackers.kind_of(c)
            except trackers.TrackerConfigError as exc:
                self.tracker_error = str(exc)
                break
            except Exception as exc:  # noqa: BLE001
                self.tracker_error = f"{type(exc).__name__}: {exc}"
                break
        problems = userconfig.profile_problems(self.user, defaults) if self.user else []
        # 원격이 있는데 owner/repo로 못 풀면 알린다(H-A1 r6. doctor `config` 행은 fail). 규칙 11은 원격 값만 보고 그대로 켠다(4-c)
        for key, remote in userconfig.remote_problems(defaults, self.user):
            self.warnings.append(f"{key}({remote})를 owner/repo로 풀 수 없다(규칙 11은 원격 값이 있으면 그대로 적용한다 — setup·"
                                 "db_pr이 그 원격을 쓰지 못할 수 있다). `config.py doctor`로 확인한다.")
        if problems:
            self.warnings.append("사용자 config 플랫폼 프로필 문제(보호는 유지, 잘못된 work_dir은 예외 근거로 쓰지 않는다): "
                                 + "; ".join(problems[:5]))
        # 규칙 12: 모든 플랫폼(층·이름 유효성과 무관)의 분석 스킬 소스
        self.skill_sources = _skill_sources(userconfig.analyzer_sources(defaults, self.user)) if self.user is not None else []
        # 규칙 12 (a)(b): 모듈 스킬 관리 clone·기록을 볼 work_dir — 모든 프로필 + 사용자 config가 없으면 기본 work_dir + 켠
        # 플랫폼의 기본 work_dir(사용자 프로필이 없어도 triage가 쓸 수 있다)
        mwd = [_norm(w) for w in self.work_dirs]
        extra = [userconfig.home() / "work"] if self.user is None else []
        site_platform = defaults.get("platform") if isinstance(defaults.get("platform"), dict) else {}
        enabled = site_platform.get("enabled") if isinstance(site_platform.get("enabled"), list) else []
        extra += [userconfig.home() / f"work-{p}" for p in enabled
                  if isinstance(p, str) and re.fullmatch(r"[a-z][a-z0-9_]*", p) and p != userconfig.TOP_PROFILE]
        for w in extra:
            if _norm(w) not in mwd:
                mwd.append(_norm(w))
        self.module_work_dirs: list[str] = mwd
        # 규칙 11 적용 조건: 모듈 스킬 원격 값이 있어도 켠다(값만 본다 — 4-c)
        self.module_remote = False
        for r in userconfig.module_remotes(defaults, self.user):
            self.module_remote = self.module_remote or bool(r.strip())
            local = r.strip().lower().startswith("file://") or os.path.isabs(os.path.expanduser(r.strip()))
            if not local and _repo_slug(r) is None:
                self.warnings.append(f"module_skills.remote({userconfig.redact_remote(r)})를 owner/repo로 풀 수 없다(규칙 11은 "
                                     "원격 값이 있으면 그대로 적용한다). `config.py doctor`로 확인한다.")
        top = self.profiles[0]            # 기본 플랫폼 프로필(옛 단일 프로필 속성)
        self.clone, self.clone_common, self.work_dir = top.clone, top.clone_common, top.work_dir
        self.base = top.base

    def _raw_read(self, defaults: dict) -> tuple[set, set]:
        """규칙 10 목록: 내장 ∪ site-defaults `guard.raw_read`. 잘못된 값은 경고하고 내장만 쓴다."""
        names, exempt = set(RAW_NAMES), set(RAW_EXEMPT_DIRS)
        guard = defaults.get("guard")
        site = guard.get("raw_read") if isinstance(guard, dict) else guard
        if site is None:
            return names, exempt
        ok = isinstance(site, dict) and set(site) <= {"names", "exempt_dirs"} and all(
            isinstance(site.get(k, []), list)
            and all(isinstance(v, str) and v and "/" not in v and "\\" not in v for v in site.get(k, []))
            for k in ("names", "exempt_dirs"))
        if not ok:
            self.warnings.append("site-defaults의 guard.raw_read가 {names: [문자열], exempt_dirs: [문자열]} 형식이 "
                                 "아니다. 내장 목록만 쓴다.")
            return names, exempt
        return names | set(site.get("names", [])), exempt | set(site.get("exempt_dirs", []))

    def raw_sniffers(self) -> list:
        """규칙 10 머리 판별: 설치된 플랫폼 **전부**(`platforms.known()`, 설정과 무관)의 원문 줄·묶음 입력 머리 판별 합집합.
        규칙 10 명령이 나올 때만 플랫폼 모듈을 불러온다. 플랫폼마다 따로 불러와 하나가 깨져도 나머지는 쓰고, 하나라도
        깨졌거나 레지스트리를 못 쓰면 경고하고 최소 내장 판별(`RAW_FALLBACK_SNIFFERS`)을 더한다 — 이전보다 약해지지 않는다."""
        if self._raw_sniffers is not None:
            return self._raw_sniffers
        sniffers: list = []
        broken = False
        try:
            import platforms
            finders, errors = platforms.known_raw_line_finders()
            for name, exc in errors:
                broken = True
                self.warnings.append(f"규칙 10: 플랫폼 {name}을(를) 불러오지 못해 내장 최소 판별로 대신한다 ({type(exc).__name__}: {exc})")
            for _name, raw_line, _find, sniff in finders:
                sniffers.append(raw_line)
                if sniff is not None:
                    sniffers.append(sniff)
        except Exception as exc:   # noqa: BLE001 — import·레지스트리 오류여도 hook은 멈추지 않는다
            broken = True
            self.warnings.append(f"규칙 10: 플랫폼 레지스트리를 쓰지 못해 내장 최소 판별만 쓴다 ({type(exc).__name__}: {exc})")
            sniffers = []
        if broken or not sniffers:
            sniffers += RAW_FALLBACK_SNIFFERS
        self._raw_sniffers = sniffers
        return sniffers

    @property
    def git_rules(self) -> bool:
        return any(p.clone_common is not None for p in self.profiles)

    @property
    def clones(self) -> list[Path]:
        return [p.clone for p in self.profiles if p.clone is not None]

    @property
    def work_dirs(self) -> list[Path]:
        return [p.work_dir for p in self.profiles if p.work_dir is not None]

    @property
    def rule11_on(self) -> bool:
        """규칙 11 적용 조건: 어느 프로필의 `issue_db.remote`나 모듈 스킬 원격 값이 있다(값만 본다 — owner/repo로 못 푸는 값도
        켠다, 닫힌 쪽. 거친 판정이라 대상 레포를 풀지 않는다, 4-c). 사용자 config가 없어도 site의 module_skills.remote는 본다."""
        return any(p.has_remote for p in self.profiles) or self.module_remote

    def is_clone_body(self, cwd: Path) -> bool:
        """cwd가 어느 프로필이든 사용자 clone 본체인가."""
        return any(p.is_clone_body(cwd) for p in self.profiles)

    def profile_of_common(self, common: str | None) -> GuardProfile | None:
        """git common dir이 같은 프로필(그 이슈 DB clone·worktree·스냅샷). 없으면 None."""
        if common is None:
            return None
        return next((p for p in self.profiles if p.clone_common is not None and p.clone_common == common), None)


def _skill_sources(sources: list[str]) -> list[str]:
    """규칙 12: 분석 스킬 `source` 값(`userconfig.analyzer_sources`) 중 절대 경로(`~` 허용)의 정규화 경로(중복 없이)."""
    out = []
    for src in sources:
        if isinstance(src, str) and src.strip() and os.path.isabs(os.path.expanduser(src)):
            norm = _norm(os.path.expanduser(src))
            if norm not in out:
                out.append(norm)
    return out


def _in_skill_source(target: str, conf: Config) -> bool:
    return any(_inside(target, src) for src in conf.skill_sources)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _common_dir(cwd: Path) -> str | None:
    if not cwd.is_dir():    # stat 오류(EACCES 등)는 올린다: 판정하지 못한 검사(`_checked` ask)다 — 레포가 아니라고 보지 않는다
        return None
    proc = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return _norm(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None


def _git_dir(cwd: Path) -> str | None:
    if not cwd.is_dir():
        return None
    proc = _git(cwd, "rev-parse", "--absolute-git-dir")
    return _norm(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None


def _repo_slug(value: str) -> tuple[str | None, str, str] | None:
    """원격 URL·`-R` 값을 `(host|None, owner, repo)`로 (`userconfig.repo_slug` — git SCP 꼴 `host:o/r` 포함, H-A1 r6)."""
    return userconfig.repo_slug(value)


# -- Jira (2) --------------------------------------------------------------------------------

OC_ADAPTER_ENV = "TT_OC_ADAPTER"      # OpenCode 어댑터(`common/oc_adapter.run_script`)가 guard를 부를 때 넣는다
JIRA_ISOLATION_ASK = ("Jira 읽기 결과 격리(규칙 9: PostToolUse `updatedToolOutput` 대체)가 이 Claude Code에서 동작하는지 아직 "
                      "확인되지 않았다(사내 확인 S1). 확인 전에는 {tool} 결과 원문이 모델 문맥·transcript에 남을 수 있다 — 그 위험을 "
                      "알고 읽을 때만 허용한다. S1에서 확인되면 site-defaults.yaml `tracker.isolation_confirmed: true`로 기록한다 "
                      "(그 뒤에는 묻지 않는다, 규칙 2).")


def check_mcp(tool: str, tool_input: dict, conf: Config, dec: Decision) -> None:
    if conf.legacy:
        dec.deny.append(f"옛 설정 키가 남아 있다: {'; '.join(conf.legacy[:3])} — config.py rename-legacy로 바꾼다 (규칙 2). "
                        f"{tool} 호출을 거부한다.")
        return
    if conf.tracker_error:
        dec.deny.append(f"트래커 설정 오류: {conf.tracker_error} — tracker.kind를 확인한다 (규칙 2). {tool} 호출을 거부한다.")
        return
    # Jira 서버 접두사: mcp_server ∪ tracker.tools 이름의 서버 (플러그인 번들 `mcp__plugin_…`도 덮는다). 넓을수록 안전 쪽
    prefixes = issuepost.jira_prefixes(conf.cfg)
    name = mcptools.normalize(tool)
    # 설정된 코멘트 도구는 read_tools보다 먼저 본다: read_tools에 넣어도 승인을 건너뛸 수 없다.
    # 설정이 무효(서버가 Jira 서버가 아님·단어 조건·read_tools에 있음 등)면 그 도구 호출은 거부한다(fail-closed)
    raw = issuepost.raw_tool(conf.cfg)
    if raw and name == raw:
        spec, err = issuepost.write_spec(conf.cfg, prefixes)
        if err or spec is None:
            dec.deny.append(f"Jira 코멘트 도구 설정 오류 (규칙 2): {err or '설정 없음'}. {tool} 호출을 거부한다.")
        else:
            check_jira_post(tool, tool_input, spec, conf, dec)
        return
    if prefixes and any(name.startswith(p) for p in prefixes):
        read_tools = userconfig.get(conf.cfg, "tracker.read_tools") or []
        if name not in {mcptools.normalize(t) for t in read_tools}:
            dec.deny.append(f"이 플러그인은 Jira 읽기 전용이다(예외: 승인한 코멘트 추가 1종, tracker.write_tools.add_comment). "
                            f"{tool}은(는) tracker.read_tools에 없어 거부한다 (규칙 2).")
        elif not userconfig.get(conf.cfg, "tracker.isolation_confirmed") and not os.environ.get(OC_ADAPTER_ENV):
            # 규칙 9(원문 격리)는 PostToolUse `updatedToolOutput` 대체에 기대고 미지원이면 열린다(원문이 모델 문맥에 남는다).
            # 사내 S1 확인 전에는 읽기마다 사람이 그 위험을 보고 허용한다. OpenCode 어댑터는 `after`가 결과를 직접 바꾸고 자체
            # 관문(`oc_jira_gate`)이 있어 묻지 않는다
            dec.ask.append(JIRA_ISOLATION_ASK.format(tool=tool))
        return
    if not prefixes:
        dec.warn.append("tracker.mcp_server가 비어 있어 Jira 읽기 전용 규칙을 적용하지 않았다 (setup 전).")
    hit = mcptools.NAME_RE.match(tool)
    srv, part = (hit.group(1), hit.group(2)) if hit else ("", tool)
    # 설정되지 않은 서버라도 이름에 트래커 서버 단어(설치된 모든 트래커의 합집합, kind와 무관: jira·atlassian …)가 들면
    # 쓰기형 도구는 거부한다 (서버 이름 휴리스틱). 레지스트리를 못 쓰면 내장 jira·atlassian — 이전보다 약해지지 않는다
    if any(w in srv.lower() for w in trackers.all_server_words()):
        if mcptools.is_write(part):
            dec.deny.append(f"Jira/Atlassian 서버의 쓰기형 도구는 설정 여부와 무관하게 거부한다 (규칙 2: {tool}).")
        return
    check_mcp_db_write(tool, part, tool_input, conf, dec)


def check_jira_post(tool: str, tool_input: dict, spec: dict, conf: Config, dec: Decision) -> None:
    """승인한 Jira 코멘트 게시 (규칙 2 예외). 승인 기록과 맞으면 ask(권한 확인은 그대로 뜬다), 아니면 deny.
    대조 중 예외도 deny다. "내부 오류"·"의존성 없음" 문구는 쓰지 않는다(doctor가 degraded 판별에 쓴다)."""
    try:
        # 프로필마다 승인 기록과 대조한다. 하나라도 맞으면 그 승인이다. 아니면 승인 기록이 있는 프로필의 문제를 보인다
        problems = []
        for prof in conf.profiles:
            got = issuepost.check_call(tool, tool_input, spec, prof.work_dir)
            if got is None:
                problems = []
                break
            key = issuepost.spec_tracker(spec).key_from_args(spec, tool_input)     # 경로 안전 작업 키 또는 None
            has_record = prof.work_dir is not None and isinstance(key, str) and issuepost.spec_tracker(spec).safe_key_re.fullmatch(key) \
                and (prof.work_dir / key / issuepost.APPROVED_FILE).is_file()
            problems.insert(0, got) if has_record else problems.append(got)
        problem = problems[0] if problems else None
    except Exception as exc:  # noqa: BLE001 — 판정하지 못하면 거부한다
        problem = f"승인 기록 판정 실패({type(exc).__name__})"
    if problem:
        dec.deny.append(f"Jira 코멘트는 확인 화면에서 승인한 본문만 올린다 (규칙 2): {problem}. "
                        "issue_post.py render → 승인 → approve부터 다시 한다.")
        return
    key = issuepost.spec_tracker(spec).key_from_args(spec, tool_input)
    sha = issuepost.body_sha256(tool_input[spec["body_arg"]])
    dec.ask.append(f"승인한 Jira 코멘트 게시다({key}, 본문 sha256 {sha[:12]}). 확인 화면의 본문과 같은지 보고 허용한다 (규칙 2).")


# 규칙 11 MCP 동작 인자 (키는 `_mcp_nkey`로 정규화 — 소문자, `_`·`-` 제거). TODO(SITE:S36) 사내 GHE MCP 서버의 쓰기 도구
# 이름과 동작 인자 이름을 `tools/list`·S1 실험 hook으로 확인해 이 목록을 보강한다(사외는 github-mcp-server 관측·추정).
MCP_ACTION_KEYS = {"event", "action", "method"}       # + 정규화 키가 `event`로 끝나는 칸(`review_event`·`reviewEvent`)


def _mcp_nkey(key) -> str:
    return re.sub(r"[_-]", "", str(key).lower())


def _mcp_keyed(obj, depth: int = 0) -> list[list[tuple[str, object]]]:
    """MCP 입력(깊이 3까지 dict·list)의 dict마다 `(정규화 키, 값)` 목록."""
    out: list[list[tuple[str, object]]] = []
    if depth > 3:
        return out
    if isinstance(obj, dict):
        out.append([(_mcp_nkey(k), v) for k, v in obj.items()])
        children = list(obj.values())
    elif isinstance(obj, list):
        children = obj
    else:
        return out
    for v in children:
        if isinstance(v, (dict, list)):
            out += _mcp_keyed(v, depth + 1)
    return out


def check_mcp_db_write(tool: str, part: str, tool_input: dict, conf: Config, dec: Decision) -> None:
    """비트래커 MCP 도구(규칙 11, 거친 판정 — 대상 레포를 보지 않는다): Approve·리뷰 기각·자동 병합 켜기(단어에 `auto`와
    `merge` — `AUTO_MERGE_DENY`, 원칙 12)는 거부, 병합은 ask(`MCP_MERGE_ASK`), 그 밖 쓰기형 도구(`mcptools.is_write`)는 ask. 거부·병합 낱말은 쓰기형 판정과 따로, 그보다 먼저 본다(H-A1
    r5 — `pr_approve`·`automerge_pr`처럼 쓰기 낱말로 잡히지 않는 이름): Approve는 어느 단어에든 `approve`가 들거나 입력의 동작 칸
    (`event`·`action`·`method`와 정규화 키가 `event`로 끝나는 칸, 깊이 3)이 approve…, 기각은 `dismiss`가 들거나 그 칸이 dismiss….
    병합은 동사 `merge`이거나 어느 단어에든 `merge`가 들고(`enable_pr_auto_merge`·`squash_and_merge`) 동사가 `disable`이 아닐 때,
    또는 입력 `action`·`method`가 merge…(`merge_method`는 보지 않는다). 동사가 읽기 동사(`get_merge_status`)면 이 낱말들을 보지
    않는다. `issue_db.remote`(·모듈 스킬 원격)가 없으면(setup 전) 보지 않는다."""
    if not conf.rule11_on or not isinstance(tool_input, dict):
        return
    layers = _mcp_keyed(tool_input)
    words, verb = mcptools._words(part), mcptools.verb(part)
    vals = [(k, v.strip().lower()) for layer in layers for k, v in layer
            if isinstance(v, str) and (k in MCP_ACTION_KEYS or k.endswith("event"))]
    acts = [v for _, v in vals]
    am = [v for k, v in vals if k in ("action", "method")]
    strong = verb not in mcptools.READ_VERBS
    if strong and (any("approve" in w for w in words) or any(v.startswith("approve") for v in acts)):
        dec.deny.append(f"{APPROVE_DENY}: {tool}).")
    elif strong and (any("dismiss" in w for w in words) or any(v.startswith("dismiss") for v in acts)):
        dec.deny.append(f"{DISMISS_DENY}: {tool}).")
    elif strong and verb != "disable" and any("auto" in w for w in words) and any("merge" in w for w in words):
        dec.deny.append(f"{AUTO_MERGE_DENY} ({tool})")
    elif strong and (verb == "merge" or (any("merge" in w for w in words) and verb != "disable")
                     or any(v.startswith("merge") for v in am)):
        dec.ask.append(MCP_MERGE_ASK.format(tool=tool))
    elif mcptools.is_write(part):
        dec.ask.append(f"원격을 바꾸는 MCP 도구다({tool} — 대상 레포를 보지 않는다, 이슈 DB가 아니어도 묻는다). 이슈 DB면 "
                       "변경·검증 결과를 보고 승인한 뒤에만 진행한다 (규칙 7·11).")


# -- 파일 도구 (8) -------------------------------------------------------------------------


POST_RECORDS = ("post.approved.json", "post.result.json")   # issue_post approve·jira_bridge만 쓴다 (규칙 2)
POST_RECORD_MSG = ("Jira 게시 승인·결과 기록은 issue_post.py approve와 jira_bridge(PostToolUse)만 쓴다. 직접 쓰거나 지우지 "
                   "않는다 (규칙 2")


def _post_record(target: str, conf: Config) -> bool:
    """어느 프로필이든 `<work_dir>/<KEY>/post.approved.json|post.result.json`인가 (target은 `_norm` 경로)."""
    p = Path(target)
    return p.name in POST_RECORDS and any(_norm(p.parent.parent) == _norm(w) for w in conf.work_dirs)


SCRIPT_RECORD_MSGS = {
    "merge": "병합 기록(merge-offer.json)은 db_pr publish·merge만 쓴다. 직접 쓰거나 지우지 않는다 (규칙 7",
    "patch": "스킬 제안 patch·기록(skill-suggestions/<이름>.patch·.meta.json)은 skill_patch.py만 쓴다. 직접 쓰거나 지우지 않는다 (규칙 12",
}


def _script_record(target: str, conf: Config) -> str | None:
    """스크립트만 쓰는 기록이면 거부 문구 머리: `<work_dir>/<KEY>/merge-offer.json`, `<work_dir>/<KEY>/skill-suggestions/<이름>.patch`·
    `<이름>.meta.json`(사본 폴더 `<이름>/<rel>`은 대상이 아니다). target은 `_norm` 경로."""
    p = Path(target)
    works = [_norm(w) for w in conf.work_dirs]
    if p.name == "merge-offer.json" and _norm(p.parent.parent) in works:
        return SCRIPT_RECORD_MSGS["merge"]
    if (p.parent.name == "skill-suggestions" and _norm(p.parent.parent.parent) in works
            and (p.name.endswith(".patch") or p.name.endswith(".meta.json"))):
        return SCRIPT_RECORD_MSGS["patch"]
    return None


MODULE_CLONE, MODULE_LOCK, SKILL_WT = "_module-skills", "_module-skills.lock", "skill-wt"
MODULE_CLONE_MSG = ("모듈 스킬 관리 clone·lock(<work_dir>/_module-skills/·_module-skills.lock)과 skill-wt는 도구가 직접 바꾸지 "
                    "않는다. 받기·갱신은 triage.py module만 한다 (규칙 12")
MODULE_RECORD_MSG = ("모듈 스킬 기록(module-skill.json·module-skill/·deep-input.json·skill-input.json·check-output.json)은 "
                     "triage.py만 쓴다. 직접 쓰거나 지우지 않는다 (규칙 12")
MODULE_GIT_MSG = ("모듈 스킬 관리 clone·skill-wt에서는 읽기 git(status·log·show·diff·ls-files 등)만 된다. 받기·갱신은 "
                  "triage.py module이 한다 (규칙 12: git {sub}).")
MODULE_GIT_PATH_MSG = "git의 경로 옵션({opt})이 모듈 스킬 관리 clone·기록을 가리킨다. 그 안은 triage.py module만 쓴다 (규칙 12)."
MODULE_NEEDLES = ("_module-skills", "module-skill", "deep-input.json", "skill-wt", "skill-input.json", "check-output.json")
MODULE_RECORD_FILES = (("module-skill.json",), ("deep-input.json",), ("skill-input.json",), ("check-output.json",))


def _module_name_part(path: str) -> bool:
    """경로 조각 하나라도 `_module-skills`이거나 `_module-skills.`로 시작(`.lock`·첫 받기 `.tmp-*`)하는가 — 설정과 무관."""
    return any(part == MODULE_CLONE or part.startswith(MODULE_CLONE + ".") for part in Path(path).parts)


def _rel_parts(target: str, work: str) -> tuple[str, ...] | None:
    if not _inside(target, work) or target == work:
        return None
    return Path(os.path.relpath(target, work)).parts


def _module_root(target: str, conf: Config) -> bool:
    """규칙 12 (a): 관리 clone·lock(이름 기반)과 `<work_dir>/<KEY>/skill-wt/**`인가 (target은 `_norm` 경로)."""
    if _module_name_part(target):
        return True
    for w in conf.module_work_dirs:
        rel = _rel_parts(target, w)
        if rel is not None and len(rel) >= 2 and rel[1] == SKILL_WT:
            return True
    return False


def _module_record(target: str, conf: Config) -> bool:
    """규칙 12 (b): `<work_dir>/<KEY>/module-skill.json`·`deep-input.json`·`skill-input.json`·`check-output.json`·
    `module-skill/**`(그 폴더 자체 포함)인가. work_dir 밖 오프라인 `--out` 작업은 보호하지 않는다."""
    for w in conf.module_work_dirs:
        rel = _rel_parts(target, w)
        if rel is not None and len(rel) >= 2 and (rel[1:] in MODULE_RECORD_FILES or rel[1] == "module-skill"):
            return True
    return False


def _in_clone(target: str, conf: Config) -> bool:
    """어느 프로필이든 clone 안이고, 그 clone **안에 들어 있는** (유효한) work_dir 안이 아닌가 (target은 `_norm` 경로).
    가장 구체적인 경로 기준이다: clone을 포함하는 work_dir은 그 clone의 보호를 풀지 못한다."""
    exempts = [_norm(p.exempt) for p in conf.profiles if p.exempt is not None]
    for clone in (_norm(c) for c in conf.clones):
        if not _inside(target, clone):
            continue
        if any(w != clone and _inside(w, clone) and _inside(target, w) for w in exempts):
            continue
        return True
    return False


GIT_META_MSG = ("이슈 DB 레포의 git 메타데이터(`.git` — ref·packed-refs·config, worktree의 `.git` 연결 파일)는 도구가 직접 쓰지 "
                "않는다 — 규칙 5의 ci_mode 근거 ref(origin/<base>)·원격을 바꿀 수 있다 (규칙 5·8")


def _db_git_meta(target: str, conf: Config) -> bool:
    """쓰기 대상(`_norm` 경로)이 이슈 DB 레포(clone·worktree·스냅샷 — git common dir로 본다)의 `.git`(파일·디렉토리) 안인가.
    clone 본체의 `.git/**`는 규칙 8도 거부한다 — 이것은 work_dir 아래 worktree의 `.git` 파일(`<clone>/.git/worktrees/…`를 가리킨다)을
    더한다."""
    parts = Path(target).parts
    if ".git" not in parts:
        return False
    return conf.profile_of_common(_common_dir(Path(*parts[:parts.index(".git")]))) is not None


def check_file(tool_input: dict, cwd: Path, conf: Config, dec: Decision) -> None:
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = cwd / path
    target = _norm(path)
    if _post_record(target, conf):
        dec.deny.append(f"{POST_RECORD_MSG}: {raw}).")
        return
    if _script_record(target, conf):
        dec.deny.append(f"{_script_record(target, conf)}: {raw}).")
        return
    if _module_root(target, conf):      # 규칙 12 (a) — 규칙 8의 work_dir 제외보다 먼저
        dec.deny.append(f"{MODULE_CLONE_MSG}: {raw}).")
        return
    if _module_record(target, conf):    # 규칙 12 (b)
        dec.deny.append(f"{MODULE_RECORD_MSG}: {raw}).")
        return
    if _in_clone(target, conf):
        dec.deny.append("이슈 DB clone은 도구가 직접 고치지 않는다. 직접 편집은 사용자가 한다 "
                        f"(규칙 8: {raw}). 도구 변경은 작업 계획과 db_pr stage로 작업 worktree에서 만든다.")
    elif _db_git_meta(target, conf):
        dec.deny.append(f"{GIT_META_MSG}: {raw}).")
    elif _in_skill_source(target, conf):
        dec.ask.append(f"{SKILL_SOURCE_ASK} ({raw})")


# -- Bash 명령 파싱 ------------------------------------------------------------------------


class _Heredoc:
    """`_heredoc_scan`이 찾은 heredoc 연산자 하나. `unit`: 연산자가 든 명령 줄(따옴표·줄 이음으로 여러 물리 줄일 수 있다),
    `found`: 끝 표시 줄을 찾았나, `lines`: 본문과 끝 표시의 물리 줄 번호(찾았을 때만), `op_pos`: 연산자(`<<`)의 글 위치."""
    __slots__ = ("tag", "quoted", "dash", "op_line", "op_pos", "unit", "body", "found", "lines")

    def __init__(self, tag: str, quoted: bool, dash: bool, op_line: int, op_pos: int = -1):
        self.tag, self.quoted, self.dash, self.op_line, self.op_pos = tag, quoted, dash, op_line, op_pos
        self.unit, self.body, self.found, self.lines = "", "", False, range(0)


def _heredoc_word(text: str, j: int) -> tuple[str, bool, int]:
    """`<<`·`<<-` 뒤(`j`)의 끝 표시 낱말 → (따옴표를 뗀 낱말, 인용했나, 다음 위치). bash처럼 `'…'`·`"…"`·`\\x`·`$'…'`을 풀고
    인용 밖 공백·`;&|()<>`·줄바꿈에서 멈춘다."""
    n = len(text)
    while j < n and text[j] in " \t":
        j += 1
    out, quoted = [], False
    while j < n and text[j] not in " \t\n;&|()<>":
        c = text[j]
        if c == "\\" and j + 1 < n:
            out.append(text[j + 1])
            quoted, j = True, j + 2
        elif c == "$" and text.startswith("$'", j):
            val, j = _ansi_c(text, j + 2)
            out.append(val)
            quoted = True
        elif c == "'":
            k = text.find("'", j + 1)
            k = n if k < 0 else k
            out.append(text[j + 1:k])
            quoted, j = True, k + 1
        elif c == '"':
            k, buf = j + 1, []
            while k < n and text[k] != '"':
                if text[k] == "\\" and k + 1 < n and text[k + 1] in '"\\$`\n':
                    buf.append(text[k + 1])
                    k += 2
                else:
                    buf.append(text[k])
                    k += 1
            out.append("".join(buf))
            quoted, j = True, k + 1
        else:
            out.append(c)
            j += 1
    return "".join(out), quoted, j


def _heredoc_bodies(text: str, pos: int, pending: list, unit: str, line_of) -> tuple[list, int]:
    """명령 줄 끝(`pos` = 줄바꿈 다음)에서 `pending` 연산자의 본문을 차례로 읽는다 → (처리한 연산자, 이어서 훑을 위치).
    끝 표시는 bash처럼 그 줄 전체가 낱말과 같을 때(`<<-`는 앞 탭만 뗀다)다. 끝 표시가 없으면 그 연산자부터는 본문이 없다
    (`found` 거짓)고 보고 본문이 될 뻔한 자리부터 다시 명령으로 훑는다(닫힌 쪽 — 뒤 줄을 지우지 않는다)."""
    n = len(text)
    for k, hd in enumerate(pending):
        hd.unit = unit
        start = p = pos
        while True:
            e = text.find("\n", p)
            line = text[p:] if e < 0 else text[p:e]
            if (line.lstrip("\t") if hd.dash else line) == hd.tag:
                hd.found, hd.body = True, text[start:max(start, p - 1)]
                hd.lines = range(line_of(start), line_of(p) + 1)
                pos = n if e < 0 else e + 1
                break
            if e < 0:
                for rest in pending[k + 1:]:
                    rest.unit = unit
                return pending, start
            p = e + 1
    return pending, pos


@functools.lru_cache(maxsize=64)
def _heredoc_scan(command: str) -> tuple[_Heredoc, ...]:
    """명령 글의 heredoc 연산자(나온 차례). bash처럼 인용(`'…'`·`"…"`·`$'…'`·`\\`) 밖·주석 밖·산술(`$(( ))`·`(( ))`) 밖의
    `<<`·`<<-`만 연산자로 본다(`<<<` here-string은 아니다). 인용 상태는 줄을 넘어 이어지고, `"$( … )"`·백틱 안은 다시 명령
    자리다. 본문은 연산자 뒤 첫 명령 줄 끝(인용 밖·줄 이음 아닌 줄바꿈) 다음 줄부터 끝 표시 줄까지다. `_strip_heredocs`·
    `_heredocs`·`word_net`·`_gh_hay`가 모두 이 탐지를 쓴다(H-A1 r6 — 인용·주석·here-string 안의 `<<WORD`와
    끝 표시 없는 연산자가 뒤 줄을 지워 모든 Bash 규칙을 피하던 부류를 닫는다)."""
    text, n = command, len(command)
    starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line_of(p: int) -> int:
        return bisect.bisect_right(starts, p) - 1

    out: list[_Heredoc] = []
    pending: list[_Heredoc] = []
    stack = [["cmd", 0]]
    unit_start, i = 0, 0
    while i < n:
        kind, c = stack[-1][0], text[i]
        if kind == "'":
            if c == "'":
                stack.pop()
            i += 1
            continue
        if kind == "arith":
            if c == "(":
                stack[-1][1] += 1
            elif c == ")" and stack[-1][1]:
                stack[-1][1] -= 1
            elif c == ")":
                stack.pop()
                i += 2 if text.startswith("))", i) else 1
                continue
            i += 1
            continue
        if c == "\\":
            i += 2              # `\x`·줄 이음(`\`+줄바꿈 — 명령 줄 끝이 아니다)
            continue
        if kind == "$'":
            if c == "'":
                stack.pop()
            i += 1
            continue
        if text.startswith("$((", i):
            stack.append(["arith", 0])
            i += 3
            continue
        if text.startswith("$(", i):
            stack.append(["subst", 0])
            i += 2
            continue
        if text.startswith("${", i):
            stack.append(["param", 0])
            i += 2
            continue
        if c == "`":
            if kind == "`":
                stack.pop()
            else:
                stack.append(["`", 0])
            i += 1
            continue
        if kind == '"':
            if c == '"':
                stack.pop()
            i += 1
            continue
        if text.startswith("$'", i):
            stack.append(["$'", 0])
            i += 2
            continue
        if c in "'\"":
            stack.append([c, 0])
            i += 1
            continue
        if kind == "param":
            if c == "{":
                stack[-1][1] += 1
            elif c == "}" and stack[-1][1]:
                stack[-1][1] -= 1
            elif c == "}":
                stack.pop()
            i += 1
            continue
        # 명령 자리(맨 위·`$( )`·백틱)
        if text.startswith("((", i):
            stack.append(["arith", 0])
            i += 2
            continue
        if kind == "subst" and c == "(":
            stack[-1][1] += 1
        elif kind == "subst" and c == ")":
            if stack[-1][1]:
                stack[-1][1] -= 1
            else:
                stack.pop()
        elif c == "#" and (i == 0 or text[i - 1] in " \t\n;&|("):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif text.startswith("<<", i):
            if text.startswith("<<<", i):
                i += 3
                continue
            dash = text.startswith("<<-", i)
            tag, quoted, j = _heredoc_word(text, i + (3 if dash else 2))
            if tag:
                pending.append(_Heredoc(tag, quoted, dash, line_of(i), i))
            i = max(j, i + 2)
            continue
        elif c == "\n":
            i += 1
            if pending:
                done, i = _heredoc_bodies(text, i, pending, text[unit_start:i - 1], line_of)
                out += done
                pending = []
                unit_start = i
            elif len(stack) == 1:
                unit_start = i
            continue
        i += 1
    for hd in pending:          # 명령 줄 끝 없이 글이 끝났다: 본문 없음
        hd.unit = text[unit_start:]
    return tuple(out + pending)


def _strip_heredocs(command: str) -> str:
    """heredoc 본문·끝 표시 줄을 뺀다(본문의 글자를 명령으로 읽지 않게). 끝 표시를 못 찾은 연산자는 아무 줄도 빼지 않는다."""
    drop = {k for hd in _heredoc_scan(command) if hd.found for k in hd.lines}
    if not drop:
        return command
    return "\n".join(line for k, line in enumerate(command.split("\n")) if k not in drop)


def _heredocs(command: str) -> list[tuple[str, str]]:
    """끝 표시를 찾은 heredoc마다 (연산자가 든 명령 줄, 본문). 본문 안의 heredoc은 그 본문을 다시 읽을 때 본다."""
    return [(hd.unit, hd.body) for hd in _heredoc_scan(command) if hd.found]


def _subst_bodies(value: str) -> list[str]:
    """글 안의 `$( … )`(괄호 짝을 센다)·`` `…` `` 본문."""
    out, i = [], value.find("$(")
    while i >= 0:
        depth, j = 1, i + 2
        while j < len(value) and depth:
            depth += {"(": 1, ")": -1}.get(value[j], 0)
            j += 1
        out.append(value[i + 2:j - 1] if not depth else value[i + 2:])   # 닫히지 않았으면 끝까지
        i = value.find("$(", j)
    return out + re.findall(r"`([^`]*)`", value)


def _strip_comments(command: str) -> str:
    """인용 밖에서 단어 첫머리의 `#`(줄 처음·공백·`;`·`&`·`|`·`(` 뒤)부터 줄 끝까지 주석을 뺀다. 줄바꿈은 남긴다(다음 줄은 다른
    명령이다 — `shown.strip_quoted`와 같은 규칙). `$#`·`${#x}`·`a#b`·인용 안 `#`·`\\#`은 그대로. `$'…'` 안은 `\\`가 다음 글자를
    막는다(`$'it\\'s'`)."""
    out, i, n, quote = [], 0, len(command), None
    while i < n:
        c = command[i]
        if c == "\\" and quote != "'" and i + 1 < n:
            out.append(command[i:i + 2])
            i += 2
            continue
        if quote:
            quote = None if c == quote[-1] else quote
        elif c == "$" and command[i + 1:i + 2] == "'":
            quote = "$'"
            out.append("$'")
            i += 2
            continue
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or command[i - 1] in " \t\n;&|("):
            j = command.find("\n", i)
            i = n if j < 0 else j
            continue
        out.append(c)
        i += 1
    return "".join(out)


class Word(str):
    """`_tokens`의 토큰. `dyn`: 셸이 풀 `$`·백틱이 있다(작은따옴표·`\\` 밖 — 값은 실행 때 정해진다). `bare`: 그중 따옴표 밖
    확장이 있다(낱말 나누기로 여러 인자·옵션이 될 수 있다). `tilde`: 따옴표 밖 첫 글자 `~`이고 tilde 접두(첫 `/`까지)에 인용이
    없다(bash가 tilde로 푼다 — `"~-"`·`\\~-`·`~"-"`는 글자 그대로). str 메서드와 겹치지 않는 이름만 쓴다."""
    dyn = False
    bare = False
    tilde = False
    op = False      # 따옴표 밖 연산자 글자로 된 토큰(리디렉션 연산자 등). 따옴표 친 `'<pw>'`는 아니다
    atilde: tuple = ()   # 대입꼴 낱말(`NAME=~-/x`·`NAME=a:~-`)의 값 안 tilde 자리(bash가 푼다 — 따옴표 밖·tilde 접두 인용 없음)


def _dyn(tok) -> bool:
    """셸이 풀 값인가. `Word`가 아니면(잘라 만든 글) `$`·백틱이 있는지로 본다(닫힌 쪽)."""
    return tok.dyn if isinstance(tok, Word) else ("$" in tok or "`" in tok)


def _split(tok) -> bool:
    """따옴표 밖 확장이 있나(여러 인자가 될 수 있다). `Word`가 아니면 `_dyn`."""
    return tok.bare if isinstance(tok, Word) else _dyn(tok)


def _ansi_c(text: str, i: int) -> tuple[str, int]:
    """`$'` 뒤(`i`)부터 닫는 `'`까지 ANSI-C 인용을 bash처럼 푼다 → (글, 닫는 `'` 다음 위치). 닫히지 않으면 끝까지.
    NUL(`\\0`·`\\000`·`\\x00`·`\\u0000`·`\\c@` 등)이 나오면 bash처럼 그 인용의 나머지를 버린다(`$'a\\0b'c`는 `ac` — C 문자열이 거기서
    끝난다). 서로게이트 코드 포인트(`\\ud800`)는 U+FFFD로 둔다(회귀 수정 R2 — NUL·짝 없는 서로게이트가 경로 연산·출력에서 예외를
    내 판정 전체가 내부 오류로 무너지던 부류)."""
    # 닫는 `'`는 bash 어휘 분석처럼 먼저 찾는다(`\\` 뒤 한 글자는 건너뛴다). 풀이는 그 안에서만 한다 — `\\c` 바로 뒤의 닫는 `'`를
    # 제어 문자 재료로 먹어 명령 글 끝까지 인용으로 삼키던 부류(e8f3342 회귀: `echo $'\\c'; git push …`가 판정 밖으로 빠졌다)
    end, n = i, len(text)
    while end < n and text[end] != "'":
        end += 2 if text[end] == "\\" else 1
    stop, n = min(end, n) + 1, min(end, n)
    out, cut = [], False
    while i < n:
        c = text[i]
        if c != "\\" or i + 1 >= n:
            ch, i = c, i + 1
        else:
            d = text[i + 1]
            octal = re.match(r"[0-7]{1,3}", text[i + 1:min(i + 4, n)])
            width = {"x": 2, "u": 4, "U": 8}.get(d)
            hexa = re.match(rf"[0-9A-Fa-f]{{1,{width}}}", text[i + 2:min(i + 10, n)]) if width else None
            if d in ANSI_C:
                ch, i = ANSI_C[d], i + 2
            elif octal:
                ch, i = chr(int(octal.group(), 8) & 0xFF), i + 1 + len(octal.group())
            elif hexa:
                ch, i = chr(min(int(hexa.group(), 16), 0x10FFFF)), i + 2 + len(hexa.group())
            elif d == "c" and i + 2 < n:          # bash `ansicstr`: `\cX` = 제어 문자, `\c\\`는 두 `\`를 함께 먹는다
                x = text[i + 2]
                i += 4 if x == "\\" and i + 3 < n and text[i + 3] == "\\" else 3
                ch = "\x7f" if x == "?" else chr(ord(x.upper()[:1] or x) & 0x1F)
            else:
                ch, i = c + d, i + 2              # 인용 끝의 `\c`도 글자 그대로(bash와 같다)
        if ch == "\0":
            cut = True
        if not cut:
            out.append(SURROGATE_RE.sub("\ufffd", ch))
    return "".join(out), min(stop, len(text))


def _shell_prep(text: str) -> str:
    """shlex 앞 손질(bash 낱말 규칙): 작은따옴표 밖 줄 이음(`\\` + 줄바꿈)은 지운다(`gh api \\⏎ -X PUT …`). `$'…'`은 풀어
    작은따옴표 글로 바꾸고 `$"…"`는 `"…"`로 본다. 셸이 풀지 않는 `$`·백틱(작은따옴표 안·`\\$`)은 `LIT_*`로, 따옴표 밖 `$`·백틱
    앞에는 `BARE`를 끼운다(`_word`가 되돌리며 `Word.dyn`·`bare`를 단다). 따옴표 밖 낱말 첫머리의 `~`(tilde 접두에 인용 없음) 앞에는
    `TILDE_AT`(`Word.tilde`), 공백 없이 `<`·`>` 앞에 붙은 fd 낱말(`2>`·`0<`·`{fd}<` — `_fd_word`) 뒤에는 `FD_AT`(`_tokens`가 연산자와
    붙인다)을 끼우고, `<<-`의 `-`는 `HD_DASH`(연산자 글자 — `<<-`가 한 연산자로 남는다)로 바꾼다. 따옴표 짝은 shlex와 같게 센다."""
    out, i, n, quote = [], 0, len(text), None
    wstart = 0                                  # 따옴표 밖 지금 낱말의 첫 글자 자리(대입꼴 `NAME=` 판정 — `TILDE_EQ`)
    while i < n:
        c = text[i]
        if quote == "'":
            quote = None if c == "'" else quote
            out.append(QOP + c if c in QUOTED_OPS else {"$": LIT_DOLLAR, "`": LIT_TICK}.get(c, c))
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            d = text[i + 1]
            if d != "\n":
                out.append(QOP + c + d if quote is None and d in QUOTED_OPS else {"$": LIT_DOLLAR, "`": LIT_TICK}.get(d, c + d))
            i += 2
            continue
        if quote == '"':
            quote = None if c == '"' else quote
            out.append(QOP + c if c in QUOTED_OPS else c)
        elif c == "$" and text[i + 1:i + 2] == "'":
            val, i = _ansi_c(text, i + 2)
            val = val.replace("'", "'\\''").replace("$", LIT_DOLLAR).replace("`", LIT_TICK)
            out.append("'" + re.sub(f"([{re.escape(QUOTED_OPS)}])", QOP + r"\1", val) + "'")
            continue
        elif c == "$" and text[i + 1:i + 2] == '"':
            pass                                   # `$"…"`(로캘 번역) = `"…"`
        elif c in "'\"":
            quote = c
            out.append(c)
        elif c in "$`":
            out.append(BARE + c)
        elif c == "~" and _word_start(text, i) and _tilde_plain(text, i + 1):
            out.append(TILDE_AT + c)
        elif c == "~" and _assign_tilde(text, wstart, i):
            out.append(TILDE_EQ + c)
        elif c == "-" and _word_start(text, i) and "".join(out[-8:]).rstrip(" \t")[-2:] in (">&", "<&"):
            out.append(DUP_DASH + c + " ")                  # `>&-`·`<&-`의 닫기 `-`: 연산자에 붙이고(`_tokens`) 공백으로 끊어
            # 나머지(`2>o`·`push`)는 bash처럼 새 토큰으로 다시 읽는다(`>&-2>o`는 닫기 + fd 리디렉션이라 인자가 아니다)
        elif c in "<>":
            fd = FD_AT if _fd_word(text, i) else ""
            if text.startswith(("<<<", "<<-"), i):          # `<<<`(here-string)·`<<-`(탭 떼는 heredoc)는 한 연산자다
                out.append(fd + ("<<<" if text[i + 2] == "<" else "<<" + HD_DASH))
                i += 3
                continue
            out.append(fd + c)
            wstart = i + 1
        else:
            out.append(" \n " if c == "\n" else c)     # 따옴표 밖 줄바꿈만 토큰(인용 안 줄바꿈은 글자 — `'a\⏎/'`)
            if c in WORD_GAP:
                wstart = i + 1
        i += 1
    return "".join(out)


WORD_GAP = " \t\r\n;&|()<>"     # 따옴표 밖에서 낱말을 끝내는 글자


def _back(text: str, j: int) -> int:
    """`text[j]`에서 뒤로 줄 이음(`\\`+줄바꿈 — 바로 앞 `\\`가 홀수 개)을 건너뛴 자리. bash는 어휘 분석 전에 줄 이음을 지우므로
    (`2\\⏎>f`는 `2>f`) 낱말·fd를 가를 때 앞 글자는 이 자리에서 본다(재리뷰 — 날 글의 줄바꿈을 낱말 끝으로 보던 부류)."""
    while j >= 1 and text[j] == "\n" and text[j - 1] == "\\":
        k = j - 1
        while k >= 0 and text[k] == "\\":
            k -= 1
        if (j - 1 - k) % 2 == 0:            # `\\\\⏎`: 막힌 `\\` 뒤의 줄바꿈 — 줄 이음이 아니다
            break
        j -= 2
    return j


def _word_start(text: str, i: int) -> bool:
    """`text[i]`가 따옴표 밖 낱말 첫 글자인가(앞이 글 처음이거나 낱말을 끝내는 글자 — 줄 이음은 건너뛴다)."""
    j = _back(text, i - 1)
    return j < 0 or text[j] in WORD_GAP


def _tilde_plain(text: str, j: int) -> bool:
    """`~` 뒤(`j`)부터 tilde 접두 끝(첫 `/`·낱말 끝)까지 인용 글자(`'`·`"`·`\\`)가 없나 — bash `bash_tilde_find_word`: 있으면 풀지 않는다.
    줄 이음(`\\`+줄바꿈)은 bash가 먼저 지우므로 인용이 아니다(`~\\⏎-` = `~-`)."""
    while j < len(text) and text[j] != "/" and text[j] not in WORD_GAP:
        if text[j] == "\\" and text[j + 1:j + 2] == "\n":
            j += 2
            continue
        if text[j] in "'\"\\":
            return False
        j += 1
    return True


def _assign_tilde(text: str, wstart: int, i: int) -> bool:
    """따옴표 밖 `text[i]`(`~`)가 대입꼴 낱말(`text[wstart:i]`가 `NAME=`·`NAME+=`로 시작 — 이름에 인용 없음) 값의 첫머리이거나 값 안
    따옴표 밖 `:` 바로 뒤이고 tilde 접두(`/`·`:`까지)에 인용이 없나 — bash는 이 `~`를 인자에서도 푼다(`env GIT_DIR=~-/.git`)."""
    head = ASSIGN_HEAD_RE.match(text, wstart)
    if not head or head.end() > i:
        return False
    k = _back(text, i - 1)                  # 줄 이음은 bash가 먼저 지운다(`a=\⏎~-`는 `a=~-`)
    if k + 1 != head.end() and not (k >= 0 and text[k] == ":" and (k < 1 or text[_back(text, k - 1)] != "\\")):
        return False
    j = i + 1
    while j < len(text) and text[j] not in "/:" and text[j] not in WORD_GAP:
        if text[j] == "\\" and text[j + 1:j + 2] == "\n":
            j += 2
            continue
        if text[j] in "'\"\\":
            return False
        j += 1
    return True


def _dup_close_before(text: str, j: int) -> bool:
    """`text[j]`(`-`) 바로 앞(공백·줄 이음 건너뛰고)이 `>&`·`<&`인가 — `>&-`·`<&-`(fd 닫기) 연산자의 닫기 `-`. bash는 닫기 뒤를
    새 토큰으로 읽으므로 그 `-`는 뒤 fd 낱말의 경계다(`>&-2>o`의 `2`는 새 fd)."""
    k = _back(text, j - 1)
    while k >= 0 and text[k] in " \t":
        k = _back(text, k - 1)
    if k < 1 or text[k] != "&":
        return False
    m = _back(text, k - 1)
    return m >= 0 and text[m] in "<>"


def _fd_word(text: str, i: int) -> bool:
    """`text[i]`(`<`·`>`) 바로 앞에 공백 없이 붙은 따옴표 밖 낱말이 bash가 fd로 읽는 꼴인가: 숫자들(`2>`·`0<`) 또는 `{이름}`(`{fd}<` —
    `FD_NAME_RE`). 줄 이음은 건너뛰고 본다(`2\\⏎>`). `2 >`·`a2>`·`"2">`·`\\2>`·`$x>`·`'{fd}'<`는 아니고, `>&`·`<&` 바로 뒤(사이 공백
    무관)의 낱말은 복제 대상이라 아니다(`2>&1</dev/null`의 `1` — bash `read_token_word`는 `>&` 다음 숫자를 대상으로 읽는다)."""
    chars, j = [], _back(text, i - 1)
    while j >= 0 and text[j] not in WORD_GAP:
        if text[j] == "-" and _dup_close_before(text, j):   # `>&-`·`<&-`의 닫기 `-`: 뒤 숫자는 새 fd 리디렉션이다(`>&-2>o`)
            break
        if not (text[j].isascii() and (text[j].isalnum() or text[j] in "_{}")):     # 인용·`$`·`/` 등: fd 꼴이 아니다
            return False
        chars.append(text[j])
        j = _back(text, j - 1)
    word = "".join(reversed(chars))
    if not ((word.isascii() and word.isdigit()) or FD_NAME_RE.match(word)):
        return False
    while j >= 0 and text[j] in " \t":
        j = _back(text, j - 1)
    k = _back(text, j - 1) if j >= 1 and text[j] == "&" else -1
    return not (k >= 0 and text[k] in "<>")


def _word(tok: str) -> Word:
    atilde: list[int] = []
    if TILDE_EQ in tok:             # 대입꼴 값 안 tilde 자리(표시를 뗀 낱말에서의 자리)
        n = 0
        for ch in tok:
            if ch == TILDE_EQ:
                atilde.append(n)
            elif ch not in (BARE, TILDE_AT, FD_AT, DUP_DASH, QOP):
                n += 1
    w = Word(tok.replace(BARE, "").replace(LIT_DOLLAR, "$").replace(LIT_TICK, "`").replace(TILDE_AT, "").replace(FD_AT, "")
             .replace(HD_DASH, "-").replace(DUP_DASH, "").replace(TILDE_EQ, "").replace(QOP, ""))
    w.atilde = tuple(atilde)
    w.bare = BARE in tok
    w.dyn = w.bare or "$" in tok or "`" in tok      # `LIT_*`가 아닌 `$`·백틱은 셸이 푼다
    w.tilde = tok.startswith(TILDE_AT)
    return w


def _tokens(command: str) -> list[str]:
    text = _shell_prep(_strip_comments(_strip_heredocs(command)))
    # `<`·`>`도 연산자 글자로 둔다: 공백 없이 붙은 리디렉션(`echo x>f`, `>>f`, `>|f`, `git</dev/null push`, `bash<<EOF`)을 따옴표
    # 밖에서만 나눈다(bash 어휘 분석과 같다 — 따옴표 안 `<`·`>`는 글자다).
    # 주석은 위에서 뺀다: shlex 기본 `commenters="#"`는 주석과 함께 줄바꿈 토큰까지 먹어 다음 줄 명령이 앞 argv에 붙는다
    lex = shlex.shlex(text, posix=True, punctuation_chars=PUNCT)
    lex.commenters = ""
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    try:
        raw = list(lex)
    except ValueError:   # 따옴표 불균형 등: 따옴표를 무시하고 연산자 글자에서도 나눈다(닫힌 쪽 — 가려진 명령을 찾는다)
        punct = re.escape(PUNCT)
        raw = [t.replace('"', "").replace("'", "")
               for t in re.findall(rf"\n|[{punct}]+|[^ \t\r\n{punct}]+", text.replace(QOP, ""))]
    out: list[str] = []
    ops: set[int] = set()       # 따옴표 밖 연산자 토큰의 자리(`Word.op` — 따옴표 친 `'<pw>'`는 연산자가 아니다)
    prev_op = False
    for tok in raw:
        quoted = QOP in tok                     # 인용 안 연산자 글자(`'<<'`): 나누기는 같게, `Word.op`만 거짓
        if quoted and set(tok) <= OP_CHARS | {QOP}:
            tok = tok.replace(QOP, "")
        if tok and set(tok) <= OP_CHARS:
            for op in OPS_RE.findall(tok):
                op = op.replace(HD_DASH, "-")
                fd = out[-1][:-1] if out and not prev_op and out[-1].endswith(FD_AT) else ""
                if op[0] in "<>" and ((fd.isascii() and fd.isdigit()) or FD_NAME_RE.match(fd)):
                    out[-1] = fd + op      # `2>`·`2>&`·`0<`·`{fd}<`: 공백 없이 붙은 앞 fd(`_fd_word`)
                else:
                    out.append(op)
                if not quoted:
                    ops.add(len(out) - 1)
                prev_op = True
        else:
            out.append(tok)
            prev_op = False
    # `>&-`·`<&-`(+fd·`{이름}`) 닫기: 뒤 낱말 첫머리의 닫기 `-`(`DUP_DASH`)는 연산자에 붙이고 나머지 글자는 별도 인자다
    # (bash: `2>&-push`→`['2>&-','push']`, `0<&-push`→`['0<&-','push']`). 복제 대상(`2>&1`)·따옴표 친 `-`는 그대로 둔다
    merged: list[str] = []
    mops: set[int] = set()
    for j, tok in enumerate(out):
        k = tok.find(DUP_DASH)
        if k == 0 and merged and DUP_OP_RE.match(merged[-1]):
            merged[-1] += "-"
            rest = tok[1:].replace("-", "", 1) if tok[1:2] == "-" else tok.replace(DUP_DASH, "", 1)
            if rest:
                merged.append(rest)
        else:
            merged.append(tok.replace(DUP_DASH, "") if k != -1 else tok)
            if j in ops:
                mops.add(len(merged) - 1)
    words = [_word(t) for t in merged]
    for j in mops:
        words[j].op = True
    return words


def _segments(tokens: list[str]) -> list[list[str]]:
    segs, cur = [], []
    for tok in tokens:
        if tok in SEPARATORS or (tok and set(tok) <= set(";&|()")):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        segs.append(cur)
    return segs


def _expand(word: str) -> str:
    return os.path.expanduser(os.path.expandvars(word))


def _redir_len(seg: list[str], i: int) -> int:
    """`seg[i]`가 리디렉션(`REDIR_RE`)이면 차지한 토큰 수(대상이 붙었으면 1, 다음 토큰이 대상이면 2), 아니면 0."""
    m = REDIR_RE.match(seg[i]) if i < len(seg) else None
    if not m:
        return 0
    return 1 if m.group(1) or i + 1 >= len(seg) else 2


def _drop_redirs(argv: list[str]) -> list[str]:
    """argv에서 리디렉션과 그 대상을 뺀다(bash는 명령에 넘기기 전에 뗀다). 따옴표 안 `">"`도 리디렉션으로 보므로 판정은 원래
    argv와 이 argv를 함께 본다(합집합 — 닫힌 쪽)."""
    out, i = argv[:1], 1
    while i < len(argv):
        n = _redir_len(argv, i)
        if not n:
            out.append(argv[i])
        i += n or 1
    return out


def _herestrings(argv: list[str]) -> list[str]:
    """argv의 here-string(`<<<w`·`<<< w`·`0<<<w`) 글. 셸(`-c` 없이)은 이 글을 stdin 스크립트로 읽는다(`bash <<<"gh pr merge 3"`)."""
    out = []
    for i, tok in enumerate(argv):
        m = HERESTRING_RE.match(tok)
        if m and (m.group(1) or i + 1 < len(argv)):
            out.append(m.group(1) or argv[i + 1])
    return out


def _bare_op(tok) -> bool:
    """`tok`이 따옴표 밖 연산자로 시작하는 리디렉션인가: `_tokens`의 토큰은 `Word.op`(따옴표 친 `'<pw>'`·`\\<%e`는 값이다). 잘라 만든
    글(`env -S` 풀이 등 — 인용을 모른다)은 연산자만인 토큰(`<`·`2>`)만 리디렉션으로 본다."""
    if isinstance(tok, Word):
        return tok.op
    m = REDIR_RE.match(tok)
    return bool(m) and not m.group(1)


def _opt_value(seg: list[str], j: int, redirs: list[str], opt_i: int) -> tuple[str | None, list[str], int]:
    """앞 래퍼 옵션의 값이 다음 낱말일 때(`env -C <dir>`·`sudo -D x`): 그 사이 리디렉션 토큰(대상째)을 `redirs`로 떼고 첫 비-리디렉션
    낱말을 값으로 본다(bash는 리디렉션을 먼저 뗀다 — `env -C </dev/null <dir> …`·붙은 `env -C</dev/null <dir>`도 값은 `<dir>`이다).
    → (값|None, redirs, 옵션 토큰부터 값까지 쓴 토큰 수). 값이 없으면 (None, …, 뗀 리디렉션까지)."""
    while j < len(seg):
        n = _redir_len(seg, j) if _bare_op(seg[j]) else 0
        if not n:
            return seg[j], redirs, j + 1 - opt_i
        redirs = redirs + seg[j:j + n]
        j += n
    return None, redirs, j - opt_i


def _strip_prefix(seg: list[str], cwd: Path) -> tuple[list[str], Path, dict]:
    """명령 낱말 앞의 것을 뗀다: `VAR=값`, 셸 예약어(`SHELL_RESERVED` — `if`·`then`·`do`·`{`·`!` …, `function NAME`,
    `coproc [NAME {]`), 리디렉션(`>/dev/null`·`2>&1`·`</dev/null` — 대상째), 래퍼(`WRAPPERS`: env·timeout·nice·sudo·xargs 등,
    옵션째). 더 뗄 것이 없을 때까지 되풀이한다(H-A1 r5 — 모르는 머리가 명령을 가리지 않게). `env -S`는 풀어 읽고,
    `env -C`·`sudo -D`는 작업 디렉토리로 반영한다. 뗀 `VAR=값`(래퍼 뒤의 것 포함)은 `env`로, 뗀 리디렉션은 argv 끝에 붙여
    돌려준다(규칙 8·10이 쓰기·입력 대상으로 본다)."""
    i = 0
    env: dict[str, str] = {}
    redirs: list[str] = []
    while i < len(seg):
        tok = seg[i]
        name = _base(tok)
        n = _redir_len(seg, i)
        if n:
            redirs += seg[i:i + n]
            i += n
            continue
        if tok in SHELL_RESERVED:
            i += 1
            continue
        if tok in ("function", "coproc"):
            i += 1
            if i < len(seg) and SHELL_NAME_RE.match(seg[i]) and (tok == "function" or seg[i + 1:i + 2] == ["{"]):
                i += 1           # `function NAME`·`coproc NAME {`의 이름
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            key, _, value = tok.partition("=")
            env[key] = value
            i += 1
            continue
        if name not in WRAPPERS:
            break
        with_arg, positional = WRAPPERS[name]
        i += 1
        while i < len(seg) and (seg[i].startswith("-") or _redir_len(seg, i)):
            n = _redir_len(seg, i)
            if n:
                redirs += seg[i:i + n]
                i += n
                continue
            opt = seg[i]
            if opt == "--":
                i += 1
                break
            # 값 받는 옵션(이름, 값, 차지한 토큰 수): 긴 옵션은 `--x=v`|`--x v`, 짧은 묶음(`-Eu x`, `-vS'…'`, `-C/dir`)은
            # 값 받는 첫 글자에서 멈추고 묶음 나머지가 값(없으면 다음 토큰)
            key, value, used = None, None, 1
            takes = with_arg | ({"-S", "--split-string"} if name == "env" else set())
            if opt.startswith("--"):
                key, eq, value = opt.partition("=")
                if not eq and key in takes:
                    value, redirs, used = _opt_value(seg, i + 1, redirs, i)   # 값은 다음 낱말(사이 리디렉션은 뗀다)
                elif not eq:
                    value, used = None, 1
            else:
                for k, ch in enumerate(opt[1:], 1):
                    if "-" + ch in takes:
                        key, value = "-" + ch, opt[k + 1:]
                        if not value:                                          # 묶음 끝: 값은 다음 낱말(사이 리디렉션은 뗀다)
                            value, redirs, used = _opt_value(seg, i + 1, redirs, i)
                        break
            if key in ("-S", "--split-string") and value is not None:
                try:
                    split = shlex.split(value)
                except ValueError:
                    split = value.split()
                seg = seg[:i] + split + seg[i + used:]
                continue   # 풀린 토큰을 다시 옵션·명령으로 읽는다
            if key in CHDIR_OPTS.get(name, set()) and value:
                d = _expand(value)
                cwd = Path(d) if Path(d).is_absolute() else cwd / d
            i += used
        skip = positional
        while skip and i < len(seg):      # 래퍼 위치 인자(`timeout 5`) — 사이의 리디렉션은 뗀다
            n = _redir_len(seg, i)
            redirs += seg[i:i + n]
            i += n or 1
            skip -= 0 if n else 1
    return seg[i:] + redirs, cwd, env


def _base(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


# 규칙 7 낱말 그물(L M-2): 이 명령만인 줄(과 그 줄이 연 heredoc 본문)은 글로 본다 — 검색·출력·파일 받기.
# git·gh는 넣지 않는다: `git -c alias.p='!…'`·`core.pager`·`GIT_SSH_COMMAND`·`gh alias set`으로 글을 실행할 수 있다
NET_TEXT_CMDS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "echo", "printf", "cat", "tee"}


def _text_only(line: str) -> bool:
    try:
        names = [_base(i.argv[0]) for i in invocations(line, Path("."))]
    except Exception:  # noqa: BLE001 — 못 읽으면 남긴다(넓게 본다)
        return False
    return bool(names) and all(n in NET_TEXT_CMDS for n in names)


def word_net(command: str, name: str = "db_pr", word: str = "publish") -> bool:
    r"""규칙 7(과 show_guard pre-bash, ②)의 호출 판정: 남은 명령 글에 이름 `name`과 낱말 `word`가 함께 있다.
    heredoc 본문 밖의 줄 이음(`\` + 줄바꿈)은 bash처럼 빈 글로 잇고, 줄마다 그 줄이 연 heredoc 본문을 붙인다(heredoc은
    `_heredoc_scan` — 인용·주석·here-string 안의 `<<`는 연산자가 아니다, 끝 표시는 원래 줄에서 찾는다 — 본문 끝 줄의 `\`가
    끝 표시를 삼키지 않게). 주석을 뺀 줄이 `$(`·백틱 없이 NET_TEXT_CMDS만이고
    셸로 넘기지 않으면(`echo … | bash`는 넘김) 그 줄과 본문을 뺀다. 끝 표시가 없는 heredoc을 연 줄은 빼지 않는다.
    남은 글 그대로, 거기서 `\` + 줄바꿈·`'`·`"`·`\`·`$'`의 `$`를 지운 글(`pub"lish"`·`db\_pr`·`pub$'l'ish`), 인용·`\` 바로
    앞의 `$VAR`를 `/`로 바꾸고 지운 글(`"$S"d""b_pr` — 지우기만 하면 `$Sdb_pr`가 된다) 중 어느 것에든 있으면 있다.
    이름은 앞이 글자·`.`·`-`가 아니고 뒤가 글자·`-`가 아니다(`test_db_pr.py`·`ws.db_pr(`·`dbpr/` 아님). 낱말은 앞이
    글자·`.`가 아니고 뒤가 글자·`.`·`-`가 아니다(`publish.py`·`publish.json`·`publish-preview`·`_publish`·`published`
    아님, `${P:-publish}`는 맞다)."""
    docs = _heredoc_scan(command)
    body = {k for hd in docs if hd.found for k in hd.lines}
    lines, kept, i = command.split("\n"), [], 0
    while i < len(lines):
        if i in body:          # 본문은 연산자를 연 줄에 붙여 본다
            i += 1
            continue
        first, raw, i = i, lines[i], i + 1
        while raw.endswith("\\") and i < len(lines) and i not in body:   # bash 줄 이음: 빈 글로 잇는다(`pub\⏎lish` = publish)
            raw, i = raw[:-1] + lines[i], i + 1
        mine = [hd for hd in docs if first <= hd.op_line < i]
        open_end = any(not hd.found for hd in mine)    # 끝 표시 없음: 본문으로 빼지 않고 이 줄도 남긴다(넓게 본다)
        line = _strip_comments(raw)
        if (open_end or "$(" in line or "`" in line or _feeds_shell(line, Path("."))
                or not _text_only(line)):
            kept += [line, *(lines[k] for hd in mine if hd.found for k in hd.lines)]
    text = "\n".join(kept)
    joined = re.sub(r"\\\n", "", text)
    unquote = re.compile(r"""\$(?=['"])|["'\\]""")
    texts = (text, unquote.sub("", joined), unquote.sub("", re.sub(r"""\$\w+(?=["'\\])""", "/", joined)))
    return (any(re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-])", t) for t in texts)
            and any(re.search(rf"(?<![\w.]){re.escape(word)}(?![\w.-])", t) for t in texts))


class Invocation:
    def __init__(self, cwd: Path, argv: list[str], env: dict | None = None):
        self.cwd = cwd
        self.argv = argv
        self.env = env or {}   # 앞의 `VAR=값` 대입


# stdin을 스크립트로 읽는 경로(`bash /dev/stdin`·`source /proc/self/fd/0`)
STDIN_PATHS = {"/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}
# 자식 셸 종류: dash(이 머신의 /bin/sh)는 dir-stack tilde(`~-`·`~+`·`~N`)를 풀지 않는다(`sh -c 'cd ~-'`는 실패, cwd 그대로 —
# 확인함). zsh·ksh는 이 머신에 없어 확인하지 못했다: tilde도 글자 그대로일 수 있고, 시작할 때 OLDPWD를 물려받지 않을 수 있다
# (자기 cwd·모르는 디렉토리도 후보 — 닫힌 쪽)
POSIX_SHELLS = {"sh", "dash", "ksh", "zsh"}
UNSURE_OLDPWD_SHELLS = {"ksh", "zsh"}


def _worst_shell(names) -> str | None:
    """여러 자식 셸 후보 중 가장 덜 확실한 것(zsh·ksh > sh·dash > bash) — 판정은 그 셸로 넓게 본다."""
    names = set(names)
    if names & {"zsh", "ksh"}:
        return "zsh"
    if names & {"sh", "dash"}:
        return "sh"
    return "bash" if names - {"source", "."} else None     # `source`·`.`만이면 이 셸(None)


def _shell_reads_stdin(rest: list[str]) -> bool:
    """셸(`SHELLS`) argv의 명령 이름 뒤(`rest`, 리디렉션 뺌)로 보아 stdin을 스크립트로 읽나: `-c`가 없고 스크립트 파일 인자가 없거나
    (`-s`면 남은 인자는 위치 인자다) 그 인자가 stdin 경로(`STDIN_PATHS`)다. 값 받는 옵션(`-o`·`+o`·`-O`·`+O`·`--rcfile`·`--init-file`)의
    값과 `+x` 같은 끄기 묶음은 스크립트 파일이 아니다. `-`·`--` 뒤 첫 인자가 스크립트 파일이다."""
    i = 0
    while i < len(rest):
        t = str(rest[i])
        if t in ("-", "--"):
            i += 1
            break
        if t in ("--rcfile", "--init-file"):
            i += 2
            continue
        if t.startswith("--"):
            i += 1
            continue
        if len(t) > 1 and t[0] in "-+":
            if t[0] == "-" and "c" in t[1:]:
                return False
            if t[0] == "-" and "s" in t[1:]:
                return True
            i += 1 + sum(ch in "oO" for ch in t[1:])
            continue
        break
    return i >= len(rest) or str(rest[i]) in STDIN_PATHS


def _stdin_reader(seg: list[str]) -> str | None:
    """이 단순 명령이 stdin을 스크립트로 읽어 실행하면 그 셸 이름(`source`·`.`은 그 이름): `-c` 없는 셸이 스크립트 파일 인자 없이
    (또는 `-s`·stdin 경로), `source`·`.`가 stdin 경로를 읽을 때. `grep`·`cat`·`wc` 등은 아니다(글만 처리) → None."""
    try:
        s2, _, _ = _strip_prefix(list(seg), Path("."))
    except Exception:  # noqa: BLE001
        return None
    if not s2:
        return None
    name = _base(s2[0])
    rest = _drop_redirs(s2)[1:]
    if name in SHELLS:
        return name if _shell_reads_stdin(rest) else None
    if name in ("source", ".") and rest and str(rest[0]) in STDIN_PATHS:
        return name
    return None


PRINTF_CONV_RE = re.compile(r"%([-+ #0']*)(\*|\d+)?(?:\.(\*|\d*))?([diouxXfFeEgGaAcsbq%])")


def _bs_unescape(text: str, b_arg: bool = False) -> str:
    """printf 서식(`b_arg` 거짓)·`%b` 인자·`echo -e`의 `\\` 이스케이프를 푼다(`\\n`·`\\t`·`\\\\`·8진·`\\xHH`·`\\uHHHH`). 모르는 꼴은
    글자 그대로. `\\c`(뒤 출력 멈춤)는 무시한다(뒤 글도 본다 — 닫힌 쪽)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        d = text[i + 1]
        octal = re.match(r"0?[0-7]{1,3}" if b_arg else r"[0-7]{1,3}", text[i + 1:i + 5])
        hexa = re.match(r"[0-9A-Fa-f]{1,2}", text[i + 2:i + 4]) if d == "x" else None
        uni = re.match(r"[0-9A-Fa-f]{1,8}" if d == "U" else r"[0-9A-Fa-f]{1,4}", text[i + 2:i + 10]) if d in "uU" else None
        if d in ANSI_C and d != "?":
            out.append(ANSI_C[d])
            i += 2
        elif d == "c":
            i += 2
        elif octal:
            out.append(chr(int(octal.group(), 8) & 0xFF))
            i += 1 + len(octal.group())
        elif hexa:
            out.append(chr(int(hexa.group(), 16)))
            i += 2 + len(hexa.group())
        elif uni:
            out.append(SURROGATE_RE.sub("�", chr(min(int(uni.group(), 16), 0x10FFFF))))
            i += 2 + len(uni.group())
        else:
            out.append(c + d)
            i += 2
    return "".join(out).replace("\0", "")


def _printf_render(fmt: str, args: list[str]) -> str | None:
    """bash printf 출력을 정적으로 만든다: 서식의 `\\` 이스케이프를 풀고, 인자가 남는 동안 서식을 되풀이해(bash와 같다) `%s`·`%b`·
    `%q`·`%d` 등 변환에 인자를 넣는다. 폭(공백 채움)은 셸 낱말을 바꾸지 않아 무시한다. 모르는 변환이면 None."""
    out: list[str] = []
    ai = 0
    for _ in range(len(args) + 1):
        i, used = 0, False
        while i < len(fmt):
            c = fmt[i]
            if c == "\\":
                m = re.match(r"\\(?:[0-7]{1,3}|x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|.)", fmt[i:], re.DOTALL)
                piece = m.group() if m else "\\"
                out.append(_bs_unescape(piece))
                i += len(piece)
                continue
            if c != "%":
                out.append(c)
                i += 1
                continue
            m = PRINTF_CONV_RE.match(fmt, i)
            if not m:
                return None
            i = m.end()
            conv, prec = m.group(4), m.group(3)
            if conv == "%":
                out.append("%")
                continue
            for g in (m.group(2), prec):
                if g == "*":
                    ai, used = ai + 1, used or ai < len(args)
            a = args[ai] if ai < len(args) else None
            if a is not None:
                ai, used = ai + 1, True
            a = "" if a is None else str(a)
            if conv in "sbq":
                v = _bs_unescape(a, True) if conv == "b" else (shlex.quote(a) if conv == "q" and a else a)
                if prec and prec != "*":
                    v = v[:int(prec)]
                out.append(v)
            elif conv == "c":
                out.append(a[:1])
            else:
                out.append(a or "0")
        if ai >= len(args) or not used:
            break
    return "".join(out)


def _producer_texts(seg: list[str]) -> list[str]:
    """파이프 앞 요소가 내보내는 글(셸에 넘겨 실행될 스크립트): `echo`(`-e`면 이스케이프를 푼 글도), `printf`(서식을 인자마다
    되풀이한 출력 — `_printf_render`. 못 만들면 인자 하나씩·인자를 줄로 이은 글·변환을 지운 서식의 합), `cat`·`tac`의 here-string.
    셸이 풀 값(`$N`)이 든 글도 그대로 낸다 — 자식 셸이 다시 읽으므로 `bash -c "…$N"`처럼 셸 값으로 판정한다(약한 경로를 만들지 않는다)."""
    try:
        s2, _, _ = _strip_prefix(list(seg), Path("."))
    except Exception:  # noqa: BLE001
        return []
    if not s2:
        return []
    name = _base(s2[0])
    rest = [str(t) for t in _drop_redirs(s2)[1:]]
    if name == "echo":
        k = 0                                   # 앞 옵션(`-n`·`-e`·`-E` 묶음). `-e`가 없어도(xpg_echo) 이스케이프를 푼 글도 본다
        while k < len(rest) and len(rest[k]) > 1 and rest[k][0] == "-" and set(rest[k][1:]) <= set("neE"):
            k += 1
        text = " ".join(rest[k:])
        return list(dict.fromkeys([text, _bs_unescape(text, True)]))
    if name == "printf":
        if rest[:1] == ["-v"] or (rest and rest[0].startswith("-v")):
            return []                           # `printf -v 변수`: 출력이 없다
        if rest[:1] == ["--"]:
            rest = rest[1:]
        if not rest:
            return []
        fmt, args = rest[0], rest[1:]
        got = _printf_render(fmt, args)
        if got is not None:
            return [got]
        stripped = PRINTF_CONV_RE.sub(" ", _bs_unescape(fmt))
        return list(dict.fromkeys([*args, "\n".join(args), stripped]))
    if name in ("cat", "tac"):
        return _herestrings(s2)
    return []


def _fed_pipe_texts(toks: list[str]) -> list[tuple[int, list[str], str]]:
    """파이프로 셸에 넘겨 실행되는 글: `echo "…" | bash`·`printf … | sh`·`cat <<<"…" | bash`·`echo … | cat | bash`·
    `echo … | bash 2>&1 | cat`·`echo … |& bash`·`(echo …) | bash`·`echo … | source /dev/stdin` → (파이프 묶음의 첫 토큰 자리, 글들,
    읽는 셸 종류 — `_worst_shell`, `source`·`.`은 bash 쪽). 파이프 요소는 서브셸이라 그 글은 묶음이 시작할 때의 cwd·OLDPWD에서 돌고 cd는 밖으로 새지 않는다.
    stdin을 읽는 셸 앞의 요소가 낸 글을 모두 본다. 브레이스 그룹(`{ …; } | bash`)·셸이 만드는 글(`eval "$(cat)"`)은 보지 않는다(남는 한계)."""
    out: list[tuple[int, list[str], str]] = []
    pipeline: list[list[str]] = []
    cur: list[str] = []
    start = None

    def flush() -> None:
        elems = pipeline + ([cur] if cur else [])
        texts: list[str] = []
        readers: set[str] = set()
        for i in range(1, len(elems)):
            reader = _stdin_reader(elems[i])
            if reader is None:
                continue
            readers.add(reader)
            for pseg in elems[:i]:
                texts += _producer_texts(pseg)
        texts = [t for t in dict.fromkeys(texts) if t.strip()]
        if texts and start is not None:
            out.append((start, texts, _worst_shell(readers)))

    for idx, tok in enumerate(toks):
        # 서브셸 괄호(`(echo …) | bash`)는 파이프 묶음을 끊지 않는다. 낱말 뒤 `(`(`$(`·`f()`)와 뒤가 파이프가 아닌 `)`(case 갈래
        # `a) echo … | bash`·`$( … )` 끝)는 묶음 경계다
        if tok == "(" or tok == ")":
            nxt = toks[idx + 1] if idx + 1 < len(toks) else None
            if cur if tok == "(" else nxt not in PIPE_OPS:
                flush()
                pipeline, cur, start = [], [], None
            continue
        if tok in PIPE_OPS:
            pipeline.append(cur)
            cur = []
        elif _is_sep(tok):                      # `;`·`&&`·`||`·`&`·줄바꿈·`;;`
            flush()
            pipeline, cur, start = [], [], None
        else:
            if start is None:
                start = idx
            cur.append(tok)
    flush()
    return out


def _feeds_shell(line: str, cwd: Path) -> bool:
    """heredoc이 시작된 줄에 stdin을 스크립트로 읽는 명령이 있다: `-c` 없는 셸(`SHELLS` — `bash <<EOF`·`cat <<EOF | sh`)이나 stdin
    경로를 읽는 `source`·`.`(`source /dev/stdin <<EOF`). `-c`는 리디렉션과 그 대상을 뺀 argv에서 찾는다(`bash << -c`·`bash <<-cmds`의
    끝 표시는 옵션이 아니다 — 재리뷰 P0). 줄을 풀다 예외가 나면 있다고 본다(닫힌 쪽 — 본문을 명령으로 보고, 낱말 그물은 그 줄을
    빼지 않는다)."""
    try:
        for seg in _segments(_tokens(line)):
            seg, _, _ = _strip_prefix(seg, cwd)
            if seg and _base(seg[0]) in SHELLS and not any(
                    t.startswith("-") and not t.startswith("--") and "c" in t[1:] for t in _drop_redirs(seg)[1:]):
                return True
            if seg and _base(seg[0]) in ("source", ".") and _stdin_reader(seg):
                return True
    except Exception:  # noqa: BLE001
        return True
    return False


# `cd -`·`popd` 등 따라갈 수 없는 디렉토리(`$`가 든 이름 — 어느 레포도 아니다). git 규칙은 이 후보를 판정하지 못하므로 이 후보로
# 옮길 때 이전 후보를 버리지 않는다(`_Walk.cd`, 회귀 수정 R1)
UNKNOWN_DIR = Path("$OLDPWD")


def _backstop(seg: list[str]) -> list[int]:
    """명령 낱말이 gh·git이 아닌데(글 명령 `NET_TEXT_CMDS` 제외) 뒤에 예약어나 리디렉션 바로 다음의 `gh`·`git` 토큰이 있으면 그
    자리들(닫힌 쪽 — `_strip_prefix`가 모르는 머리 뒤에 숨은 호출을 따로 본다)."""
    if not seg or _base(seg[0]) in ("gh", "git") or _base(seg[0]) in NET_TEXT_CMDS:
        return []
    return [j for j in range(1, len(seg)) if _base(seg[j]) in ("gh", "git") and (
        seg[j - 1] in SHELL_RESERVED or seg[j - 1] in ("function", "coproc") or _redir_len(seg, j - 1) == 1
        or (j >= 2 and _redir_len(seg, j - 2) == 2))]


CD_NAMES = ("cd", "pushd", "popd")
# 디렉토리 스택 tilde(bash `bash_special_tilde_expansions`): `~+`(PWD)·`~-`(OLDPWD)·`~N`·`~+N`(dirs 왼쪽에서 N번째, 0 = cwd)·
# `~-N`(오른쪽에서 N번째), 뒤에 `/…`가 붙을 수 있다. `~`·`~/x`·`~user`는 아니다(HOME — `_expand`). N은 ASCII 숫자만(bash
# `legal_number` — `~١`는 글자 그대로다)
DIRSTACK_TILDE_RE = re.compile(r"^~([+-]?)([0-9]*)(/.*)?$", re.DOTALL)
# 명령 글에서 PWD·OLDPWD를 바꿀 수 있다(대입·`export`·`read`·`unset`·`${OLDPWD:=…}` — `$PWD` 읽기는 아니다): `cd -`·`~-`·`~+`의 값을 모른다
PWD_VAR_RE = re.compile(r"(?<![\w${])(?:OLD)?PWD\b|\$\{(?:OLD)?PWD:?=")
# 같은 명령 글에서 OLDPWD·PWD에 정적(따옴표만, 셸이 풀 값 없음) 절대 경로를 넣는 대입을 모은다 → `cd -`·`~-`·`~+`의 후보(더할
# 뿐 모르는 디렉토리를 빼지 않는다 — 대입이 돌지 않았거나 범위가 좁을 수 있다). 자리: 앞 대입(명령 앞 `OLDPWD=…`)·대입 빌트인
# (`export`·`declare`·`typeset`·`readonly`·`local` — `builtin`·`command` 뒤 포함, 옵션 뒤 모든 `NAME=값`). `env NAME=…`은 부모 셸
# 변수가 아니라 자식 환경이라 세지 않는다(`_Walk._child`가 자식에게 넘긴다). 이름은 `_tokens`가 푼 것(`$'OLD\x50WD'`·`OLDPW''D`)
PWD_ASSIGN_CMDS = {"export", "declare", "typeset", "readonly", "local"}
PWD_NAME_RE = re.compile(r"^(?:OLD)?PWD(?:\+?=|$)")
# `${OLDPWD:=/abs}`·`${PWD=/abs}`: 비었으면(`:=`) 또는 없으면(`=`) 넣는 정적 값(인용·확장 없는 절대 경로만 — 그 밖은 모르는 값)
PWD_DEFAULT_RE = re.compile(r"\$\{((?:OLD)?PWD):?=(/[^}$`'\"\\\s]*)\}")


def _pwd_write_val(tok) -> tuple[str | None, str | None]:
    """`NAME=값` 토큰 → (이름 OLDPWD|PWD|None, 정적 절대 경로|None — 동적·상대 값이면 None)."""
    name, eq, val = str(tok).partition("=")
    name = name.removesuffix("+")
    if not eq or name not in ("OLDPWD", "PWD"):
        return None, None
    if _dyn(tok) or str(tok).partition("=")[0].endswith("+"):     # 셸이 풀 값·덧붙이기: 모르는 값
        return name, None
    val = _expand(val)
    return name, (val if val.startswith("/") else None)


def _pwd_writes(toks: list[str]) -> tuple[list[str], list[str], bool]:
    """토큰(`_tokens`)의 정적 OLDPWD·PWD 대입 값(절대 경로) → (OLDPWD 값들, PWD 값들, OLDPWD·PWD를 바꿀 수 있나). 셋째는 어느 자리든
    푼 낱말이 `OLDPWD`·`PWD`(`=…`)이면 참이다(숨긴 이름의 `read`·`unset`·대입 — `PWD_VAR_RE`가 날 글에서 놓치는 꼴, 닫힌 쪽)."""
    old_vals: list[str] = []
    pwd_vals: list[str] = []
    wrote = False

    def take(tok) -> None:
        name, val = _pwd_write_val(tok)
        if name is not None and val is not None:
            (old_vals if name == "OLDPWD" else pwd_vals).append(val)

    for seg in _segments(toks):
        if not any(PWD_NAME_RE.match(str(t)) for t in seg):
            continue
        wrote = True
        i = 0
        while i < len(seg) and (str(seg[i]) in SHELL_RESERVED or str(seg[i]) in ("{", "!", "time")):   # 앞머리 예약어
            i += 1
        while i < len(seg) and ASSIGN_HEAD_RE.match(str(seg[i])):    # 앞 대입(`OLDPWD=…` 앞머리)
            take(seg[i])
            i += 1
        while i < len(seg) and _base(seg[i]) in ("builtin", "command"):     # `builtin export …`·`command -p export …`
            i += 1
            while i < len(seg) and str(seg[i]).startswith("-") and str(seg[i]) != "-":
                i += 1
                if str(seg[i - 1]) == "--":
                    break
        if i < len(seg) and _base(seg[i]) in PWD_ASSIGN_CMDS:   # 대입 빌트인: 옵션 뒤 모든 `NAME=값`(`export FOO=1 OLDPWD=…`)
            for t in seg[i + 1:]:
                take(t)
    return old_vals, pwd_vals, wrote
CWD_CAP = 8                         # 따라가는 cwd 후보 상한(넘으면 처음·보호 뿌리 안·최근 후보만 남기고 나머지를 모르는 디렉토리로 접는다)
# 이보다 긴 cwd 후보(상대 cd가 길게 이어진 것)는 실제 경로와 `..`을 글자로 접은 경로로 바꾼다(`_shorten`) — 후보 경로가 cd마다
# 길어져 비용이 cd 수의 제곱으로 늘지 않게(재리뷰 P1 성능)
LONG_CWD = 1024
MAX_CWD = 4096                      # PATH_MAX: 이보다 긴 후보는 실제로 있는 디렉토리가 아니면 조상으로 자른다(모르는 디렉토리도 둔다)
MAX_KEEP_CWD = 1 << 16              # 실제로 있어도 이보다 길면 자른다(비용 상한)
PIPE_OPS = {"|", "|&"}
# 복합 명령(`_Walk`): 여는 말 → 닫는 말. `for`·`select`·`case` 머리의 나머지(`x in a b`)는 명령이 아니다
COMPOUND = {"{": "}", "if": "fi", "case": "esac", "while": "done", "until": "done", "for": "done", "select": "done"}
CLOSERS = {"}": ("{",), "fi": ("if",), "esac": ("case",), "done": ("while", "until", "for", "select")}
LOOPS = {"while", "until", "for", "select"}


# 넘침 때 접지 않는 cwd 후보의 뿌리(정규화 경로): 사용자 설정의 clone·work_dir(작업 worktree·스냅샷)·스킬 소스. 설정을 아는
# 검사가 `invocations(keep=…)`로 그 걷기 동안만 둔다(`_keep_roots`)
_KEEP_ROOTS: tuple[str, ...] = ()


_REAL: dict[str, str] = {}


def _real(path: str) -> str:
    """`_norm`(realpath)과 같은 실제 경로를 캐시한 부모 결과에 한 칸씩 이어 만든다 — 한 칸씩 깊어지는 cd 후보마다 realpath를
    처음부터 하면 cd 수의 제곱으로 느려진다. 칸이 심볼릭 링크면 그 자리에서 `_norm`으로 풀고, `.`은 그대로, `..`은 이미 푼 실제
    경로의 부모다(realpath가 하는 것과 같다 — 재리뷰 P1 성능: `..`마다 realpath를 처음부터 해 깊은 디렉토리에서 cd 1000개가 hook
    시간 한도를 넘겼다). 푼 실제 경로도 그 자체를 키로 둔다(실제 꼴에서 이어지는 후보가 캐시에 맞게)."""
    if path in _REAL:
        return _REAL[path]
    if len(_REAL) > 50000:
        _REAL.clear()
    names, p = [], path
    while p not in _REAL:
        parent, name = os.path.split(p)
        if not name or parent == p:
            _REAL[p] = _norm(p)
            break
        names.append(name)
        p = parent
    base, cur = _REAL[p], p
    for name in reversed(names):
        cur = os.path.join(cur, name)
        if name == "..":
            base = os.path.dirname(base)
        elif name != ".":
            joined = os.path.join(base, name)
            base = _norm(joined) if os.path.islink(joined) else os.path.normcase(joined)   # islink은 예외를 내지 않는다
        _REAL[cur] = base
        _REAL.setdefault(base, base)
    return base


@functools.lru_cache(maxsize=8192)
def _root_of(path: str, roots: tuple[str, ...]) -> str | None:
    """`path`가 든 가장 구체적인 뿌리(`roots`), 없으면 None. 글자 그대로(`normpath`) 뿌리 안이면 그것, 아니면 실제 경로(`_real`)로
    본다. 셸이 풀 글자가 있거나 정규화하지 못하면 None."""
    if not roots or "$" in path or "`" in path:
        return None
    try:
        hits = [r for r in roots if _inside(os.path.normpath(path), r)] or [r for r in roots if _inside(_real(path), r)]
    except Exception:  # noqa: BLE001
        return None
    return max(hits, key=len) if hits else None


_SHORT: dict[str, tuple[Path, ...]] = {}


def _deep_isdir(f: str) -> bool:
    """PATH_MAX보다 긴 절대 경로가 실제 디렉토리인가. 긴 경로는 `os.stat`이 ENAMETOOLONG이라 상한 안 조상을 열고 나머지 칸을
    하나씩 `dir_fd`로 연다(칸이 없으면 바로 거짓). `dir_fd`를 못 쓰는 OS(Windows)·오류는 거짓(자른다 — 예전 동작)."""
    anc = f
    while len(anc) > MAX_CWD:
        anc = os.path.dirname(anc[:MAX_CWD + 1])
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fds = []
    try:
        fds.append(os.open(anc, flags))
        for name in f[len(anc):].strip(os.sep).split(os.sep):
            fds.append(os.open(name, flags, dir_fd=fds[-1]))
        return True
    except (OSError, ValueError, NotImplementedError, TypeError):
        return False
    finally:
        for fd in fds:
            os.close(fd)


def _shorten(d: Path) -> tuple[Path, ...]:
    """`LONG_CWD`보다 긴 cwd 후보를 짧은 꼴로 바꾼다(후보 경로가 cd마다 길어져 비용이 cd 수의 제곱으로 늘지 않게). 실제 경로(심볼릭
    링크를 푼 `_real` — 짧은 후보를 git·`_norm`이 푸는 것과 같다, bash `cd -P`·글자 경로가 없을 때의 기본 cd)와 글자로 `..`·`.`을
    접은 경로(bash 논리 cd `-L`, 기본)를 다르면 둘 다 남긴다. 둘 다 그대로의 깊이다 — 뒤 상대 `..`가 실제 디렉토리에서 올라간다.
    `MAX_CWD`(PATH_MAX)보다 길면 그 안의 가장 깊은 조상으로 자르고 모르는 디렉토리도 둔다(재리뷰 P1 2건: 글자로만 접으면 링크를
    지나 clone·worktree·작업 폴더로 드는 사슬을 놓치고, 1024자 안 조상으로 자르면 깊이를 잊어 뒤 `..`가 그 밖으로 올라갔다. 그 전에는
    보호 뿌리로 접어 worktree·작업 폴더 후보가 work_dir 자체가 됐다). 셸이 풀 글자가 있거나 상대 경로면 보호 뿌리나 모르는 디렉토리."""
    s = str(d)
    if "$" in s or "`" in s or not d.is_absolute():
        return (Path(_root_of(s, _KEEP_ROOTS) or UNKNOWN_DIR),)
    if s in _SHORT:                     # 이미 줄인 꼴(그 자체로 고정점)이나 앞서 줄인 경로: `_dedupe`마다 다시 풀지 않는다(성능)
        return _SHORT[s]
    if len(_SHORT) > 50000:
        _SHORT.clear()
    forms = [os.path.normpath(s)]
    try:
        forms.insert(0, _real(s))
    except Exception:  # noqa: BLE001 — 실제 경로를 못 풀면 글자 꼴만(판정 예외로 무너지지 않게)
        pass
    out: list[Path] = []
    for f in dict.fromkeys(forms):
        if len(f) <= MAX_CWD or (len(f) <= MAX_KEEP_CWD and _deep_isdir(f)):
            out.append(Path(f))          # 실제로 있는 깊은 디렉토리는 자르지 않는다 — bash는 상대 cd로 들어갈 수 있다(재리뷰 P0)
            continue
        while len(f) > MAX_CWD:
            f = os.path.dirname(f[:MAX_CWD + 1])
        out += [Path(f), UNKNOWN_DIR]
    res = _SHORT[s] = tuple(dict.fromkeys(out))
    for q in res:
        _SHORT.setdefault(str(q), (q,))
    return res


@functools.lru_cache(maxsize=8192)
def _anchor_of(path: str, roots: tuple[str, ...]) -> str | None:
    """넘친 보호 뿌리 안 후보를 접을 자리: 그 후보(뿌리 안이면 글자 경로, 아니면 실제 경로)가 든 가장 가까운 git 작업 트리
    꼭대기(`.git`이 있는 곳 — clone·worktree·스냅샷), 없으면 뿌리 바로 아래 첫 칸(`<work_dir>/<KEY>` 작업 폴더), 그것도
    아니면 뿌리. 뿌리 밖이면 None. 예전에는 뿌리 자체로 접어 worktree·작업 폴더 후보가 work_dir(레포도 작업 폴더도 아님)이
    돼 git 규칙·규칙 2/7 기록 검사를 건너뛰었다(재리뷰 — 긴 후보를 실제·글자 두 꼴로 보면서 넘침이 잦아졌다)."""
    root = _root_of(path, roots)
    if root is None:
        return None
    try:
        p = os.path.normpath(path)
        p = p if _inside(p, root) else _real(path)
    except Exception:  # noqa: BLE001
        return root
    if not _inside(p, root):
        return root
    q = p
    while True:
        try:
            if os.path.lexists(os.path.join(q, ".git")):
                return q
        except (OSError, ValueError):
            pass
        if len(q) <= len(root.rstrip(os.sep)) or os.path.dirname(q) == q:
            break
        q = os.path.dirname(q)
    first = os.path.relpath(p, root).split(os.sep)[0]
    return os.path.join(root, first) if first not in ("", ".", "..") else root


def _dedupe(dirs) -> tuple[Path, ...]:
    """중복을 뺀 cwd 후보(처음 나온 순서). `CWD_CAP`을 넘으면 처음 후보, 보호 뿌리(`_KEEP_ROOTS` — 이슈 DB clone·work_dir·스킬
    소스) 안의 후보 가장 최근 `CWD_CAP`개(그보다 많으면 나머지는 그 후보가 든 레포 꼭대기나 작업 폴더 — `_anchor_of`), 그 밖의 가장 최근 후보들을 남기고 나머지를 모르는
    디렉토리 하나로 접는다(회귀 수정 R4 — 넘침이 마지막 cd 대상을 버리던 부류, 재리뷰 — 분기·실패할 수 있는 이동이 후보를 늘려 처음
    cwd인 clone이 접히던 부류. 접힌 후보는 모르는 디렉토리로 남는다. git 규칙이 보는 후보는 보호 뿌리 안에 있다)."""
    dirs = tuple(x for d in dirs for x in ((d,) if len(str(d)) <= LONG_CWD else _shorten(d)))
    out = tuple(dict.fromkeys(dirs))
    if len(out) <= CWD_CAP:
        return out
    head = out[0]
    rev = [d for d in dict.fromkeys(reversed(dirs)) if d != head and d != UNKNOWN_DIR]     # 가장 최근 것부터
    roots = _KEEP_ROOTS
    guarded = [d for d in rev if _root_of(str(d), roots)]
    keep = set(guarded[:CWD_CAP]) | set([d for d in rev if not _root_of(str(d), roots)][:CWD_CAP - 2])
    # 넘친(오래된) 보호 후보는 레포 꼭대기·작업 폴더로 접고(최근 것부터 `CWD_CAP`개), 그래도 넘치면 뿌리로 접는다. 접은 자리는
    # 오래된 쪽(처음 후보 바로 뒤)에 둔다 — 끝(최근 자리)에 두면 다음 넘침 때 진짜 최근 후보를 밀어냈다(마지막 리뷰 검증)
    anchors = [Path(a) for a in dict.fromkeys(_anchor_of(str(d), roots) for d in guarded[CWD_CAP:])]
    anchors = [a for a in anchors if a not in keep and a != head]
    rooted = [Path(r) for r in dict.fromkeys(_root_of(str(a), roots) for a in anchors[CWD_CAP:])]
    rooted = [r for r in rooted if r not in keep and r != head and r not in anchors[:CWD_CAP]]
    kept = [d for d in reversed(rev) if d in keep]
    return (head, *rooted, *reversed(anchors[:CWD_CAP]), *kept, *(() if head == UNKNOWN_DIR else (UNKNOWN_DIR,)))


def _sure_dir(p: Path) -> bool:
    """cd가 지금 확실히 갈 수 있는 디렉토리인가: 셸이 풀 글자 없는 절대 경로이고, 있는 디렉토리이며 들어갈 권한(x)이 있다. 아니면
    (없는 경로 — 같은 명령에서 만들지 않는 한 —, stat 오류, 권한 없음) cd가 실패할 수 있다 — cwd는 그대로다. 예외를 내지 않는다."""
    s = str(p)
    if not p.is_absolute() or "$" in s or "`" in s:
        return False
    try:
        return os.path.isdir(s) and os.access(s, os.X_OK)
    except (OSError, ValueError):
        return False


class _Cwd:
    """`invocations`가 따라가는 작업 디렉토리 상태. `dirs`: 가능한 cwd 후보(조건부 cd·분기·실패할 수 있는 cd 뒤에는 여럿이고 모두
    판정한다 — 닫힌 쪽), `old`: `cd -`의 이전 디렉토리 후보(모르면 None), `stack`: pushd 스택에서 이 명령 글이 쌓은 칸(bash `dirs`의
    1번부터, 끝이 맨 위 — 그 아래 칸은 모른다), `exact`: `stack` 칸을 정확히 안다(분기를 합쳐 스택이 달랐거나 실패할 수 있는
    pushd 뒤에는 모른다 — 그러면 popd 등은 스택의 어느 칸·이전 후보·모르는 디렉토리로든 갈 수 있다), `sticky`: 언제 도는지 모르는
    cd(함수 본문 안)나 짝 없는 `)`·닫는 말이 있었다 — 뒤 명령마다 모르는 디렉토리(`UNKNOWN_DIR`)도 후보이고 스택도 모른다."""

    def __init__(self, dirs, old=None, stack=None, sticky: bool = False, exact: bool = True):
        self.dirs = _dedupe(dirs)
        self.old = old
        self.stack = list(stack or [])
        self.sticky = sticky
        self.exact = exact

    def copy(self) -> _Cwd:
        return _Cwd(self.dirs, self.old, self.stack, self.sticky, self.exact)

    def all(self) -> tuple[Path, ...]:
        return _dedupe(self.dirs + ((UNKNOWN_DIR,) if self.sticky else ()))

    def stack_dirs(self) -> tuple[Path, ...]:
        return tuple(d for level in self.stack for d in level)

    def settle(self) -> _Cwd:
        """칸을 정확히 모르는 스택(`exact` 거짓 — 다시 참이 되지 않는다)은 칸 하나로 합친다. 그 뒤 연산은 스택 칸 전체(`stack_dirs`
        — popd·`pushd ±N`·`cd ±N`의 `anywhere`)만 보므로 판정은 같고, 칸이 pushd마다 쌓여 popd마다 모두 다시 보는 비용이 pushd 수의
        세제곱으로 늘지 않는다(재리뷰 P1 성능: 없는 경로 pushd 1000개 + popd 1000개가 hook 시간 한도 180초를 넘겨 판정 없이 통과했다
        — Claude Code는 시간 초과를 막지 않는다). 합친 칸도 후보 상한(`_dedupe`) 안이다."""
        if (not self.exact or self.sticky) and len(self.stack) > 1:
            # bash처럼 마지막에 넣은 것이 이긴다(다시 넣은 칸은 최근 자리로 — 재리뷰 P0: 첫 자리로 두면 넘침 때 최근 칸을 접었다).
            # 자기 자신으로만 접히는 칸(보호 뿌리 그 자체·모르는 디렉토리)은 처음 후보 바로 뒤에 둬 구체적인 칸을 밀어내지 않게
            flat = self.stack_dirs()
            head = flat[0]
            last = [d for d in reversed(dict.fromkeys(reversed(flat))) if d != head]
            old = [d for d in last if d == UNKNOWN_DIR or str(d) in _KEEP_ROOTS]
            self.stack = [_dedupe((head, *old, *(d for d in last if d not in old)))]
            self.exact = False          # sticky면 어차피 칸을 정확히 쓰지 않는다(`cd`의 `exact`) — 재리뷰 P1 성능
        return self

    @staticmethod
    def union(states) -> _Cwd:
        """여러 경로 끝 상태의 합(후보 순서는 넘긴 순서 — 뒤가 최근이다). 스택이 다르면 칸을 모두 남기고 모른다고 표시한다
        (뒤 popd는 그 칸들·이전 후보·모르는 디렉토리 모두로 본다 — 회귀 수정 R1)."""
        states = list(states)
        olds = [s.old for s in states]
        old = None if all(o is None for o in olds) else _dedupe(d for o in olds for d in (o or (UNKNOWN_DIR,)))
        same = all(s.stack == states[0].stack for s in states)
        stack = states[0].stack if same else list(dict.fromkeys(level for s in states for level in s.stack))
        return _Cwd([d for s in states for d in s.dirs], old, stack, any(s.sticky for s in states),
                    same and all(s.exact for s in states)).settle()


def _is_sep(tok: str) -> bool:
    return tok in SEPARATORS or bool(tok and set(tok) <= set(";&|()"))


def _only_redirs(toks: list[str]) -> bool:
    i = 0
    while i < len(toks):
        n = _redir_len(toks, i)
        if not n:
            return False
        i += n
    return True


class _Walk:
    """`invocations`의 명령 글 하나 걷기. 토큰을 구분자에서 나눠 단순 명령마다 `Invocation`을 만들고, cd·pushd·popd는 bash의
    범위대로 따라간다(H-A1 r6 — 서브셸·파이프 안 cd가 바깥 명령의 cwd로 새던 부류를 닫는다):
    - `( … )`·`$( … )`·`<( … )`(서브셸)는 닫을 때 들어가기 전 상태로 되돌린다.
    - 파이프 요소(`|`·`|&` 앞뒤)와 `&` 백그라운드 목록은 서브셸이다: 그 cd는 밖에 남지 않는다(`{ …; } | cat`·
      `… | while …; done`처럼 복합 명령이 요소여도 같다).
    - `&&`·`||` 뒤 cd, `if`·`case` 분기·루프 안 cd는 돌지 않았을 수도 있다: 목록·복합 명령이 끝나면 전후 후보를 합친다(루프는
      여러 번 돌 수 있어 모르는 디렉토리도 더한다). and-or 목록에서 건너뛴 명령의 상태도 뒤 명령의 후보다(`A || B && C`의 C는 B를
      건너뛴 A의 성공 상태에서도, `A && B || C`의 C는 A의 실패 상태에서도 돈다 — `fails`·`oks`). `else`·`elif`·`fi` 뒤는 `if`에
      들어갈 때 상태와 조건들의 끝 상태(조건의 cd도 돌았다)를 합친 데서 본다(재리뷰).
    - 함수 본문(`f() { …; }`·`function f { …; }`)은 정의할 때 돌지 않는다. 본문에 cd가 있으면 뒤에서 부를 수 있어 그 뒤 명령마다
      모르는 디렉토리를 후보에 더한다. `eval`의 cd는 밖에 남는다.
    - 짝 없는 `)`·닫는 말도 모르는 디렉토리를 더한다(닫힌 쪽 — bash에선 문법 오류다).
    - `source`·`.`(읽는 파일이 cd할 수 있다)와 셸 값이 든 `eval`(`eval "$X"`)도 그 뒤에 모르는 디렉토리를 더한다. 명령 글에 `CDPATH`가
      있으면 `/`·`.`로 시작하지 않는 상대 cd는 모르는 디렉토리도 후보다(bash가 CDPATH에서 먼저 찾는다).
    - 실패할 수 있거나 대상을 모르는 이동(없는 경로·셸이 풀 경로·빈 스택이나 이 글 밖 스택의 popd·pushd·`cd -`의 처음 이전
      디렉토리, 다른 셸에선 뜻이 다른 옵션·남는 인자 등)은 이전 후보를 버리지 않는다(`cd` — 회귀 수정 R1, 재리뷰). 이동을 따라가다
      예외가 나면 그 이동은 실패했거나 모르는 곳으로 간 것으로 본다.
    - `dirs`에 인자가 있거나 `DIRSTACK`이 나오면 스택 칸을 모른다(뒤 popd는 스택 칸·이전 후보·모르는 디렉토리 모두로 본다).
    셸(`-c` 없이)이 읽는 heredoc 본문은 그 연산자가 든 명령의 cwd 후보·OLDPWD로 한 번, 이 글에서 거친 나머지 cwd 후보(상한 안)와
    넓은 OLDPWD로 한 번 걷는다(재리뷰 P1 — 거친 cwd마다 본문을 다시 걸어 중첩 heredoc에서 시간이 곱으로 늘던 부류). 파이프로 셸에
    넘긴 글은 그 묶음이 시작할 때의 cwd 후보·OLDPWD로 한 번 걷는다(11/04 재리뷰)."""

    def __init__(self, st: _Cwd, depth: int, cdpath: bool = False, pwdvar: bool = False,
                 old_vals: tuple[Path, ...] = (), pwd_vals: tuple[Path, ...] = (), posix: bool = False):
        self.st, self.depth, self.cdpath, self.pwdvar = st, depth, cdpath, pwdvar
        # 정적 OLDPWD·PWD 대입 값(이 글의 것, `eval`이면 바깥 것도). `cd -`·`~-`·`~+` 후보를 넓힌다(E). 중첩 셸은 부모의 OLDPWD
        # 후보를 `st.old`로 물려받는다(`_child` — B)
        self.old_vals, self.pwd_vals = tuple(old_vals), tuple(pwd_vals)
        self.posix = posix      # POSIX 셸(dash) 글: dir-stack tilde를 풀지 않을 수 있다(글자 그대로도 본다)
        self.out: list[Invocation] = []
        # [여는 말, 들어갈 때 상태, 바깥 and-or 상태, 바깥 목록 시작 상태, 파이프·백그라운드 요소인가, 함수 본문인가, 분기 끝 상태들,
        #  바깥 실패 상태들, 바깥 성공 상태들]
        self.frames: list[list] = []
        self.andor: _Cwd | None = None      # 이 and-or 목록이 처음 `&&`·`||`를 만났을 때 상태(뒤 cd는 조건부다)
        # 이 and-or 목록에서 `&&` 앞 명령이 실패했을 때 상태들(cd면 이동 전 cwd, 그 밖의 명령이면 그때 상태). `&&` 뒤 명령은 돌지 않지만
        # `||` 뒤와 목록 끝에는 남는다
        self.fails: list[_Cwd] = []
        # `||` 앞 명령이 성공했을 때 상태들: `||` 뒤 명령은 돌지 않지만 다음 `&&` 뒤와 목록 끝에는 남는다(`A || B && C`의 C는 A가 성공해
        # B를 건너뛴 상태에서도 돈다 — 재리뷰)
        self.oks: list[_Cwd] = []
        self.cd_last = False                # 바로 앞 단순 명령이 이 셸의 cd·pushd·popd다(실패 상태는 `cd`가 `fails`에 넣는다)
        self.list_start = st.copy()         # 이 and-or 목록이 시작할 때 상태(`&` 백그라운드면 되돌린다)
        self.func = False                   # 바로 앞이 함수 정의 머리(`f()`·`function f`)다
        self.seen: list[Path] = list(st.all())
        self.hd_at: dict[int, tuple[Path, ...]] = {}    # heredoc 연산자 번호 → 그 연산자가 든 명령의 cwd 후보
        self.hd_old: dict[int, tuple[Path, ...]] = {}   # heredoc 연산자 번호 → 그때 OLDPWD 후보(자식 셸이 물려받는다 — B)
        self.pipe_at: dict[int, tuple] = {}             # 셸에 글을 넘기는 파이프 묶음 번호 → 시작할 때 (cwd 후보, OLDPWD 후보)
        self.hds: tuple = ()                            # 이 글의 heredoc 연산자(`_heredoc_scan`)
        self.seg_hd: tuple = ()                         # 지금 단순 명령에 든 셸이 읽는 heredoc 연산자 번호
        self.hd_inline: set[int] = set()                # 이 셸에서 바로 걸은 heredoc(`source /dev/stdin <<EOF`)

    @staticmethod
    def _marked_tokens(command: str, hds, ids) -> tuple[list, list[tuple[int, ...]]]:
        """`_tokens(command)`와 같은 토큰과, 토큰마다 그 안에 든 heredoc 연산자 번호(`ids`에 든 것만). 연산자(`<<`·`<<-`) 뒤 끝 표시
        낱말 바로 앞에 명령 글에 없는 표시 글자(사용자 영역 U+F000~ — `_shell_prep`의 `BARE`·`LIT_*`·`TILDE_AT`·`FD_AT`·`HD_DASH`와
        겹치지 않는다)를 끼워 토큰을 만든 뒤 표시를 뗀다 — 표시는 낱말 글자라 끝 표시 낱말에 붙고 토큰 경계·글을 바꾸지 않는다(`<`는
        연산자 글자라 연산자 앞에 끼우면 따로 토큰이 된다)."""
        plain = _tokens(command)
        if not ids:
            return plain, [()] * len(plain)
        # 본문을 먼저 뺀 글(`_strip_heredocs`)에서 연산자 자리를 다시 찾아 표시를 끼운다(G): 표시를 든 글에 본문이 남으면 끝 표시가
        # 어긋나 `_strip_heredocs`가 본문을 못 빼고(연산자별 cwd 미기록·늘 대체 경로) 큰 본문을 토큰으로 썰어 느려졌다. 본문 없는
        # 글은 `_tokens`가 다시 썰어도 같은 토큰이고(끝 표시에 표시가 끼어도 뺄 본문이 없다) 빠르다
        stripped = _strip_heredocs(command)
        shds = _heredoc_scan(stripped)
        marks = next(((chr(c), chr(c + 1)) for c in range(0xF000, 0xF8FE, 2)
                      if chr(c) not in stripped and chr(c + 1) not in stripped), None)
        if marks is None or len(shds) != len(hds):
            return plain, [()] * len(plain)
        text = stripped
        for k in sorted(ids, key=lambda j: shds[j].op_pos, reverse=True):
            p = shds[k].op_pos + (3 if shds[k].dash else 2)
            while p < len(text) and text[p] in " \t":
                p += 1
            text = f"{text[:p]}{marks[0]}{k}{marks[1]}{text[p:]}"
        pat = re.compile(f"{re.escape(marks[0])}(\\d+){re.escape(marks[1])}")
        toks, found = [], []
        for t in _tokens(text):
            got = tuple(int(x) for x in pat.findall(t))
            if got:
                w = Word(pat.sub("", t))
                w.dyn, w.bare, w.tilde = _dyn(t), _split(t), getattr(t, "tilde", False)
                w.op, w.atilde = getattr(t, "op", False), getattr(t, "atilde", ())
                t = w
            toks.append(t)
            found.append(got)
        if [str(t) for t in toks] != [str(t) for t in plain]:   # 표시가 토큰을 바꿨다(없어야 한다): 자리 없이 본다
            return plain, [()] * len(plain)
        return toks, found

    def run(self, command: str) -> list[Invocation]:
        self.cdpath = self.cdpath or "CDPATH" in command
        self.pwdvar = self.pwdvar or bool(PWD_VAR_RE.search(command))
        hds = self.hds = _heredoc_scan(command) if self.depth < MAX_DEPTH else ()
        fed_ids = [k for k, hd in enumerate(hds) if hd.found and _feeds_shell(hd.unit, self.seen[0])]
        toks, tok_ids = self._marked_tokens(command, hds, fed_ids)
        # 정적 OLDPWD·PWD 대입(E): 푼 토큰으로 본다(숨긴 이름 `export $'OLDP\x57D'=…`·`OLDPW''D`도). 바꿀 수 있으면 모르는 값도 후보다
        old_w, pwd_w, wrote = _pwd_writes(toks)
        if self.pwdvar and "PWD" in command:           # `: ${OLDPWD:=/abs}`의 정적 값도 후보(모르는 값은 그대로 둔다)
            for m in PWD_DEFAULT_RE.finditer(command):
                (old_w if m.group(1) == "OLDPWD" else pwd_w).append(m.group(2))
        self.pwdvar = self.pwdvar or wrote
        # 값이 많으면 후보 상한으로 접는다(`_dedupe` — 보호 뿌리 안 값은 남고 나머지는 모르는 디렉토리, `cd -`마다 다시 보는 비용 상한)
        if old_w:
            self.old_vals = _dedupe(self.old_vals + tuple(Path(v) for v in old_w))
        if pwd_w:
            self.pwd_vals = _dedupe(self.pwd_vals + tuple(Path(v) for v in pwd_w))
        # 파이프로 셸에 넘기는 글(D): 묶음 첫 토큰 자리 → 번호. 그 단순 명령에 이르렀을 때 cwd·OLDPWD를 적어 둔다(`_note`)
        pipes = _fed_pipe_texts(toks) if self.depth < MAX_DEPTH and "|" in command else []
        pipe_start: dict[int, list[int]] = {}
        for j, (start, _, _) in enumerate(pipes):
            pipe_start.setdefault(start, []).append(j)
        prev, cur, cur_ids, k, cur_at = None, [], [], 0, 0
        while True:
            tok = toks[k] if k < len(toks) else None
            here = tok_ids[k] if k < len(toks) else ()
            k += 1
            if tok is not None and not _is_sep(tok):
                if not cur:
                    cur_at = k - 1
                cur.append(tok)
                cur_ids += here
                continue
            seg, cur, seg_ids, cur_ids = cur, [], cur_ids, []
            if seg:
                if any("DIRSTACK" in t for t in seg):     # 스택을 셸 배열로 바꿀 수 있다: 칸을 모른다
                    self.st.exact = False
                    self.st.settle()
                self.segment(seg, prev, tok, seg_ids, pipe_start.get(cur_at, ()))
            if tok in ("&&", "||"):
                if self.andor is None:
                    self.andor = self.st.copy()
                if tok == "||":             # 앞이 성공했으면 `||` 뒤는 건너뛴다(다음 `&&` 뒤에 남는다), 실패 상태에서 돈다
                    self.oks.append(self.st.copy())
                    self._flush_fails()
                else:                       # 앞이 실패했으면 `&&` 뒤는 건너뛴다(`||` 뒤에 남는다), `||`를 건너뛴 성공 상태도 돈다
                    if not self.cd_last:
                        self.fails.append(self.st.copy())
                    if self.oks:
                        self.st = _Cwd.union([*self.oks, self.st])
                        self.oks = []
            elif tok == "(":
                if k < len(toks) and toks[k] == ")" and (self.func or (
                        len(seg) == 1 and not _dyn(seg[0]) and re.match(r"^[^\s=()<>;&|'\"]+$", seg[0])
                        and seg[0] not in SHELL_RESERVED)):
                    self.func, tok = True, ")"     # `f()`: 함수 정의 머리. 본문은 다음 복합 명령이다
                    k += 1
                else:
                    self.open("(", False)
            elif tok == ")":
                self.close_paren()
            elif tok not in PIPE_OPS:              # `;`·줄바꿈·`&`·`;;`·끝
                self.end_list(tok == "&")
                if tok == ";;":
                    self.arm()
            if tok is None:
                break
            prev = tok
        # 셸이 읽는 heredoc 본문은 명령이다: 그 연산자가 든 명령의 cwd 후보(셸 자식이라 스택은 비었다)와 그때 OLDPWD(자식이 물려받는다
        # — B)로 한 번, 이 글에서 거친 나머지 후보(상한 안 — 연산자 자리를 찾지 못했거나 걷기가 놓친 이동이 있어도 닫힌 쪽)와 넓은
        # OLDPWD(거친 cwd 모두·모르는 디렉토리)로 한 번 걷는다. 후보마다 다시 걷지 않는다
        fed: list[Invocation] = []
        broad = None
        for k in fed_ids:
            if k in self.hd_inline:
                continue
            at = self.hd_at.get(k, ())
            shell = _worst_shell(re.findall(r"(?<![\w.-])(sh|dash|ksh|zsh)(?![\w-])", hds[k].unit))
            if at:
                fed += self._child(hds[k].body, at, old=self.hd_old.get(k), shell=shell)
            rest = tuple(d for d in _dedupe(self.seen) if d not in at)
            if rest:
                broad = broad or self._broad_old()
                fed += self._child(hds[k].body, rest, old=broad, shell=shell)
        # 파이프로 셸에 넘긴 글(서브셸 — cd는 새지 않는다, D): 묶음이 시작할 때의 cwd 후보·OLDPWD로 한 번 걷는다(못 적었으면 거친
        # cwd 모두·넓은 OLDPWD로). 같은 글·상태는 한 번만
        done: set = set()
        for j, (_, texts, shell) in enumerate(pipes):
            dirs, old = self.pipe_at.get(j) or (_dedupe(self.seen), broad or self._broad_old())
            for text in texts:
                if (text, dirs, old, shell) not in done:
                    done.add((text, dirs, old, shell))
                    fed += self._child(text, dirs, old=old, shell=shell)
        self.out[:0] = fed
        return self.out

    def _broad_old(self) -> tuple[Path, ...]:
        """어느 자리의 OLDPWD인지 모를 때의 후보: 이 글에서 거친 cwd 모두·정적 대입 값·모르는 디렉토리(OLDPWD는 앞 cwd나 셸이
        물려받은 값이다)."""
        return tuple(dict.fromkeys((*_dedupe(self.seen), *self._oldpwd_dirs(), UNKNOWN_DIR)))

    def _note(self, hd_ids, pipe_ids=()) -> None:
        """이 명령에 든 heredoc 연산자(셸이 읽는 본문)와 이 명령에서 시작하는 파이프 묶음(셸에 글을 넘긴다)의 cwd 후보·OLDPWD 후보를
        적어 둔다 — 앞머리 말(`else`·`then` 등)을 처리한 뒤의 상태."""
        if hd_ids or pipe_ids:
            dirs, old = self.st.all(), self._oldpwd_dirs()
            for k in hd_ids:
                self.hd_at[k], self.hd_old[k] = dirs, old
            for j in pipe_ids:
                self.pipe_at.setdefault(j, (dirs, old))

    def segment(self, seg: list[str], before, after, hd_ids=(), pipe_ids=()) -> None:
        """구분자 사이 토큰 하나. 앞머리의 복합 명령 말(여는 말·닫는 말·`then`·`do`·`else`·`elif`·`!`·`time`·`coproc`·
        `function NAME`)을 처리하고 남은 단순 명령을 `simple`로 넘긴다. `!`(부정)는 `simple`에 알린다."""
        piped = before in PIPE_OPS
        bg_after = after in PIPE_OPS or after == "&"
        i, opened, negated = 0, False, False
        self.cd_last = False
        while i < len(seg):
            t = seg[i]
            if t == "!":
                negated, i = True, i + 1
            elif t == "time":
                i += 2 if seg[i + 1:i + 2] == ["-p"] else 1
            elif t == "coproc":                    # 비동기 서브셸이다
                piped, i = True, i + 1
                if i + 1 < len(seg) and SHELL_NAME_RE.match(seg[i]) and seg[i + 1] in ("{", "("):
                    i += 1
            elif t == "function":
                self.func, i = True, i + 1
                if i < len(seg) and seg[i] not in COMPOUND:
                    i += 1
            elif t in COMPOUND:
                self.open(t, piped)
                piped, opened, i = False, True, i + 1
                if t in ("for", "select", "case"):
                    self._note(hd_ids, pipe_ids)
                    return
            elif t in CLOSERS:
                self.close(t, bg_after and _only_redirs(seg[i + 1:]))
                i += 1
            elif t in ("then", "do", "else", "elif"):
                if t in ("else", "elif"):
                    self.branch()
                elif t == "then" and self.frames and self.frames[-1][0] == "if":
                    self.frames[-1][9].append(self.st.copy())      # 조건의 끝 상태(else·fi 뒤에도 남는다)
                i += 1
            else:
                break
        self._note(hd_ids, pipe_ids)
        rest = seg[i:]
        if not rest:
            return
        if not opened:
            self.func = False
        self.seg_hd = tuple(hd_ids)
        self.simple(rest, piped or bg_after, after, negated)
        self.seg_hd = ()

    def _child(self, body: str, dirs: tuple[Path, ...], env: dict | None = None, old=None,
               shell: str | None = None) -> list[Invocation]:
        """중첩 셸(`bash -c`·here-string·셸이 읽는 heredoc·파이프로 넘긴 글·`$( … )`) 걷기. bash는 `$OLDPWD`를 자식 셸에 내보내므로
        자식의 `cd -`·`~-`는 부모의 OLDPWD 후보(`old` — 없으면 지금 `_oldpwd_dirs`: 따라간 이전 디렉토리·정적 대입 값, 모르면 모르는
        디렉토리도)를 쓴다(B — 모르는 후보를 빼지 않는다). 앞 대입(`env OLDPWD=… bash -c …`)의 값도 더한다(정적이 아니면 모르는
        디렉토리). 자식 스택은 비었다. `shell`: 자식 셸 이름(None이면 이 셸의 서브셸 — `$( … )`): dash(`sh`)·zsh·ksh면 dir-stack
        tilde를 풀지 않을 수 있고(`POSIX_SHELLS`), zsh·ksh는 OLDPWD를 물려받지 않을 수 있다(`UNSURE_OLDPWD_SHELLS`)."""
        old = list(self._oldpwd_dirs() if old is None else old)
        if shell in UNSURE_OLDPWD_SHELLS:
            old += [UNKNOWN_DIR, *dirs]
        pwd = list(self.pwd_vals)
        for key, vals in (("OLDPWD", old), ("PWD", pwd)):
            v = (env or {}).get(key)
            if v is None:
                continue
            if "$" not in v and "`" not in v and _expand(v).startswith("/"):
                vals.append(Path(_expand(v)))
            elif key == "OLDPWD":
                vals.append(UNKNOWN_DIR)
        posix = self.posix if shell is None else shell in POSIX_SHELLS
        return _Walk(_Cwd(dirs, old=tuple(dict.fromkeys(old))), self.depth + 1, pwdvar=self.pwdvar,
                     pwd_vals=tuple(pwd), posix=posix).run(body)

    def _inline(self, body: str, scoped: bool) -> None:
        """이 셸에서 도는 글(`eval`·`source /dev/stdin <<<…`): 같은 상태로 걷고 cd·정적 OLDPWD 대입이 밖에 남는다(`scoped`면 남지 않는다)."""
        inner = _Walk(self.st.copy() if scoped else self.st, self.depth + 1, self.cdpath, self.pwdvar,
                      self.old_vals, self.pwd_vals, self.posix)
        self.out += inner.run(body)
        self.seen += inner.seen
        if not scoped:
            self.st = inner.st
            self.old_vals, self.pwd_vals = inner.old_vals, inner.pwd_vals
            self.pwdvar = self.pwdvar or inner.pwdvar

    def simple(self, rest: list[str], scoped: bool, after=None, negated: bool = False) -> None:
        """단순 명령 하나: cwd 후보마다 Invocation. cd·pushd·popd는 서브셸 요소(`scoped`)가 아닐 때만 상태를 바꾼다(`negated`: 앞에
        `!`가 있다 — 뒤 `&&`는 cd가 실패했을 때 돈다)."""
        first, _, _ = _strip_prefix(rest, self.st.dirs[0])
        name = _base(first[0]) if first else ""
        for d in self.st.all():
            # cd 대상 밖의 dir-stack tilde(`git -C ~-`·`env -C ~-`·리디렉션 대상 `> ~-/f`)를 이 상태로 풀어 argv 변형마다 본다(F)
            for rv in (self._tilde_variants(rest, d) if name not in CD_NAMES and name != "eval" else [rest]):
                seg, seg_cwd, env = _strip_prefix(rv, d)
                if self.depth < MAX_DEPTH:   # `R="$(…)"`·`R="`…`"` 대입 값의 명령 치환은 실행된다(shlex는 대입 토큰 하나로 붙인다)
                    for value in env.values():
                        for body in _subst_bodies(value):
                            self.out += self._child(body, (seg_cwd,), env)
                if not seg or name in CD_NAMES or name == "eval":
                    continue
                if name in SHELLS and self.depth < MAX_DEPTH:
                    # `-c` 스크립트: 리디렉션을 뺀 argv(`bash -c </dev/null '…'` — bash는 리디렉션을 떼고 읽는다)와 원래 argv(따옴표 안
                    # `">"`도 리디렉션으로 보므로) 둘 다에서 찾는다(합집합 — 닫힌 쪽)
                    plain_seg = _drop_redirs(seg)
                    scripts = []
                    for argv in (plain_seg, seg):
                        for i, tok in enumerate(argv[1:], 1):
                            if tok.startswith("-") and not tok.startswith("--") and "c" in tok[1:] and i + 1 < len(argv):
                                scripts.append(argv[i + 1])
                                break
                    for body in dict.fromkeys(scripts):
                        self.out += self._child(body, (seg_cwd,), env, shell=name)
                    if not any(t.startswith("-") and not t.startswith("--") and "c" in t[1:] for t in plain_seg[1:]):
                        for body in _herestrings(seg):      # `-c` 없는 셸은 here-string(`bash <<<"…"`)을 스크립트로 읽는다
                            self.out += self._child(body, (seg_cwd,), env, shell=name)
                    continue
                self.out.append(Invocation(seg_cwd, seg, env))
                for j in _backstop(seg):
                    more, more_cwd, more_env = _strip_prefix(seg[j:], seg_cwd)
                    self.out.append(Invocation(more_cwd, more, {**env, **more_env}))
        if name in CD_NAMES and not scoped:
            saved, self.cd_last = self.st.copy(), True
            try:
                self.cd(name, first, after, negated)
            except Exception:  # noqa: BLE001 — 이동을 따라가지 못했다: 실패했거나 모르는 곳으로 갔다(닫힌 쪽 — 판정은 이어 간다)
                self.st = _Cwd.union([saved, _Cwd((UNKNOWN_DIR,))])
                self.st.exact = False
                self.st.settle()
                self.seen += self.st.all()
        elif name == "dirs" and not scoped and len(_drop_redirs(first)) > 1:
            self.st.exact = False       # `dirs -c`(스택 비우기)·zsh `dirs <칸…>`(스택 바꾸기): 스택 칸을 모른다
            self.st.settle()
        elif name == "eval" and self.depth < MAX_DEPTH and len(first) > 1:    # eval은 이 셸에서 돈다: cd·OLDPWD 대입이 남는다
            self._inline(" ".join(first[1:]), scoped)
        elif name in ("source", ".") and self.depth < MAX_DEPTH and _stdin_reader(first):
            # `source /dev/stdin <<<"…"`·`. /dev/stdin <<EOF`: 글을 이 셸에서 읽는다(D — cd가 남는다)
            for body in _herestrings(first):
                self._inline(body, scoped)
            for k in self.seg_hd:
                if self.hds[k].found:
                    self.hd_inline.add(k)
                    self._inline(self.hds[k].body, scoped)
        if not scoped and (name in ("source", ".") or (name == "eval" and any(_dyn(t) for t in first[1:]))):
            self.st.sticky = True       # 읽는 파일·셸 값이 cd할 수 있다

    def cd(self, name: str, seg: list[str], after=None, negated: bool = False) -> None:
        """cd·pushd·popd를 bash 의미로 따라간다(`pushd -n`·`popd -n`은 cwd를 바꾸지 않고 스택만, `popd +N`(N≥1)은 그 칸만 지우고
        cwd 그대로, `popd`·`popd +0`은 맨 위 칸으로, `pushd`(인자 없음)는 맨 위 두 칸을 바꾼다).
        이동이 실패할 수 있거나(없는 경로·들어갈 수 없는 경로, 빈 스택 — bash는 실패하고 cwd는 그대로다) 대상을 모르면(셸이 풀 경로,
        이 글 밖에서 쌓인 스택 — Claude Code는 Bash 호출마다 새 셸이다 —, 모르는 스택의 칸, `cd -`의 처음 이전 디렉토리,
        `popd -N`·`pushd ±N`·`cd ±N`) 이전 후보를 버리지 않는다: 모르는 디렉토리 후보는 git 규칙(3~8·12)에선
        판정하지 못하는 후보라(규칙 11은 4-c부터 cwd를 보지 않는다), 이전 후보를 버리면 이슈 DB에서 도는 명령을 놓친다(회귀 수정 R1). bash가 거절하거나
        다른 셸(zsh 등)에선 뜻이 다른 꼴 — cd의 `-L`·`-P`·`-e`·`-@` 밖 옵션, pushd·popd의 `-n` 밖 옵션(`popd -q`), 남는 인자
        (`cd a b` — zsh는 경로 바꾸기) — 도 실패할 수 있는 이동이다: 이전 후보와 옵션을 무시한 대상(남는 인자면 모르는 디렉토리도)을
        모두 보고 스택을 모른다고 표시한다(재리뷰 P1). 바로 뒤가 `&&`면 실패할 때 뒤 명령이 돌지 않으므로 이전 후보는 그 목록의
        `||` 뒤와 목록 끝에만 남긴다(`fails`). 단 `!`로 부정했으면(`negated`) 뒤 `&&`는 cd가 실패했을 때만 도므로 미루지 않고 곧바로
        합친다(재리뷰 P1)."""
        st, fail = self.st, self.st.copy()
        prev = st.dirs
        exact = st.exact and not st.sticky
        no_cd, odd, args, ended = False, False, [], False
        for a in _drop_redirs(seg)[1:]:
            if not ended and a == "--":
                ended = True
            elif not ended and len(a) > 1 and a.startswith("-") and not re.match(r"^-\d+$", a):
                if name == "cd":
                    odd = odd or not set(a[1:]) <= set("LPe@")     # bash cd 옵션 밖: bash는 실패, zsh(-q·-s)는 이동
                elif a == "-n":
                    no_cd = True                                    # cwd를 바꾸지 않는다(스택만)
                else:
                    odd = True                                      # bash는 실패, zsh(`-q`)는 이동
            else:
                args.append(a)
        extra = len(args) > 1
        odd = odd or extra
        if odd:
            no_cd = False                                  # 옵션을 무시한 읽기(이동)도 본다 — 이전 후보는 아래에서 더한다
        arg = args[0] if args else None
        num = re.match(r"^([+-])(\d+)$", arg) if arg is not None else None
        dyn = arg is not None and _dyn(arg)
        anywhere = st.stack_dirs() + (UNKNOWN_DIR,)       # 모르는 스택 칸: 쌓은 칸 어디든·이 글 밖 칸
        targets = None                                     # None: cwd가 바뀌지 않는다
        if name == "cd":
            if arg == "-":
                targets = self._oldpwd_dirs()              # OLDPWD(정적 대입·물려받은 값 포함 — E)
            elif num:                                      # bash는 잘못된 옵션(그대로)이나 그 이름의 디렉토리, zsh는 스택 칸
                targets = anywhere + self._targets(arg, prev)
            else:
                targets = self._dest(arg, prev)
                if self.cdpath and arg is not None and not _expand(arg).startswith((".", "/")):
                    targets += (UNKNOWN_DIR,)              # CDPATH에서 먼저 찾는다
        elif no_cd:                                        # `pushd -n`·`popd -n`: 스택만
            self._stack_only(name, arg, num, dyn, exact, prev)
        elif name == "pushd":
            if arg is None and exact and st.stack:         # 맨 위 두 칸 바꾸기
                targets, st.stack[-1] = st.stack[-1], prev
            elif arg is None or num or dyn:                # 빈·모르는 스택의 맞바꾸기, 칸 돌리기, 셸 값
                targets = (self._targets(arg, prev) if dyn else ()) + anywhere
                st.stack.append(prev)
                st.exact = False
            else:
                targets = self._dest(arg, prev)
                st.stack.append(prev)
        else:                                              # popd
            k = 0 if arg is None else int(num.group(2)) if num and num.group(1) == "+" else None
            if k == 0 and exact and st.stack:
                targets = st.stack.pop()
            elif k == 0:                                   # 빈·모르는 스택: 실패(그대로)거나 모르는 칸으로
                targets = anywhere
            elif k is not None:                            # `+N`: 그 칸만 지운다, cwd 그대로
                if exact and k <= len(st.stack):
                    del st.stack[-k]
            elif num or dyn:                               # `-N`·셸 값: 맨 위 칸일 수도 있다
                targets = anywhere
                st.exact = False
            # 그 밖의 인자는 bash 오류다(그대로)
        if odd:                                            # 실패하거나 다른 뜻: 이전 후보·대상·(남는 인자면) 모르는 디렉토리
            targets = (targets or ()) + ((UNKNOWN_DIR,) if extra else ()) + prev
            if name != "cd":
                st.exact = False
        if targets is not None:
            st.old, st.dirs = prev, _dedupe(targets)
            if negated and after == "&&":                  # `! cd … && X`: X는 cd가 실패했을 때 돈다 — 곧바로 합친다
                self.st = _Cwd.union([fail, st])
            elif odd or UNKNOWN_DIR in targets or not all(_sure_dir(t) for t in targets):     # 실패할 수 있다 — 이동 전 상태도 남는다
                if after == "&&" and not negated:
                    self.fails.append(fail)
                else:
                    self.st = _Cwd.union([fail, st])
        self.st.settle()
        self.seen += self.st.all()

    def _oldpwd_dirs(self) -> tuple[Path, ...]:
        """`cd -`·`~-`(OLDPWD) 후보: 따라간 이전 디렉토리(`st.old`) + 정적 OLDPWD·PWD 대입 값(cd가 `$PWD`를 OLDPWD로 복사하므로
        가짜 PWD도 — E) + (없거나 모르면 모르는 디렉토리)."""
        dirs = list(self.st.old) if self.st.old is not None else []
        dirs += list(self.old_vals) + list(self.pwd_vals)
        if self.st.old is None or self.pwdvar:      # 셸이 물려받은 OLDPWD·바뀌었을 수 있는 값: 모르는 디렉토리도(대입 값은 더할 뿐)
            dirs.append(UNKNOWN_DIR)
        return tuple(dict.fromkeys(dirs))

    def _pwdnow_dirs(self, prev) -> tuple[Path, ...]:
        """`~+`·`~0`(PWD) 후보: 지금 cwd + 정적 PWD 대입 값(E) + (모르면 모르는 디렉토리)."""
        dirs = list(prev) + list(self.pwd_vals)
        if self.pwdvar:
            dirs.append(UNKNOWN_DIR)
        return tuple(dirs)

    @staticmethod
    def _targets(arg, prev) -> tuple[Path, ...]:
        target = _expand(arg) if arg is not None else str(Path.home())
        return tuple(Path(target) if Path(target).is_absolute() else d / target for d in prev)

    def _dest(self, arg, prev) -> tuple[Path, ...]:
        """cd·pushd 대상 후보. 디렉토리 스택 tilde(`DIRSTACK_TILDE_RE` — 따옴표 밖, tilde 접두에 인용 없음: `Word.tilde`)는 bash처럼
        이 글이 따라간 상태로 푼다: `~-` = `cd -`의 이전 디렉토리(모르면 — 셸이 물려받은 OLDPWD — 모르는 디렉토리), `~+`·`~0` = 지금
        cwd, `~N`·`~+N` = 이 글이 쌓은 스택 맨 위에서 N번째 칸(칸을 정확히 알 때. 넘으면 이 글 밖 칸 — 모르는 디렉토리), `~-N`(아래에서
        세므로 이 글 밖 칸 수에 달렸다)·칸을 모르는 스택 = 스택 칸 어디든·모르는 디렉토리·cwd. 풀 수 없으면 bash는 글자 그대로 두므로
        (`~-`라는 이름의 경로 — 보통 없어 cd가 실패하고 cwd는 그대로다) 글자 경로도 후보다(확실히 풀리는 칸만이면 빼서 이동이 확실하다).
        명령 글에서 PWD·OLDPWD를 바꿀 수 있으면(`PWD_VAR_RE`) `~-`·`~+`·`~0`은 모르는 디렉토리도 후보다. 따옴표를 모르는 토큰(`Word`가
        아님)은 푼 후보와 글자 경로를 모두 본다. 그 밖의 대상은 `_targets`."""
        literal = self._targets(arg, prev)
        dirs, lit = self._tilde_dirs(arg, prev)
        if dirs is None:
            return literal
        # 뒤 경로의 앞 `/`는 모두 뗀다: bash는 `~-//x`를 `$OLDPWD//x`(= `$OLDPWD/x`)로 푼다 — `Path(d) / "/x"`는 `/x`가 된다(재리뷰 P0)
        rest = (DIRSTACK_TILDE_RE.match(arg).group(3) or "").lstrip("/")
        out = tuple(d if d == UNKNOWN_DIR or not rest else d / rest for d in dirs)
        return out + literal if lit or not isinstance(arg, Word) else out

    def _tilde_dirs(self, arg, prev) -> tuple[tuple[Path, ...] | None, bool]:
        """dir-stack tilde `arg`의 후보 디렉토리(뒤 `/...` 적용 전) + 글자 그대로도 볼지(`lit`). dir-stack tilde(`~-`·`~+`·`~N`·`~+N`·
        `~-N`, 따옴표 밖·tilde 접두에 인용 없음)가 아니면 (None, False). `_dest`(cd 대상)와 `_tilde_variants`(cd 대상 밖, F)가 같이 쓴다."""
        m = DIRSTACK_TILDE_RE.match(arg) if arg is not None and getattr(arg, "tilde", True) else None
        if not m or not (m.group(1) or m.group(2)):
            return None, False
        return self._key_dirs(m.group(1), m.group(2), prev)

    def _key_dirs(self, sign: str, num: str, prev) -> tuple[tuple[Path, ...], bool]:
        """dir-stack tilde 접두(`~` + `sign` + `num`)의 후보 디렉토리와 글자 그대로도 볼지. POSIX 셸(dash) 글이면 늘 글자 그대로도 본다
        (dash는 `~-`·`~+`·`~N`을 풀지 않는다 — `sh -c 'cd ~-'`는 실패하고 cwd는 그대로다)."""
        st = self.st
        exact = st.exact and not st.sticky
        n = int(num) if num else None
        lit = True                                         # 풀지 못했을 수 있다(글자 그대로)
        if n is None and sign == "-":                      # `~-`: OLDPWD(정적 대입·물려받은 값 포함 — E)
            dirs, lit = self._oldpwd_dirs(), False
        elif n is None or (n == 0 and sign != "-"):        # `~+`·`~0`·`~+0`: PWD(정적 대입 포함 — E)
            dirs, lit = self._pwdnow_dirs(prev), False
        elif sign != "-" and exact and n <= len(st.stack):    # `~N`·`~+N`: 맨 위에서 N번째
            dirs, lit = st.stack[-n], False
        elif sign != "-" and exact:                        # 이 글이 쌓은 칸보다 깊다: 이 글 밖 칸이거나 풀지 못한다
            dirs = (UNKNOWN_DIR,)
        else:                                              # `~-N`·칸을 모르는 스택
            dirs = st.stack_dirs() + (UNKNOWN_DIR,) + prev
        return dirs, lit or self.posix or UNKNOWN_DIR in dirs

    def _tilde_variants(self, rest: list[str], d: Path) -> list[list[str]]:
        """cd 대상 밖의 dir-stack tilde(`-C ~-`·`env -C ~-`·리디렉션 대상 `> ~-/f`, 대입꼴 값 `GIT_DIR=~-/.git`·`env X=a:~-`)를 이 글의
        cd/스택 상태로 풀어 argv 변형을 만든다(F). 한 단순 명령의 같은 접두(`~-`끼리·`~+`·`~0`끼리·같은 `~N`끼리)는 같은 값으로 풀리므로
        접두 값마다 변형 하나다(풀 수 없으면 글자 그대로도). 접두가 여럿이라 변형이 넘치면(16개) 접두 하나만 푼 변형들로 본다(후보를
        버리지 않는다). 셸이 풀지 않는 꼴(`--opt=~-`·`"~-"`·`a=x=~-`)은 표시가 없어 그대로 둔다."""
        slots: list[tuple] = []         # (낱말 자리, 접두 시작, 끝, 열쇠, 부호, 수)
        for i, t in enumerate(rest):
            word = str(t)
            starts = ((0,) if getattr(t, "tilde", False) else ()) + tuple(getattr(t, "atilde", ()))
            for p in starts:
                e = p + 1
                while e < len(word) and word[e] != "/" and not (p and word[e] == ":"):
                    e += 1
                m = re.fullmatch(r"~([+-]?)([0-9]*)", word[p:e])
                if not m or not (m.group(1) or m.group(2)):
                    continue
                sign, num = m.group(1), m.group(2)
                n = int(num) if num else None
                key = ("pwd",) if (n is None and sign != "-") or (n == 0 and sign != "-") else (
                    ("old",) if n is None else (sign or "+", n))
                slots.append((i, p, e, key, sign, num))
        if not slots:
            return [rest]
        reps: dict[tuple, list] = {}
        for _, _, _, key, sign, num in slots:
            if key in reps:
                continue
            dirs, lit = self._key_dirs(sign, num, (d,))
            vals: list = [str(c) for c in dict.fromkeys(dirs) if c != UNKNOWN_DIR]
            if lit or not vals:
                vals.append(None)                           # 글자 그대로(모르는 칸 — 판정 못 하는 후보도 버리지 않는다)
            reps[key] = vals

        def subst(choice: dict) -> list[str]:
            out = list(rest)
            for i, p, e, key, _, _ in sorted(slots, key=lambda x: (x[0], -x[1])):   # 한 낱말 안은 뒤 자리부터
                val = choice.get(key)
                if val is None:
                    continue
                word = str(out[i])
                after = word[e:]
                if after.startswith("/"):                   # `~-//x`는 `$OLDPWD/x`(앞 `/`를 모두 뗀다 — 재리뷰 P0)
                    val, after = val.rstrip("/"), "/" + after.lstrip("/")
                out[i] = word[:p] + val + after
            return out

        keys = list(reps)
        total = 1
        for key in keys:
            total *= len(reps[key])
        if total <= 16:
            choices: list[dict] = [{}]
            for key in keys:
                choices = [{**c, key: v} for c in choices for v in reps[key]]
        else:
            choices = [{}] + [{key: v} for key in keys for v in reps[key] if v is not None]
        return [subst(c) for c in choices]

    def _stack_only(self, name: str, arg, num, dyn: bool, exact: bool, prev) -> None:
        """`pushd -n`·`popd -n`: cwd는 그대로 두고 스택만 고친다. 칸을 정확히 모르면 스택을 모른다고 표시한다."""
        st = self.st
        if name == "pushd" and arg is not None and not num and not dyn:
            targets = self._dest(arg, prev)
            st.stack.append(targets)                   # bash `dirs`의 1번 칸
            if not all(_sure_dir(t) for t in targets):
                st.exact = False
            return
        k = 1 if arg is None else int(num.group(2)) if num and num.group(1) == "+" else None
        if name == "popd" and exact and k is not None and 1 <= k:
            if k <= len(st.stack):
                del st.stack[-k]
            return                                     # 이 글 밖 칸을 지우거나 실패한다
        st.exact = False

    def _flush_fails(self) -> None:
        """`&&` 앞 명령이 실패했을 때 상태들을 지금 상태에 합친다(`||` 뒤)."""
        if self.fails:
            self.st = _Cwd.union([*self.fails, self.st])
            self.fails = []

    def _flush(self) -> None:
        """건너뛴 상태들(`&&` 앞 실패·`||` 앞 성공)을 모두 지금 상태에 합친다(목록 끝·복합 명령 끝·분기 끝)."""
        self._flush_fails()
        if self.oks:
            self.st = _Cwd.union([*self.oks, self.st])
            self.oks = []

    def end_list(self, background: bool) -> None:
        """and-or 목록 끝. `&` 백그라운드면 목록 시작 상태로 되돌리고, 조건부(`&&`·`||`)였거나 실패했을 수 있는 cd가 있었으면 전후
        후보를 합친다."""
        if background:
            self.st, self.fails, self.oks = self.list_start.copy(), [], []
        else:
            self._flush()
            if self.andor is not None:
                self.st = _Cwd.union([self.andor, self.st])
        self.andor, self.list_start, self.cd_last = None, self.st.copy(), False

    def open(self, kind: str, piped: bool) -> None:
        self.frames.append([kind, self.st.copy(), self.andor, self.list_start, piped, self.func, [], self.fails,
                            self.oks, []])
        self.func = False
        self.andor, self.list_start, self.fails, self.oks = None, self.st.copy(), [], []

    def _pop_to(self, kinds) -> list | None:
        for idx in range(len(self.frames) - 1, -1, -1):
            if self.frames[idx][0] in kinds:
                frame = self.frames[idx]
                del self.frames[idx:]
                return frame
        return None

    def close(self, word: str, piped_after: bool) -> None:
        frame = self._pop_to(CLOSERS[word])
        if frame is None:
            self.st.sticky = True           # 짝 없는 닫는 말
            return
        self._flush()
        kind, saved, andor, list_start, piped, func, branches, fails, oks, conds = frame
        if func:                            # 정의만 했다. 본문 cd는 부를 때 돈다 — 언제인지 모른다
            changed = any(s.dirs != saved.dirs or s.stack != saved.stack or s.sticky for s in (*branches, self.st))
            st = saved.copy()
            st.sticky = st.sticky or changed
        elif piped or piped_after:          # 파이프·백그라운드 요소: 서브셸
            st = saved.copy()
        elif kind == "{":
            st = self.st
        else:                               # 분기·루프: 돌지 않았을 수도 있다(조건의 끝 상태에서 분기 없이 끝났을 수도 있다)
            st = _Cwd.union([saved, *conds, *branches, self.st])
            if kind in LOOPS and st.dirs != saved.dirs:
                st.dirs = _dedupe(st.dirs + (UNKNOWN_DIR,))
        self.st, self.andor, self.list_start, self.fails, self.oks = st, andor, list_start, fails, oks
        self.cd_last = False                # 복합 명령의 실패 상태는 끝 상태다(`&&`가 `fails`에 넣는다)
        self.seen += st.all()

    def close_paren(self) -> None:
        for idx in range(len(self.frames) - 1, -1, -1):
            kind = self.frames[idx][0]
            if kind == "case":              # case 패턴의 `)`
                return
            if kind == "(":
                frame = self.frames[idx]
                del self.frames[idx:]
                self.st, self.andor, self.list_start, self.fails, self.oks = (frame[1].copy(), frame[2], frame[3],
                                                                              frame[7], frame[8])
                self.cd_last = False
                return
        self.st.sticky = True               # 짝 없는 `)`

    def branch(self) -> None:
        """`else`·`elif`: 앞 분기의 끝 상태를 두고 `if`에 들어갈 때 상태와 앞 조건들의 끝 상태(조건의 cd도 돌았다 — `if ! cd X;
        then …; else …`의 else는 X에서 돈다, 재리뷰)를 합친 데서 다시 시작한다."""
        if self.frames and self.frames[-1][0] == "if":
            self._flush()
            self.frames[-1][6].append(self.st)
            self.st = _Cwd.union([self.frames[-1][1], *self.frames[-1][9]])

    def arm(self) -> None:
        """case 갈래 끝(`;;`): 갈래 끝 상태를 두고 `case`에 들어갈 때 상태에서 다시 시작한다."""
        if self.frames and self.frames[-1][0] == "case":
            self._flush()
            self.frames[-1][6].append(self.st)
            self.st = self.frames[-1][1].copy()


def invocations(command: str, cwd: Path, depth: int = 0, keep: tuple[str, ...] | None = None) -> list[Invocation]:
    """명령 글의 단순 명령들(`Invocation`: cwd·argv·앞 대입). cwd는 `_Walk`가 bash 범위대로 따라간다(조건부·분기 뒤에는 cwd
    후보마다 하나씩 — 닫힌 쪽). `keep`: 후보가 넘칠 때 접지 않을 보호 뿌리(`_keep_roots`, 이 걷기 동안만)."""
    global _KEEP_ROOTS
    if keep is None:
        return _Walk(_Cwd((cwd,)), depth).run(command)
    saved, _KEEP_ROOTS = _KEEP_ROOTS, tuple(keep)
    try:
        return _Walk(_Cwd((cwd,)), depth).run(command)
    finally:
        _KEEP_ROOTS = saved


def _keep_roots(conf: Config) -> tuple[str, ...]:
    """cwd 후보 넘침 때 접지 않을 보호 뿌리: 모든 프로필의 clone·work_dir(작업 worktree·스냅샷)과 스킬 소스(정규화 경로)."""
    roots = []
    for p in [*conf.clones, *conf.work_dirs, *conf.skill_sources]:
        try:
            roots.append(_norm(str(p)))
        except Exception:  # noqa: BLE001, S112
            continue
    return tuple(dict.fromkeys(roots))


# -- git 명령 판정 ----------------------------------------------------------------------------


class GitCall:
    """`git [전역 옵션] <sub> <args>`를 나눈다. 레포 판별 디렉토리(`cwd`)는 `-C` 뒤에 환경변수
    `GIT_DIR`·`GIT_COMMON_DIR`·`GIT_WORK_TREE`, 그 뒤에 `--git-dir`·`--work-tree`(명령줄이 환경변수보다 우선)를 반영한다
    (work tree가 있으면 그것, 없으면 git dir)."""

    def __init__(self, inv: Invocation):
        argv = inv.argv
        cwd = inv.cwd
        self.config_overrides: list[str] = []
        self.sub = None
        self.args: list[str] = []
        git_dir = work_tree = None

        def at(base: Path, value: str) -> Path:
            d = _expand(value)
            return Path(d) if Path(d).is_absolute() else base / d

        i = 1
        while i < len(argv):
            tok = argv[i]
            if tok == "-C" and i + 1 < len(argv):
                cwd = at(cwd, argv[i + 1])
                i += 2
            elif tok == "-c" and i + 1 < len(argv):
                self.config_overrides.append(argv[i + 1])
                i += 2
            elif tok.startswith("--config-env="):
                self.config_overrides.append(tok.split("=", 1)[1])
                i += 1
            elif tok.startswith(("--git-dir=", "--work-tree=")):
                key, _, value = tok.partition("=")
                if key == "--git-dir":
                    git_dir = at(cwd, value)
                else:
                    work_tree = at(cwd, value)
                i += 1
            elif tok in GIT_GLOBAL_WITH_ARG:
                if i + 1 < len(argv):
                    if tok == "--config-env":
                        self.config_overrides.append(argv[i + 1])
                    elif tok == "--git-dir":
                        git_dir = at(cwd, argv[i + 1])
                    elif tok == "--work-tree":
                        work_tree = at(cwd, argv[i + 1])
                i += 2
            elif tok.startswith("-"):
                i += 1
            else:
                self.sub = tok
                self.args = argv[i + 1:]
                break
        env = inv.env
        env_dir = env.get("GIT_DIR") or env.get("GIT_COMMON_DIR")
        git_dir = git_dir or (at(cwd, env_dir) if env_dir else None)
        work_tree = work_tree or (at(cwd, env["GIT_WORK_TREE"]) if env.get("GIT_WORK_TREE") else None)
        self.cwd = work_tree or git_dir or cwd
        # 규칙 12 (a)는 셋을 따로 본다(어느 하나라도 관리 clone 안이면 읽기 목록만): -C 뒤 cwd, git dir, work tree
        self.dir, self.git_dir, self.work_tree = cwd, git_dir, work_tree
        # 값 해석 없이 존재만 본다: hooksPath·index를 끼워 넣는 통로이고 정상 흐름에 없다 (규칙 5)
        self.config_env = sorted(k for k in env if k in GIT_CONFIG_ENV or re.match(r"^GIT_CONFIG_(KEY|VALUE)_\d+$", k))

    def overrides_hooks_path(self) -> bool:
        return any(o.split("=", 1)[0].strip().lower() == HOOKS_PATH_KEY for o in self.config_overrides)


def _is_no_verify(arg: str) -> bool:
    name = arg.split("=", 1)[0]
    return len(name) >= len("--no-v") and "--no-verify".startswith(name)


def commit_bypass(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a.startswith("--"):
            if _is_no_verify(a):
                return a
            if a in COMMIT_LONG_WITH_ARG:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            for j, ch in enumerate(a[1:], 1):
                if ch == "n":
                    return a
                if ch in COMMIT_SHORT_WITH_ARG:
                    if j == len(a) - 1:
                        i += 1
                    break
        i += 1
    return None


def _db_cfg(top: Path):
    """이슈 DB 레포 꼭대기의 `issue-db.config.yaml`(읽지 못하면 빈 dict — 객체가 아닐 수 있다)."""
    try:
        from common import yamlio
        return yamlio.safe_load((top / "issue-db.config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        return {}


RULE5_ACTIONS_NOTE = (" 이 이슈 DB는 ci_mode: actions라 서버 CI(db-check)가 마스킹·생성 파일 검사를 다시 하므로 거부 대신 "
                      "확인한다 — 사용자가 직접 요청했을 때만 허용한다.")


def _ci_actions(cwd: Path, base: str | None) -> bool:
    """규칙 5 완화 조건: `origin/<base>`(그 clone 프로필의 base 브랜치)의 `issue-db.config.yaml` `ci_mode`가 정확히 `actions`다.
    작업 트리·index의 파일은 보지 않는다(Claude가 고칠 수 있다). 없음·못 읽음·객체가 아님·오류면 False(닫힌 쪽)."""
    if not base:
        return False
    try:
        from common import yamlio
        got = _git(cwd, "--no-replace-objects", "show", f"refs/remotes/origin/{base}:issue-db.config.yaml")   # `git replace` 무시
        cfg = yamlio.safe_load(got.stdout) if got.returncode == 0 else None
        return isinstance(cfg, dict) and cfg.get("ci_mode") == "actions"
    except Exception:  # noqa: BLE001 — 확인하지 못하면 거부
        return False


def _rule5(call: GitCall, dec: Decision, msg: str) -> bool:
    """규칙 5(hook 우회) 결정. 그 clone의 `origin/<base>` `issue-db.config.yaml` `ci_mode`가 정확히 `actions`로 확인되면
    (`_ci_actions`) ask하고 False, 아니면(local·없음·읽지 못함·객체가 아님·오류 — 닫힌 쪽) deny하고 True(호출한 쪽은 예전처럼
    거기서 멈춘다). base는 `check_git`이 `call.db_base`에 둔다."""
    if _ci_actions(call.cwd, getattr(call, "db_base", None)):
        dec.ask.append(msg + RULE5_ACTIONS_NOTE)
        return False
    dec.deny.append(msg)
    return True


def check_push(call: GitCall, dec: Decision) -> None:
    """이슈 DB push는 ask(규칙 7). base 브랜치 push(refspec·`--all`·`--mirror` — 규칙 6)는 따로 거부하지 않는다: 서버 브랜치
    보호(필수 PR·force push·삭제 금지·관리자 포함)가 막는다(전제: site_checks `s4a.protection_guard`). push `--no-verify`는 규칙 5."""
    if any(a.startswith("--") and _is_no_verify(a) for a in call.args):
        _rule5(call, dec, "git push의 --no-verify는 pre-push 검사를 건너뛰므로 금지한다 (규칙 5).")
    dec.ask.append("이슈 DB push다. 확인 화면(변경 파일·diff·검사 결과·커밋 메시지)을 승인한 뒤에만 진행한다 (규칙 7). "
                   "base 브랜치(main)로는 push하지 않는다 — 서버 브랜치 보호가 막는다 (규칙 6).")


def _config_parse(args: list[str]) -> tuple[str | None, list[str]]:
    """`git config` 인자 → (동작 — `--get`·`--unset`·`set`·`-e` 등, 없으면 None, 위치 인자)."""
    action = None
    pos: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in CONFIG_WITH_ARG:
            i += 2
            continue
        if a.startswith("--"):
            name = a[2:].split("=", 1)[0]
            if name in CONFIG_READ_ACTIONS or name in ("unset", "unset-all", "replace-all", "add", "edit",
                                                       "remove-section", "rename-section"):
                action = action or name
        elif a == "-e":
            action = action or "edit"
        elif a == "-l":
            action = action or "list"
        elif a.startswith("-"):
            pass
        elif not pos and action is None and a in CONFIG_SUBCOMMANDS:
            action = a
        else:
            pos.append(a)
        i += 1
    return action, pos


def check_config(call: GitCall, dec: Decision) -> None:
    action, pos = _config_parse(call.args)
    if action in CONFIG_READ_ACTIONS:
        return
    if action == "edit":
        _rule5(call, dec, "이슈 DB에서 git config --edit는 core.hooksPath를 바꿀 수 있어 금지한다 (규칙 5).")
        return
    if action in ("remove-section", "rename-section"):
        if pos and pos[0].lower() == "core":
            _rule5(call, dec, "core 섹션을 지우거나 바꾸면 core.hooksPath가 해제된다 (규칙 5).")
        return
    if not pos or pos[0].lower() != HOOKS_PATH_KEY:
        return
    if action in ("unset", "unset-all"):
        _rule5(call, dec, "core.hooksPath 해제는 금지다 (규칙 5). git hook(pre-commit·pre-push)이 꺼진다.")
        return
    if len(pos) < 2:
        return   # 값 없이 키만: 읽기
    if pos[1] != ".githooks":
        _rule5(call, dec, f"core.hooksPath는 정확히 .githooks여야 한다 (규칙 5): '{pos[1]}'는 거부한다.")


def check_commit(call: GitCall, conf: Config, dec: Decision) -> None:
    """규칙 5(우회 플래그·hooksPath — `_rule5`: ci_mode actions면 ask하고 이어 간다)와 규칙 3·4(staged 검사)."""
    flag = commit_bypass(call.args)
    if flag and _rule5(call, dec, f"git commit {flag}는 pre-commit 검사를 건너뛰므로 금지한다 (규칙 5)."):
        return
    hooks = _git(call.cwd, "config", "--get", "core.hooksPath").stdout.strip()
    if hooks != ".githooks" and _rule5(call, dec, f"이 레포의 core.hooksPath가 '{hooks or '(없음)'}'다. 정확히 .githooks여야 "
                                                  "커밋할 수 있다 (규칙 5). setup 5번(hook)만 다시 한다 — `config.py install-hooks`."):
        return
    top = _git(call.cwd, "rev-parse", "--show-toplevel").stdout.strip()
    if not top:
        return
    staged = [p for p in _git(Path(top), "diff", "--cached", "--name-only", "-z").stdout.split("\0") if p]
    if not staged:
        return
    db_cfg = _db_cfg(Path(top))
    ci_mode = db_cfg.get("ci_mode", "local")
    branch = _git(Path(top), "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() if ci_mode != "actions-build" else ""
    ctx = checks.Ctx(db=top, scope="staged", files=staged, branch=branch, ci_mode=ci_mode, db_cfg=db_cfg,
                     plugin_root=conf.plugin_root)
    # 단계 순서(마스킹 → 캐시 → 생성 파일)와 migrate 브랜치 허용은 common/checks.py guard 프로필이 정한다.
    # 여기서는 실패한 단계를 deny 문구로 바꾼다 (실행 불가 2도 거부다).
    dec.deny.extend(checks.guard_deny_messages(checks.run_checks(checks.PROFILES["guard"], ctx).steps))


# -- 로그 원문 통독 차단 (10) ---------------------------------------------------------------


def _raw_cmd_verb(inv: Invocation) -> str | None:
    """원문 통독이 될 수 있는 명령이면 표시용 동사(`cat`, `head -c`, `unzip -p`), 아니면 None."""
    name = _base(inv.argv[0])
    flags = [a for a in inv.argv[1:] if a.startswith("-") and a != "-"]
    if name in RAW_ALWAYS_CMDS:
        return name
    if name in ("head", "tail"):
        for a in flags:
            if a == "--bytes" or a.startswith("--bytes="):
                return f"{name} -c"
            if not a.startswith("--") and "c" in re.split(r"\d", a[1:], maxsplit=1)[0]:
                return f"{name} -c"
    elif name == "unzip":
        for a in flags:
            if not a.startswith("--") and ("p" in a[1:] or "c" in a[1:]):
                return "unzip -p"
    return None


# 모든 줄에 맞는 패턴·스크립트: 통독과 같다 (보수적인 목록만)
MATCH_ALL_PATTERNS = {"", "^", ".*", "$", ".", "^.*$"}
MATCH_ALL_AWK = {"{print}", "{print$0}", "1"}
MATCH_ALL_SED = {"", "p", "1,$p", "0,$p"}
GREP_NON_DUMP_FLAGS = set("cqlL")   # 개수·존재만 내는 옵션은 통독이 아니다


def _words_and_stdin(argv: list[str]) -> tuple[list[str], list[str]]:
    """플래그를 남기고 출력 리디렉션·heredoc을 뺀 단어와, `<` 입력 파일."""
    words: list[str] = []
    stdin: list[str] = []
    skip = redir_in = False
    for tok in argv[1:]:
        m = IN_REDIR_RE.match(tok)
        if skip:
            skip = False
        elif redir_in:
            redir_in = False
            stdin.append(tok)
        elif m and m.group(1) in ("<", "<>"):           # 입력 파일(`<f`·`< f`·`0<f`)
            if m.group(2):
                stdin.append(m.group(2))
            else:
                redir_in = True
        elif m:                                         # heredoc 끝 표시·here-string·fd 복제: 파일이 아니다
            skip = not m.group(2)
        elif tok and REDIRECT_RE.match(tok):
            skip = not REDIRECT_RE.match(tok).group(1)
        else:
            words.append(tok)
    return words, stdin


def _dump_verb_and_files(inv: Invocation) -> tuple[str, list[str]] | None:
    """grep·rg·awk·sed가 모든 줄을 내보내는 형태면 (표시 동사, 대상 인자들), 아니면 None."""
    name = _base(inv.argv[0])
    if name not in ("grep", "egrep", "fgrep", "rg", "awk", "gawk", "mawk", "sed"):
        return None
    words, stdin = _words_and_stdin(inv.argv)
    pos: list[str] = []
    pats: list[str] = []
    short_flags = ""
    quiet_kinds = False
    i = 0
    while i < len(words):
        w = words[i]
        i += 1
        if w == "--":
            pos += words[i:]
            break
        if w.startswith("--") and len(w) > 2:
            if name in ("grep", "egrep", "fgrep", "rg"):
                if w.startswith("--regexp="):
                    pats.append(w.split("=", 1)[1])
                elif w == "--regexp" and i < len(words):
                    pats.append(words[i])
                    i += 1
                elif w in ("--count", "--quiet", "--silent", "--files-with-matches", "--files-without-match"):
                    quiet_kinds = True
            elif name == "sed":
                if w.startswith("--expression="):
                    pats.append(w.split("=", 1)[1])
                elif w == "--expression" and i < len(words):
                    pats.append(words[i])
                    i += 1
                elif w in ("--quiet", "--silent"):
                    short_flags += "n"
            continue
        if w.startswith("-") and len(w) > 1:
            cluster = w[1:]
            short_flags += cluster
            takes = {"grep": "efmAB", "egrep": "efmAB", "fgrep": "efmAB", "rg": "efmABg",
                     "awk": "Fvf", "gawk": "Fvf", "mawk": "Fvf", "sed": "ef"}[name]
            # 값을 받는 옵션이 클러스터 끝에 오면 다음 단어가 값, 중간에 오면 나머지가 값
            for k, ch in enumerate(cluster):
                if ch in takes:
                    rest = cluster[k + 1:]
                    val = rest or (words[i] if i < len(words) else None)
                    if not rest:
                        i += 1
                    if ch == "e" and val is not None:
                        pats.append(val)
                    elif ch in "fv" and name in ("awk", "gawk", "mawk", "sed", "grep", "egrep", "fgrep", "rg"):
                        if ch == "f":
                            pats.append("\0file")   # 파일에서 읽는 프로그램·패턴: 판단하지 않는다
                    break
            continue
        pos.append(w)
    if name in ("grep", "egrep", "fgrep", "rg"):
        if set(short_flags) & GREP_NON_DUMP_FLAGS or quiet_kinds:
            return None
        if not pats:
            if not pos:
                return None
            pats, pos = [pos[0]], pos[1:]
        hit = any(p in MATCH_ALL_PATTERNS for p in pats) and "\0file" not in pats
        if "v" in short_flags or "--invert-match" in inv.argv:
            hit = False
        verb = f"{name} {pats[0]!r}"
    elif name == "sed":
        if not pats:
            if not pos:
                return None
            pats, pos = [pos[0]], pos[1:]
        script = pats[0].replace(" ", "")
        hit = len(pats) == 1 and "\0file" not in pats and script in MATCH_ALL_SED and "i" not in short_flags
        verb = f"sed {pats[0]!r}"
    else:
        if not pats or "\0file" in pats:
            if not pos:
                return None
            prog, pos = pos[0], pos[1:]
        else:
            return None
        hit = prog.replace(" ", "").rstrip(";") in MATCH_ALL_AWK or prog.replace(" ", "") in ("{print;}",)
        verb = f"{name} {prog!r}"
    if not hit:
        return None
    return verb, pos + stdin


def _raw_args(argv: list[str]) -> list[str]:
    """위치 인자와 `<` 대상. `>`·`>>`·`2>` 등 출력 리디렉션과 heredoc은 뺀다."""
    out: list[str] = []
    skip = False
    redir_in = False
    for tok in argv[1:]:
        if skip:
            skip = False
            continue
        if redir_in:
            redir_in = False
            out.append(tok)
            continue
        m = IN_REDIR_RE.match(tok)
        if m and m.group(1) in ("<", "<>"):             # 입력 파일(`<f`·`< f`·`0<f`)
            if m.group(2):
                out.append(m.group(2))
            else:
                redir_in = True
            continue
        if m:                                           # heredoc 끝 표시·here-string·fd 복제: 파일이 아니다
            skip = not m.group(2)
            continue
        m = REDIRECT_RE.match(tok)
        if m:
            skip = not m.group(1)
            continue
        if tok.startswith("-") and tok != "-":
            continue
        out.append(tok)
    return out


# 규칙 10 최소 내장 판별: 플랫폼 레지스트리(또는 플랫폼 하나)를 못 불러올 때만 더한다. 플랫폼 판별보다 넓게 잡는다
# (줄 맨 앞 logcat 스탬프 — threadtime·time 형식을 모두 덮는다 — 와 bugreport 머리). 원문 차단은 넓을수록 안전하다.
_RAW_FALLBACK_STAMP = re.compile(r"^(?:\d{4}-)?\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3,9}\s")
RAW_FALLBACK_SNIFFERS = [
    lambda line: bool(_RAW_FALLBACK_STAMP.match(line)),
    lambda line: line.startswith("== dumpstate") or (line.startswith("------ ") and line.rstrip().endswith(" ------")),
]


def _sniff_hit(sniff, line: str) -> bool:
    """판별 함수 하나. 예외가 나면 원문으로 본다(fail-closed — 판별이 깨져 원문 통독이 통과되지 않게)."""
    try:
        return bool(sniff(line))
    except Exception:  # noqa: BLE001
        return True


def _is_raw_file(path: Path, names: set, exempt: set, sniffers=()) -> bool:
    real = _norm(path)
    segs = real.replace("\\", "/").split("/")
    if exempt & set(segs[:-1]):
        return False
    if not os.path.isfile(real):
        return False
    if path.name in names:
        return True
    with open(real, "rb") as fh:
        head = fh.read(RAW_SNIFF_BYTES)
    if head.startswith(b"PK\x03\x04") or head.startswith(b"\x1f\x8b"):
        return True
    lines = head.decode("utf-8", errors="replace").splitlines()[:RAW_SNIFF_LINES]
    sniffers = sniffers() if callable(sniffers) else sniffers   # 머리를 볼 때만 플랫폼 모듈을 불러온다
    return any(_sniff_hit(sniff, line) for line in lines for sniff in sniffers)


def check_raw_read(command: str, cwd: Path, dec: Decision, conf: Config) -> None:
    names, exempt = conf.raw_names, conf.raw_exempt
    invs, _ = _walk_or_flat(command, cwd, keep=_keep_roots(conf))   # 걷기 예외면 대체 목록(거부는 check_bash가 남긴다)
    for inv in invs:
        verb = _raw_cmd_verb(inv)
        if verb is not None:
            args = _raw_args(inv.argv)
        else:
            dump = _dump_verb_and_files(inv)
            if dump is None:
                continue
            verb, args = dump
        for arg in args:
            word = _expand(arg)
            path = Path(word) if Path(word).is_absolute() else inv.cwd / word
            cands = [path]
            if any(ch in word for ch in "*?["):
                try:
                    cands = [Path(p) for p in sorted(glob.glob(str(path)))[:RAW_GLOB_MAX]]
                except ValueError:      # 경로에 NUL 등: OS도 열 수 없다(못 읽는 파일과 같다)
                    cands = []
            for cand in cands:
                try:
                    hit = _is_raw_file(cand, names, exempt, conf.raw_sniffers)
                except (OSError, ValueError):
                    hit = False
                if hit:
                    dec.deny.append(
                        "로그 원문·zip·events/issue_raw/match.json은 통째로 읽지 않는다(원칙 §로그 원문, "
                        f"규칙 10: {verb} {arg}). grep -n '<패턴>' <파일> 또는 sed -n '<a>,<b>p' <파일>로 필요한 "
                        "줄만 — 작업 디렉토리에 마스킹 사본 logs-masked/<이름>(analyze가 만든다, 줄 번호 같음)이 있으면 원문 대신 "
                        "그것을 읽는다. bugreport는 parse_logcat.py extract-bugreport. Read 도구도 limit·offset으로 구간만. "
                        "탐색·심층 분석을 묻기 전·답 대기 중·탐색 중이면 grep·sed·Read로도 원문을 보지 않는다(SKILL 5-2·explore.md).")
                    return


# -- gh (11) ---------------------------------------------------------------------------------
# 거친 판정(4-c): 대상 레포를 풀지 않는다(-R·GH_REPO·URL·cwd 원격을 보지 않는다 — 이슈 DB가 아닌 레포의 gh 병합·쓰기도 ask다).
# 병합 계열(`pr merge`·REST 병합 엔드포인트·GraphQL 병합·자동 병합 mutation·병합 별칭)과 그 밖 쓰기·모르는 그룹은 ask: 병합·main
# push는 이슈 DB 서버 브랜치 보호(필수 승인 1·Dismiss stale·관리자 포함·force push·삭제 금지)가 막는다(전제: site_checks
# `s4a.protection_guard`). 서버가 막지 못하는 Claude의 Approve·리뷰 기각과, 그것일 수 있는 꼴(셸이 정한 그룹·`pr` 동작·api 끝 칸,
# 못 보는 리뷰 별칭)은 거부한다 — 낱말 수준(따옴표를 뗀 명령 글·argv·gh가 읽는 파일)으로 본다.

GH_READ_ACTIONS = {"list", "view", "status", "download", "watch", "verify", "diff", "checks", "check", "clone", "get", "token"}
GH_READ_GROUPS = {"", "help", "version", "status", "search", "browse", "completion"}     # 동작과 무관하게 읽기
# 동작이 읽기 목록이면 읽기인 그룹. 그 밖 그룹(이미 만든 별칭 `gh <별칭>` 포함)은 모르는 그룹 — 쓰기(ask)
GH_GROUPS = {"pr", "issue", "release", "label", "secret", "variable", "ruleset", "workflow", "run", "cache", "project",
             "repo", "auth", "config", "extension", "gist", "org", "codespace", "gpg-key", "ssh-key", "attestation",
             "alias"}
# cobra 동작 별칭(gh 2.89 `--help`의 ALIASES): 원래 이름으로 바꿔 본다. 그룹 `co`는 gh 기본 별칭 `pr checkout`이다
GH_ACTION_ALIASES = {"ls": "list", "new": "create", "co": "checkout", "remove": "delete"}
GH_API_WITH_ARG = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "-H", "--header", "--input", "-q", "--jq",
                   "-t", "--template", "--hostname", "--cache", "-p", "--preview"}
GH_API_FIELDS = {"-f", "-F", "--field", "--raw-field"}
GH_API_SHORT_WITH_ARG = {k[1] for k in GH_API_WITH_ARG if not k.startswith("--")}
GH_API_LONG_WITH_ARG = {k for k in GH_API_WITH_ARG if k.startswith("--")}
# `gh pr review`의 값 받는 옵션(긴 이름과 짧은 글자). `-a`(--approve)는 bool이다
GH_REVIEW_LONG_WITH_ARG = {"--body", "--body-file", "--repo"}
GH_REVIEW_SHORT_WITH_ARG = set("bFR")
GH_FALSE = {"0", "f", "F", "false", "FALSE", "False"}    # strconv.ParseBool 거짓. 그 밖 값은 approve로 본다(못 읽는 값은 gh가 오류)
GH_BODY_MAX = 65536          # --input·@파일·별칭 파일은 이만큼까지 읽는다(넘거나 못 읽으면 못 읽은 본문)
GH_JSON_DEPTH_MAX = 64       # gh가 읽는 JSON 본문의 중첩 깊이 상한 — 넘으면 못 읽은 본문. 깊은 중첩에 `json.loads`가
                             # RecursionError를 내는지는 Python 판마다 다르다(3.14는 스택 기반 — 25,000단도 그냥 읽는다)
                             # 그래서 예외에 기대지 않고 글자를 세서 자른다
# GraphQL 엔드포인트: `graphql`, `/graphql`, 경로가 `/graphql`로 끝나는 URL(gh는 URL을 그대로 쓰고 필드를 JSON 본문으로 보낸다)
GH_GRAPHQL_RE = re.compile(r"^(?:/?|https?://[^/?#]+/(?:[^?#]*/)?)graphql/?(?:[?#].*)?$", re.IGNORECASE | re.DOTALL)
GH_REST_MERGE_RE = re.compile(r"/pulls/[^/]+/merge/?$|/merges/?$")
GH_REST_REVIEW_RE = re.compile(r"(?:^|/)pulls/[^/]+/reviews(?:/[^/]+/events)?/?$")    # 리뷰 만들기·PENDING 제출
GH_REST_DISMISS_RE = re.compile(r"(?:^|/)pulls/[^/]+/reviews/[^/]+/dismissals/?$")
GQL_MERGE_RE = re.compile(r"\b(?:mergePullRequest|enqueuePullRequest|mergeBranch)\b")
GQL_AUTOMERGE_RE = re.compile(r"\benablePullRequestAutoMerge\b")        # PR 자동 병합 켜기(거부 — 원칙 12)
# `gh pr merge --auto`(거짓 `--auto=false` 밖) — 별칭 정의 글에서도 본다
GH_AUTO_FLAG_RE = re.compile(r"(?<![\w-])--auto(?![\w-])(?!=(?:0|f|false)\b)", re.IGNORECASE)
GQL_REVIEW_RE = re.compile(r"\b(?:addPullRequestReview|submitPullRequestReview)\b")
GQL_EVENT_VAR_RE = re.compile(r"\bevent\s*:\s*\$")      # 리뷰 mutation의 event가 GraphQL 변수다
# 낱말 수준 Approve·기각(대소문자 무관): `--approve`·`event=APPROVE`·GraphQL `APPROVE`·`dismissals`·`dismissPullRequestReview`.
# 읽기에 흔한 `APPROVED`·`DISMISSED`(상태 값)와 bool 거짓 `--approve=0|f|false`(`GH_FALSE`)는 아니다
GH_APPROVE_WORD_RE = re.compile(r"approve(?!d)(?!=(?:0|f|false)\b)", re.IGNORECASE)
GH_DISMISS_WORD_RE = re.compile(r"dismiss(?!ed)", re.IGNORECASE)
# 리뷰 별칭은 `gh <별칭> 3 -a`를 못 본다. 자리 표시(`$1`·`$@`·`$*`)·셸 별칭(`--shell`·`!…`)은 실행 때 동작이 정해진다
ALIAS_RISKY_RE = re.compile(r"review|approve|dismiss|\$[0-9@*]|--shell|(?:^|\s)!", re.IGNORECASE)
GH_SUBST_FILE_RE = re.compile(r"^\s*\$\(\s*(?:cat\s+|<\s*)([^\s$`'\"()<>|;&]+)\s*\)\s*$")    # `query="$(cat f)"`·`$(< f)`
# `query="$(cat <<'EOF' …)"` — 걷기가 토큰에서 본문을 떼 낸다(본문은 명령 글에 있다)
GH_SUBST_HEREDOC_RE = re.compile(r"^\s*\$\(\s*cat\s+<<-?\s*\\?(['\"]?)(\w+)\1(?=\s)[\s\S]*\)\s*$")   # 끝 표시 전체(`EOF-`·`'EOF'X`는 아니다)
# 서버 브랜치 보호·ruleset 바꾸기(4-c 뒤 병합을 막는 유일한 장치 — Approve와 같은 급, 사용자 결정)
GH_PROTECTION_RE = re.compile(r"(?:^|/)branches/.+?/protection(?:/|$)|(?:^|/)rulesets(?:/|$)", re.IGNORECASE)
GQL_PROTECTION_RE = re.compile(r"\b(?:create|update|delete)(?:BranchProtectionRule|RepositoryRuleset)\b")
GH_REPO_PATH_RE = re.compile(r"(?:^|/)(?:repos/[^/]+/[^/]+|repositories/\d+)/?$")   # 레포 설정(`PATCH repos/<o>/<r>`·`repositories/<id>`)
# 레포 설정의 자동 병합 허용·병합 뒤 브랜치 지우기 켜기(REST 필드·JSON — 거짓 `false`·`0` 밖은 켜기로 본다)
GH_AUTO_MERGE_ON_RE = re.compile(r"(?:allow_auto_merge|delete_branch_on_merge)[\"']?"
                                 r"\s*[:=]\s*[\"']?(?!false\b|0\b)\S", re.IGNORECASE)
GH_RANK = {"read": 0, "local": 1, "write": 2, "merge": 3, "alias": 4, "approve": 4, "dismiss": 4, "dynamic": 4,
           "protection": 4, "automerge": 4}
GH_MERGE_ASK = ("PR을 gh로 직접 머지하지 않는다(병합 계열). 이슈 DB면 병합은 +1 뒤 사용자가 요청할 때 db_pr.py merge"
                "(+1·승인 커밋·PR 검사 대조)로 하거나 사람이 GHE에서 한다 — 서버 브랜치 보호가 승인 1을 강제한다. 대상 레포를 보지 "
                "않으므로 다른 레포여도 묻는다. 사용자가 직접 요청한 병합일 때만 허용한다 (규칙 7·11).")
GH_WRITE_ASK = ("원격을 바꾸는 gh 명령이다(대상 레포를 보지 않는다 — 이슈 DB가 아니어도 묻는다). 이슈 DB면 변경·검증 결과를 보고 "
                "승인한 뒤에만 진행한다 (규칙 7·11).")
APPROVE_DENY = ("이슈 DB PR을 Claude가 Approve하지 않는다. +1(작성자 외 1명의 Approve)은 사람이 GHE에서 하고, "
                "병합은 그 뒤 db_pr.py merge가 확인한다 (규칙 11")
DISMISS_DENY = "리뷰를 Claude가 기각(dismiss)하지 않는다. 변경 요청은 그 리뷰어나 메인테이너가 GHE에서 푼다 (규칙 11"
ALIAS_DENY = ("gh 별칭으로 리뷰·Approve·기각 명령을 만들지 않는다(별칭 실행은 guard가 보지 못한다 — 못 읽은 별칭 파일도) "
              "(규칙 11).")
MCP_MERGE_ASK = ("MCP로 PR을 직접 머지하지 않는다(병합 계열, {tool}). 이슈 DB면 병합은 +1 뒤 사용자가 요청할 때 "
                 "db_pr.py merge로 하거나 사람이 GHE에서 한다. 대상 레포를 보지 않으므로 다른 레포여도 묻는다 (규칙 7·11).")
GH_DYN_DENY = ("셸이 푸는 값(`$`·백틱)으로 gh 동작·옵션·엔드포인트를 정하지 않는다. Approve·기각일 수 있어 거부한다. "
               "글자 그대로 쓴다 (규칙 11")
PROTECTION_DENY = ("서버 브랜치 보호·ruleset·레포 설정(자동 병합 허용·병합 뒤 브랜치 지우기)을 Claude가 바꾸지 않는다. 4-c 뒤 서버 브랜치 보호가 유일한 병합 장치라 "
                   "그것을 끄는 호출은 Approve와 같은 급이다 — 관리자가 GHE에서 한다 (규칙 11).")
AUTO_MERGE_DENY = ("PR 자동 병합을 Claude가 켜지 않는다. 자동 병합은 +1이 붙는 즉시 db_pr merge의 확인(승인 커밋 SHA 대조·메인테이너 "
                   "경로 PR 거부) 없이 병합한다 — 병합은 +1 뒤 사용자가 요청할 때 db_pr.py merge로만 한다 (원칙 12·규칙 11).")
# 낱말 수준 Approve·기각 거부의 안내(사용자 결정: 오탐을 받아들인다)
GH_WORD_NOTE = "approve·dismiss 낱말이 들어간 gh 호출은 본문·검색어라도 거부된다. 코멘트 본문에 그 낱말을 쓰지 않는다."
# 규칙 11 판정 사유의 첫 마디(eval 채점기가 hook이 막거나 물은 호출의 결과에서 찾는다 — 병합 계열은 ask)
GATE_DENY_HEADS = tuple(m.split("않는다", 1)[0] + "않는다" for m in (APPROVE_DENY, DISMISS_DENY, ALIAS_DENY, GH_DYN_DENY,
                                                                   PROTECTION_DENY, AUTO_MERGE_DENY))
GATE_ASK_HEADS = tuple(m.split("않는다", 1)[0] + "않는다" for m in (GH_MERGE_ASK, MCP_MERGE_ASK))


def _gh_words(argv: list[str]) -> list[str]:
    """`-R/--repo` 값을 뺀 위치 인자 (그룹·동작만 본다)."""
    words, skip = [], False
    for tok in argv[1:]:
        if skip:
            skip = False
        elif tok in ("-R", "--repo"):
            skip = True
        elif not tok.startswith("-"):
            words.append(tok)
    return words


def _json_too_deep(text: str | None, limit: int = GH_JSON_DEPTH_MAX) -> bool:
    """JSON 글의 `[`·`{` 중첩이 `limit`보다 깊은가(문자열 안은 세지 않는다). 파싱하지 않는 한 번 훑기 — `json.loads` 앞에서
    돌려 깊은 중첩을 Python 판과 무관하게 못 읽은 본문으로 만든다."""
    if not text:
        return False
    depth, in_str, esc = 0, False, False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}":
            depth -= 1
    return False


def _gh_read(path: str, cwd: Path | None) -> str | None:
    """`--input`·`@파일`·별칭 파일 내용(cwd 기준, `GH_BODY_MAX`까지). 없거나 크거나 못 읽으면 None. 내용은 출력하지 않는다."""
    target = Path(_expand(path))
    if not target.is_absolute():
        target = (cwd or Path(".")) / target
    try:
        if not target.is_file() or target.stat().st_size > GH_BODY_MAX:
            return None
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _pflag(tok: str, nxt: str | None, short, long) -> tuple[str | None, str, bool]:
    """pflag 옵션 토큰 하나 → `(값 받는 옵션, 값, 다음 토큰을 값으로 썼나)`. 값 받는 옵션이 없으면 `(None, "", False)`.
    긴 옵션은 `--k v`·`--k=v`. 짧은 옵션 묶음은 bool 글자를 건너뛰고, 첫 값 받는 글자 뒤 나머지(앞 `=` 하나는 뗀다)나 다음
    토큰이 값이다(`-X PUT`·`-XPUT`·`-X=PUT`·`-iX PUT`·`-if k=v`). bool 글자 뒤 `=`(`-i=true`)면 묶음이 끝난다. 토큰에서 잘라 낸
    값은 토큰의 셸 표시(`Word.dyn`·`bare`)를 물려받는다."""
    def cut(value: str) -> str:
        if not isinstance(tok, Word):
            return value
        w = Word(value)
        w.dyn, w.bare = tok.dyn, tok.bare
        return w
    if tok.startswith("--"):
        key, eq, value = tok.partition("=")
        if key not in long:
            return None, "", False
        return (key, cut(value), False) if eq else (key, nxt or "", nxt is not None)
    cluster = tok[1:]
    for k, ch in enumerate(cluster):
        rest = cluster[k + 1:]
        if ch in short:
            return ("-" + ch, cut(rest.removeprefix("=")), False) if rest else ("-" + ch, nxt or "", nxt is not None)
        if rest.startswith("="):
            break
    return None, "", False


def _gh_api_parse(argv: list[str]) -> dict:
    """`gh api` 인자 → `{endpoint, method, fields["k=v"], inputs[경로]}`. 옵션은 pflag 꼴로 읽는다(`_pflag`). `api` 앞 토큰
    (`gh -X PUT api …` — cobra가 끝 명령에 넘긴다)도 읽는다."""
    at = argv.index("api") if "api" in argv else len(argv)
    args = argv[1:at] + argv[at + 1:] if at < len(argv) else []
    endpoint, method, fields, inputs = None, None, [], []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("-"):
            key, value, used = _pflag(tok, args[i + 1] if i + 1 < len(args) else None,
                                      GH_API_SHORT_WITH_ARG, GH_API_LONG_WITH_ARG)
            i += used
            if key in ("-X", "--method"):
                method = value.upper()
            elif key in GH_API_FIELDS:
                fields.append(value)
            elif key == "--input":
                inputs.append(value)
        elif endpoint is None:
            endpoint = tok
        i += 1
    return {"endpoint": endpoint, "method": method, "fields": fields, "inputs": inputs}


def _gh_hay(argv: list[str], cwd: Path | None, text: str | None, stdin_known: bool = False) -> tuple[str, bool, list[str]]:
    """낱말 수준 검사의 글 `(글, 못 읽은 본문이 있나, --input 본문들)`. 글 = 따옴표·`\\`를 뗀 Bash 명령 글 전체(heredoc 본문·셸이
    만든 값 포함) + argv + gh가 읽는 파일(`@파일`·`--input`·`$(cat 파일)`·`alias import` 파일, `GH_BODY_MAX`까지). stdin(`-`·
    `@-`)은 그 호출 자신의 heredoc을 글자 그대로 알 때만(`stdin_known` — `_gh_kind`가 리디렉션을 빼기 전 argv로 `_gh_stdin_known`을
    본다) 읽은 것이다(그 글은 이미 들어 있다). 셸이 풀 경로·없는 파일은 못 읽은 본문이다."""
    toks, words = list(argv), _gh_words(_drop_redirs(list(argv)))     # `alias import - <<EOF`의 `<<EOF`는 파일이 아니다
    srcs = []
    for k, t in enumerate(toks):
        if t == "--input" and k + 1 < len(toks):
            srcs.append(("input", toks[k + 1]))
        elif t.startswith("--input="):
            srcs.append(("input", t[len("--input="):]))
        elif "=@" in t:
            srcs.append(("field", t.split("=@", 1)[1]))
        elif (m := GH_SUBST_FILE_RE.match(t.partition("=")[2])):
            srcs.append(("field", m.group(1)))
    if words[:2] == ["alias", "import"]:
        srcs.append(("field", words[2] if len(words) > 2 else "-"))
    elif words[:2] == ["alias", "set"] and "-" in toks:
        srcs.append(("field", "-"))
    parts, unread, inputs = [re.sub(r"[\"'\\]", "", text or ""), " ".join(toks)], False, []
    for kind, src in srcs:
        dyn = "$" in src or "`" in src or (isinstance(src, Word) and src.dyn)
        got = None if dyn else ((text or "") if stdin_known else None) if src == "-" else _gh_read(src, cwd)
        if _json_too_deep(got):            # 너무 깊은 JSON은 못 읽은 본문(리뷰 엔드포인트면 Approve 거부, 별칭이면 거부)
            got = None
        unread = unread or got is None
        parts.append(got or "")
        try:        # JSON 본문은 이스케이프를 푼 글도 본다(`"\u0041PPROVE"`·`\u006dergePullRequest` — gh는 그대로 보낸다)
            parts.append(json.dumps(json.loads(got), ensure_ascii=False))
        except (TypeError, ValueError):     # JSON 아님(깊은 중첩은 위에서 못 읽은 본문). 그 밖 예외는 올린다 — 판정 예외(거부, 4-c)
            pass
        if kind == "input":
            inputs.append(got)
    return "\n".join(parts), unread, inputs


def _json_obj(text: str | None) -> bool:
    if text is None or _json_too_deep(text):
        return False
    try:
        return isinstance(json.loads(text), dict)
    except (TypeError, ValueError):     # JSON 아님: 객체로 보지 않는다(리뷰 엔드포인트면 Approve). 그 밖 예외는 판정 예외(거부)
        return False


def _heredoc_known(text: str | None, tag: str | None = None) -> bool:
    """명령 글의 heredoc 본문(`tag`가 있으면 그 끝 표시의 것만)을 글자 그대로 아는가: 명령 글의 `<<` 수가 찾은 heredoc 수와
    같고(인용·`bash -c` 문자열·here-string 안의 `<<`가 있으면 어느 본문이 쓰이는지 모른다), 모두 끝까지 찾았고, 끝 표시를
    인용했거나(`<<'EOF'`·`<<"EOF"`·`<<\\EOF`) 본문에 `$`(`${` 포함)·백틱·`\\`(줄 이음)가 없다(인용하지 않은 본문은 셸이 푼다)."""
    scan = _heredoc_scan(text or "")
    if (text or "").count("<<") != len(scan):
        return False
    hds = [hd for hd in scan if tag is None or hd.tag == tag]
    return bool(hds) and all(hd.found and (hd.quoted or not any(c in hd.body for c in "$`\\")) for hd in hds)


def _gh_stdin_known(argv: list, text: str | None) -> bool:
    """gh가 stdin(`-`·`@-`)으로 읽는 글을 아는가: 그 호출의 마지막 stdin 리디렉션(fd 0)이 `<<`·`<<-`이고 그 끝 표시의 본문을
    글자 그대로 안다(`_heredoc_known`). 파이프·`<`·`<<<`·`<&`·리디렉션 없음은 모른다."""
    last = None
    for k, t in enumerate(argv):
        m = IN_REDIR_RE.match(str(t)) if getattr(t, "op", False) else None
        if m and str(t)[:m.start(1)] in ("", "0"):
            last = (m.group(1), m.group(2) or (str(argv[k + 1]) if k + 1 < len(argv) else ""))
    return bool(last) and last[0] in ("<<", "<<-") and _heredoc_known(text, last[1])


def _gh_review_approves(argv: list[str]) -> bool:
    """`gh pr review`가 Approve인가(순서·위치 무관, `review` 뒤 토큰): `--approve`, `--approve=<v>`·`-a=<v>`(v가 ParseBool 거짓이
    아니면), 짧은 옵션 묶음에서 값 받는 글자(`b`·`F`·`R`) 앞의 `a`(`-a`, `-ab LGTM`, `-ra`). 값 받는 옵션의 값은 건너뛴다.
    셸이 풀 토큰(`--approve`가 될 수 있다)도 Approve로 본다: 옵션 자리의 셸 값(`"$FLAG"`·`$OPT`), 선택자(첫 위치 인자) 뒤 위치
    인자의 셸 값, 따옴표 밖 확장인 옵션 값(`-b $B` — 낱말 나누기로 뒤가 옵션이 될 수 있다). 선택자(`"$N"`)와 따옴표 안 셸 값인
    옵션 값(`-b "$B"`)은 그대로다."""
    i = next((k + 1 for k, a in enumerate(argv) if str(a) == "review"), len(argv))
    positional = 0
    while i < len(argv):
        tok, i = argv[i], i + 1
        if tok == "--":
            break
        nxt = argv[i] if i < len(argv) else ""
        if not tok.startswith("-") or len(tok) < 2:
            positional += 1
            if _dyn(tok) and positional > 1:
                return True
            continue
        if tok.startswith("--"):
            key, eq, value = tok.partition("=")
            if _dyn(tok) and ("$" in key or "`" in key or (eq and _split(tok))):
                return True         # 옵션 이름이 셸 값이거나 값이 낱말 나누기로 옵션을 더할 수 있다
            if key in GH_REVIEW_LONG_WITH_ARG and not eq:
                if _split(nxt):
                    return True
                i += 1
            elif key == "--approve" and (not eq or value not in GH_FALSE):
                return True
            continue
        cluster = tok[1:]
        for k, ch in enumerate(cluster):
            if ch in "$`":
                return True         # 옵션 글자가 셸 값이다
            if ch == "a":
                rest = cluster[k + 1:]
                if not rest.startswith("=") or rest[1:] not in GH_FALSE:
                    return True
                break
            if ch in GH_REVIEW_SHORT_WITH_ARG or ch == "=":
                value = cluster[k + 1:] if ch != "=" else ""
                if ch != "=" and (_split(nxt) if not value else _split(tok)):
                    return True
                if ch != "=" and not value:
                    i += 1          # 값이 다음 토큰
                break
    return False


def _gql_query_read(value: str, text: str | None) -> bool:
    """셸이 만든 `query` 값을 읽었나: `$(cat 파일)`(`_gh_hay`가 읽었다 — 못 읽으면 따로 unread)·`$(cat <<EOF …)`(그 heredoc
    본문을 글자 그대로 안다 — `_heredoc_known`). 그 밖(`"$Q"`, 인용하지 않은 본문의 `$(…)`·`$Q`·백틱)은 못 읽은 본문이다."""
    if GH_SUBST_FILE_RE.match(value):
        return True
    m = GH_SUBST_HEREDOC_RE.match(value)
    return bool(m) and _heredoc_known(text, m.group(2))


def _gh_api_kind(argv: list[str], hay: str, unread: bool, inputs: list, text: str | None = None) -> str:
    """`gh api`의 종류(대상 레포는 보지 않는다). REST는 메서드를 밝히면 GET이 아닐 때만 쓰기, 밝히지 않으면 필드·`--input`이
    있을 때 쓰기(gh 기본 POST). GraphQL은 `mutation`·`--input`·못 읽은 본문·셸 값 필드가 있으면 쓰기. 쓰기의 REST 기각
    엔드포인트는 dismiss, 리뷰 엔드포인트는 `event=@…`·셸 값 필드·못 읽은·JSON 객체가 아닌 본문이면 Approve(`event=APPROVE`는
    낱말 수준이 먼저 본다), 병합 엔드포인트는 merge. 셸이 푼 엔드포인트는 끝 칸으로 가리고 끝 칸이 셸 값이면 dynamic."""
    p = _gh_api_parse(argv)
    ep = p["endpoint"] or ""
    path = urllib.parse.unquote(re.split(r"[?#]", ep, maxsplit=1)[0])    # `pulls/3/%6Derge`(서버가 경로를 푼다)
    tail = path.rstrip("/").rsplit("/", 1)[-1].lower()
    dyn_ep, dyn_field = _dyn(ep), any(_dyn(f) for f in [*p["fields"], *p["inputs"]])
    write = p["method"] not in (None, "GET") or (p["method"] is None and bool(p["fields"] or p["inputs"]))
    if GQL_PROTECTION_RE.search(hay) or (write and (GH_PROTECTION_RE.search(path) or (
            GH_REPO_PATH_RE.search(path) and GH_AUTO_MERGE_ON_RE.search(hay)))):
        return "protection"
    if GQL_AUTOMERGE_RE.search(hay):
        return "automerge"
    if GQL_MERGE_RE.search(hay):
        return "merge"
    if GH_GRAPHQL_RE.match(urllib.parse.unquote(ep)) or (dyn_ep and tail == "graphql"):
        # 못 읽은 `query`(`"$Q"` — `$(cat 파일)`·`$(cat <<EOF …)` 밖 셸 값)는 쓰기. 그 밖 셸 값 변수(`-f o="$OWNER"`)는 mutation일
        # 때만 쓰기다(mutation이면 아래에서 이미 쓰기)
        q_unread = any(_dyn(f) and f.partition("=")[0] == "query" and not _gql_query_read(f.partition("=")[2], text)
                       for f in p["fields"])
        return "write" if unread or q_unread or p["inputs"] or re.search(r"\bmutation\b", hay) else "read"
    if not (p["method"] != "GET" if p["method"] is not None else p["fields"] or p["inputs"]):
        return "read"
    if GH_REST_DISMISS_RE.search(path) or tail == "dismissals":
        return "dismiss"
    if GH_REST_REVIEW_RE.search(path) or (dyn_ep and tail in ("reviews", "events")):
        bad = unread or dyn_field or "event=@" in " ".join(argv) or not all(map(_json_obj, inputs))
        return "approve" if bad else "write"
    if GH_REST_MERGE_RE.search(path) or (dyn_ep and tail in ("merge", "merges")):
        return "merge"
    return "dynamic" if dyn_ep and ("$" in tail or "`" in tail or not tail) else "write"


def _gh_slot(toks: list[str], start: int) -> list[int]:
    """`start`부터 옵션을 건너뛴 첫 위치 인자 자리의 후보(토큰 번호). `=` 없는 옵션 바로 뒤 토큰은 그 옵션의 값일 수도 있어
    (cobra — bool로 등록됐는지 guard는 모른다) 그 다음 위치 인자도 후보다(닫힌 쪽 — `gh pr -b x -b y checkout 3`)."""
    out, i = [], start
    while i < len(toks):
        t = toks[i]
        if t.startswith("-") and len(t) > 1:
            i += 1
            continue
        out.append(i)
        prev = toks[i - 1] if i > start else ""
        if not (prev.startswith("-") and len(prev) > 1 and "=" not in prev and prev != "--"):
            break
        i += 1
    return out


def _gh_local(argv: list[str]) -> bool:
    """`gh pr checkout`·`gh pr co`·`gh co`(로컬 브랜치를 바꾼다 — 규칙 8). 그룹 자리와 `pr` 뒤 동작 자리만 본다(`gh pr list
    --search checkout`은 아니다). 그 앞의 옵션은 몇 개든 건너뛴다(`_gh_slot` — 값을 먹을 수 있는 옵션 뒤는 다음 자리도)."""
    toks = [str(t) for t in argv]
    for g in _gh_slot(toks, 1):
        if toks[g] == "co" or (toks[g] == "pr" and {"checkout", "co"} & {toks[a] for a in _gh_slot(toks, g + 1)}):
            return True
    return False


def _gh_merge_auto(argv: list) -> bool:
    """`gh pr merge`가 자동 병합을 켜나(원칙 12로 거부): `--auto`(거짓 `--auto=false` 밖), 선택자(첫 위치 인자) 뒤의 따옴표 밖
    셸 값과 셸 값 옵션(낱말 나누기로 `--auto`가 될 수 있다 — `_gh_review_approves`와 같은 닫힌 쪽)."""
    i = next((k + 1 for k, a in enumerate(argv) if str(a) == "merge"), len(argv))
    positional = 0
    for t in argv[i:]:
        key, _, val = str(t).partition("=")
        if key == "--auto" and val.lower() not in GH_FALSE:
            return True
        if not str(t).startswith("-"):
            positional += 1
        if _split(t) and (positional > 1 or str(t).startswith("-")):
            return True
    return False


def _gh_kind1(argv: list[str], cwd: Path | None, text: str | None, stdin_known: bool = False) -> str:
    hay, unread, inputs = _gh_hay(argv, cwd, text, stdin_known)
    words = _gh_words(argv)
    group = words[0] if words else ""
    action = GH_ACTION_ALIASES.get(words[1], words[1]) if len(words) > 1 else ""
    if group == "alias" and action in ("set", "import"):
        # `gh alias set x "$(…)"` — 별칭 내용을 모른다. `-s`(셸 별칭)는 실행 때 무엇이든 돌린다
        dyn = any(_dyn(t) for t in argv[2:]) or any(str(t) in ("-s", "--shell") for t in argv[3:])
        if unread or dyn or ALIAS_RISKY_RE.search(hay):
            return "alias"
        merge = "merge" in hay.lower()
        return ("automerge" if GH_AUTO_FLAG_RE.search(hay) or GQL_AUTOMERGE_RE.search(hay) else "merge") if merge else "read"
    if GH_DISMISS_WORD_RE.search(hay):
        return "dismiss"
    if GH_APPROVE_WORD_RE.search(hay) or ("review" in words and _gh_review_approves(argv)) or (
            GQL_REVIEW_RE.search(hay) and GQL_EVENT_VAR_RE.search(hay) and (unread or any(map(_dyn, argv)))):
        return "approve"
    if group == "repo" and action == "edit" and any(
            str(t).startswith(("--enable-auto-merge", "--delete-branch-on-merge")) and
            str(t).partition("=")[2].lower() not in GH_FALSE for t in argv):
        return "protection"
    if _dyn(group) or (group in ("pr", "alias") and action and _dyn(action)):
        return "dynamic"
    if group == "api":
        return _gh_api_kind(argv, hay, unread, inputs, text)
    if _gh_local(argv):
        return "local"
    if "pr" in words and "merge" in words[words.index("pr") + 1:]:
        return "automerge" if _gh_merge_auto(argv) else "merge"
    if group in GH_READ_GROUPS or (group in GH_GROUPS and (not action or action in GH_READ_ACTIONS)):
        return "read"
    return "write"


def _gh_kind(argv: list[str], cwd: Path | None = None, text: str | None = None) -> str:
    """gh 호출의 종류(낱말 수준 — 대상 레포는 보지 않는다): `approve`·`dismiss`(Claude의 Approve·리뷰 기각), `dynamic`(셸이 정한
    그룹·`pr` 동작·api 끝 칸 — 그것일 수 있다), `alias`(리뷰 별칭·못 읽은 별칭 파일), `merge`(병합 계열), `write`(그 밖 쓰기·모르는
    그룹), `local`(`pr checkout` — 규칙 8), `read`. `text`는 Bash 명령 글(heredoc 본문), `cwd`는 `@파일`·`--input` 기준. 리디렉션을
    뺀 argv(`gh 2>/dev/null pr merge 3`)도 보고 센 쪽을 쓴다."""
    known = _gh_stdin_known(argv, text)
    return max((_gh_kind1(list(a), cwd, text, known) for a in dict.fromkeys(map(tuple, (argv, _drop_redirs(argv))))),
               key=lambda k: GH_RANK.get(k, 0))


GH_DENY_KINDS = ("approve", "dismiss", "dynamic", "alias", "protection", "automerge")


def _gh_deny_msg(kind: str) -> str:
    """거부 종류(`GH_DENY_KINDS`)의 사유. Approve·기각에는 낱말 수준 오탐 안내를 붙인다."""
    return {"approve": f"{APPROVE_DENY}: gh). {GH_WORD_NOTE}", "dismiss": f"{DISMISS_DENY}: gh). {GH_WORD_NOTE}",
            "dynamic": f"{GH_DYN_DENY}).", "alias": ALIAS_DENY, "protection": PROTECTION_DENY, "automerge": AUTO_MERGE_DENY}[kind]


def _gh_judged_deny(invs, text: str, why: str = "") -> str | None:
    """의존성 없음 판정(`_degraded`)의 규칙 11 거부: gh 호출마다 `_gh_kind`(설정·PyYAML 없이 돈다)가 거부 종류면 그 사유,
    `_gh_kind`가 예외면 `INTERNAL_ERROR` 거부. 거부할 것이 없으면 None(병합 계열·그 밖 쓰기는 호출한 쪽이 ask). 낱말
    수준(`_text_unjudged_deny`)은 명령 걷기 예외(`_walk_or_flat`)에서만 쓴다."""
    for inv in invs:
        if _base(inv.argv[0]) != "gh":
            continue
        try:
            kind = _gh_kind(inv.argv, inv.cwd, text)
        except Exception as exc:  # noqa: BLE001
            return why + INTERNAL_ERROR.format(exc=type(exc).__name__, rule="규칙 11")
        if kind in GH_DENY_KINDS:
            return f"{why}{_gh_deny_msg(kind)}"
    return None


def check_gh(inv: Invocation, conf: Config, dec: Decision, text: str | None = None) -> None:
    """규칙 11(gh, 거친 판정 — `_gh_kind`). Approve·기각·셸이 정한 동작·리뷰 별칭은 거부, 병합 계열·그 밖 쓰기는 ask,
    `pr checkout`·`co`는 clone 본체에서 거부(규칙 8). `issue_db.remote`(·모듈 스킬 원격)가 없으면(setup 전) 보지 않는다."""
    if not conf.rule11_on:
        return
    if any(map(_gh_local, (inv.argv, _drop_redirs(inv.argv)))) and conf.is_clone_body(inv.cwd):
        dec.deny.append(CLONE_MUTATION_MSG)
    kind = _gh_kind(inv.argv, inv.cwd, text)
    if kind in GH_DENY_KINDS:
        dec.deny.append(_gh_deny_msg(kind))
    elif kind == "merge":
        dec.ask.append(GH_MERGE_ASK)
    elif kind == "write":
        dec.ask.append(GH_WRITE_ASK)


# -- 사용자 clone 불변 (8, Bash) -------------------------------------------------------------

CLONE_MUTATION_MSG = ("사용자 clone의 브랜치·파일은 도구가 바꾸지 않는다 (규칙 8). 분석은 _snapshot, "
                      "쓰기는 db_pr의 작업 worktree")
CLONE_GIT_SUBS = {"checkout", "switch", "reset", "merge", "rebase", "pull", "clean", "rm", "mv", "apply", "am",
                  "cherry-pick", "revert", "restore", "update-ref", "read-tree", "checkout-index", "filter-branch",
                  "filter-repo"}
BRANCH_MUTATING = {"-D", "-d", "-M", "-m", "-f", "-c", "-C", "--delete", "--move", "--force", "--copy"}
# 서브커맨드별 첫 인자로 쓰기를 정하는 것: 이름 → 바꾸는 동작
CLONE_GIT_ACTIONS = {"worktree": {"add", "remove", "prune", "move"},
                     "bisect": {"start", "good", "bad", "new", "old", "skip", "reset", "run", "replay"},
                     "sparse-checkout": {"set", "add", "init", "disable", "reapply"},
                     "submodule": {"update", "add", "deinit"}}
MIGRATE_RE = re.compile(r"^migrate/schema-v\d+$")
# 파일을 쓰는 명령: 이름 → (값을 다음 토큰으로 받는 옵션, 대상 위치 인자: "last"|"all"|"rest")
FILE_WRITERS = {
    "cp": ({"-S", "--suffix"}, "last"), "mv": ({"-S", "--suffix"}, "last"), "ln": ({"-S", "--suffix"}, "last"),
    "install": ({"-m", "--mode", "-o", "--owner", "-g", "--group", "-S", "--suffix"}, "last"),
    "rsync": ({"-e", "--rsh", "--exclude", "--include", "--filter", "-f"}, "last"),
    "rm": (set(), "all"), "rmdir": (set(), "all"), "mkdir": ({"-m", "--mode"}, "all"), "touch": ({"-d", "-r", "-t"}, "all"),
    "truncate": ({"-s", "--size", "-r", "--reference"}, "all"), "tee": (set(), "all"),
    "chmod": (set(), "rest"), "chown": (set(), "rest"),
}


def _perl_cluster(x: str) -> tuple[bool, str | None]:
    """perl 짧은 옵션 묶음 하나: (in-place `-i` 여부, 코드 위치). 코드 위치는 "next"(다음 토큰이 코드)·"here"(묶음
    나머지가 코드)·None. 값을 받는 옵션(`-M`·`-m`·`-I`·`-x`·`-0`, 숫자가 붙은 `-l`)에서 멈춘다(`-Mstrict`의 i는 -i가 아니다).
    `-i`는 묶음 나머지를 백업 확장자로 먹는다."""
    for j in range(1, len(x)):
        ch = x[j]
        if ch == "i":
            return True, None
        if ch in "eE":
            return False, "next" if j == len(x) - 1 else "here"
        if ch in "MmIx0" or (ch == "l" and x[j + 1:j + 2].isdigit()):
            return False, None
    return False, None


def _perl_inplace_files(rest: list[str]) -> list[str]:
    inplace, script_given, pos, i = False, False, [], 0
    while i < len(rest):
        x = rest[i]
        if x == "--":
            pos += rest[i + 1:]
            break
        if x.startswith("-") and not x.startswith("--") and len(x) > 1:
            ip, code = _perl_cluster(x)
            inplace = inplace or ip
            if code:
                script_given = True
                i += 2 if code == "next" else 1
                continue
        elif not x.startswith("-"):
            pos.append(x)
        i += 1
    if not inplace:
        return []
    return pos if script_given else pos[1:]


# 플러그인 스크립트의 출력 인자(규칙 8·2·12·스킬 소스가 함께 본다): 스크립트 → (출력 옵션, 그 스크립트의 모든 긴 옵션 — argparse
# 약어 판별용). `--out V`·`--out=V`·3자 이상 접두사 약어(`--o` — 출력 옵션은 유일성을 보지 않는다, F2 r2). 위치 인자를 쓰는 꼴(`mask_pii --in-place`, `jira_fields extract
# --consume`)은 `_script_out_targets`가 따로 본다.
SCRIPT_OUT_OPTS = {
    "mask_pii.py": (("--out",), ("--check", "--changed", "--staged", "--events", "--out", "--in-place", "--db", "--json",
                                 "--plugin-root")),
    "parse_logcat.py": (("--out",), ("--json", "--plugin-root", "--around", "--between", "--full", "--minutes", "--rules",
                                     "--tz", "--year", "--mask", "--no-external", "--step-events", "--out", "--evidence",
                                     "--cause", "--seconds", "--context", "--max-lines")),
    "db_review.py": (("--out",), ("--db", "--out", "--as-of", "--json", "--owners", "--plugin-root")),
    "triage.py": (("--out",), ("--plugin-root", "--json", "--logs", "--more-logs", "--issue-raw", "--issue-file",
                               "--issue-meta", "--code", "--dry-run", "--analysis-only", "--answer", "--tz", "--year",
                               "--minutes", "--refresh", "--offline-db", "--out", "--failed-step", "--steps-file",
                               "--clock-offset", "--for", "--module", "--choose", "--also", "--at", "--skipped")),
    "db_build.py": (("--preview",), ("--db", "--write", "--verify", "--preview", "--staged", "--index-tree", "--json",
                                     "--plugin-root")),
    "jira_fields.py": (("--meta-out",), ("--db", "--json", "--plugin-root", "--origin", "--meta-out", "--consume",
                                         "--comments", "--comment-chars", "--failed-step", "--steps-file")),
}
MASK_PII_VALUE_OPTS = ("--db", "--events", "--changed", "--out", "--plugin-root")
JIRA_FIELDS_VALUE_OPTS = ("--db", "--plugin-root", "--origin", "--meta-out", "--comments", "--comment-chars",
                          "--failed-step", "--steps-file")


def _script_call(argv: list[str]) -> tuple[str, list[str]] | None:
    """플러그인 스크립트 호출이면 `(스크립트 기저 이름, 그 뒤 인자)`. argv[0] 기저가 `python|python3|python3.N`이면 인터프리터
    옵션 뒤 첫 위치 인자, 아니면 argv[0]. `-m`·`-c`·`-`가 아닌 단일 대시 옵션은 모두 플래그(묶음 포함), `-X`·`-W`는 값을 받는다."""
    if not argv:
        return None
    if re.fullmatch(r"python(3(\.\d+)?)?", _base(argv[0])):
        i = 1
        while i < len(argv) and argv[i].startswith("-") and argv[i] != "-":
            a = argv[i]
            if a.startswith("--"):
                if a == "--check-hash-based-pycs":
                    i += 2
                    continue
                return None     # `--help`·`--version` 등: 스크립트를 돌리지 않는다
            step = 1
            for j, ch in enumerate(a[1:]):
                if ch in "mc":
                    return None     # `-m`·`-c`(묶음 포함): 스크립트 파일 호출이 아니다
                if ch in "XW":
                    step = 2 if j == len(a) - 2 else 1      # 값이 다음 단어거나 붙어 있다
                    break
            i += step           # 그 밖 단일 대시 옵션은 모두 플래그로 보고 계속 본다(F3)
        return (_base(argv[i]), argv[i + 1:]) if i < len(argv) else None
    return _base(argv[0]), argv[1:]


def _opt_hit(tok: str, opt: str, longs: tuple[str, ...], lax: bool = False) -> tuple[bool, str | None]:
    """`tok`이 긴 옵션 `opt`(또는 유일한 접두사 약어)인가와 붙은 값(`--out=V`). `lax`(출력 옵션 — 닫힌 쪽)면 3자 이상 접두사는
    유일성을 보지 않고 맞다고 본다(F2: 하위 명령마다 옵션 집합이 달라 `--o`가 `--out`으로 풀린다)."""
    name, eq, val = tok.partition("=")
    if not name.startswith("--") or len(name) < 3:
        return False, None
    if name != opt and not (opt.startswith(name) and (lax or [o for o in longs if o.startswith(name)] == [opt])):
        return False, None
    return True, (val if eq else None)


def _opt_values(rest: list[str], opts: tuple[str, ...], longs: tuple[str, ...]) -> list[str]:
    out = []
    for i, a in enumerate(rest):
        if a == "--":
            break
        for opt in opts:
            hit, val = _opt_hit(a, opt, longs, lax=True)
            if hit:
                if val is not None:
                    out.append(val)
                elif i + 1 < len(rest):
                    out.append(rest[i + 1])
    return out


def _has_opt(rest: list[str], opt: str, longs: tuple[str, ...], lax: bool = False) -> bool:
    return any(_opt_hit(a, opt, longs, lax)[0] for a in rest if a != "--")


def _positionals(rest: list[str], value_opts: tuple[str, ...], longs: tuple[str, ...]) -> list[str]:
    pos, i = [], 0
    while i < len(rest):
        a = rest[i]
        if a == "--":
            pos += rest[i + 1:]
            break
        if a.startswith("-") and a != "-":
            hit = next((o for o in value_opts if _opt_hit(a, o, longs)[0]), None)
            i += 2 if hit and "=" not in a else 1
            continue
        pos.append(a)
        i += 1
    return pos


def _script_out_targets(argv: list[str]) -> list[str]:
    """플러그인 스크립트가 쓰거나 지우는 경로(펼치기 전 단어): `SCRIPT_OUT_OPTS`의 출력 옵션 값, `mask_pii.py --in-place`의 위치
    인자(`--check`·`--events`가 있으면 그쪽이 먼저 돌아 쓰지 않는다), `jira_fields.py extract --consume`의 원본(지운다)."""
    call = _script_call(argv)
    if call is None or call[0] not in SCRIPT_OUT_OPTS:
        return []
    name, rest = call
    opts, longs = SCRIPT_OUT_OPTS[name]
    out = _opt_values(rest, opts, longs)
    if name == "mask_pii.py" and _has_opt(rest, "--in-place", longs, lax=True) and not _has_opt(rest, "--check", longs) \
            and not _has_opt(rest, "--events", longs):
        out += _positionals(rest, MASK_PII_VALUE_OPTS, longs)
    if name == "jira_fields.py" and _has_opt(rest, "--consume", longs, lax=True):
        pos = _positionals(rest, JIRA_FIELDS_VALUE_OPTS, longs)
        if pos and pos[0] == "extract":
            out += pos[1:]
    return out


def _db_build_write_target(inv: Invocation, conf: Config) -> str | None:
    """`db_build.py --write`가 사용자 clone을 고쳐 쓰는가(자체 preflight 없음): `--db` 값이 clone 안이거나, `--db`가 없고 cwd가
    clone 본체면 그 단어. `db_migrate --to/--write`는 자체 preflight가 있어 보지 않는다."""
    call = _script_call(_drop_redirs(inv.argv))
    if call is None or call[0] != "db_build.py":
        return None
    longs = SCRIPT_OUT_OPTS["db_build.py"][1]
    rest = call[1]
    if not _has_opt(rest, "--write", longs):
        return None
    dbs = _opt_values(rest, ("--db",), longs)
    for word in dbs:
        p = _expand(word)
        if _in_clone(_norm(Path(p) if Path(p).is_absolute() else inv.cwd / p), conf):
            return word
    if not dbs and conf.is_clone_body(inv.cwd):
        return str(inv.cwd)
    return None


def _write_targets(inv: Invocation) -> list[str]:
    """이 호출이 쓰는 파일 경로(펼치기 전 단어): 출력 리디렉션 대상, tee·cp·mv·rm 등의 대상, `sed -i`·`perl -i`·
    `sort -o`·`unzip -d`·`tar -x -C`·`dd of=`."""
    argv = inv.argv
    out: list[str] = []
    rest: list[str] = []
    pending = None   # 값이 다음 토큰인 리디렉션: "out"(쓰기 대상)·"dup"(fd 복제)·"in"(입력, 쓰기 아님)
    for k, tok in enumerate(argv):   # argv[0]도 본다: 리디렉션이 맨 앞에 올 수 있다
        if pending is not None:
            if pending == "out" or (pending == "dup" and not (tok.isdigit() or tok == "-")):
                out.append(tok)
            pending = None
            continue
        m = IN_REDIR_RE.match(tok)
        if m and m.group(1) == "<>":   # `[n]<>f`는 읽고 쓰기로 연다(O_RDWR|O_CREAT — 내용을 덮어쓰고 없으면 만든다): 쓰기 대상
            if m.group(2):
                out.append(m.group(2))
            else:
                pending = "out"
            continue
        if m:   # 입력 리디렉션·heredoc·here-string·입력 fd 복제(`0<`·`<&`)는 쓰기가 아니다
            if not m.group(2):
                pending = "in"
            continue
        m = REDIRECT_RE.match(tok) if tok else None
        if m:
            target = m.group(1)
            dup = ">&" in tok[:len(tok) - len(target)]
            if not target:
                pending = "dup" if dup else "out"
            elif not (dup and (target.isdigit() or target == "-")):
                out.append(target)
            continue
        if k:
            rest.append(tok)
    name = _base(argv[0]) if argv and not REDIRECT_RE.match(argv[0]) else ""
    if name in FILE_WRITERS:
        with_arg, which = FILE_WRITERS[name]
        pos, i = [], 0
        while i < len(rest):
            a = rest[i]
            if a in ("-t", "--target-directory") and i + 1 < len(rest):
                out.append(rest[i + 1])
                i += 2
                continue
            if a.startswith("--target-directory="):
                out.append(a.split("=", 1)[1])
            elif a in with_arg:
                i += 1
            elif not a.startswith("-") or a == "-":
                pos.append(a)
            i += 1
        out += pos[-1:] if which == "last" else pos[1:] if which == "rest" else pos
    elif name == "sed":
        if any(x.startswith("--in-place") or re.match(r"^-[A-Za-z]*i", x) for x in rest):
            pos, script_given, i = [], False, 0
            while i < len(rest):
                x = rest[i]
                if x.startswith(("--expression=", "--file=")):
                    script_given = True
                elif x in ("--expression", "--file") or (re.match(r"^-[A-Za-z]+$", x) and x[-1] in "ef"):
                    script_given = True   # 다음 토큰이 스크립트
                    i += 1
                elif not x.startswith("-"):
                    pos.append(x)
                i += 1
            out += pos if script_given else pos[1:]
    elif name == "perl":
        out += _perl_inplace_files(rest)
    elif name == "sort":
        for i, a in enumerate(rest):
            if a in ("-o", "--output") and i + 1 < len(rest):
                out.append(rest[i + 1])
            elif a.startswith("--output="):
                out.append(a.split("=", 1)[1])
            elif a.startswith("-o") and len(a) > 2 and not a.startswith("--"):
                out.append(a[2:])
    elif name == "unzip":
        out += [rest[i + 1] for i, a in enumerate(rest) if a == "-d" and i + 1 < len(rest)]
    elif name == "tar":
        if any(a == "--extract" or a == "--get" or (not a.startswith("--") and "x" in a.lstrip("-")) for a in rest[:3]):
            for i, a in enumerate(rest):
                if a in ("-C", "--directory") and i + 1 < len(rest):
                    out.append(rest[i + 1])
                elif a.startswith("--directory="):
                    out.append(a.split("=", 1)[1])
    elif name == "dd":
        out += [a[3:] for a in rest if a.startswith("of=")]
    return out + _script_out_targets([argv[0]] + rest if argv and not REDIRECT_RE.match(argv[0]) else [])


# 규칙 8·10 보강(종합 리뷰 P2 — 재현된 우회): 셸 파서는 인터프리터 인라인 코드(`python3 -c …`·`perl -e …`·`python3 - <<EOF` 본문)
# 안의 open()·쓰기를 보지 못해 clone 쓰기(규칙 8)와 원문 통독(규칙 10)이 통과했다. 코드 의미는 모르므로 거부하지 않고, 코드 글에 든
# 경로 낱말이 사용자 clone 안이거나 로그 원문·분석 파일이면 ask로 사람이 본다. 상대 경로 낱말(`/` 없는 이름)은 보지 않는다(한계).
INLINE_CODE_OPTS = {"python": {"-c"}, "perl": {"-e", "-E"}, "ruby": {"-e"}, "node": {"-e", "-p"}, "php": {"-r"}, "lua": {"-e"}}
_INTERP_RE = re.compile(r"^(?:(python)(?:[23](?:\.\d+)?)?|pypy3?|(perl)5?[\d.]*|(ruby)[\d.]*|(node)(?:js)?\d*|(php)\d*|(lua)[\d.]*)$")
PATH_WORD_RE = re.compile(r"(?:~[A-Za-z0-9_-]*|\.{1,2})?(?:/[A-Za-z0-9_.@%+-]+)+")


def _interp_family(word: str) -> str | None:
    m = _INTERP_RE.match(_base(word))
    if not m:
        return None
    if m.group(0).startswith("pypy"):
        return "python"
    return next(g for g in m.groups() if g)


def _inline_code_texts(command: str, cwd: Path, invs) -> list[tuple[str, Path]]:
    """명령 글의 인터프리터 인라인 코드 `(코드, 그 호출의 cwd)`: 코드 옵션의 다음 토큰(`-c CODE`)·붙여 쓴 꼴(`-c'CODE'`는 토큰이
    `-cCODE`)·인터프리터가 든 줄이 연 heredoc 본문(`python3 - <<EOF`, 끝 표시를 찾은 것만). `invs`는 check_bash가 이미 걸은
    호출 목록이다(다시 걷지 않는다 — 걷기 비용은 큰 명령에서 지배적이다)."""
    out: list[tuple[str, Path]] = []
    for inv in invs:
        fam = _interp_family(inv.argv[0]) if inv.argv else None
        if fam is None:
            continue
        opts = INLINE_CODE_OPTS[fam]
        argv = inv.argv
        for i in range(1, len(argv)):
            tok = argv[i]
            if tok in opts and i + 1 < len(argv):
                out.append((argv[i + 1], inv.cwd))
            elif len(tok) > 2 and tok[:2] in opts and not tok.startswith("--"):
                out.append((tok[2:], inv.cwd))
    for unit, body in _heredocs(command):
        try:
            words = _tokens(unit)
        except Exception:  # noqa: BLE001 — 토큰화 실패면 낱말로 본다(닫힌 쪽)
            words = unit.split()
        if any(_interp_family(w) for w in words):
            out.append((body, cwd))
    return out


def check_inline_code(command: str, cwd: Path, dec: Decision, conf: Config, invs) -> None:
    """인라인 코드의 경로 낱말이 사용자 clone 안이면 ask(규칙 8), 로그 원문·zip·`events*.json`·`issue_raw.json`·`match.json`이면
    ask(규칙 10). 코드 하나에 한 번만 묻는다."""
    for code, at in _inline_code_texts(command, cwd, invs):
        for word in dict.fromkeys(m.group(0) for m in PATH_WORD_RE.finditer(code)):
            p = _expand(word)
            path = Path(p) if Path(p).is_absolute() else at / p
            if conf.clones and _in_clone(_norm(path), conf):
                dec.ask.append(f"인터프리터 인라인 코드에 사용자 clone 안 경로가 있다({word}). 코드가 그 파일을 쓰면 규칙 8 위반이다 — "
                               "읽기만인지 확인한 뒤 허용한다 (규칙 8, 셸 파서는 코드 안 쓰기를 보지 못한다).")
                break
            try:
                raw = _is_raw_file(path, conf.raw_names, conf.raw_exempt, conf.raw_sniffers)
            except (OSError, ValueError):
                raw = False
            if raw:
                dec.ask.append(f"인터프리터 인라인 코드가 로그 원문·분석 파일을 연다({word}). 통째로 읽어 출력하면 규칙 10 위반이다 — "
                               "필요한 구간만 다루는지 확인한 뒤 허용한다 (규칙 10).")
                break


def check_clone_writes(inv: Invocation, conf: Config, dec: Decision) -> None:
    """Bash 명령의 파일 쓰기 대상이 어느 프로필이든 사용자 clone 안이면 거부 (어느 `<work_dir>` 아래든 제외). `ln`의 **원본**이
    clone 안이면 ask — 링크를 거친 쓰기는 `_norm`(realpath)이 잡지만 같은 명령 안에서 만들고 바로 쓰는 꼴은 판정 때 링크가 없다."""
    for word in _write_targets(inv):
        p = _expand(word)
        target = _norm(Path(p) if Path(p).is_absolute() else inv.cwd / p)
        if _in_clone(target, conf):
            dec.deny.append(f"{CLONE_MUTATION_MSG}: {word}")
            return
    for word in _write_targets(inv) + _rename_sources(inv):    # worktree의 `.git` 연결 파일 등(규칙 5 근거 ref)
        p = _expand(word)
        if _db_git_meta(_norm(Path(p) if Path(p).is_absolute() else inv.cwd / p), conf):
            dec.deny.append(f"{GIT_META_MSG}: {word})")
            return
    if inv.argv and _base(inv.argv[0]) == "ln":
        pos = [a for a in inv.argv[1:] if not a.startswith("-") or a == "-"]
        for word in pos[:-1]:
            p = _expand(word)
            if _in_clone(_norm(Path(p) if Path(p).is_absolute() else inv.cwd / p), conf):
                dec.ask.append(f"사용자 clone 안을 가리키는 링크를 만든다({word}). 링크를 거친 쓰기는 clone을 바꾼다 — 읽기 용도인지 "
                               "확인한 뒤 허용한다 (규칙 8).")
                return
    word = _db_build_write_target(inv, conf)
    if word is not None:
        dec.ask.append(f"db_build.py --write가 사용자 clone({word})의 생성 파일을 고쳐 쓴다. 메인테이너 migrate 흐름인지 확인한 "
                       "뒤에만 진행한다 (규칙 8).")


def check_clone_git(call: GitCall, conf: Config, dec: Decision) -> None:
    """사용자 clone 본체에서 브랜치·파일을 바꾸는 git 명령 거부. migrate 브랜치 생성(깨끗한 트리)만 ask."""
    sub, args = call.sub, call.args
    if sub == "stash":
        mutating = not args or args[0] not in ("list", "show")
    elif sub == "branch":
        mutating = any(a in BRANCH_MUTATING or a.split("=", 1)[0] in BRANCH_MUTATING for a in args)
    elif sub in CLONE_GIT_ACTIONS:
        action = next((a for a in args if not a.startswith("-")), "")
        mutating = action in CLONE_GIT_ACTIONS[sub]
    elif sub == "symbolic-ref":   # `symbolic-ref HEAD refs/heads/x`(인자 2개)·`-d`는 HEAD를 바꾼다
        mutating = len([a for a in args if not a.startswith("-")]) >= 2 or any(a in ("-d", "--delete") for a in args)
    elif sub == "clean":          # `-n`·`--dry-run`은 지울 목록만 보인다
        mutating = not any(a == "--dry-run" or (re.match(r"^-[A-Za-z]+$", a) and "n" in a) for a in args)
    else:
        mutating = sub in CLONE_GIT_SUBS
    if not mutating or not conf.is_clone_body(call.cwd):
        return
    create = {"switch": ("-c", "-C", "--create", "--force-create"), "checkout": ("-b", "-B")}.get(sub, ())
    for i, a in enumerate(args):
        if a in create and i + 1 < len(args) and MIGRATE_RE.match(args[i + 1]):
            if not _git(call.cwd, "status", "--porcelain").stdout.strip():
                dec.ask.append("migrate 브랜치 생성: 메인테이너 흐름(migrate 커맨드)이면 승인한다 (규칙 8 예외).")
                return
    dec.deny.append(CLONE_MUTATION_MSG)


def check_post_record_writes(inv: Invocation, conf: Config, dec: Decision) -> None:
    """Bash 파일 쓰기 대상(규칙 8과 같은 판별)이 Jira 게시 승인·결과 기록이면 거부 (규칙 2). 디렉토리째 지우기·옮기기와
    대상 디렉토리 인자(`cp x JOB/`)는 보지 못한다(최선 노력)."""
    for word in _write_targets(inv):
        p = _expand(word)
        target = _norm(Path(p) if Path(p).is_absolute() else inv.cwd / p)
        if _post_record(target, conf):
            dec.deny.append(f"{POST_RECORD_MSG}: {word}).")
            return
        if _script_record(target, conf):
            dec.deny.append(f"{_script_record(target, conf)}: {word}).")
            return


def _rename_sources(inv: Invocation) -> list[str]:
    """규칙 12에서 쓰기로 보는 원본: `mv`·`ln`·`rsync --remove-source-files`의 마지막이 아닌 위치 인자(`-t DIR`이면 모두).
    이름 바꾸기는 lock 탈취, `ln` 원본은 관리 clone의 쓰기 가능한 별칭이다(B1 §7.3)."""
    argv = _drop_redirs(inv.argv)
    name = _base(argv[0]) if argv else ""
    if name not in ("mv", "ln") and not (name == "rsync" and "--remove-source-files" in argv):
        return []
    with_arg = FILE_WRITERS[name][0]
    pos, target_dir, i = [], False, 1
    while i < len(argv):
        a = argv[i]
        if a == "--":
            pos += argv[i + 1:]
            break
        if a in ("-t", "--target-directory"):
            target_dir, i = True, i + 2
            continue
        if a.startswith("--target-directory="):
            target_dir = True
        elif a in with_arg:
            i += 1
        elif not a.startswith("-") or a == "-":
            pos.append(a)
        i += 1
    return pos if target_dir else pos[:-1]


def _module_gate(inv: Invocation) -> bool:
    """규칙 12 Bash 검사 관문: 낱말·cwd·환경 값 어디에도 모듈 표지가 없으면 판정하지 않는다(설정 없는 평소 Bash에 새 경로
    연산·판정 불가 ask가 생기지 않게)."""
    words = [*inv.argv, str(inv.cwd), *(str(v) for v in inv.env.values())]
    return any(n in w for w in words for n in MODULE_NEEDLES)


def check_module_writes(inv: Invocation, conf: Config, dec: Decision) -> None:
    """규칙 12 (a)(b), Bash: 파일 쓰기 대상(규칙 8과 같은 판별)과 이름 바꾸기·링크 원본이 관리 clone·lock·skill-wt나 모듈 스킬
    기록이면 거부. 셸 glob·변수로 표지를 숨긴 것(`rm -rf _mod*`)은 보지 못한다(최선 노력, 스크립트 preflight가 뒤를 받친다)."""
    if not _module_gate(inv):
        return
    for word in _write_targets(inv) + _rename_sources(inv):
        p = _expand(word)
        target = _norm(Path(p) if Path(p).is_absolute() else inv.cwd / p)
        if _module_root(target, conf):
            dec.deny.append(f"{MODULE_CLONE_MSG}: {word}).")
            return
        if _module_record(target, conf):
            dec.deny.append(f"{MODULE_RECORD_MSG}: {word}).")
            return


MODULE_GIT_READ = {"status", "log", "show", "diff", "rev-parse", "rev-list", "ls-files", "ls-tree", "cat-file", "describe",
                   "blame", "grep", "shortlog", "for-each-ref", "merge-base", "name-rev", "show-ref", "help", "version", "var",
                   "check-ignore"}
MODULE_GIT_EXEC = ("--output", "-O", "--open-files-in-pager", "--ext-diff", "--textconv")
MODULE_CONFIG_READ = {"--get", "--get-all", "--get-regexp", "--list", "-l"}
MODULE_CONFIG_WRITE = {"--add", "--unset", "--unset-all", "--replace-all", "--rename-section", "--remove-section", "-e",
                       "--edit", "set", "unset"}


def _git_path_options(call: GitCall) -> list[tuple[str, str]]:
    """`(옵션, 값)`: `--output[=]`·`-o`·`--output-directory[=]`·config의 `--file[=]`/`-f`·`--git-dir`·`--work-tree`·
    `--separate-git-dir`(하위 명령 인자 안)."""
    out = []
    args = call.args
    names = {"--output", "-o", "--output-directory", "--git-dir", "--work-tree", "--separate-git-dir"}
    if call.sub == "config":
        names |= {"--file", "-f"}
    for i, a in enumerate(args):
        key, eq, value = a.partition("=")
        if eq and key in names and key.startswith("--"):
            out.append((key, value))
        elif a in names and i + 1 < len(args):
            out.append((a, args[i + 1]))
    if call.git_dir is not None:
        out.append(("--git-dir", str(call.git_dir)))
    if call.work_tree is not None:
        out.append(("--work-tree", str(call.work_tree)))
    return out


def _module_git_read(sub: str | None, args: list[str]) -> bool:
    """관리 clone 안에서 허용하는 읽기 꼴인가(B1 §7.4 3~7)."""
    pos = [a for a in args if not a.startswith("-")]
    if sub in MODULE_GIT_READ:
        return True
    if sub == "branch":
        mutating = any(a in BRANCH_MUTATING or a.split("=", 1)[0] in BRANCH_MUTATING for a in args)
        return not mutating and (not pos or any(a in ("-l", "--list") for a in args))
    if sub == "remote":
        return not args or all(a in ("-v", "--verbose") for a in args) or (pos[:1] == ["get-url"])
    if sub == "config":
        if any(a in MODULE_CONFIG_WRITE for a in args):
            return False
        return pos[:1] in (["get"], ["list"]) or any(a in MODULE_CONFIG_READ for a in args)
    if sub in ("sparse-checkout", "worktree"):
        return pos[:1] == ["list"]
    if sub == "stash":
        return pos[:1] in (["list"], ["show"])
    return False


def check_module_git(call: GitCall, conf: Config, dec: Decision) -> None:
    """규칙 12 (a), git: 경로 옵션이 관리 clone·기록을 가리키면 어디서 돌든 거부. 작업 디렉토리·git dir·work tree 중 하나라도
    관리 clone 안이면 읽기 목록만(`-c`·pager·외부 diff 옵션 거부). 대상이 관리 clone인 clone·init 거부. 이슈 DB 설정과 무관."""
    for opt, value in _git_path_options(call):
        v = _expand(value)
        target = _norm(Path(v) if Path(v).is_absolute() else call.dir / v)
        if _module_root(target, conf) or _module_record(target, conf):
            dec.deny.append(MODULE_GIT_PATH_MSG.format(opt=opt))
            return
    if call.sub in ("clone", "init"):
        for a in call.args:
            if a.startswith("-"):
                continue
            v = _expand(a)
            if "://" not in v and _module_root(_norm(Path(v) if Path(v).is_absolute() else call.dir / v), conf):
                dec.deny.append(MODULE_GIT_MSG.format(sub=call.sub))
                return
    dirs = [d for d in (call.dir, call.git_dir, call.work_tree) if d is not None]
    if not any(_module_root(_norm(d), conf) for d in dirs):
        return
    if (call.config_overrides or call.config_env or any(a.startswith(MODULE_GIT_EXEC) for a in call.args)
            or not _module_git_read(call.sub, call.args)):
        dec.deny.append(MODULE_GIT_MSG.format(sub=call.sub or "?"))


PUBLISH_ASK = "db_pr.py publish는 이슈 DB에 push한다. 확인 화면을 승인한 뒤에만 진행한다 (규칙 7)."
MERGE_ASK = ("db_pr.py merge는 이슈 DB PR을 main에 병합한다. 사용자가 병합을 요청한 뒤에만 진행한다"
             "(+1·승인 커밋·검사는 스크립트가 대조) (규칙 7).")
REVIEW_REQUEST_ASK = ("db_pr.py request-review는 이슈 DB PR에 리뷰어를 요청한다(GHE 쓰기). 사용자가 push 뒤 리뷰어 질문에서 "
                      "고른 뒤에만 진행한다 (규칙 7).")
SKILL_APPLY_ASK = ("skill_patch.py --apply는 분석 스킬 소스의 워킹 트리를 바꾼다(커밋·push 안 함). patch를 보이고 사용자가 "
                   "'적용'을 고른 뒤에만 진행한다 (규칙 12).")
MODULE_EVAL_ASK = ("module_eval.py는 자식 claude -p를 띄워 비용이 든다(모듈 eval, MODULE_SKILLS_PLAN_IMPL §5.6). "
                   "--dry-run 결과를 보이고 사용자가 실행을 승인한 뒤에만 부른다(규칙 7).")
SKILL_SOURCE_ASK = ("분석 스킬 소스(analyzers.<카테고리>.source)는 skill_patch.py --apply로만 바꾼다. 사용자가 직접 요청한 "
                    "편집일 때만 승인한다 (규칙 12)")


def check_skill_source(inv: Invocation, conf: Config, dec: Decision) -> None:
    """규칙 12(Bash): 파일 쓰기 대상이나 파일을 바꾸는 git 명령의 작업 디렉토리가 분석 스킬 소스 안이면 ask."""
    for word in _write_targets(inv):
        p = _expand(word)
        if _in_skill_source(_norm(Path(p) if Path(p).is_absolute() else inv.cwd / p), conf):
            dec.ask.append(f"{SKILL_SOURCE_ASK}: {word}")
            return
    if _base(inv.argv[0]) == "git":
        call = GitCall(inv)
        if call.sub in CLONE_GIT_SUBS | {"commit", "push", "stash"} and _in_skill_source(_norm(call.cwd), conf):
            dec.ask.append(f"{SKILL_SOURCE_ASK}: git {call.sub}")


INTERNAL_ERROR = "guard 내부 오류({exc}) — 판정하지 못했으므로 거부한다 ({rule}). 같은 일을 다른 꼴로 하거나 사용자가 직접 한다."


def _checked(dec: Decision, rule: str, fn, *args) -> None:
    """검사 하나를 돌린다. 어떤 예외든(경로·인코딩 오류·`RecursionError` 포함) 그 호출은 거부(`INTERNAL_ERROR`, 4-c)하고, 사유를
    다 남기도록 다른 검사는 이어 간다(예외 하나가 다른 검사의 거부 사유를 지우지 않게)."""
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001
        dec.deny.append(INTERNAL_ERROR.format(exc=type(exc).__name__, rule=rule))


GH_WORD_RE = re.compile(r"(?<![\w.-])gh(?![\w-])")
# 판정하지 못했을 때(걷기 예외·내부 오류·의존성 없음) gh와 함께 있으면 거부할 낱말: Approve·기각(`approve`·`APPROVE`·`--approve`·
# `dismiss`·`dismissals`, 상태 값 `APPROVED`·`DISMISSED`는 아니다), `review` 뒤의 짧은 옵션 묶음 `-…a…`(`gh pr review -a`)와
# 셸 값(`gh pr review 3 "$OPT"` — `--approve`일 수 있다)
_TEXT_PROT = r"/(?:branches/\S+?/protection|rulesets)\b"
_TEXT_WRITE = r"(?:-X\s*=?\s*|--method[=\s]+)(?:DELETE|PUT|PATCH|POST)\b|(?<![\w-])-[fF](?![\w-])|--(?:raw-)?field\b|--input\b"
# … 보호·ruleset 바꾸기(엔드포인트와 쓰기 표시가 함께)·자동 병합 허용·병합 뒤 브랜치 지우기 켜기도 거부한다(사용자 결정, 4-c)
TEXT_DENY_RE = re.compile(r"approve(?!d)|dismiss(?!ed)|\breview\b.*?(?:(?<![\w-])-[A-Za-z]*a|[$`])|--enable-auto-merge"
                          r"|--delete-branch-on-merge|delete_branch_on_merge"
                          r"|\b(?:create|update|delete)(?:BranchProtectionRule|RepositoryRuleset)\b|enablePullRequestAutoMerge"
                          r"|\bmerge\b.*?(?<![\w-])--auto(?![\w-])"
                          r"|allow_auto_merge"
                          rf"|{_TEXT_PROT}.*?(?:{_TEXT_WRITE})|(?:{_TEXT_WRITE}).*?{_TEXT_PROT}", re.IGNORECASE | re.DOTALL)
TEXT_DENY = ("gh 동작을 판정할 수 없다. Approve·리뷰 기각 낱말, 보호·ruleset 바꾸기·자동 병합 켜기가 든 gh 명령은 거부한다"
             f"({GH_WORD_NOTE} 규칙 11")


def _text_unjudged_deny(command: str, why: str = "") -> str | None:
    """낱말 수준의 거부: 따옴표·`\\`를 뗀 글에 `gh`와 `TEXT_DENY_RE` 낱말이 함께 있으면 거부 사유. 예외를 내지 않는다."""
    try:
        flat = re.sub(r"[\"'\\]", "", str(command or ""))
        hit = GH_WORD_RE.search(flat) and TEXT_DENY_RE.search(flat)
        return f"{why}{TEXT_DENY}: {hit.group()[:40]})." if hit else None
    except Exception:  # noqa: BLE001 — 낱말도 못 보면 아래 ask가 남는다
        return None


def _flat_invocations(command: str, cwd: Path, depth: int = 0) -> list[Invocation]:
    """`invocations`(걷기)가 예외로 끝났을 때의 닫힌 쪽 대체: cd를 따라가지 않고, 단순 명령마다 처음 cwd·명령 글의 cd·pushd 절대
    대상·모르는 디렉토리(`UNKNOWN_DIR`) 모두를 cwd 후보로 본다(상한 안). 셸이 읽는 heredoc 본문도 같은 후보로 본다. 예외를 내지
    않는다(못 푼 명령은 뺀다 — 호출하는 쪽이 거부·낱말 거부를 남긴다)."""
    try:
        segs = _segments(_tokens(command))
    except Exception:  # noqa: BLE001
        return []
    cands = [cwd]
    for seg in segs:
        try:
            first, _, _ = _strip_prefix(seg, cwd)
            if first and _base(first[0]) in CD_NAMES:
                cands += [Path(_expand(a)) for a in first[1:] if _expand(a).startswith("/")]
        except Exception:  # noqa: BLE001, S112
            continue
    dirs = _dedupe([*cands, UNKNOWN_DIR])
    out: list[Invocation] = []
    for seg in segs:
        for d in dirs:
            try:
                argv, seg_cwd, env = _strip_prefix(seg, d)
            except Exception:  # noqa: BLE001, S112
                continue
            if argv:
                out.append(Invocation(seg_cwd, argv, env))
    if depth < MAX_DEPTH:
        try:
            bodies = [body for line, body in _heredocs(command) if _feeds_shell(line, cwd)]
        except Exception:  # noqa: BLE001
            bodies = []
        for body in bodies:
            for d in dirs:
                out += _flat_invocations(body, d, depth + 1)
    return out


def _walk_or_flat(command: str, cwd: Path, dec: Decision | None = None,
                  keep: tuple[str, ...] = ()) -> tuple[list[Invocation], str | None]:
    """`invocations`(`keep` — 넘침 때 접지 않을 보호 뿌리), 예외면 `_flat_invocations`(다른 검사가 사유를 남기도록)와 낱말 거부
    사유(`_text_unjudged_deny` — 의존성 없음 판정이 쓴다). `dec`이 있으면 거부(`INTERNAL_ERROR`, 4-c)를 남긴다."""
    try:
        return invocations(command, cwd, keep=keep), None
    except Exception as exc:  # noqa: BLE001
        deny = _text_unjudged_deny(command)
        if dec is not None:
            dec.deny.append(INTERNAL_ERROR.format(exc=type(exc).__name__, rule="명령 파싱"))
        global _KEEP_ROOTS
        saved, _KEEP_ROOTS = _KEEP_ROOTS, tuple(keep)
        try:
            return _flat_invocations(command, cwd), deny
        finally:
            _KEEP_ROOTS = saved


def check_bash(command: str, cwd: Path, conf: Config, dec: Decision) -> None:
    """Bash 규칙. 검사마다 `_checked`로 돌린다 — 예외면 그 호출은 거부하고 다른 검사는 사유를 위해 이어 간다(4-c). 명령 걷기
    (`invocations`)가 예외로 끝나도 거부하고 cd를 따라가지 않는 대체 목록으로 검사를 이어 간다."""
    _checked(dec, "규칙 10", check_raw_read, command, cwd, dec, conf)
    if conf.user is not None and word_net(command):   # 규칙 7: 명령 글 전체의 낱말 그물 하나 (argv·치환·heredoc 무관)
        dec.ask.append(PUBLISH_ASK)
    if conf.user is not None and word_net(command, "db_pr", "merge"):        # 규칙 7: +1 병합(사용자가 요청한 뒤)
        dec.ask.append(MERGE_ASK)
    if conf.user is not None and word_net(command, "db_pr", "request-review"):   # 규칙 7: 리뷰어 요청(매번)
        dec.ask.append(REVIEW_REQUEST_ASK)
    if conf.user is not None and word_net(command, "skill_patch", "apply"):  # 규칙 12: 분석 스킬 소스 적용
        dec.ask.append(SKILL_APPLY_ASK)
    if conf.user is not None and word_net(command, "module_eval", "module"):  # 규칙 7: 모듈 eval(유료 자식 실행)
        dec.ask.append(MODULE_EVAL_ASK)
    invs, _ = _walk_or_flat(command, cwd, dec, _keep_roots(conf))
    _checked(dec, "규칙 8·10", check_inline_code, command, cwd, dec, conf, invs)   # 인터프리터 인라인 코드의 clone·원문 경로 → ask
    for inv in invs:
        name = _base(inv.argv[0])
        if conf.work_dirs:
            _checked(dec, "규칙 2", check_post_record_writes, inv, conf, dec)
        if conf.skill_sources:
            _checked(dec, "규칙 12", check_skill_source, inv, conf, dec)
        if conf.clones:
            _checked(dec, "규칙 8", check_clone_writes, inv, conf, dec)
        # 규칙 12 (a)(b): 사용자 config 없이도(이름 기반) — 모듈 표지 관문이 평소 Bash를 건너뛴다
        _checked(dec, "규칙 12", check_module_writes, inv, conf, dec)
        if name == "gh":
            _checked(dec, "규칙 11", check_gh, inv, conf, dec, command)
            continue
        if name == "git" and _module_gate(inv):     # git 규칙 관문(git_rules = 이슈 DB clone 있음)보다 먼저
            for argv in dict.fromkeys(map(tuple, (inv.argv, _drop_redirs(inv.argv)))):
                _checked(dec, "규칙 12", lambda a=argv, i=inv: check_module_git(GitCall(Invocation(i.cwd, list(a), i.env)),
                                                                              conf, dec))
        if name != "git" or not conf.git_rules:
            continue
        # 리디렉션을 뺀 argv도 본다(`git 2>&1 push …` — 합집합, 닫힌 쪽)
        for argv in dict.fromkeys(map(tuple, (inv.argv, _drop_redirs(inv.argv)))):
            _checked(dec, "규칙 3~8", lambda a=argv, i=inv: check_git(GitCall(Invocation(i.cwd, list(a), i.env)), conf, dec))


REMOTE_REF_MSG = ("이슈 DB에서 원격 추적 ref(`refs/remotes/…`)·origin 원격 설정을 바꾸거나 origin 밖에서 받지 않는다 — 규칙 5의 "
                  "ci_mode 근거 ref(origin/<base>)를 바꿀 수 있다. 원격은 `git fetch`·`git fetch origin [<브랜치>]`·"
                  "`git pull [origin]`으로만 받는다 (규칙 5).")
REMOTE_SUBS = {"update-ref", "symbolic-ref", "fetch", "pull", "remote", "config", "replace", "push"}
REMOTE_CFG_RE = re.compile(r"^\s*(?:remote\.origin(?:\.|$)|url\.|include(?:if)?(?:\.|$))", re.IGNORECASE)   # origin URL·refspec을 바꾸는 키
REMOTE_DST_RE = re.compile(r"^[^:]*:(?:refs/)?remotes/")                 # refspec `[+]<src>:<dst>`의 dst가 원격 추적 ref
PUSH_WITH_ARG = {"-o", "--push-option", "--receive-pack", "--exec", "--repo"}
REMOTE_WRITE_ACTIONS = {"add", "set-url", "rename", "remove", "rm", "set-branches", "set-head", "prune"}
# fetch·pull에서 값을 다음 토큰으로 받는 옵션(모르는 것은 값이 위치 인자로 남아 origin 밖으로 본다 — 닫힌 쪽)
FETCH_WITH_ARG = {"--depth", "--deepen", "--shallow-since", "--shallow-exclude", "--upload-pack", "-j", "--jobs", "-o",
                  "--server-option", "--negotiation-tip", "--filter", "--refmap", "-s", "--strategy", "-X",
                  "--strategy-option", "--cleanup", "--recurse-submodules-default", "--submodule-prefix"}


def _fetch_forges(call: GitCall) -> bool:
    """fetch·pull이 origin 추적 ref를 origin의 같은 이름 밖에서 채울 수 있나: `-c`·`--config-env`의 origin URL·refspec 키,
    `GIT_CONFIG_*` 환경(`GIT_INDEX_FILE` 밖), `--all`·`--multiple`·`--stdin`, origin 밖 원격·URL·경로(`.` 포함),
    dst가 `refs/remotes/origin/…`인 refspec·`--refmap`. 허용: `git fetch`·`git fetch origin [<브랜치>…]`·`git pull [origin …]`."""
    if set(call.config_env) - {"GIT_INDEX_FILE"} or any(REMOTE_CFG_RE.match(o) for o in call.config_overrides):
        return True
    args, pos, i = [str(a) for a in call.args], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        key, eq, val = a.partition("=")
        if key == "--refmap" and REMOTE_DST_RE.match(val if eq else (args[i + 1] if i + 1 < len(args) else "")):
            return True
        if a in ("--all", "--multiple", "--stdin"):
            return True
        if a in FETCH_WITH_ARG:
            i += 1
        elif not a.startswith("-"):
            pos.append(a)
        i += 1
    return (bool(pos) and pos[0] != "origin") or any(REMOTE_DST_RE.match(r) for r in pos[1:])


def _push_pos(call: GitCall) -> list[str]:
    args, pos, i = [str(a) for a in call.args], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return pos + args[i + 1:]
        if a in PUSH_WITH_ARG:
            i += 1
        elif not a.startswith("-"):
            pos.append(a)
        i += 1
    return pos


def _push_into_db(call: GitCall, conf: Config) -> bool:
    """push 대상이 경로(`.`·`/…`·`./…`·`~…`·`file://…`)이고 그 레포가 이슈 DB다 — 다른 레포에서 이슈 DB의 ref(origin 추적 ref
    포함)를 그 자리에서 덮는다."""
    pos = _push_pos(call)
    t = pos[0] if pos else ""
    if not (t == "." or t.startswith(("./", "../", "~", "file://")) or os.path.isabs(t)):
        return False
    p = os.path.expanduser(t.removeprefix("file://"))
    return conf.profile_of_common(_common_dir(Path(p) if os.path.isabs(p) else call.cwd / p)) is not None


def _forges_remote_ref(call: GitCall) -> bool:
    """규칙 5 근거 ref(origin/<base>)를 바꿀 수 있는 git: `update-ref`(`--stdin`은 대상을 모른다)·`symbolic-ref` 쓰기(인자 2개·
    `-d`)가 `refs/remotes/…`·`refs/replace/…`를 바꾼다, `replace` 쓰기, `remote`의 origin 바꾸기(`REMOTE_WRITE_ACTIONS`)·
    `update`(origin 밖 원격도 받는다), `config`의 origin URL·refspec 키 쓰기·`--edit`, fetch·pull(`_fetch_forges`), dst가
    `refs/remotes/…`인 push refspec."""
    args, sub = [str(a) for a in call.args], call.sub
    pos = [a for a in args if not a.startswith("-")]
    if sub == "update-ref":
        return "--stdin" in args or any(a.startswith(("refs/remotes/", "remotes/", "refs/replace/")) for a in args)
    if sub == "replace":        # 목록(`-l`·인자 없음)만 읽기 — `_ci_actions`는 `--no-replace-objects`로도 막는다
        return bool(args) and not any(a in ("-l", "--list") for a in args)
    if sub == "push":
        return any(REMOTE_DST_RE.match(r) for r in _push_pos(call)[1:])
    if sub == "symbolic-ref":
        return bool(pos) and pos[0].startswith(("refs/remotes/", "remotes/")) and (
            len(pos) >= 2 or any(a in ("-d", "--delete") for a in args))
    if sub == "remote":
        return (pos[:1] == ["update"] and pos[1:] != ["origin"]) or (
            bool(pos) and pos[0] in REMOTE_WRITE_ACTIONS and "origin" in pos[1:])
    if sub == "config":
        action, cpos = _config_parse(args)
        keys = cpos[:2] if action == "rename-section" else cpos[:1]
        return action == "edit" or (action not in CONFIG_READ_ACTIONS and (action is not None or len(cpos) >= 2)
                                    and any(REMOTE_CFG_RE.match(k) for k in keys))
    return sub in ("fetch", "pull") and _fetch_forges(call)


def check_git(call: GitCall, conf: Config, dec: Decision) -> None:
    """git 규칙 3~8(clone 불변·hooksPath·커밋 검사·push). 규칙 5는 `_rule5`(ci_mode actions면 ask하고 이어 간다)."""
    check_clone_git(call, conf, dec)
    if (call.sub in REMOTE_SUBS and _forges_remote_ref(call) and conf.profile_of_common(_common_dir(call.cwd)) is not None) or \
            (call.sub == "push" and _push_into_db(call, conf)):
        dec.deny.append(REMOTE_REF_MSG)
    if call.sub not in ("commit", "config", "push") and not call.overrides_hooks_path():
        return
    prof = conf.profile_of_common(_common_dir(call.cwd))
    if prof is None:
        return   # 이슈 DB가 아니다: 어떤 git 규칙도 적용하지 않는다
    call.db_base = prof.base        # 규칙 5 완화(`_rule5`)는 origin/<이 base>의 ci_mode만 본다
    if call.overrides_hooks_path() and _rule5(call, dec, "git -c core.hooksPath=… 로 hook을 바꾸는 것은 금지다 (규칙 5)."):
        return
    env_msg = f"환경변수로 git 설정·index를 바꾸는 커밋/푸시는 금지 (규칙 5: {', '.join(call.config_env)})."
    if call.sub == "commit" and "GIT_INDEX_FILE" in call.config_env:
        # 다른 index의 커밋은 staged 검사(규칙 3·4 — 기본 index를 본다)를 피한다: ci_mode와 무관하게 거부
        dec.deny.append(env_msg + " GIT_INDEX_FILE 커밋은 커밋 검사가 보지 못하므로 ci_mode와 무관하게 거부한다.")
        return
    if call.config_env and call.sub in ("commit", "push", "config") and _rule5(call, dec, env_msg):
        return
    if call.sub == "commit":
        check_commit(call, conf, dec)
    elif call.sub == "config":
        check_config(call, dec)
    elif call.sub == "push":
        check_push(call, dec)


# -- 진입점 ----------------------------------------------------------------------------------


def _shell_text(command) -> str:
    """셸에 넘어가는 명령 글: 짝 없는 서로게이트는 U+FFFD(UTF-8 인코더가 셸에 넘길 때와 같다), 날 NUL은 뺀다(bash는 입력의 NUL을
    버리고, `bash -c`의 인자는 NUL을 담을 수 없다). 회귀 수정 R2 — 이런 글자가 경로 연산·출력에서 예외를 내지 않게."""
    return SURROGATE_RE.sub("\ufffd", str(command or "")).replace("\0", "")


def judge(event: dict, plugin_root: str | None = None) -> tuple[dict | None, list[str]]:
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") or {}
    cwd = Path(str(event.get("cwd") or os.getcwd()))
    try:
        conf = Config(plugin_root)
    except Exception as exc:  # noqa: BLE001 — 설정 읽기 오류는 판정 예외가 아니다: degraded(4-c 리뷰)
        return _degraded(event, f"guard 설정 읽기 오류({type(exc).__name__}: {exc})", CONFIG_HINT)
    dec = Decision()
    if tool.startswith("mcp__"):
        check_mcp(tool, tool_input, conf, dec)
    elif tool in FILE_TOOLS:
        check_file(tool_input, cwd, conf, dec)
    elif tool == "Bash":
        check_bash(_shell_text(tool_input.get("command")), cwd, conf, dec)
    # 설정 경고는 검사 **뒤에** 합친다 — 검사 중에 늦게 생기는 경고(규칙 10 fail-soft)도 빠지지 않게. 순서는 설정 경고가 먼저.
    dec.warn[:0] = conf.warnings
    return dec.output(), dec.warn


INSTALL_HINT = "pyproject 의존성(PyYAML·jsonschema)을 설치한 뒤 `config.py doctor`로 확인한다"
CONFIG_HINT = ("설정 파일을 읽지 못해 제한 모드입니다. config.yaml(·site-defaults.yaml)을 고치면 풀립니다 — "
               "고친 뒤 `config.py doctor`로 확인한다")


def _degraded(event: dict, why: str, hint: str = INSTALL_HINT) -> tuple[dict | None, list[str]]:
    """의존성 없음(import 실패)·설정 읽기 오류(`judge`의 `Config` — 사용자 config·site-defaults YAML 오류)로 정상 판정을 못 할 때.
    판정 중 예외는 여기로 오지 않고 거부한다(`main`). 설정이 깨졌다고 모든 호출을 막으면 그 설정을 고치는 Write·`config.py
    doctor`까지 막힌다(종료 2와 같은 사고). MCP는 거부(Jira 쓰기
    차단은 guard가 유일한 장치), gh Approve·리뷰 기각(`_gh_judged_deny`, 걷기 예외면 낱말 수준 `_text_unjudged_deny`)은 거부,
    병합 계열은 아래 ask(서버 브랜치 보호가 막는다). 명령 걷기도 예외면 cd를 따라가지 않는 대체 목록(재리뷰 P0), git·gh·
    `db_pr.py publish`·`merge`·`request-review`와 파일 도구는 레포·clone을 판별할 수 없으므로 ask, `module_eval.py`(유료 자식
    실행, 규칙 7)도 ask, 그 밖의 Bash는 통과 + 경고. 경로 조각 `_module-skills`(·`_module-skills.`로 시작)를 바꾸는 파일 도구·
    Bash 쓰기는 이름만으로 판정되므로 deny(규칙 12 (a)).
    종료 2(모든 Bash 차단, 설치 명령까지)는 쓰지 않는다."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    if tool.startswith("mcp__"):
        return _decision("deny", f"{why}: MCP 도구 판정 불가. {hint}."), []
    if tool in FILE_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path")
        if raw and _module_name_part(str(raw)):     # 규칙 12 (a) 이름 기반 — 설정 없이도 판정한다
            return _decision("deny", f"{why}: {MODULE_CLONE_MSG}: {raw}). {hint}."), []
        return _decision("ask", f"{why}: 이슈 DB clone 경로를 판별할 수 없다 — 직접 확인한다. {hint}."), []
    if tool == "Bash":
        risky = True
        try:
            cmd = _shell_text(tool_input.get("command"))
            invs, deny = _walk_or_flat(cmd, Path(str(event.get("cwd") or os.getcwd())))
            if deny:                # 걷기 예외: 낱말 수준으로 거부 꼴을 찾았다
                return _decision("deny", f"{why}: {deny} {hint}."), []
            for inv in invs:        # 규칙 12 (a) 이름 기반: 관리 clone·lock 쓰기는 ask가 아니라 deny
                for word in _write_targets(inv) + _rename_sources(inv):
                    p = _expand(word)
                    if _module_name_part(p if Path(p).is_absolute() else str(inv.cwd / p)):
                        return _decision("deny", f"{why}: {MODULE_CLONE_MSG}: {word}). {hint}."), []
            names = [_base(i.argv[0]) for i in invs]
            deny = _gh_judged_deny(invs, cmd, f"{why}: ")   # gh Approve·기각·셸 값·보호 바꾸기(병합 계열은 아래 ask)
            if deny:
                return _decision("deny", f"{deny} {hint}."), []
            risky = any(n in ("git", "gh") for n in names) or word_net(cmd) or word_net(cmd, "db_pr", "merge") or \
                word_net(cmd, "db_pr", "request-review") or word_net(cmd, "skill_patch", "apply") or \
                word_net(cmd, "module_eval", "module") or any(
                not _expand(t).startswith("/dev/") for i in invs for t in _write_targets(i))   # 파일 쓰기(clone일 수 있다)
        except Exception:  # noqa: BLE001 — 파싱도 못 하면 낱말 수준 거부를 보고 사람에게 넘긴다
            deny = _text_unjudged_deny(str(tool_input.get("command") or ""), f"{why}: ")
            if deny:
                return _decision("deny", f"{deny} {hint}."), []
        if risky:
            return _decision("ask", f"{why}: 레포 판별 불가 — git·gh·publish·파일 쓰기는 직접 확인한다. "
                                    f"{hint}."), []
        return None, [f"{why}: Bash 규칙을 적용하지 못했다. {hint}."]
    return None, [f"{why}. {hint}."]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="guard.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plugin-root", default=None)
    return parser


def _warn(text: str) -> None:
    try:
        print(f"[telephony-triage] {text}", file=sys.stderr)
    except Exception:  # noqa: BLE001, S110 — 경고를 못 내도 판정 출력은 낸다
        pass


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        print("[telephony-triage] guard: hook 입력이 JSON이 아니다. 판정하지 않는다.", file=sys.stderr)
        return 0
    if not isinstance(event, dict):
        print("[telephony-triage] guard: hook 입력이 객체가 아니다. 판정하지 않는다.", file=sys.stderr)
        return 0
    # 판정과 출력 직렬화를 모두 try 안에서 한다: 실패해도 종료 0 + 거부를 낸다. 출력은 ASCII JSON이다(ensure_ascii — 사유에
    # 인코딩할 수 없는 글자가 들어도 출력에서 죽지 않게, 회귀 수정 R2. 종료 1·출력 없음은 Claude Code가 막지 않는다 — fail-open).
    # 의존성 없음(PyYAML 등 import 실패)은 `_degraded`(낱말 수준 표), 판정 중 예외는 그 호출을 거부한다(4-c — 사유 `guard 내부 오류`).
    try:
        if IMPORT_ERROR is not None:
            out, warnings = _degraded(event, f"guard 의존성 없음({type(IMPORT_ERROR).__name__}: {IMPORT_ERROR})")
        else:
            out, warnings = judge(event, args.plugin_root)
        text = json.dumps(out, ensure_ascii=True) if out is not None else None
    except Exception as exc:  # noqa: BLE001
        text = json.dumps(_decision("deny", INTERNAL_ERROR.format(exc=type(exc).__name__, rule="판정")), ensure_ascii=True)
        try:
            warnings = [f"guard 내부 오류: {type(exc).__name__}: {exc}"]
        except Exception:  # noqa: BLE001 — 예외 글을 못 만들어도 판정은 낸다
            warnings = [f"guard 내부 오류: {type(exc).__name__}"]
    for w in warnings:
        _warn(w)
    if text is not None:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
