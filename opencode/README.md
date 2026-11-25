# OpenCode v1 (분석 전용)

OpenCode 1.19.5 + 사내 GLM용 바깥 층이다(계획 I, `docs/development/MODULE_SKILLS_DECISIONS.md` 11/05 "계획 I 1단계 결과").
v1은 **분석 전용(안 A)**: Jira 코멘트, 이슈 DB push, `db_pr publish|merge`, 리뷰어 요청, 스킬 적용, module_eval은 OpenCode에서
막는다. 그 단계에 이르면 정확한 명령을 출력하고, 사용자가 터미널이나 Claude Code에서 직접 실행한다. 예외는 analyze 결과의 이슈 DB
등록(PR) 하나다. 이것은 모델의 명령을 붙여 넣지 않고 사람이 `tt-oc publish`로 한다(아래 순서).

## 처음부터 PR까지 (순서)

OpenCode로 분석하고 이슈 DB에 PR까지 올리는 순서다. 자세한 것은 각 단계가 가리키는 절에 있다.

1. **사용자 설정을 먼저 만든다.** 사용자 설정(`~/.telephony-triage/config.yaml`)이 없으면 `tt-oc`가 사전 점검에서 멈추고
   시작하지 않는다. Claude Code의 `/telephony-triage:setup`이나 터미널의 `python3 <설치된 plugin>/scripts/config.py init`
   (질문에 직접 답하는 대화형)으로 만든다(`docs/TEAM_GUIDE.md` 2절 1번).
2. **프로젝트 폴더를 만든다**("설치"). `--plugin-root`는 설치된 플러그인 폴더(`scripts/`가 든 곳)다. `--work-root`는 모델이
   파일을 쓸 수 있는 작업 루트로, 사용자 설정의 작업 디렉토리(`work_dir`)이거나 그것을 품는 폴더다. PR까지 가려면
   `--allow-publish`를 같이 준다(없으면 게시가 닫힌다).
3. **Jira 읽기 관문을 연다**("Jira 읽기"). 실제 PR은 Jira에서 읽은 값으로만 만들어진다. 이슈 내용을 파일로 주는
   `--issue-file`은 연습(`--dry-run`·`--analysis-only`)에서만 받는다. `runtime-check` 통과 → `config.py set opencode.jira_read open`
   → install을 2번과 같은 인자에 `--jira-read-tool <서버>_<도구> --force`를 더해 한 번 더 한다.
4. **`tt-oc --project <dest> doctor`** 로 점검한다. fail이 없고 `publish` 행이 열림이어야 한다.
5. **분석한다**: `tt-oc --project <dest> --command tt-analyze -- <KEY> <로그>`(`--issue-file`·`--analysis-only`·`--dry-run` 없이).
   모델이 확인 화면까지 가서 멈추면 tt-oc가 `게시:` 줄로 다음 할 일을 알린다("실행").
6. **OpenCode를 닫고 터미널에서 `tt-oc --project <dest> publish`** 를 돌린다("게시"). 확인 화면을 읽고 작업 키를 입력하면
   PR이 만들어지고, 마지막 줄에 `PR: <url>`이 나온다.
7. **병합**은 작성자 외 1명이 Approve(+1)한 뒤 Claude Code("병합해줘")나 GHE 웹에서 한다. OpenCode에서는 병합이 닫혀 있다.

| 파일 | 내용 |
|---|---|
| `opencode.json.template` | 프로젝트 설정(v1 키만). `snapshot:false` 필수, `autoupdate:false`, `share:"disabled"`, 한도 202000/16000, 허용 목록(`"*":"deny"` 뒤 read·glob·grep·list·bash·edit만 — read 도구는 원문 작업 파일 `issue_raw.json`·`events.json`·`events-full.json`·`match.json`·`jira_raw.json`을 deny(grep 도구·site 추가 이름은 막지 않는다, 08-safety 10번의 한계), bash도 `"*":"deny"` 뒤 `python3 *`·읽기 명령만), `jira_*`·`github_*` deny, `task`는 `tt-explore`만 allow(Jira 읽기 도구는 `install --jira-read-tool`로만 끝에 allow), `external_directory`는 플러그인·작업 루트·clone만 |
| `managed.json.sample` | `/etc/opencode/opencode.json` 예시(관리자 배포, 다중 방어). 프로젝트 설정 뒤에 합쳐진다 |
| `agents/triage.md` | 에이전트 프롬프트(약 2.5KB): 스크립트가 판정, Read ≤200줄, 화면 그대로, 쓰기는 명령 출력만, 탐색 분석은 `tt-explore`에 맡김 |
| `agents/tt-explore.md` | 탐색 분석(analyze Step 5-2) 하위 에이전트: 새 문맥에서 `explore.md` 절차만 한다. 아래 "탐색 분석 하위 에이전트" |
| `commands/tt-*.md` | `tools/gen_opencode.py`가 `plugin/commands/*.md`에서 만든다(손으로 고치지 않는다) |
| `bin/tt-oc` | 실행 래퍼: 확인 화면·must_show가 있는 흐름은 이것으로. 표준 라이브러리만 쓰고 OpenCode 표면은 아래 한 파일에서 읽는다 |
| `../plugin/scripts/common/oc_version.py` | **OpenCode 바이너리 의존 한 곳**: 고정 버전, CLI 인자, 거부·자식 환경 변수, 바이너리의 거부 문구, `run --format json` 이벤트 키, 플러그인 hook 이름. 버전을 올릴 때는 이 파일과 `tests/test_oc_version.py`의 고정값만 바꾸고, 파일에 적힌 실험을 새 버전으로 다시 한다(tt-guard.js는 시험이 대조) |
| `plugins/tt-guard.js` | guard 플러그인: 모든 도구 호출을 `plugin/scripts/common/oc_adapter.py`로 바뀌지 않은 `guard.py`에 넘긴다(닫힘 실패). 오류로 끝난 MCP 호출의 Jira 오류 본문은 모델 요청 직전(`experimental.chat.messages.transform`)에 숨긴다. `install`이 `<dest>/.opencode/plugins/`(1.19.5가 자동으로 싣는 폴더)에 복사하며 플러그인 루트를 써 넣으므로 TUI에서도 `TT_PLUGIN_ROOT` 없이 걸린다 |

## 설치

```sh
python3 tools/gen_opencode.py install --dest <git 레포 밖 폴더> --plugin-root <설치된 plugin/> \
    --work-root <작업 루트> [--issue-db <clone>]... --gateway-url <http(s)://…/v1> --model <모델 ID>
# 게이트웨이가 OpenCode 내장 provider로만 받으면 --gateway-url·--model 대신 --provider-model <provider>/<모델>
# (provider 블록 없이 model·small_model만 쓴다 — 키·주소는 OpenCode 전역 설정 몫, TT_GATEWAY_API_KEY 불필요)
# 탐색 분석만 다른 모델로 돌리려면 --explore-model <provider>/<모델>을 더한다(아래 "탐색 분석 하위 에이전트")
export TT_GATEWAY_API_KEY=…            # 설정 파일에는 쓰지 않는다
opencode/bin/tt-oc --project <dest> doctor
python3 tools/site_step.py runtime-check opencode --project <dest>   # 사내 확인: 버전·설정·관리 설정 + 확인 0 curl 명령(모델 호출 없음)
```

- `<dest>`는 git 레포 밖이어야 한다. 1.19.5는 `edit` 권한을 worktree 기준 상대 경로로 맞추는데, git 레포가 아닌 폴더의 worktree는
  `/`다(그래서 템플릿의 `@@*_REL@@` = 앞 `/`를 뗀 절대 경로).
- 플러그인 루트는 가능하면 읽기 전용(root 소유)으로 설치한다. 설정의 `edit` deny는 다중 방어다.
- `--work-root` 아래는 모델이 쓸 수 있다. 홈(`$HOME`)·`~/.ssh`·`~/.claude`·`~/.config`·`~/.gnupg`·Python 사용자 site
  (`site.getuserbase()`·site-packages)·플러그인·이 레포이거나 그것을 품는 폴더는 `install`이 거부한다(홈 말고는 그 안의 폴더도.
  심볼릭 링크를 푼 실제 경로로, 둘 다 있으면 `os.path.samefile`로도 비교, 종료 2). `~/tt-work`처럼 홈 안의 따로 둔 폴더를 쓴다.
- `install`은 설치한 파일과 플러그인 스크립트(`scripts/**/*.py`)의 지문을 `tt-oc.json` `integrity`에 남기고, `tt-oc`가 실행마다
  비교한다(guard 플러그인이 지워지거나 adapter·guard가 바뀌면 시작하지 않는다). 플러그인을 갱신하면 `install --force`로 다시 설치한다.
- `<dest>`와 그 위 폴더(`/`까지)에 `AGENTS.md`·`CONTEXT.md`가 있거나 `~/.config/opencode/AGENTS.md`가 있으면 OpenCode가 에이전트
  프롬프트에 자동으로 붙이므로 `tt-oc`가 시작하지 않는다(사용자 결정 ⑤). `~/.claude/CLAUDE.md`는 `tt-oc`가
  `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1`로 끈다.
- `plugin/commands`를 고치면 `python3 tools/gen_opencode.py`로 다시 만든다(`--check`가 골든 테스트).
- `install`은 고정 버전(1.19.5) opencode의 절대 경로를 `tt-oc.json` `opencode_bin`에 남긴다(`--opencode <경로>`, 없으면
  `TT_OPENCODE`·PATH에서 찾고 버전이 다르면 남기지 않는다). `tt-oc`는 `--opencode` > `TT_OPENCODE` > 남긴 경로 > PATH 순으로 쓴다.
  **고정한 opencode를 직접 실행하지 않는다** — 직접 띄우면 스스로 새 버전으로 바뀔 수 있고(`tt-oc`는 자동 업데이트를 끄고 돌린다),
  그러면 `tt-oc doctor`의 `opencode-version` 행이 "설치 때 기록한 opencode가 바뀌었다"로 실패한다.

## 실행

```sh
opencode/bin/tt-oc --project <dest> --command tt-analyze -- ABC-123 /path/logcat.txt --issue-file <이슈 yaml> --analysis-only   # 관문을 열기 전(연습)
opencode/bin/tt-oc --project <dest> -s <세션> -- 2          # 질문에 답하고 이어가기
```

- `--pure`·`--auto`·`--attach`·`-i`·`--agent`·`--model`과 설정을 덮는 `OPENCODE_*` 환경 변수는 거부한다.
- guard는 `tt-oc`를 실행한 python을 쓴다(`TT_PYTHON`을 따로 정하지 않았으면 tt-oc가 자기 python을 넘긴다. venv python이면 그 venv를
  PATH 앞에 둬서 모델이 돌리는 `python3` 스크립트도 같은 venv). 의존성(PyYAML·jsonschema)이 있는 python으로 `tt-oc`를 실행한다 —
  `tt-oc doctor`의 `guard-python`·`script-python` 행이 그 python으로 guard를 실제로 돌려 본다. venv는 `--work-root` 밖에 둔다
  (작업 루트는 모델이 쓸 수 있다 — 그 안의 venv면 모델이 guard가 불러오는 모듈을 바꿀 수 있다).
- 값이 빈 `OPENCODE_*` 거부 변수(예: `export OPENCODE_CONFIG=`)는 tt-oc가 자식 환경에서 뺀다(guard는 이름만 있어도 모든 도구를 거부한다).
- 셸 별칭(alias)은 `setsid`·`nohup`·포털 시작 스크립트에서 풀리지 않는다. 그렇게 띄울 때는 `<venv>/bin/python <레포>/opencode/bin/tt-oc …`처럼
  실제 경로를 쓴다(`.bashrc`의 `TT_OPENCODE`도 그 환경에서는 안 읽힐 수 있다 — install이 남긴 경로가 그때 쓰인다).
- 사전 점검(버전 = `oc_version.OPENCODE_VERSION`, `snapshot:false`·bash 허용 목록 등 실제 설정, 설치 지문, 자동 지시 파일, `config.py doctor`)이 실패하면
  시작하지 않는다. 설치는 설치 permission을 두 에이전트 frontmatter에도 둔다 — OpenCode 1.19.5는 에이전트 규칙을 설정 규칙 뒤에
  붙이므로, 사용자 전역 OpenCode 설정의 permission 키가 합친 설정의 `"*": "deny"`를 뒤로 밀거나 전역에만 있는 허용을 더해도
  설치 규칙이 이긴다. 에이전트 규칙은 관리 설정의 deny도 이기므로 설치가 그때의 관리 설정 permission을 합쳐 적는다. doctor
  `agent-permission` 행은 관리 설정이 설치 뒤 바뀌었거나 그 전에 설치한 곳이면 fail이다 — `install --force`로 다시 설치하면 풀린다.
- bash는 분석 스크립트(`python3 "<plugin>/scripts/<이름>.py" …`, 절대 경로)와 읽기 명령(ls·cat·head·tail·grep·find·git log 등)만
  돈다(`oc_adapter.py` 허용 목록 — 셸 펼침·파일 리디렉션·대입·스크립트 파일·`python3 -c`·중첩 `opencode`/`claude`는 거부).
  `TT_LOCK_OWNER=` 대입도 거부라 analyze 작업의 `db_pr`·`db_verify`는 lock owner를 작업 상태(`triage-state.json`)에서 읽는다(`dbpr/lock.py`). 생성 커맨드 안내(`gen_opencode.LOCK_NOTE`)가 접두를 붙이지 말라고 하고, 그래도 붙이면 거부 사유가 "접두만 빼고 같은 명령"을 알린다(`[telephony-triage] retry without TT_LOCK_OWNER=` — 에이전트 규칙 6에 적힌 예외, 다시 돌렸으면 tt-oc는 막힌 호출로 세지 않는다).
  다시 하라는 거부가 하나 더 있다. 스크립트 출력이 작업 루트 밖이거나 루트 자체면 거부 문구가 절대 경로로 한 번 다시 하라고 한다(`OUT_RETRY`).
  이때는 다시 해서 성공해도 tt-oc 결과가 막힘(종료 3)으로 보인다 — 결과물이 만들어졌으면 정상이다.
- 결과는 이벤트로 판정한다: 0 끝남, 1 오류·마지막 글 없음·출력 한도에서 잘림(`length`)·에이전트 스텝 한도(`step-limit`)·스크립트 출력 없음(`tt-analyze`·`tt-record`가 스크립트를 한 번도 돌리지 않음, `no-script-output`), 2 거부·점검 실패, 3 막힌 호출 있음, 124 시간 초과(첫 응답이 120초 안에 없으면 그때 멈춘다 — `no-response`, 게이트웨이 점검 안내. 시한은 `--first-timeout <초>`·`TT_OC_FIRST_TIMEOUT`, 0이면 끔).
- 결과 줄에 끝난 이유(`finish`)를 보이고, 토큰 사용량이 0이면 주의 한 줄(게이트웨이가 스트리밍 usage를 안 줄 때).
- 이번 실행에서 스크립트가 남긴 화면(`<work_dir>/.shown/log.jsonl`)은 모델을 거치지 않고 래퍼가 그대로 출력한다.
- "직접 실행" 절의 명령은 모델이 만든 그대로다 — tt-oc는 고치거나 접두를 붙이지 않는다. 모델 글은 줄마다 `  │ ` 뒤에 내고
  (tt-oc 자신의 줄은 이것으로 시작하지 않는다), 줄바꿈은 `⏎`, 그 밖의 제어 문자(CR·ESC·C1·줄 구분·양방향 제어)는 `\xNN`·`\uNNNN`로
  보인다. 최종 답·막힌 호출 전문도 같다. 명령에 `$`·백틱·`!`가 있으면 그 앞에 `↓ 모델이 만든 명령 — … 확인 후 실행` 줄.
  `--json`은 제어 문자를 모두 JSON 이스케이프한다.
- lock owner가 필요한 명령(`db_pr.OWNER_CMDS`·`lock release`(--force 없음)·`db_verify --draft`)이 있으면 tt-oc가 자기 줄로
  `주의: 터미널에서는 위 N번째 명령의 db_pr 앞에 TT_LOCK_OWNER=<owner> 를 붙인다 — 작업 <KEY>의 session.lock owner`를 낸다
  (`db_pr.py publish` 명령에는 내지 않는다 — 아래 `게시:` 줄). owner는 모델 명령 인자가 아니라 지금 `session.lock`을 쥔 작업에서 읽고, 그 작업의
  `triage-state.json` owner가 lock owner와 같을 때만 알린다(`dbpr.lock.handoff_owner`). 아니면 owner가 있는 곳과 `lock owner 불일치`로
  멈춘다는 안내. 조회 하위 프로세스는 플러그인 `scripts` 폴더에서 `PYTHONPATH`류 없이 돈다(작업 폴더에 심은 모듈을 import하지 않는다).
- 모델이 `db_pr.py publish`를 호출했거나 글로 보였으면 tt-oc가 `게시:`로 시작하는 한 줄로 갈 길을 알린다. **팀원이 할 일**: 모델이 보인 `db_pr.py publish` 명령은 붙여 넣지 않는다. 열린 설치면 OpenCode를
  닫고 `tt-oc --project <dest> publish`, 닫힌 설치면 Claude Code에서 등록한다. 그 밖의 `db_pr`·`db_verify` 명령은 읽은 뒤
  `주의:` 줄의 `TT_LOCK_OWNER=` 접두를 붙여 터미널에서 실행한다.
- TUI(`opencode`를 직접 띄움)에서는 플러그인 스크립트와 git이 모두 거부된다 — `tt-oc`로 실행한다.
- 끝난 세션은 `--delete-session`으로 지운다(`~/.local/share/opencode/opencode.db`에 도구 출력이 남는다).

### OpenCode 안에서 막는 것

- 사용자 설정 쓰기(`config.py`의 `init`·`set`·`set-tracker`·`install-hooks`·`rename-legacy --apply`·
  `tracker-candidates --mcp-config|--opencode-config`)는 돌리지 않고 정확한 명령만 보인다. 사람이 읽고 터미널에서 직접 실행한다.
  `init --answers <파일>`의 답 파일은 모델이 쓴 것이므로 붙여 넣지 않는다. `config.py init`(대화형)으로 직접 답한다.
- 플러그인 스크립트는 `--plugin-root`를 받지 않는다.
- 스크립트 출력(`--out` 등)은 설치의 작업 루트(`--work-root`) 안에만 쓴다.
- `.git`·`.githooks` 아래와 `HEAD`라는 이름에는 어떤 도구로도 쓰지 않는다. 작업 루트 안에서 `HEAD` 파일이 있는 폴더(bare 저장소 —
  작업 트리 없이 git 데이터만 든 폴더 — 와 미러) 아래에도 쓰지 않는다. 코드 루트(AOSP 등)는 작업 루트 안에 두지 않는다.
- tt-oc는 OpenCode에 `safe.bareRepository=explicit`(bare 저장소는 직접 가리켜 열지 않는다)·`protocol.ext.allow=never`를 준다.
  사용자 환경의 `GIT_ALLOW_PROTOCOL`·`GIT_CONFIG_PARAMETERS`는 뺀다. 그래서 `git -C <aosp>/.repo/projects/x.git log` 꼴은
  거부된다. 작업 트리 폴더에서 돌린다.
- git 버전: 플러그인 자체가 요구하는 git은 2.31 이상이다(`GUIDE.md` 4장 환경 점검). OpenCode의 `safe.bareRepository` 방어
  한 겹만 2.38 이상에서 듣는다. 그보다 낮으면 doctor의 `git` 행이 warn이고 시작은 한다. 그때 빠지는 것은 그 한 겹뿐이고
  `.git`·`.githooks`·`HEAD` 쓰기 거부는 그대로다. Ubuntu 22.04의 기본 git은 2.34라 이 warn이 늘 나온다.

OpenCode 허용 목록·guard·tt-oc 점검은 모델의 실수, 로그·Jira 본문에 섞인 지시, 승인 화면 위조를 줄이는 사고 방지 장치다.
작정하고 우회를 찾는 모델을 막는다고 보장하지 않는다. 모델은 사용자와 같은 OS 계정으로 돌아 사용자의 git·gh 로그인을 그대로 쓸 수
있다. 그래서 승인 없는 push가 main에 들어가는 것을 확실히 막는 것은 서버의 브랜치 보호(PR 필수)와 +1 리뷰다.

## 탐색 분석 하위 에이전트(`tt-explore`)

analyze의 탐색 분석(Step 5-2, 맞는 규칙이 없을 때 원인 가설을 세우는 단계)의 본 작업은 OpenCode에서 하위 에이전트 `tt-explore`가
한다. Claude Code 쪽 동작은 바뀌지 않았다(같은 세션에서 한다). 순서는 이렇다.

1. 메인 에이전트가 `explore.md` "언제"대로 실행할지 정하고(플래그·설정, 필요하면 사용자에게 묻기, 로그 범위 밖이면 먼저 알림),
   `triage.py explore <KEY>`와 모듈 문서가 있으면 `module --for explore`를 돌린다. 모듈 고르기·받기 실패·
   정밀 탐색(`--deep`) 질문도 모두 메인 에이전트가 사용자에게 묻는다(`module-skills.md` 5-2).
2. 메인 에이전트가 `task` 도구로 `tt-explore`를 부른다. 하위 에이전트는 앞선 대화를 보지 못하고, 메인 에이전트가 넘긴 값(작업 키·작업
   폴더·분석 사유·고른 모듈과 `--deep`·모듈 출력의 `read` 파일·5-1을 했으면 report.md의 `- 심층 분석` 줄·사용자가 준 기준 줄과
   시각)만 받는다. `explore.md`대로
   가설을 세워 `explore-output.md`를 쓰고 `check-output`을 돌린 뒤 그 결과 줄을 돌려준다. 사용자에게 묻지 않는다 — 스크립트가
   질문을 내면 그 질문을 답에 그대로 넣고 멈춘다.
3. 메인 에이전트는 받은 줄을 그대로 보이고 평소 흐름을 잇는다(Step 6 리포트, Step 7은 `explore.md` "다음"대로). 답에
   `check-output` 줄이 없으면(멈춤·스텝 한도·막힘) `check-output <KEY> --for explore --skipped "<사유>"`를 돌린다. task 도구가 없거나
   실패하면 오류를 보이고 같은 세션에서 탐색 분석을 한다.

- 왜: 탐색 분석에만 집중한 새 문맥으로 돌리고, 원하면 더 강한 모델을 이 단계에만 쓰기 위해서다(분석 정확도).
- 모델 고르기: `install --explore-model <provider>/<모델>`. 주지 않으면 세션 모델을 그대로 쓴다. 쓸 수 있는 모델 중 가장 강한
  모델을 여기에 주는 것을 권한다(탐색 분석은 토큰이 많이 들지만 한 작업에 한 번이다). `gw/<모델>`이면 `--gateway-url` 설치의
  gw provider에 같은 한도로 선언된다. 다른 provider는 OpenCode 전역 설정에 있어야 한다. `--provider-model` 설치에는 gw가 없어서
  `gw/…`를 거부한다. 다시 설치할 때 빠뜨리면 세션 모델로 돌아가고 `꺼짐:` 줄로 알린다.
- 하위 에이전트가 할 수 있는 것: `triage.py run … --look-at`, 모듈을 지정한 `module … --for explore --module <p>/<모듈>`(후보
  모듈이 다를 때), `check-output … --for explore`, `db_search.py`, 읽기 명령(ls·cat·head·tail·wc·grep·find), `explore-output.md`
  쓰기. 할 수 없는 것: `triage.py explore`와 모듈을 지정하지 않은 `module`(메인 에이전트 몫), `task`(다시 하위 에이전트), 질문,
  외부 전송, 다른 스크립트(`db_pr`·`issue_post`·`skill_patch`·`module_eval`·`config.py set`)와 git, `explore-output.md` 밖 쓰기.
- 위 bash 허용 목록은 명령 글자열을 단어 패턴으로 맞춰 보는 것이라 빈틈이 있을 수 있다. 하위 세션의 도구 호출도 guard를 그대로 거치므로,
  허용 목록에 맞아도 guard 규칙(로그 원문 통독, 인라인 코드·스크립트 파일 실행, 작업 루트 밖 출력 등)에 걸리면 막힌다.
  guard 첫 경고("guard warning")는 하위 에이전트도 읽고 같은 호출을 한 번 다시 한다.
- `task`는 `tt-explore`만 허용한다(사용자 결정 ⑧ "task 전역 거부"를 11/17에 좁혔다). 설정(`permission.task`)과 guard가 둘 다 막는다.
  `tt-oc doctor`와 관리 설정 점검은 글자가 아니라 효과로 본다(마지막으로 맞는 규칙이 이긴다): `tt-explore`만 allow이고 다른 이름은
  deny이거나, 모두 deny일 때만 통과하고 어느 쪽인지 행에 보인다.
- 관리 설정을 바꾼 뒤에는 사용자마다 `gen_opencode.py install … --force`로 다시 설치한다(설치가 관리 설정 permission을 에이전트에
  옮겨 적는다 — 다시 설치하기 전에는 `tt-oc doctor`의 `agent-permission`이 fail이다).
- 관리 설정(`/etc/opencode`)으로 하위 에이전트를 아예 막으려면 `"task": "deny"` **문자열**로 둔다. 1.19.5 실험(관리 설정 폴더를 바꿔
  `debug config`·`debug agent`로 확인)에서 문자열은 프로젝트 설정을 덮었지만, 객체 `{"*": "deny"}`는 프로젝트 객체와 합쳐져
  `tt-explore` allow가 남았다. 막으면 메인 에이전트에 task 도구가 없어 같은 세션에서 탐색 분석을 한다. 예시(`managed.json.sample`)는
  새 객체(`tt-explore`만 허용)다.
- `tt-oc`는 하위 세션도 판정한다. 1.19.5 `run --format json`은 하위 세션 이벤트를 내보내지 않아서, task 결과에 든 하위 세션 ID로
  `opencode export`를 읽는다. 하위의 막힌 호출은 막힌 호출(종료 3, 메시지에 `하위 <세션>`), 토큰은 합계에 더하고(세션별은 `--json`의
  `children`), 하위 스텝 한도(`tt-explore.md` `steps:`)에 닿으면 `step-limit`, 하위 출력이 한도에서 잘리면 `length`, 하위가 마지막 글·정상 종료 없이 끝나면 `no-final-text`, 하위 세션을 읽지 못하면 오류(종료 1)다.
  `--delete-session`은 하위 세션도 지운다.
- 출처 기록(`TT_MODEL`)은 세션 모델 이름이다. 탐색 분석을 다른 모델이 했어도 기록에는 세션 모델로 남는다.

## 게시(`tt-oc publish`, 기본 닫힘)

OpenCode 안의 모델이 이슈 DB에 push·PR을 만드는 길은 막아 둔다(사고 방지 — 위 문단). 열린 설치에서는 analyze 확인 화면까지 간 작업을 **사람이
터미널에서 직접** 게시한다:

```sh
opencode/bin/tt-oc --project <dest> publish [--job <작업 키>]      # OpenCode 세션(tt-oc·TUI)을 닫은 터미널에서
```

- 하는 일: session.lock을 쥔 작업(그 작업 `triage-state.json` owner가 lock owner와 같은 것, 여럿이면 `--job`)을 찾아
  `db_pr preflight` → `stage --then-summary`(작업 파일·wt를 새로 만들고 검사를 다시 돈다 — 몇 분 걸릴 수 있다)의 확인 화면을
  `  ┃ ` 뒤에 그대로 보이고, 작업 키를 입력하면 같은 프로세스가 `db_pr publish … --approved <화면의 approved_hash> --commit
  --and-discard`를 한다. 끝나면 마지막 줄에 `PR: <url>`이 나온다. `d`는 전체 diff를 보이고 다시 묻는다. 그 밖의 입력·빈 줄·EOF는
  취소다(종료 0, 아무것도 push되지 않는다 — 작업은 다시 stage된 상태). 취소하면 작업을 그만두는 `discard` 명령을 그대로 칠 수 있는
  꼴로 보인다. 입력 직후 `state.json`·`pr.json`·`stage.json`·`plan.json`이 화면 때와 다르면 거부한다.
- 무시된(`.gitignore`) 파일은 approved_hash·화면 diff에 안 나오는데 화면 diff를 가리거나(`.gitattributes`) 커밋 때 hook이 wt에서
  import·실행할 수 있다. 그래서 stage가 계획을 적용하기 전에 wt를 되돌리며 무시된 파일까지 지우고(`git clean -ffdx`, wt의 hook은
  돌리지 않는다), 화면을 보이기 전에 한 번 더 지운다(`git clean -ffdX`). 입력 뒤에 무시된 파일이 다시 있으면 거부한다.
- 원격 `issue/<KEY>`에 커밋이 이미 있으면(계획의 PR head와 같을 때만 진행) 그 커밋의 작성자·날짜·제목을 보이고, 작업 키 다음에
  `덮어쓰기`를 따로 받는다(그 밖의 입력·빈 줄·EOF는 취소, 종료 0). 이 작업이 올린 커밋이 아니면 취소한다.
- 거부(종료 2): 닫힘, tty 아님(파이프·CI), `TT_RUNTIME`·`CLAUDECODE`가 있음(OpenCode·Claude Code 안), `GIT_DIR`·`GIT_WORK_TREE`·
  `GIT_INDEX_FILE`·`GIT_CONFIG*`·`GIT_ALLOW_PROTOCOL`이 있음, 설치 지문 불일치, 사용자 config `plugin.scripts_path`가 설치본 `<plugin>/scripts`가 아님
  (`config.py sync-scripts-path`로 되돌린다 — pre-commit이 그 폴더의 코드를 돌린다), 계획 `source`가 analyze가 아님, `state.json`
  브랜치가 `issue/<KEY>`가 아님, `--dry-run`으로 stage한 작업, 원격 브랜치가 계획의 PR head와 다름(덮어쓰기·중단은 Claude Code에서).
- 설치 지문(`tt-oc doctor`·publish가 대조)은 `opencode.json`·`.opencode/` 아래 설치 파일(`tt-guard.js` 포함)·`<plugin>/scripts/**/*.py`를
  덮고, tt-oc 자신과 `tt-oc.json`은 덮지 않는다(둘 다 모델이 쓸 수 없는 경로에 둔다).
- 범위: **analyze 등록만**. record·verify-fix·fix-submitted·sync-pr·병합·리뷰어 요청·Jira 코멘트는 OpenCode 설치에서 닫혀 있다
  (Claude Code에서 한다).
- **모델이 보인 `db_pr.py publish` 명령은 붙여 넣지 않는다** — 그 경로에는 재stage·`scripts_path` 대조가 없다(모델이 작업
  파일·`wt/.githooks`·사용자 config를 바꿔 둘 수 있다). tt-oc가 `게시:` 줄로 대신 할 일을 알린다("실행").
- Claude Code와 같이 쓰면: Claude Code 세션이 시작할 때마다 사용자 설정의 `plugin.scripts_path`를 Claude Code 쪽 플러그인 폴더로
  바꾼다. 두 쪽 플러그인 폴더가 다르면 publish가 "`plugin.scripts_path`가 설치본과 다르다"로 거부한다. 거부 문구에 나온
  `config.py sync-scripts-path` 명령을 터미널에서 돌린 뒤 publish를 다시 한다.
- 여는 사람이 확인할 것:
  - 터미널(tty)에서 직접 돌린다. 파이프·리디렉션·CI에서는 publish가 거부된다.
  - `gh auth status --hostname <GHE 호스트>`가 로그인 상태다.
  - 이슈 DB clone의 `core.hooksPath`가 `.githooks`다(`config.py doctor`의 `hook` 행이 ok). 그 clone에 `.githooks/pre-push`
    (main push와 승인 토큰 없는 push를 막는 hook)가 있다.
  - 서버의 main 브랜치 보호(PR 필수·+1)가 켜져 있다(`docs/SITE_INSTALL.md` 9절 3, `site_step.py check`의 `s4a.protection`).
- 여는 법: install에 `--allow-publish`를 준다(없으면 닫힘) → `tt-oc doctor`의 `publish` 행이 열림인지 본다. 첫 실제 작업에서는
  `tt-oc publish`로 화면까지 보고 빈 줄로 취소한 뒤(아무것도 push되지 않는다) 다시 돌려 작업 키로 승인해도 된다.
- install을 한 번 더 할 때(`--force`)는 `--allow-publish`와 `--jira-read-tool`을 매번 함께 준다. 빠진 것은 꺼진다. install이
  꺼진 것을 `꺼짐:` 줄로, 지금 상태(게시 열림·닫힘, Jira 읽기 도구 수)를 한 줄로 알린다.

## Jira 읽기(관문, 기본 닫힘)

OpenCode에서 Jira MCP 읽기는 사내 확인을 통과한 뒤 사용자가 직접 열 때만 된다(`docs/development/RUNTIMES.md` §5.5). 코멘트 쓰기는 v1에서 늘 막힌다.

```sh
python3 tools/site_step.py runtime-check opencode --project <dest> --jira <있는 키> --missing-key <없는 키>   # 모델 토큰 0
python3 <plugin>/scripts/config.py set opencode.jira_read open        # 터미널에서 직접(통과 기록이 있을 때만, OpenCode 안에서는 거부)
python3 tools/gen_opencode.py install … --jira-read-tool <서버>_<도구> [--allow-publish] --force   # 설치 설정에 읽기 도구 allow(게시를 열었으면 --allow-publish도)
```

- 원문은 `<work_dir>/<KEY>/issue_raw.json`에만, 모델에는 jira_bridge 마스킹 요약만 간다(Claude Code와 같다). Jira 오류 응답은
  "Jira 오류(본문 숨김): <도구> <분류>"로만 보인다.
- 관문은 OpenCode를 시작할 때 한 번 정해진다. 열거나 닫은 뒤에는 OpenCode(tt-oc·TUI)를 다시 시작한다 — 세션 중에 바뀐 설정·
  기록은 그 세션에 적용되지 않는다. OpenCode 안에서는 edit·write와 플러그인 스크립트 인자(`--out` 등) 모두 사용자 설정·통과
  기록·OpenCode 설정을 가리키면 거부된다.
- 플러그인 스크립트나 OpenCode 버전이 바뀌면 관문이 다시 닫힌다(통과 기록의 지문·버전 불일치) — 확인을 다시 돌린다.
  `config.py doctor`(OpenCode 안)의 `jira_gate` 행이 열림·닫힘과 마지막 확인을 보인다. 닫기: `config.py set opencode.jira_read closed`.
