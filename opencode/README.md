# OpenCode v1 (분석 전용)

OpenCode 1.19.5 + 사내 GLM용 바깥 층이다(계획 I, `docs/development/MODULE_SKILLS_DECISIONS.md` 11/05 "계획 I 1단계 결과").
v1은 **분석 전용(안 A)**: Jira 코멘트, 이슈 DB push, `db_pr publish|merge`, 리뷰어 요청, 스킬 적용, module_eval은 OpenCode에서
막는다. 그 단계에 이르면 정확한 명령을 출력하고, 사용자가 터미널이나 Claude Code에서 직접 실행한다.

| 파일 | 내용 |
|---|---|
| `opencode.json.template` | 프로젝트 설정(v1 키만). `snapshot:false` 필수, `autoupdate:false`, `share:"disabled"`, 한도 202000/16000, 허용 목록(`"*":"deny"` 뒤 read·glob·grep·list·bash·edit만 — read 도구는 원문 작업 파일 `issue_raw.json`·`events.json`·`events-full.json`·`match.json`·`jira_raw.json`을 deny(grep 도구·site 추가 이름은 막지 않는다, 08-safety 10번의 한계), bash도 `"*":"deny"` 뒤 `python3 *`·읽기 명령만), `jira_*`·`github_*`·`task` deny(Jira 읽기 도구는 `install --jira-read-tool`로만 끝에 allow), `external_directory`는 플러그인·작업 루트·clone만 |
| `managed.json.sample` | `/etc/opencode/opencode.json` 예시(관리자 배포, 다중 방어). 프로젝트 설정 뒤에 합쳐진다 |
| `agents/triage.md` | 에이전트 프롬프트(약 2KB): 스크립트가 판정, Read ≤200줄, 화면 그대로, 쓰기는 명령 출력만 |
| `commands/tt-*.md` | `tools/gen_opencode.py`가 `plugin/commands/*.md`에서 만든다(손으로 고치지 않는다) |
| `bin/tt-oc` | 실행 래퍼: 확인 화면·must_show가 있는 흐름은 이것으로. 표준 라이브러리만 쓰고 OpenCode 표면은 아래 한 파일에서 읽는다 |
| `../plugin/scripts/common/oc_version.py` | **OpenCode 바이너리 의존 한 곳**: 고정 버전, CLI 인자, 거부·자식 환경 변수, 바이너리의 거부 문구, `run --format json` 이벤트 키, 플러그인 hook 이름. 버전을 올릴 때는 이 파일과 `tests/test_oc_version.py`의 고정값만 바꾸고, 파일에 적힌 실험을 새 버전으로 다시 한다(tt-guard.js는 시험이 대조) |
| `plugins/tt-guard.js` | guard 플러그인: 모든 도구 호출을 `plugin/scripts/common/oc_adapter.py`로 바뀌지 않은 `guard.py`에 넘긴다(닫힘 실패). 오류로 끝난 MCP 호출의 Jira 오류 본문은 모델 요청 직전(`experimental.chat.messages.transform`)에 숨긴다. `install`이 `<dest>/.opencode/plugins/`(1.19.5가 자동으로 싣는 폴더)에 복사하며 플러그인 루트를 써 넣으므로 TUI에서도 `TT_PLUGIN_ROOT` 없이 걸린다 |

## 설치

```sh
python3 tools/gen_opencode.py install --dest <git 레포 밖 폴더> --plugin-root <설치된 plugin/> \
    --work-root <작업 루트> [--issue-db <clone>]... --gateway-url <http(s)://…/v1> --model <모델 ID>
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

## 실행

```sh
opencode/bin/tt-oc --project <dest> --command tt-analyze -- ABC-123 /path/logcat.txt --analysis-only
opencode/bin/tt-oc --project <dest> -s <세션> -- 2          # 질문에 답하고 이어가기
```

- `--pure`·`--auto`·`--attach`·`-i`·`--agent`·`--model`과 설정을 덮는 `OPENCODE_*` 환경 변수는 거부한다.
- 사전 점검(버전 = `oc_version.OPENCODE_VERSION`, `snapshot:false`·bash 허용 목록 등 실제 설정, 설치 지문, 자동 지시 파일, `config.py doctor`)이 실패하면
  시작하지 않는다.
- bash는 분석 스크립트(`python3 "<plugin>/scripts/<이름>.py" …`, 절대 경로)와 읽기 명령(ls·cat·head·tail·grep·find·git log 등)만
  돈다(`oc_adapter.py` 허용 목록 — 셸 펼침·파일 리디렉션·대입·스크립트 파일·`python3 -c`·중첩 `opencode`/`claude`는 거부).
  `TT_LOCK_OWNER=` 대입도 거부라 analyze 작업의 `db_pr`·`db_verify`는 lock owner를 작업 상태(`triage-state.json`)에서 읽는다(`dbpr/lock.py`). 생성 커맨드 안내(`gen_opencode.LOCK_NOTE`)가 접두를 붙이지 말라고 하고, 그래도 붙이면 거부 사유가 "접두만 빼고 같은 명령"을 알린다(`[telephony-triage] retry without TT_LOCK_OWNER=` — 에이전트 규칙 6의 유일한 예외, 다시 돌렸으면 tt-oc는 막힌 호출로 세지 않는다).
- 결과는 이벤트로 판정한다: 0 끝남, 1 오류·마지막 글 없음·출력 한도에서 잘림(`length`)·에이전트 스텝 한도(`step-limit`)·스크립트 출력 없음(`tt-analyze`·`tt-record`가 스크립트를 한 번도 돌리지 않음, `no-script-output`), 2 거부·점검 실패, 3 막힌 호출 있음, 124 시간 초과(첫 응답이 120초 안에 없으면 그때 멈춘다 — `no-response`, 게이트웨이 점검 안내. 시한은 `--first-timeout <초>`·`TT_OC_FIRST_TIMEOUT`, 0이면 끔).
- 결과 줄에 끝난 이유(`finish`)를 보이고, 토큰 사용량이 0이면 주의 한 줄(게이트웨이가 스트리밍 usage를 안 줄 때).
- 이번 실행에서 스크립트가 남긴 화면(`<work_dir>/.shown/log.jsonl`)은 모델을 거치지 않고 래퍼가 그대로 출력한다.
- "직접 실행" 절의 명령은 모델이 만든 그대로다 — tt-oc는 고치거나 접두를 붙이지 않는다. 모델 글은 줄마다 `  │ ` 뒤에 내고
  (tt-oc 자신의 줄은 이것으로 시작하지 않는다), 줄바꿈은 `⏎`, 그 밖의 제어 문자(CR·ESC·C1·줄 구분·양방향 제어)는 `\xNN`·`\uNNNN`로
  보인다. 최종 답·막힌 호출 전문도 같다. 명령에 `$`·백틱·`!`가 있으면 그 앞에 `↓ 모델이 만든 명령 — … 확인 후 실행` 줄.
  `--json`은 제어 문자를 모두 JSON 이스케이프한다.
- lock owner가 필요한 명령(`db_pr.OWNER_CMDS`·`lock release`(--force 없음)·`db_verify --draft`)이 있으면 tt-oc가 자기 줄로
  `주의: 터미널에서는 위 N번째 명령의 db_pr 앞에 TT_LOCK_OWNER=<owner> 를 붙인다 — 작업 <KEY>의 session.lock owner`를 낸다. 명령을
  복사하고 그 접두를 붙여 실행한다. owner는 모델 명령 인자가 아니라 지금 `session.lock`을 쥔 작업에서 읽고, 그 작업의
  `triage-state.json` owner가 lock owner와 같을 때만 알린다(`dbpr.lock.handoff_owner`). 아니면 owner가 있는 곳과 `lock owner 불일치`로
  멈춘다는 안내. 조회 하위 프로세스는 플러그인 `scripts` 폴더에서 `PYTHONPATH`류 없이 돈다(작업 폴더에 심은 모듈을 import하지 않는다).
- TUI(`opencode`)는 자유 탐색만 — 표시 보장이 없다.
- 끝난 세션은 `--delete-session`으로 지운다(`~/.local/share/opencode/opencode.db`에 도구 출력이 남는다).

## 게시(`tt-oc publish`, 기본 닫힘)

OpenCode 안의 모델은 이슈 DB에 push·PR을 만들지 못한다(위 "직접 실행"). 열린 설치에서는 analyze 확인 화면까지 간 작업을 **사람이
터미널에서 직접** 게시한다:

```sh
opencode/bin/tt-oc --project <dest> publish [--job <작업 키>]      # OpenCode 세션(tt-oc·TUI)을 닫은 터미널에서
```

- 하는 일: session.lock을 쥔 작업(그 작업 `triage-state.json` owner가 lock owner와 같은 것, 여럿이면 `--job`)을 찾아
  `db_pr preflight` → `stage --then-summary`(작업 파일·wt를 새로 만들고 검사를 다시 돈다 — 몇 분 걸릴 수 있다)의 확인 화면을
  `  ┃ ` 뒤에 그대로 보이고, 작업 키를 입력하면 같은 프로세스가 `db_pr publish … --approved <화면의 approved_hash> --commit
  --and-discard`를 한다. `d`는 전체 diff를 보이고 다시 묻는다. 그 밖의 입력·빈 줄·EOF는 취소(종료 0, 아무것도 push되지 않는다 —
  작업은 다시 stage된 상태). 입력 직후 `state.json`·`pr.json`·`stage.json`·`plan.json`이 화면 때와 다르면 거부한다.
- 거부(종료 2): 닫힘, tty 아님(파이프·CI), `TT_RUNTIME`·`CLAUDECODE`가 있음(OpenCode·Claude Code 안), `GIT_DIR`·`GIT_WORK_TREE`·
  `GIT_INDEX_FILE`·`GIT_CONFIG*`가 있음, 설치 지문 불일치, 사용자 config `plugin.scripts_path`가 설치본 `<plugin>/scripts`가 아님
  (`config.py sync-scripts-path`로 되돌린다 — pre-commit이 그 폴더의 코드를 돌린다), 계획 `source`가 analyze가 아님, `state.json`
  브랜치가 `issue/<KEY>`가 아님, `--dry-run`으로 stage한 작업, 원격 브랜치가 계획의 PR head와 다름(덮어쓰기·중단은 Claude Code에서).
- 범위: **analyze 등록만**. record·verify-fix·fix-submitted·sync-pr·병합·리뷰어 요청·Jira 코멘트는 OpenCode 설치에서 닫혀 있다
  (Claude Code에서 한다).
- **모델이 출력한 `db_pr.py publish` 명령을 붙여 넣지 않는다** — 그 경로에는 재stage·`scripts_path` 대조가 없다(모델이 작업
  파일·`wt/.githooks`·사용자 config를 바꿔 둘 수 있다). 열린 설치에서는 "직접 실행" 절 끝에 `tt-oc … publish` 안내 줄이 나온다.
- 여는 절차: 사내 확인(tty인 터미널, gh 인증·GHE 호스트, 이슈 DB clone의 hooksPath·pre-push 토큰 검사, 서버 브랜치 보호)을 마친 뒤
  설치할 때 `python3 tools/gen_opencode.py install … --allow-publish`로 연다(플래그 없이 설치하면 닫힘) → `tt-oc doctor`의
  `publish` 행이 열림인지 본다 → 첫 실제 작업에서 `tt-oc publish`로 화면까지 보고 빈 줄로 취소(아무것도 push되지 않는다) → 다시
  돌려 작업 키로 승인한다. 이미 설치한 곳을 나중에 열거나 닫으려면 같은 install을 `--force`로 다시 한다(플래그 유무대로 `tt-oc.json`이
  다시 쓰인다).

## Jira 읽기(관문, 기본 닫힘)

OpenCode에서 Jira MCP 읽기는 사내 확인을 통과한 뒤 사용자가 직접 열 때만 된다(`docs/development/RUNTIMES.md` §5.5). 코멘트 쓰기는 v1에서 늘 막힌다.

```sh
python3 tools/site_step.py runtime-check opencode --project <dest> --jira <있는 키> --missing-key <없는 키>   # 모델 토큰 0
python3 <plugin>/scripts/config.py set opencode.jira_read open        # 터미널에서 직접(통과 기록이 있을 때만, OpenCode 안에서는 거부)
python3 tools/gen_opencode.py install … --jira-read-tool <서버>_<도구> --force   # 설치 설정에 읽기 도구 allow
```

- 원문은 `<work_dir>/<KEY>/issue_raw.json`에만, 모델에는 jira_bridge 마스킹 요약만 간다(Claude Code와 같다). Jira 오류 응답은
  "Jira 오류(본문 숨김): <도구> <분류>"로만 보인다.
- 관문은 OpenCode를 시작할 때 한 번 정해진다. 열거나 닫은 뒤에는 OpenCode(tt-oc·TUI)를 다시 시작한다 — 세션 중에 바뀐 설정·
  기록은 그 세션에 적용되지 않는다. OpenCode 안에서는 edit·write와 플러그인 스크립트 인자(`--out` 등) 모두 사용자 설정·통과
  기록·OpenCode 설정을 가리키면 거부된다.
- 플러그인 스크립트나 OpenCode 버전이 바뀌면 관문이 다시 닫힌다(통과 기록의 지문·버전 불일치) — 확인을 다시 돌린다.
  `config.py doctor`(OpenCode 안)의 `jira_gate` 행이 열림·닫힘과 마지막 확인을 보인다. 닫기: `config.py set opencode.jira_read closed`.
