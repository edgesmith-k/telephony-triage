# 팀원 사용 가이드: telephony-triage 플러그인(Claude Code · Claude Code + 사내 모델 · OpenCode)

도입 담당자가 사내 점검·배포를 끝낸 뒤 읽는다. 꺾쇠 값은 도입 담당자에게 받는다.

**용어**: 5-1 심층 분석(1위 후보를 모듈 문서·설치 스킬로) · 5-2 탐색 분석(후보 없을 때 가설) · must_show 모델이 그대로 보여야 하는 스크립트 화면 · guard 승인 없는 쓰기를 막는 hook · integrity OpenCode 설치 파일 지문.

## 0. 어떤 환경을 쓸까

| 환경 | 할 수 있는 일 | 추천 용도 |
|---|---|---|
| Claude Code + Claude | 분석, 기록(PR), Jira 코멘트, 병합 | 기본. **기록·코멘트는 여기서** |
| Claude Code + 사내 모델 | 위와 같다(모델만 게이트웨이로) | 사내 모델로 분석·기록. 5절 주의 |
| OpenCode + 사내 모델 | **분석 전용**. 쓰기 단계면 명령을 출력하고 멈춘다 | 빠른 분석. 명령은 터미널·Claude Code에서 직접 |

세 환경은 같은 사용자 설정(`~/.telephony-triage/config.yaml`)·이슈 DB clone·작업 디렉토리를 쓴다.

## 1. 설치

### 1.1 공통 준비 (Ubuntu 22.04)

```
python3 --version   # 3.10 이상
python3 -m pip --version || sudo apt install python3-pip
pip config --user set global.index-url https://<사내 미러>/simple
python3 -m pip install --user PyYAML==6.0.3 jsonschema==4.26.0
gh auth login -h <GHE 호스트>   # 이슈 DB PR용. 없으면 읽기 분석·연습만 된다
claude mcp list   # <Jira MCP 서버 이름>이 사용자 범위로 보여야 한다
```

- 두 패키지를 설치한 Python이 `claude`·`opencode`를 띄운 터미널의 `python3`여야 한다(venv면 켠 터미널에서). 막히면 `docs/SITE_INSTALL.md` §4 표.
- OpenCode는 Jira MCP를 `~/.config/opencode/opencode.json`의 `mcp`에도 둔다(4절).

### 1.2 Claude Code 플러그인

플러그인 화면에서 사내 마켓플레이스(`<사내 마켓플레이스>`)의 `telephony-triage`를 설치한다. 레포 clone은 필요 없다. 설치된 스크립트 폴더는 setup(2절) 뒤 `grep scripts_path ~/.telephony-triage/config.yaml`의 값이다. 이 문서에서는 `S=<그 값>`으로 쓴다(`<설치된 plugin 폴더>`는 그 상위).

### 1.3 Claude Code + 사내 모델 (환경 프로필)

`~/.claude/settings.json`의 `env` 블록에, 도입 담당자가 준 값 그대로.

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "<게이트웨이 URL(/v1 앞까지)>",
    "ANTHROPIC_AUTH_TOKEN": "<사내 자격>",
    "ANTHROPIC_MODEL": "<사내 모델 이름>",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "<사내 모델 이름>",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "<사내 모델 이름>",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "<사내 모델 이름>",
    "CLAUDE_CODE_SUBAGENT_MODEL": "<사내 모델 이름>",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16000",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "202000",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    "CLAUDE_CODE_EFFORT_LEVEL": "unset",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  }
}
```

- 자격은 게이트웨이가 받는 쪽 하나만(`ANTHROPIC_AUTH_TOKEN` 또는 `ANTHROPIC_API_KEY`).
- `CLAUDE_CODE_DISABLE_THINKING=1`은 게이트웨이가 thinking을 거부할 때만. `CLAUDE_CODE_EFFORT_LEVEL`은 `"unset"`을 넣는다(없어도 통과). 모델 ID는 모두 같게.
- Claude와 번갈아 쓰려면 settings.json `env` 대신 같은 키를 셸 파일에 `export`로 적고 그 터미널에서만 `source` 뒤 `claude`(둘 다 두면 모든 `claude`가 게이트웨이로).
- `claude -p`에 `--no-session-persistence`를 붙이지 않는다(표시 점검이 꺼진다).
- 레포 사본(1.4)이 있으면 점검(모델 호출 없음): `python3 $TT/tools/site_step.py runtime-check claude-gateway`. `CLAUDE_CODE_EFFORT_LEVEL`이 없어도 통과.

### 1.4 OpenCode + 사내 모델 (`tt-oc`)

필요한 것: OpenCode **1.19.5**(다른 버전이면 시작 안 함), 레포 사본(`opencode/`·`tools/`), 설치된 플러그인 폴더, **setup이 끝난 사용자 설정**(2절 1번).

- 레포 사본은 사내 tt 레포를 도입 담당자가 공지한 반입 태그로 읽기 전용 clone한다: `git clone --depth 1 --branch <반입 태그> <사내 tt 레포> <사본>`. **설치된 플러그인과 같은 판**이어야 한다(`diff -rq -x __pycache__ $TT/plugin/scripts <설치된 plugin>/scripts`가 빈 출력). 사본은 고치지 않는다(install이 커맨드·`tt-guard.js`를 사본에서 복사). Jira 확인·`runtime-check`도 이 사본으로.

```
TT=<tt 레포 사본>
alias tt-oc=$TT/opencode/bin/tt-oc   # 이 문서의 tt-oc는 이것
python3 $TT/tools/gen_opencode.py install --dest ~/tt-oc \
    --plugin-root <설치된 plugin 폴더> --work-root <작업 디렉토리> --issue-db <이슈 DB clone> \
    --gateway-url <게이트웨이 OpenAI 호환 주소(…/v1까지)> --model <사내 모델 이름>
export TT_GATEWAY_API_KEY=<사내 자격>   # 설정 파일에는 쓰지 않는다
export TT_OC_PROJECT=~/tt-oc   # 그 뒤로는 --project 생략 가능
tt-oc doctor   # 사전 점검. fail이 있으면 시작하지 않는다
```

- `--dest`는 git 밖. 그 폴더와 위 폴더(`/`까지)의 `AGENTS.md`·`CONTEXT.md`, 또는 `~/.config/opencode/AGENTS.md`가 있으면 시작 안 함.
- `<작업 디렉토리>`는 사용자 설정의 `work_dir`(기본 플랫폼 `~/.telephony-triage/work`). 다른 플랫폼(oFono 등)의 기본 `~/.telephony-triage/work-<플랫폼>`은 그 밖이다 — 한 설치는 작업 폴더 하나만 쓰므로 oFono도 OpenCode로 쓰면 다른 `--dest`(예: `~/tt-oc-ofono`)에 `--work-root <work-ofono>`로 한 번 더 install한다. `--work-root`에 `~/.telephony-triage`는 주지 않는다(config.yaml이 edit 범위에 든다). `--issue-db`는 clone마다.

## 2. 처음 한 번 설정

1. **setup**: Claude Code에서 `/telephony-triage:setup`으로 먼저 한다(OpenCode도 같은 설정을 쓴다). OpenCode의 `/tt-setup`은 그 뒤 다시 점검하거나 바꿀 때만(config가 없으면 `tt-oc`가 시작하지 않는다).
   - Jira MCP 등록을 먼저 점검하고(없으면 거기서 멈춘다), clone 경로만 묻는다(GHE 아이디는 gh 로그인에서 읽고, 원격 URL은 팀 기본값 — 못 읽거나 없을 때만 묻는다. 타임존 등 나머지는 팀 기본값을 한 줄씩 보여 주기만). 그 뒤 Jira 도구 짝·git hook·스냅샷·gh를 확인하고 점검표(doctor)를 보여 준다.
2. **점검표**: 모든 행이 `ok`면 끝. `warn`·`fail`은 그 행의 "다음" 칸대로(7절).
   - Claude Code: `/telephony-triage:status --doctor`
   - OpenCode: `tt-oc doctor` — `env`·`project-git`·`instructions`·`integrity`·`opencode-version`·`opencode-config`·`config-doctor`(개수만), warn `module-skills`·`read-roots`·`gateway-key`·`gateway-url`. 점검표 행을 하나씩 보려면 `TT_RUNTIME=opencode python3 $S/config.py doctor --format markdown`(모델 호출 없음, `opencode_env`·`jira_gate` 포함).
3. **이슈 DB clone**은 내 것이다. 도구는 그 브랜치도 파일도 바꾸지 않는다. 경로 바꾸기는 `docs/SITE_INSTALL.md` 7절.
4. **모듈 스킬**: 팀이 모듈 스킬 레포를 켰으면 할 일이 없다. 심층·탐색 분석에 동의하면 그 분야 문서를 최신판으로 받아 읽는다(받기에 실패해도 분석은 끝난다). 모듈은 oFono·Android 각 data·sim·network·call·sms·ims·modem 7개다(팀 레포에 있는지는 MS-1 결과를 따른다). 문서는 증상별 첫 점검 표와 대체 근거(핵심 줄이 없을 때 볼 다른 층 줄)를 갖는다.
5. **설치 스킬을 계속 쓰기(선택)**: 이미 쓰는 사내 분석 스킬을 분야별로 고른다.
   ```
   python3 $S/config.py set analyzers.data.prefer skill
   python3 $S/config.py set --platform ofono analyzers.data.prefer skill   # oFono
   python3 $S/config.py set analyzers.data.skill_dir <스킬 폴더 절대 경로>  # 못 찾을 때만
   ```
   점검표 `module_skills` 행에 `5-1 설치 스킬: data · 그 밖=모듈 문서`처럼 보인다. OpenCode면 `install --force`.
6. **반복 질문 줄이기(선택)**: 사용자 설정에 `analyzers: {data: {when: never}}`·`explore: {when: never}`, 한 번만이면 `--no-analyzer`·`--no-explore`.

## 3. 매일 쓰는 흐름

1. **분석 요청**: `/telephony-triage:analyze ABC-12345 ~/logs/radio.txt` 또는 말로 "ABC-12345 로그 분석해줘, 로그는 ~/logs/radio.txt". 연습 `--dry-run`, 결과만 `--analysis-only`. **처음 몇 번은 `--analysis-only`를 권한다** — 리포트만 받고(계획·PR 없음, 질문도 적다) 읽는 법에 익숙해진 뒤 기록까지 한다. 리포트의 `결론:` 한 줄이 분류와 다음 행동이다.
2. **질문에 답하기**: 코드 경로, 심층·탐색 분석 여부(토큰이 더 든다), 어느 모듈 문서로 볼지.
3. **리포트 읽기**

   | 부분 | 읽는 법 |
   |---|---|
   | 분류 후보 | 스크립트 점수. 판정 기준 |
   | 근거 로그 | 마스킹된 로그 줄 |
   | 원인 | 로그로 확인 / 코드로 추정 / placeholder 규칙 결과가 나뉜다. 반대 근거도 본다 |
   | 심층 분석 | `심층 분석 (모듈 스킬 ofono/data @a1b2c3d): …` — 모델 의견. 분류 점수에 쓰지 않는다 |
   | 탐색 분석 | `탐색 분석 (추정, timeline.md n/m줄): …` — 가설 1~3개. 추정이다 |
   | 근거 원문 검사 | `인용 n개 중 원문에 없음 k · 약함 m`(5절) |
   | 출처 | 모듈 문서 판본(`@sha7`)·설치 스킬 이름. 생략되면 `심층 분석 생략: <사유>` |

4. **기록 여부**: "이 분류가 맞나요?"에 1위 / 다른 원인·유형 / 원인 미확정 / 기록 안 함. 새 원인·유형·시그니처는 내가 확인해야 들어간다.
5. **확인 화면 승인**: 바뀌는 파일·검증 결과·커밋 메시지·PR 제목을 보고 승인 / 수정 요청 / 전체 diff / 취소. 승인 뒤 바뀌면 다시 묻는다.
6. **PR**: 도구가 별도 작업 공간·도구 브랜치에서 커밋·push하고 PR 링크를 보인다. 리뷰어 지정, Jira 코멘트(본문 확인 화면을 따로 거침)는 선택.
7. **병합**: 작성자가 아닌 동료가 최신 커밋에 Approve(+1)한 뒤 "병합해줘"(또는 GHE 웹). main이 바뀌었으면 `sync-pr` 뒤 +1을 다시.
8. **이어서 하기**: `/telephony-triage:status [JIRA-KEY]`.

### 커맨드 목록

Claude Code는 `/telephony-triage:<이름>`, OpenCode는 `/tt-<이름>`(`tt-oc --command tt-<이름>`). ★는 OpenCode에서 쓰기 단계가 명령 출력으로 바뀌는 흐름이다.

| 이름 | 한 줄 설명 |
|---|---|
| `analyze` ★ | Jira 이슈·logcat 분석, 이슈 DB에 분류·기록 |
| `record` ★ | 스스로 해결한 이슈를 분석 없이 기록 |
| `search` | 증상·키워드·Jira 키·ID로 이슈 DB 검색 |
| `status` ★ | 작업 상태(읽기 전용), `--doctor`면 점검 행. ★는 이어지는 병합 |
| `sync` | 이슈 DB 읽기 스냅샷 최신화 |
| `sync-pr` ★ | 머지 대기 PR을 최신 main 위에 다시 적용 |
| `fix-submitted` ★ | 수정 CL 반영 기록(PR) |
| `verify-fix` ★ | 수정 빌드 logcat으로 재발 판정(PR) |
| `validate` ★ | 인자 없으면 변경 검사, `--cause`면 해결책 검증 뒤 PR |
| `preview` | 생성 파일 미리보기 |
| `review` ★ | 카테고리 월간 리뷰(읽기 전용). ★는 이어지는 계획 적용 PR |
| `migrate` ★ | 이슈 DB 스키마 마이그레이션(메인테이너용) |
| `setup` | 사용자 설정·Jira 도구·hook·스냅샷·gh |
| `help` | 커맨드 목록과 상황별 추천 |

## 4. OpenCode에서 다른 점

```
tt-oc --command tt-analyze -- ABC-12345 /path/logcat.txt --issue-file <이슈 yaml> --analysis-only   # 관문을 열기 전
tt-oc -s <세션> -- 2   # 질문에 답하고 이어가기
tt-oc -s <세션> --delete-session -- 2   # 마지막 답 + 세션 삭제
```

- tt-oc 옵션(`-s`·`--delete-session` 등)은 `--` 앞에 둔다. 뒤는 모델에게 가는 메시지다.
- **분석 전용**: 쓰기(코멘트·push·PR·병합·리뷰어 요청·스킬 적용)는 "OpenCode v1에서 실행하지 않은 명령" 절에 명령으로 낸다. "스크립트 화면" 절(모델을 거치지 않은 원본)을 읽고 승인할 때만 터미널에서 실행한다. `db_pr`·`db_verify` 명령은 tt-oc가 그 작업의 lock owner를 `TT_LOCK_OWNER=…`로 앞에 붙여 보인다 — 그 작업이 지금 lock을 쥐고 있을 때만, 줄 끝 `# owner: 작업 <KEY>`가 지금 작업인지 확인하고 실행한다. 붙이지 못했으면 `주의:` 줄이 owner가 있는 파일을 알린다 — 붙이지 않고 실행하면 `lock owner 불일치`로 멈춘다.
- **종료 코드**: 0 끝남, 1 오류(`no-script-output`이면 분석 스크립트가 한 번도 돌지 않았다 — 도입 담당자에게. `length`·`step-limit`이면 출력·스텝 한도에서 끊겼다 — `-s <세션>`으로 이어가기), 2 거부·사전 점검 실패, 3 막힌 호출(내 차례일 수 있음), 124 시간 초과(`no-response`면 게이트웨이가 120초 안에 답하지 않았다 — `tt-oc doctor`). 비용은 "미상"(`cost:0`≠0원).
- **막힘 표시**: `[telephony-triage]`로 시작하면 guard가 막은 것(`… guard warning`은 경고뿐).
- **Jira 읽기 관문**: 기본은 닫힘(`jira_gate` 행 warn). 이슈 내용은 `--issue-file <yaml>`로(`--analysis-only`·`--dry-run`에서만) 주거나 Claude Code에서 분석한다. 열기는 내가 직접 한다(OpenCode 안의 모델은 못 연다. 코멘트는 계속 막힘):
  1. Jira MCP를 `~/.config/opencode/opencode.json`의 `mcp`에 둔다.
  2. `python3 $TT/tools/site_step.py runtime-check opencode --project ~/tt-oc --jira <있는 키> --missing-key <없는 키>` 통과.
  3. `python3 $S/config.py set opencode.jira_read open`(오류 경로가 pass가 아니면 `--accept-error-bodies` — 허용 여부는 도입 담당자 안내).
  4. `gen_opencode.py install … --jira-read-tool <서버>_<도구> --force`. 플러그인을 갱신하면 2부터 다시.
- **설치 스킬**: 스킬 도구가 없다(`skill: deny`). 스크립트가 알려 준 `SKILL.md`를 파일로 읽고, 못 읽으면 `심층 분석 생략: 설치 스킬 못 찾음`으로 계속한다. 모듈 문서 받기 실패도 분석을 멈추지 않는다.
- **TUI**(`opencode` 직접 실행)는 화면 표시를 보장하지 않아 기록 판단에 쓰지 않는다.
- 거부되는 옵션: `--pure`·`--auto`·`--attach`·`--port`·`-i`(`--interactive`)·`--fork`·`-c`(`--continue`)·`--agent`·`-m`(`--model`), 설정을 덮는 `OPENCODE_*` 변수.
- 도구 출력이 `~/.local/share/opencode/opencode.db`에 남는다(지우려면 `--delete-session`).

## 5. 사내 모델 결과를 볼 때 주의

- 분류 점수·검증·마스킹·쓰기 차단은 스크립트가 지킨다. 원인 설명과 심층·탐색 분석은 모델 몫이라 더 약할 수 있다.
- **근거 원문 검사 줄**: `원문에 없음` 1 이상은 입력에 없는 줄을 인용한 것(지어낸 근거일 수 있다). `약함`은 일부만 맞음. `건너뜀(…)`은 통과가 아니다.
- **출처 기록**: 커밋 끝 `Triage-Env: runtime=…; model=…; gateway=…; label=…`와 확인 화면 `분석 환경` 줄이 자동으로 붙는다. 지우지 않는다(점검에 쓴다).
- **의심되면**: Claude Code + Claude로 `--analysis-only` 비교. 확인 화면이 요약돼 보이면 승인 말고 전문 요청.
- **정기 점검**: 도입 담당자가 사내 모델 기록만 골라 점검한다(`site_step.py audit` — 새 빌드 뒤 0건이 된 시그니처(drift)도 본다). 걸린 것은 이슈 DB 레포 Issue(`[triage-audit] …`)로도 올라온다(`audit --notify --create`, 담당자 확인 뒤). 고칠 것은 PR로 온다.
- **부분 일치**: 후보가 없거나 약하면 리포트에 `규칙 제안 (부분 일치):`가 나온다(코드 루트를 골랐으면 코드 대조 결과도). 기본은 받지 않음. 받으면 시그니처 추가 PR(+1)로 간다.
- **토큰 아끼기**: 필요 없으면 `--no-analyzer --no-explore`.

## 6. 하지 말 것

- `<work_dir>` 안의 스냅샷·작업 공간·lock은 손으로 고치지 않는다. 내 clone은 도구가 바꾸지 않는다. 직접 편집은 내 clone의 별도 브랜치에서 `validate` 뒤 PR로.
- main에 직접 push하지 않는다. `--no-verify`·`core.hooksPath` 변경으로 hook을 우회하지 않는다.
- 확인 화면을 보지 않고 승인하지 않는다. +1(작성자 외) 없이 병합하지 않는다. Claude에게 Approve를 시키지 않는다.
- 마스킹 안 된 로그(IMSI·전화번호·ICCID 등)를 대화·이슈 DB·Jira에 넣지 않는다.
- Jira는 읽기와 승인한 코멘트만. 필드·상태를 바꾸게 하지 않는다.
- README·STATS·CHANGELOG(생성 파일)를 손으로 고치지 않는다.
- 인증 실패·충돌·버전 불일치는 우회하지 않고 보고한다.

## 7. 자주 묻는 것·문제 해결

### 점검표(doctor) 행

| 행 | 뜻 | `warn`·`fail`일 때 |
|---|---|---|
| `python`·`deps` | Python 3.10+, 패키지 | 1.1을 `claude`를 띄우는 Python으로 |
| `config`·`platform`·`scripts_path` | 사용자 설정, 플랫폼, 플러그인 경로 | 없으면 setup |
| `clone` | 이슈 DB clone | 안내된 `git clone`을 터미널에서 |
| `hook` | `core.hooksPath=.githooks` | `config.py install-hooks` |
| `guard` | 안전 hook 자가시험 | 도입 담당자에게(`hook python3≠doctor python`이면 다른 Python) |
| `tracker`·`tracker_post` | Jira 도구 짝 | setup의 Jira 단계만 다시 |
| `gh` | GHE 인증 | `gh auth login -h <GHE 호스트>` |
| `snapshot` | 스냅샷 나이 | `/telephony-triage:sync` |
| `retention`(site-defaults `retention_days`를 둔 팀만) | 마지막 활동(안의 파일 갱신) 뒤 보존 기간 넘은 작업 폴더 수 — `cleanup --older-than`과 같은 기준 | `db_pr.py cleanup --older-than <일> --dry-run` 확인 뒤 `--yes` |
| `compat` | 이슈 DB 스키마 호환 | 플러그인 업데이트 |
| `lock` | 세션 잠금 | 그 세션이 끝난 뒤에만 해제 |
| `module_skills` | 모듈 스킬·설치 스킬 설정 | 팀 기본 값 문제면 도입 담당자 |
| `opencode_env`·`jira_gate`(OpenCode만) | 설정을 덮는 환경 변수, Jira 관문 | 변수를 지우고 다시 / 4절 |

### 그 밖의 증상

| 보이는 것 | 할 일 |
|---|---|
| "…사이트 설정(site-defaults.yaml)을 아직 올리지 않았습니다" | 도입 담당자에게(그 전에는 help만) |
| setup이 Jira MCP 단계에서 멈춤 | Jira MCP를 사용자 범위로 등록한 뒤 다시 |
| `모듈 스킬 받기 실패(관리 clone 사용 중)` | 잠시 뒤 다시(잠금 파일을 지우지 않는다) |
| 받기 실패(`인증`·`네트워크`·`원격 브랜치 없음`) | 확인 뒤 다시 |
| 받기 실패(`관리 clone 불일치`·`ff-only 실패`·`점검(…)`) | 화면 그대로 도입 담당자에게 |
| `설치 스킬 못 찾음` | `skill_dir` 지정(2절 5번). OpenCode는 그 뒤 `install --force` |
| `read-roots` warn·`integrity` fail | 설정·플러그인이 바뀜. `install ... --force` |
| `opencode-version` fail | OpenCode를 1.19.5로(우회 말고 보고) |
| `instructions` fail | 지시 파일을 치우거나 `--dest`를 옮긴다 |
| `config-doctor` fail | 2절 2번의 `config.py doctor`로 원인(config 없으면 setup) |
| `gateway-key`·`gateway-url` warn | 키 환경 변수(`TT_GATEWAY_API_KEY` 등)를 export했는지, 주소가 `…/v1`인지. 모르면 도입 담당자에게 |
| `outcome: no-script-output`·`no-response` | 게이트웨이 문제일 수 있다 — 화면 그대로 도입 담당자에게 |
| "병합해줘"가 거절됨 | 사유대로. 보통 최신 커밋 +1이 필요 |

막히면 `/telephony-triage:status --doctor`(OpenCode는 `tt-oc doctor`) 화면을 고치지 말고 그대로 도입 담당자에게 보낸다.

### 누구에게 보내나 (2선 지원)

| 순서 | 누구 | 무엇을 |
|---|---|---|
| 1선 | 도입 담당자 | doctor 화면, 막힌 명령·사유 한 줄 |
| 2선 | 이슈 DB 메인테이너(`CODEOWNERS`의 메인테이너 경로 오너 — 도입 담당자가 자리에 없을 때) | 같은 것. 시그니처·파서 규칙·DB 스키마 문제는 처음부터 이쪽 |
| 접수 | 팀이 정한 한 곳(권장: 이슈 DB 레포 Issue, 제목 `[support] <doctor 행 이름>`) | 메일·채팅으로 흩어지지 않게. 해결 뒤 같은 Issue에 원인·조치 한 줄(다음 사람의 답이 된다) |

도입 담당자·메인테이너가 같은 사람이면 대리인을 한 명 정해 `SITE_PROFILE.md`에 적어 둔다(작성자 부재 시 열린 PR 인수는 `docs/design/06-collaboration.md §6.3`).

## 8. 플러그인을 갱신할 때

1. Claude Code 마켓플레이스에서 `telephony-triage`를 업데이트한다.
2. OpenCode면 레포 사본도 같은 태그로(`git fetch --depth 1 origin tag <새 태그> && git checkout <새 태그>`) 바꾸고 1.4의 install을 같은 인자 + `--force`로(Jira를 열었으면 4절 4도). 이번 묶음 반입 뒤에도 한 번.
3. OpenCode Jira를 열어 두었으면 4절의 확인과 `config.py set … open`을 다시 한다(통과 기록이 플러그인 지문과 트래커/MCP 설정 지문에 묶인다 — Jira 도구 매핑·MCP 서버 이름을 바꿨을 때도 같다).
4. 사내 모델 `env`(1.3)는 그대로. 점검표를 다시 본다.

근거: `SITE_INSTALL.md` 7절, `RUNTIMES.md`, `opencode/README.md`, `plugin/commands/`.
