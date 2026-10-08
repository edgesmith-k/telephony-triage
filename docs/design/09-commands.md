# 09. 커맨드 목록

> 원본 10장. 파일 위치는 `01-architecture.md §3`의 `commands/`와 같은 목록이다 (13개).

---

## 10. 커맨드 목록

| 커맨드 | 하는 일 | 흐름 |
|---|---|---|
| `help [커맨드]` | 커맨드 목록(각 커맨드 파일 frontmatter의 `description`·`argument-hint`)과 상황별 추천. 커맨드 이름을 주면 그 파일과 그 파일이 가리키는 스킬·reference의 해당 절에서 형식·옵션·예시를 보인다. 읽기 전용, 스크립트·lock·이슈 DB·Jira 없음 | §10.1 |
| `setup` | 설정 생성, clone, 버전·gh·Jira MCP 확인, git hook 설치, 읽기 스냅샷 생성, 끝에 `config.py doctor` 점검 표 | `02-config.md §4` |
| `analyze <JIRA-KEY> [logcat...] [--code <프로필\|경로>] [--dry-run \| --analysis-only] [--jira-file <yaml>] [--more-logs <logcat...>] [--failed-step <한 줄>] [--steps-file <파일>] [--clock-offset <±시간>] [--analyzer \| --no-analyzer] [--explore \| --no-explore]` | 분석 → 분류 → PR. `--failed-step`·`--steps-file`은 선택 보조 정보(없어도 묻지 않음, 점수·분류에 쓰지 않음)다. `--steps-file`은 txt/csv·html(`report.html`)·zip이고, 스텝 목록을 붙여넣으면 `WD/<KEY>/steps-pasted.txt`에 써서 넘긴다. 스텝 순서로 분석 구간을 정하고(시계 불필요), `--clock-offset <±시간>`(단말 = 장비 + 값)을 주면 steps-file의 시각도 쓴다(`07-workflow.md §Step 3`). logcat 자리에 bugreport(`.zip`/txt)를 주면 logcat 섹션만 추출해서 쓴다(`07-workflow.md §Step 3`). `--code`가 없으면 Step 2-1에서 묻는다. `--jira-file`은 `--dry-run` 또는 `--analysis-only`와 함께만. `--more-logs`는 이전 분석의 로그 뒤에 로그를 더해 다시 분석한다(순서 유지·내용 중복은 건너뜀·합친 로그 전체를 다시 계산, 이전 결과는 `runs/<n>/`에 보관; 이전 로그가 없으면 오류, `07-workflow.md §추가 로그 재분석`). `--analysis-only`는 이슈 DB에 기록하지 않는 분석 전용이다(`--dry-run`과 함께 못 씀): cleanup·기존 계획·열린 PR 확인을 건너뛰고 Step 6 리포트로 끝나며 lock을 푼다(`07-workflow.md §분석 전용`). 카테고리 분석 스킬(Step 5-1)은 기본적으로 호출 여부를 묻고, `--analyzer`면 묻지 않고 호출, `--no-analyzer`면 호출하지 않는다. 후보 없음·원인 미확인이면 탐색 분석(Step 5-2, Claude 가설)을 `explore.when`(기본 묻기)에 따라 하고, `--explore`면 묻지 않고, `--no-explore`면 하지 않는다 | `07-workflow.md §analyze` |
| `record <JIRA-KEY> [--cause <원인 ID> \| --new-cause <유형 ID> \| --new-type <category> \| --unresolved <유형 ID>] [--fixture <logcat>] [--resolved-fixture <logcat>] [--dry-run] [--jira-file <yaml>] [--failed-step <한 줄>] [--steps-file <파일>]` | 수동 기록: 스스로 해결한 이슈를 분석·매칭 없이 히스토리에 남긴다. 옵션이 없으면 유사 유형을 보여주고 대화형으로 묻는다. 쓰기 경로와 검증은 analyze Step 8과 같다. `fixed`는 기록할 수 없다(`fix-submitted`까지) | `07-workflow.md §record`, `05-verification.md §5.12 (1)` 수동 기록 검증 |
| `sync` | Step 1만 수행 (세션 lock → `db_pr snapshot`(base 변경 한 줄), 사후 lint → lock 해제). 이어 `db_pr cleanup --dry-run --older-than`으로 닫힌 PR의 오래된 작업 디렉토리를 보여주고 확인 후 지운다. 마지막에 `db_pr my-prs`(읽기 전용)로 내 열린 PR과 base 이동 여부를 한 줄씩 보이고 `sync-pr`은 안내만 한다 (`contracts.md §3.2`) | `07-workflow.md §Step 1` |
| `search <증상 문장\|keyword\|JIRA-KEY\|ID>` | `db_search.py`로 이슈 DB 검색 (secondary/related, 옛 ID → 새 ID 연결 포함). 증상 문장("데이터 안 붙어, 이슈 번호 알려줘")은 단어별·별칭으로 찾는다. 유형, 원인, 해결책, 수정 상태, Jira를 보여주고 Jira 번호는 맨 위에 모아 요약한다. 스냅샷을 읽는다. 절차는 `reference/search.md` | `03-issue-db.md §5.5` |
| `sync-pr [branch]` | 머지 전 재동기화: 원래 작업 계획을 최신 main에 재적용(drift 확인, ID 재할당), 생성 파일 재생성, ID·Jira 재검사, 확인 후 SHA 지정 lease push. 인자가 없으면 작업 계획에 기록된 열린 PR에서 고른다. 계획이 없는 브랜치는 수동 절차만 안내한다 | `07-workflow.md §sync-pr`, `06-collaboration.md §6.3` |
| `preview` | `db_build.py --preview <임시 디렉토리>`로 생성 결과를 보여준다. 워킹 트리를 바꾸지 않는다 | `03-issue-db.md §5.6` |
| `review [category]` | 월간 리뷰 리포트. 인자가 없으면 오너 카테고리를 묻는다 | `06-collaboration.md §6.6` |
| `validate [--cause <원인 ID> <적용 후 logcat...>] [--extra <logcat...>]` | 인자 없으면 현재 이슈 DB 변경분에 lint·전체 회귀·R1~R5(`--extra`면 R6) 실행 (직접 편집 기여자가 push 전에 실행, 아무것도 바꾸지 않음, 스크립트 래퍼). `--cause`면 해결책 검증 → passed 시 `verify-res/<원인 ID>-<YYYYMMDD>` PR | `07-workflow.md §validate` |
| `fix-submitted <원인 ID> --ref <CL> --fixed-in <branch>[:<build>]` | 수정 CL 반영 기록 (`fix.status: fix-submitted`) → `fix-submit/<원인 ID>` PR. `--fixed-in`은 여러 번 가능, 빌드는 선택 | `07-workflow.md §fix-submitted` |
| `verify-fix <원인 ID> <수정 빌드 logcat...> [--jira <키>]` | 코드 수정 검증 → 판정 → `verify-fix/<원인 ID>-<build>` PR | `07-workflow.md §verify-fix`, `05-verification.md §5.12 (2)` |
| `migrate --to <N> [--dry-run]` | 메인테이너용. cwd가 이슈 DB clone이고 현재 브랜치가 `migrate/schema-v<N>`이며 깨끗할 때 `db_migrate --to <N>`으로 **그 브랜치의 워킹 트리를 직접 바꾼다**. 이어서 `validate` → 커밋 → push 절차를 안내한다. PR·계획·worktree·lock을 만들지 않는다(직접 편집 브랜치). CI 모드 전환(`migrate/ci-<mode>`)도 직접 편집이다 | `06-collaboration.md §6.4`, `13-actions.md` |

- 모든 커맨드는 **얇은 래퍼**다. 로직은 스킬과 스크립트에 둔다 (`help`만 예외: 스크립트 없이 본문이 플러그인 파일을 읽는 절차다, §10.1).
- 이슈 DB에 쓰는 커맨드(`analyze`, `record`, `sync-pr`, `validate --cause`, `fix-submitted`, `verify-fix`)와 `sync`(작업 키 `sync`)는 시작할 때 세션 lock을 잡고(`db_pr lock acquire`), 끝나는 모든 경로에서 푼다 (`contracts.md §3.2`). 이어서 `config.py check --db <work_dir>/_snapshot`으로 쓰기 가능 여부(스키마·생성기·파서 백엔드·외부 파서 버전, gh 인증)를 확인하고, 불가면 이유를 보여주고 멈춘다 (`analyze`는 읽기 전용으로 계속). `--dry-run`은 `--for dry-run`으로 gh 인증 없이 확인 화면까지 간다.
- `migrate`는 lock을 잡지 않고 스냅샷도 옮기지 않는다(메인테이너 자기 브랜치의 워킹 트리만 바꾼다). `migrate/schema-v<N>` 브랜치에서는 `config.py check`·pre-commit·`validate`가 버전 불일치를 차단하지 않는다 (`06-collaboration.md §6.4`).
- 읽기 전용 커맨드(`search`, `preview`, `review`, `help`, 인자 없는 `validate`)는 lock을 잡지 않는다.
- 모든 커맨드(`help` 제외: 플러그인 파일만 읽는다)는 `plugin/site-defaults.yaml`이 없으면 "사내 기본값 없음(S-3 미완료)"으로 멈춘다 (`15-local-draft.md §15.1`).
- 최신 Claude Code에서 커맨드와 스킬의 관계(커맨드가 스킬로 통합됐는지 등)와 본문의 `${CLAUDE_PLUGIN_ROOT}` 치환 여부는 구현 전에 확인한다 (S1).

### 10.1 help

- 커맨드 목록은 help 파일에 적지 않는다. 실행할 때 `${CLAUDE_PLUGIN_ROOT}/commands/*.md`의 frontmatter(`description`, `argument-hint`)를 읽어 만든다. help 파일에는 상황별 추천 표만 있고, 표의 커맨드 이름이 실제 커맨드 파일과 맞는지는 `tests/test_commands.py`가 검사한다.
- `help <커맨드>`는 그 커맨드 파일을 읽는다. 본문이 스킬·reference 파일을 가리키면 그 커맨드의 사용법 절만 `offset`·`limit`로 읽는다. 없는 커맨드면 목록을 보이고 추측하지 않는다.
- 파일에 없는 옵션을 만들지 않는다. Bash·스크립트를 부르지 않고, lock·이슈 DB·config·Jira를 쓰지 않으며, `plugin/site-defaults.yaml`이 없어도 동작한다.
- **말로 요청하기 안내**: 인자 없는 help 첫 화면에, 커맨드 없이 말로 요청해도 스킬 description으로 흐름이 연결된다는 두 줄을 보인다. 말로 연결되는 흐름은 analyze, search(증상 문장 검색), record, fix-submitted, verify-fix, `validate --cause`, sync-pr이다(`SKILL.md` description에 있는 것). setup, sync, preview, review, migrate, 인자 없는 `validate`는 description에 없으므로 커맨드로 실행하라고 안내한다. 근거: `10-skill-eval.md` "description 트리거 테스트"(2026-10-05 실제 플러그인 측정 `trigger_real.py`, 24개×2회 recall 100%·precision 100% — 모의 환경 측정이므로 사내 S-2에서 재측정). 측정 문장(`tests/skill_evals/trigger_evals.json`)에는 sync-pr 1건이 있고 `validate --cause`는 없다 — 그 흐름의 연결은 description 기준이지 측정 결과가 아니다.
