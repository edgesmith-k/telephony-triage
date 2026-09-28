# 08. 마스킹과 Hooks

> 원본 8장, 9장. CLI는 `contracts.md §3.2`.

---

## 8. 개인정보 마스킹 (`mask_pii.py`)

이슈 DB에 들어가는 모든 로그 예시, fixture, 본문, 리포트에 적용한다. **extractor와 매칭 전 로그 줄에도 적용한다** (`parse_logcat.py parse --mask`, `07-workflow.md §Step 3`). 마스킹 함수는 `common/`에 있고 `mask_pii.py`와 `parse_logcat.py`가 공유한다.

| 항목 | 탐지 방법 (참고) | 치환 |
|---|---|---|
| IMSI | 키 이름 문맥(`imsi=`, `IMSI:` 등) 우선, 문맥 없는 15자리는 MCC/MNC 유효성 확인 | `<IMSI#n>` (MCC/MNC 유지 옵션) |
| IMEI | 키 이름 문맥 우선, 15자리 + Luhn 체크 | `<IMEI#n>` |
| ICCID | `89`로 시작하는 19~20자리 + 문맥 | `<ICCID#n>` |
| SUPI / SUCI | `imsi-…`, `suci-…` 형식 | `<SUPI#n>` / `<SUCI#n>` |
| TMSI / GUTI / 5G-GUTI | 키 이름 문맥 | `<TMSI#n>` / `<GUTI#n>` |
| MSISDN / 전화번호 | `+`국가번호, 국내 번호 형식, `tel:` URI | `<MSISDN#n>` |
| SIP URI / IMPU / IMPI | `sip:…@…`, `tel:…`, IMS 도메인의 사용자 부분 | 사용자 부분만 `<IMPU#n>` / `<IMPI#n>` (도메인은 유지 옵션) |
| Cell ID / TAC / CI / PCI 등 셀 식별자 | `mCi=`, `mTac=`, `cid=` 등 키 이름 문맥 | `<CELL#n>` |
| IP 주소 | IPv4/IPv6 | `<IP#n>` |
| MAC 주소 | 6옥텟 형식 | `<MAC#n>` |
| 이메일 | 이메일 형식 | `<EMAIL#n>` |
| 자격증명 성격 값 | SIP `Authorization`/`WWW-Authenticate` 헤더의 `response=`, `nonce=`, `cnonce=`; AKA `RES`/`AUTN`/`AUTS`; 키 이름 문맥 `password`, `passwd`, `secret`, `token`, `key`의 값 (IMS REGISTER 로그가 fixture에 들어가므로 필요) | `<CRED#n>` |

- **번호 토큰(가명화)**: 같은 파일(분석 1회) 안에서 **같은 원래 값은 같은 번호**, 다른 값은 다른 번호로 바꾼다(`<CELL#1>`, `<CELL#2>`). 번호는 파일 안에서 처음 나온 순서로 매긴다. 그래서 "셀이 바뀌었다", "같은 번호로 재시도했다" 같은 **값 비교 관계가 마스킹 뒤에도 보존**되고, 기존 파서의 판별 로직이 마스킹된 fixture에서도 같게 동작한다 (`16-existing-assets.md §16.3`). 원래 값과 번호의 대응표는 메모리에만 두고 저장하지 않는다.
- 시그니처와 extractor는 특정 번호(`#1`)가 아니라 토큰 종류(`<CELL#\d+>`)나 "같은 토큰/다른 토큰" 관계로만 쓴다 (`db_lint`가 특정 번호 고정을 경고).
- **문맥 기반 탐지를 우선**하고, 숫자 길이만으로 판정하는 규칙은 보수적으로 쓴다 (빌드 번호, 타임스탬프 오탐 방지).
- 오탐 예외는 `issue-db.config.yaml`의 `mask.allow_patterns`로 관리한다 (메인테이너 리뷰).
- Android 자체 마스킹(`***`, `xxxxxx`)은 그대로 둔다.
- extractor와 매처는 항상 마스킹된 텍스트에 대해 돈다. 그래서 시그니처와 extractor 패턴은 마스킹 이후 텍스트 기준으로 작성하고, 그 안의 원본 식별자 패턴은 `db_lint`가 금지한다 (`04-parser-matching.md §5.11 (1)`).
- 마스킹은 같은 입력이면 항상 같은 출력을 내고, 이미 마스킹된 입력(`<…#n>` 토큰)에 다시 적용해도 결과가 같다(멱등, 기존 토큰은 그대로 둔다). 분석과 회귀(마스킹된 fixture를 다시 파싱)의 일치를 위해서다.
- **이미 토큰이 있는 입력**(부분 마스킹된 외부 로그, 사람이 원본 값을 끼워 넣은 fixture): 먼저 입력 전체에서 종류별 기존 최대 번호를 구하고, 새 원본 값에는 그 다음 번호부터 준다. 예: `<CELL#1>`이 이미 있는 파일에 새 셀 ID가 나오면 `<CELL#2>`. 서로 다른 값이 같은 토큰이 되어 값 비교 관계가 거짓으로 바뀌는 것을 막기 위해서다.
- 파서 백엔드·외부 파서가 낸 이벤트의 `msg`와 `fields`도 extractor 전에 같은 함수(같은 번호 대응)로 마스킹한다 (`parse_logcat.py parse --mask`).
- `--check` 모드는 검출 시 종료 코드 1이다. `db_precommit`(`--staged`), `db_pr stage`(`--changed`), Claude hook이 쓴다.
- 항목별 누락/과잉 마스킹 테스트를 둔다.

### 8.1 Jira 텍스트

마스킹 표는 logcat 형식 기준이지만, Jira에서 읽은 텍스트도 리포트·계획·PR 본문에 들어가므로 같은 규칙을 적용한다. Jira 설명에는 테스터 이름, 고객 전화번호, IMEI가 자유 텍스트로 자주 적히고 **사람 이름은 위 표로 잡히지 않는다.** 그래서 마스킹에만 기대지 않고 **저장하는 정보 자체를 줄인다.**

- 이슈 DB(`jira/<KEY>.yaml`, 원인 본문, 피드백)와 PR 본문에는 Jira의 **구조화 필드**(`model`, `sw`, `android_version`, `carrier`, `occurred_on`)와 **사용자가 확인한 한 줄 요약**(`note`)만 넣는다. Jira 요약·설명·코멘트 **원문은 저장하지 않는다** (`03-issue-db.md §5.4 (2)`).
- `field_map`으로 뽑은 텍스트 필드(요약, 설명, 재현 절차, 코멘트)는 Step 2에서 읽은 직후 `mask_pii`를 거치고, 이후 단계(리포트, 키워드 보너스, `note` 초안)는 마스킹된 텍스트만 쓴다. 계획 `jira`에는 원문 필드를 두지 않는다 (`contracts.md §작업 계획`).
- `note` 초안은 스킬이 마스킹된 요약에서 한 문장으로 만들고 사용자가 확인한다. 사람 이름·고객명은 초안에 넣지 않는다.
- `db_lint`는 `jira/*.yaml`의 `note`, 원인 본문, `cp_evidence`에 대해서도 원본 식별자 패턴(표의 항목)을 검사한다.

---

## 9. Hooks (`hooks/hooks.json`)

**적용 범위**: 플러그인 hook은 플러그인이 켜진 모든 세션에 적용된다. `record`도 같은 hook(Jira 읽기 전용, 커밋·push 검사)을 거친다. 새 hook은 없다. 그래서 git 관련 hook은 모두 먼저 **대상 레포를 판별**한다. `guard.py`가 명령의 작업 디렉토리(cwd, `git -C <dir>`)에서 `git rev-parse --git-common-dir`을 구해, config의 `issue_db.path` 레포(그 worktree와 읽기 스냅샷 포함)일 때만 규칙을 적용하고, 아니면 아무것도 하지 않는다.

**매처 원칙**: `hooks.json`의 matcher는 도구 이름까지만 거른다. 명령 내용과 서버 판정은 `guard.py`가 한다.
- Bash 규칙: matcher `Bash`.
- Jira 규칙: matcher **`mcp__.*`** (모든 MCP 도구). `guard.py`가 도구 이름 `mcp__<server>__<tool>`에서 `<server>`를 config의 `jira.mcp_server`와 비교해서, **그 서버의 도구만** 판정한다. 다른 서버 도구는 그대로 통과시킨다. 서버 이름을 matcher에 직접 넣지 않는 이유는 서버 이름이 사용자 config에 있고 플러그인 hooks.json은 고정 파일이기 때문이다.
- `jira.read_tools`는 **전체 도구 이름**(`mcp__<server>__<tool>`)으로 저장하고, guard는 전체 이름으로 비교한다. 플러그인 hook에 전달되는 MCP 도구 이름 형식은 S1·S3에서 확인한다 (`14-site.md §14.2`).

**명령 판정의 한계**: `guard.py`의 명령 파싱은 **최선 노력**이다. `git -C <dir>`, `cd <dir> && git …`, `;`/`&&`/`||`로 이어진 명령, `sh -c "…"`/`bash -c "…"` 한 단계까지 풀어서 판정한다. 변수 치환, 별칭, 스크립트 파일 안의 git 호출은 판정하지 못한다. 그래서 커밋 검사의 **진짜 강제는 git pre-commit hook**이고, Claude hook은 빠른 차단과 우회 방지 역할이다. 워크플로우는 `git add`와 `git commit`을 별도 Bash 호출로 실행해서 guard가 명확하게 보게 한다 (`07-workflow.md §Step 8-6`).

| # | Hook | 이벤트 / 매처 | 동작 |
|---|---|---|---|
| 1 | scripts 경로 갱신 | SessionStart | `config.py sync-scripts-path`: config의 `plugin.scripts_path`를 `${CLAUDE_PLUGIN_ROOT}/scripts`로 갱신 |
| 2 | Jira 쓰기 차단 | PreToolUse, `mcp__.*` (guard가 `jira.mcp_server` 서버만 판정) | **`jira.read_tools`에 없는 그 서버의 도구는 모두 거부** (허용 목록 방식). 메시지: "이 플러그인은 Jira 읽기 전용" |
| 3 | PII 검사 | PreToolUse, Bash (`git commit`, 이슈 DB 레포) | staged 변경에 `mask_pii.py --check --staged`, 검출되면 차단 |
| 4 | 생성 파일 정합성 | PreToolUse, Bash (`git commit`, 이슈 DB 레포) | `ci_mode: local`/`actions`: `db_build.py --verify --staged` 실패 시 차단, `.cache/` staged면 차단. `ci_mode: actions-build`: 생성 파일이 staged면 차단 (`13-actions.md`). 현재 브랜치가 `migrate/schema-v<N>`이면 `generator_version` 불일치를 차단하지 않는다(pre-commit도 같음, `06-collaboration.md §6.4`) |
| 5 | hook 우회 차단 | PreToolUse, Bash (`git commit`, `git config`, 이슈 DB 레포) | 커밋: `--no-verify`, `-n`, `-c core.hooksPath=…`가 있으면 차단. 그리고 그 레포(worktree 포함)의 유효한 `core.hooksPath` 값(`git config --get core.hooksPath`)이 **정확히 `.githooks`가 아니면**(unset, 다른 값) 차단하고 setup 재실행을 안내한다. 설정: `core.hooksPath`를 바꾸거나 해제하는 `git config` 명령을 차단한다. 단, 값을 정확히 `.githooks`로 설정하는 명령(`git config core.hooksPath .githooks`, setup이 실행)은 허용한다 |
| 6 | main 직접 push 차단 | PreToolUse, Bash (`git push`, 이슈 DB 레포) | 대상이 base_branch면 차단. 명령의 refspec(`HEAD:refs/heads/<br>`, `<src>:<dst>`)에서 대상 ref를 읽어 판정한다 |
| 7 | push 확인 강제 | PreToolUse, Bash (`git push`, 이슈 DB 레포) | 권한 결정을 `ask`로 반환해서 승인 프롬프트가 반드시 뜨게 한다 |
| 8 | 사용자 clone 직접 편집 차단 | PreToolUse, `Write\|Edit\|MultiEdit\|NotebookEdit` | 대상 파일 경로가 config의 `issue_db.path`(사용자 clone) 안이면 **거부**. `<work_dir>` 아래(작업 worktree `wt/`·`draft/`, `_snapshot`)는 대상이 아니다. 메시지: "이슈 DB clone은 도구가 직접 고치지 않는다. 직접 편집은 사용자가 한다". Bash 규칙만으로는 Write/Edit 도구의 파일 쓰기를 볼 수 없기 때문에 둔다 (`07-workflow.md` 워킹 트리 불변 원칙) |

- Hook은 **8종**이다 (SessionStart 1 + Jira 1 + Bash 5 + 파일 도구 1).
- **로컬 장치는 모두 우회 가능하다.** Claude hook은 최선 노력 파싱이고, git hook은 `core.hooksPath`를 바꾸면 꺼진다. main 직접 push 금지와 CODEOWNERS 필수 리뷰는 **GHE 브랜치 보호로 서버에서 강제**되어야 한다 (`06-collaboration.md §6.1`). 이 전제가 없으면 `.githooks/`(main에 커밋된 스크립트가 모든 기여자 PC에서 실행됨)가 코드 실행 경로가 된다.
- git hook은 두 개다: `pre-commit`(`db_precommit.py`)과 **`pre-push`**. `pre-push`는 (a) 대상 ref가 `refs/heads/<base_branch>`면 거부하고, (b) 환경변수 `TT_PUBLISH_TOKEN`이 없거나 `<work_dir>/<작업 키>/state.json`의 `approved_hash`와 다르면 거부한다. 토큰은 `db_pr publish`가 자기 `git push` 호출에만 넣는다 (`contracts.md §3.2`). 직접 편집 기여자는 `validate` 통과 후 `TT_PUBLISH_TOKEN=manual`로 push한다(`CONTRIBUTING.md`). 목적은 도구 경로 밖의 실수 방지이지 권한 통제가 아니다.
- 3·4번은 git pre-commit hook(`db_precommit.py`)과 검사 내용이 겹친다. Claude 세션 안에서 더 빨리, 명확한 메시지로 막기 위한 이중 장치다.
- 7번은 `db_pr publish`가 내부에서 실행하는 `git push`에도 적용된다. `db_pr.py`는 Bash로 실행되므로 guard는 `python …/db_pr.py publish` 명령도 push로 보고 `ask`를 반환한다.
- **설정 없음 처리**: config가 없거나 `issue_db.path`로 레포를 판별할 수 없으면 git 규칙은 적용하지 않는다(통과). `jira.mcp_server`가 비어 있으면 Jira 규칙은 적용하지 않고 경고만 한다(setup 전 상태). config가 있는데 `jira.read_tools`가 비어 있으면 그 서버의 도구는 모두 거부한다.
- 권한 결정 필드 이름(`allow`/`deny`/`ask` 반환 형식), SessionStart hook 지원 여부, MCP 도구 이름 형식은 공식 문서(사내에서 접근 불가면 빈 플러그인 실험, S1)로 확인한다.
