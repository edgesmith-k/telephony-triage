# 15. 사외 초안 → 사내 보완

사내 Claude Code 토큰이 적으므로, **구현의 대부분은 사외 PC의 Claude Code에서 모의(mock) 환경으로 만들고**, 사내에서는 사내 환경에 맞추는 일만 한다.

## 15.1 원칙

- 사외 초안은 **사내 정보 없이** 만든다. 사내 서버 이름, 도구 이름, 로그 원문, 소스, 빌드명은 쓰지 않는다. 필요한 곳은 모의 값과 `TODO(SITE:S<n>)` 표시로 둔다 (`S<n>`은 `14-site.md §14.2` 레지스트리 번호).
- 사내 값과 사내 코드는 **`SITE_PATHS`(15.6)에 있는 경로에만** 둔다. 코드의 기본값은 모두 `plugin/site-defaults.yaml`에서 읽고, 사외 초안에는 `plugin/site-defaults.example.yaml`(모의 값)만 둔다. 사내 S-3에서 `site-defaults.yaml`을 만들어 커밋하면 팀원이 설치하는 플러그인에 같이 들어간다. 그래서 사외에서 코드를 다시 고쳐 반입해도 **사내 값이 덮어써지지 않는다.**
  - 사내 값이 들어가는 곳: `SITE_PATHS` 경로(`site-defaults.yaml`, 포팅한 파서 백엔드, 사내 어댑터, 골든, `SITE_PROFILE.md`), 사용자 config, 이슈 DB 레포(`issue-db.config.yaml`, `parser-rules/`, fixture). 모두 사내에만 있다.
  - **설정 우선순위**: 사용자 config > `plugin/site-defaults.yaml` > 코드 내장 기본값. **런타임 코드는 "사내/사외 모드"를 판별하지 않는다** (설치된 플러그인 캐시 경로 옆에는 `SITE_PROFILE.md`도 `.local-draft`도 없으므로 판별할 방법이 없다). `plugin/site-defaults.yaml`이 없으면 setup과 모든 커맨드·스크립트가 "사내 기본값 없음(S-3 미완료)"으로 멈춘다(종료 코드 2). `site-defaults.example.yaml`은 코드가 절대 읽지 않는다.
  - **사외 테스트·eval**은 테스트 헬퍼 `tests/helpers/make_plugin_root.py`가 `plugin/`을 임시 디렉토리에 복사하고 example을 `site-defaults.yaml`로 넣은 **임시 플러그인 루트**를 만들어 `${CLAUDE_PLUGIN_ROOT}`로 준다. 개발 레포의 `plugin/` 안에는 `site-defaults.yaml`을 만들지 않는다(반입 체크리스트 15.4). "사외 초안 모드/사내 모드"라는 말은 개발 세션의 모드 판별(`CLAUDE.md` 머리말)에만 쓴다.
- 코드를 사내로 가져가기 전에 **사내 반입 규정**(외부 작성 코드 반입 절차, 오픈소스 의존성 승인)을 사용자가 확인한다.
- 사외 초안의 판단과 가정은 `DRAFT_NOTES.md`에 기록한다 (사내 Claude Code가 전체 설계 문서를 다시 읽지 않고도 초안 상태를 파악하게).

## 15.2 모의 환경 (Phase D0에서 만든다)

모두 플러그인 개발 레포의 `tests/mocks/` 아래에 두고 **배포(`plugin/`)에 넣지 않는다.**

| 모의 대상 | 만드는 것 | 대체하는 사내 요소 |
|---|---|---|
| Jira MCP | `tests/mocks/jira_mcp/server.py`: 로컬 MCP 서버(stdio), 서버 이름 **`mock-jira`**. 도구 이름은 일부러 **비표준**으로 둔다: 읽기 `jira_fetch_ticket`, `jira_query_tickets`, `jira_ticket_comments`, **쓰기** `jira_post_comment`, `jira_move_ticket`(guard 차단 테스트용). `jira.tools` 매핑을 반드시 거치게 하기 위해서다 (`16-existing-assets.md §16.1`). 데이터는 `tests/mocks/jira/*.yaml`. 커스텀 필드 이름은 일부러 사내와 다를 법한 이름(`customfield_10001` 등)으로 두어 `jira.field_map`을 반드시 거치게 한다. 등록은 레포 루트 `.mcp.json`이 아니라 **`tests/mocks/mcp.json`** 에 두고, 사외 초안 세션만 이 설정을 불러온다(`--mcp-config` 등 불러오는 방법은 사외 Claude Code 버전에서 확인해 `DRAFT_NOTES.md`에 기록). 사내에서 가짜 Jira가 진짜로 잡히지 않게 하기 위해서다. setup은 이름이 `mock-`로 시작하는 서버를 사내 모드에서 후보에서 제외한다 | S3, S4 |
| GitHub Enterprise | 원격: 로컬 bare 레포 `tests/mocks/remote/telephony-issue-db.git`를 이슈 DB의 `origin`으로 쓴다. `gh`: `tests/mocks/bin/gh` 스텁(`auth status`, `pr create/list/edit/view`, `--search`)이 상태를 `tests/mocks/gh-state/*.json`에 저장. 테스트 시 `PATH` 앞에 `tests/mocks/bin`을 둔다. `db_pr`은 PATH의 `gh`를 쓰므로 코드 변경 없음 | S5, S6 |
| logcat | `tests/mocks/logcat_gen.py`: 시나리오(yaml)로 threadtime 형식 로그 생성. 데이터 스택 태그는 확정 형식(`DNC-<n>`, `DN-…`, `DPM-<n>`, `DRM-<n>`), 나머지 태그와 문구는 placeholder. 시나리오 항목마다 **슬롯**(`phone: 0|1`, 태그 접미사·메시지 접두어에 반영)과 **시계 이상**(`clock_jump_sec`)을 지정할 수 있고, `--bugreport`로 합성 bugreport(txt/zip: 헤더 fingerprint + logcat 섹션 + 가짜 dumpsys 섹션)로 감쌀 수 있다. 생성한 fixture의 `.expect.yaml`에 `origin: synthetic`을 적는다 | S7~S9, S20, S21 |
| 소스 트리 | `tests/mocks/src/android16/`, `android17/`: `frameworks/opt/telephony` 등 최소 디렉토리와 심볼만 있는 스텁 파일. 한 파일은 16과 17에서 경로가 다르게 두어 `find-symbol`을 시험. 버전 정의 파일도 스텁 | S10, S11 |
| 빌드명 | `tests/mocks/builds.yaml`: 가상 빌드명 체계와 `build_compare` 예시 | S12 |
| 사내 Claude Code 기능 | 사외 Claude Code에서 플러그인 로드, hooks, `${CLAUDE_PLUGIN_ROOT}`, MCP 도구 이름 형식, **`CLAUDE.md`의 `@SITE_PROFILE.md` import가 파일이 없을 때 오류·경고를 내는지**를 실험하고 결과를 `DRAFT_NOTES.md`에 기록 (사내 버전과 다를 수 있으므로 사내에서 S1로 재확인). 사외에서는 `SITE_PROFILE.md`가 없어도 머리말 규칙 3(`.local-draft`)으로 판별하므로 경고가 나도 동작에는 문제가 없다 | S1 |
| 플러그인 루트 | `tests/helpers/make_plugin_root.py`: `plugin/`을 임시 디렉토리에 복사하고 `site-defaults.example.yaml`을 `site-defaults.yaml`로 넣는다. 모든 테스트·eval은 이 루트를 `${CLAUDE_PLUGIN_ROOT}`로 쓴다 (15.1) | S-3 |
| OS | **Ubuntu(Linux)** 기준으로만 만들고 시험한다. 셸 스크립트(`.githooks/pre-commit`)·PATH 스텁·홈 경로·실행 비트 모두 POSIX 가정. 다른 OS는 v1 범위 밖 | S15 |

- **모드 표식 `.local-draft`**: 사외 PC의 플러그인 레포 루트에 두는 빈 파일. `.gitignore`에 등록하고 반입 묶음에 넣지 않는다. 이 파일이 있으면 매 세션 모드를 묻지 않고 사외 초안으로 판별한다 (`CLAUDE.md` 머리말).
- **합성 샘플은 플러그인 레포 테스트 데이터로만 쓴다** (`tests/fixtures/issue-db-sample/`). 운영 이슈 DB에는 들어가지 않는다. 반입하는 이슈 DB는 `tools/make_db_skeleton.py`로 만든 뼈대다 (`11-phases.md` Phase 1).
- `db_lint`는 `site-defaults.yaml`의 `synthetic_allowed`가 `false`(기본값, 사내 S-3에서 만든 파일)이면 `origin: synthetic` fixture가 이슈 DB에 있을 때 경고한다 (운영 레포에 합성 fixture가 섞이지 않았는지 확인). `site-defaults.example.yaml`(테스트 헬퍼 복사본)은 `synthetic_allowed: true`다.

## 15.3 사외에서 진행하는 Phase

| Phase | 사외 진행 | 비고 |
|---|---|---|
| **D0** 모의 환경 | ✅ | 15.2 전부 + `16-existing-assets.md §16.6` 사외분(모의 site 백엔드, 골든 테스트 틀, 모의 분석 스킬) + `SITE_PATHS`·`tools/import_draft.py`·반입 기준선(15.6) + `.local-draft` + 테스트 헬퍼 플러그인 루트. 완료 기준은 `11-phases.md` Phase D0. **사내 처음부터 모드도 Phase 0 뒤에 D0를 한다**(테스트에 모의 환경이 필요한 것은 모드와 무관) |
| 0 사내 환경 확인 | ❌ 건너뜀 | 사내에서 S-1로 수행. 대신 `DRAFT_NOTES.md`를 만든다 |
| 1 이슈 DB 뼈대 | ✅ 합성 샘플 | 합성 샘플 6개 유형은 `tests/fixtures/issue-db-sample/`(fixture 합성). 운영용 뼈대는 `tools/make_db_skeleton.py`. `parser-rules`는 placeholder(`reason: placeholder`) |
| 2~5 | ✅ | 합성 fixture로 테스트. **Phase 2는 파서 백엔드 인터페이스 + reference 백엔드(공통 처리는 제품 수준, builtin 판별 없음)** 를 만든다 (data 판별은 사내에서 검증된 기존 파서로 포팅, `16-existing-assets.md §16.3`). Phase 3이 끝나면 사내 **S-0(선택)** 을 할 수 있다 (§15.5) |
| 6 설정·setup | ✅ 모의 값 | 기본값은 `site-defaults.example.yaml`. 트리 버전 추정은 모의 소스 트리 기준 |
| 7 반영·PR·sync-pr | ✅ | 모의 원격 + `gh` 스텁 |
| 8 hooks | ✅ | 사외 Claude Code 기준. 사내 재확인 필요 항목은 `DRAFT_NOTES.md`에 |
| 9~12 | ✅ | |
| 13 SKILL.md·eval | ✅ 모의 | eval은 모의 Jira + 합성 로그로 통과시킨다. 실제 로그 eval은 사내 S-5 |
| 14 배포·파일럿 | ❌ | 사내 |

- 각 Phase의 "읽을 문서"와 완료 기준은 그대로 따른다. `SITE_PROFILE.md` 대신 `DRAFT_NOTES.md`의 "진행 상태"를 갱신한다.
- 사외 초안 세션은 `SITE_PROFILE.md`가 없어도 Phase 0으로 가지 않는다 (CLAUDE.md 머리말의 모드 판별).

## 15.4 사내 반입 전 체크리스트

- [ ] 전체 테스트 통과 (`pytest`, `db_regress --all`, eval 45개 모의 실행, `tools/offline_eval.py` 합성 라벨셋 실행 — 모두 테스트 헬퍼 플러그인 루트에서)
- [ ] 사내 정보 없음 (애초에 없지만, 실제 회사명·서버명 등을 쓰지 않았는지 검색)
- [ ] `plugin/site-defaults.yaml`이 없고 `site-defaults.example.yaml`만 있음. `SITE_PATHS`의 다른 경로(`.draft-manifest.json` 포함)도 비어 있음
- [ ] 레포 루트에 `.mcp.json`이 없음 (모의 MCP는 `tests/mocks/mcp.json`). `.local-draft`는 반입 묶음에 넣지 않음
- [ ] `tools/make_db_skeleton.py`로 이슈 DB 뼈대를 만들었고, 뼈대에 유형·Jira·fixture(합성 포함)가 없음
- [ ] `tools/list_site_todos.py`로 `TODO(SITE:S<n>)` 목록을 `DRAFT_NOTES.md`에 갱신 (S번호별로 묶어서)
- [ ] `DRAFT_NOTES.md`: 진행 상태, 가정, 사외 Claude Code 실험 결과, 모의와 실제가 다를 것으로 예상되는 지점
- [ ] 플러그인 레포 전체(코드, 테스트, 모의, 합성 샘플, 문서)와 이슈 DB 뼈대를 묶어서 반입

## 15.5 사내 보완 (Phase S) — 토큰 최소화

사내에서는 **Phase 1~13을 다시 하지 않는다.** 아래 순서(S-1~S-7)로 사내 환경에 맞추는 일만 한다. 각 단계는 별도 세션으로 하고, 끝날 때마다 `SITE_PROFILE.md`의 진행 상태를 갱신해서 다음 세션이 이어서 하게 한다.

| 단계 | 할 일 | 읽을 것 (이것만) |
|---|---|---|
| S-0 (선택) | **선행 확인** — 사외 Phase 3(파서·매처)이 끝난 뒤 반입 전에 언제든. 사외 초안의 `parse_logcat.py`(reference 백엔드)와 `match_signatures.py`만 사내로 가져가 **Claude 없이 Python으로** 실제 로그 3~5개(카테고리 섞어서, 듀얼 SIM 포함)에 돌린다. 태그별 빈도, RIL 페어링 성공률, 시각 파싱 실패율, `coverage` 판정(범위 밖·시계 이상 비율), `phone_id` 추출률을 `SITE_PROFILE.md`에만 기록한다. 사외로는 **정성 결론만** 가져간다("페어링 방식 재검토 필요", "슬롯 표기가 문서와 다름" 등). 숫자·로그 반출은 사내 반출 규정을 사용자가 확인한다. 목적: 시그니처 매칭이 실제 logcat에서 통하는지를 S-4까지 기다리지 않고 확인해서, 모델이 안 맞을 때 되돌리는 비용을 줄이는 것 | `04-parser-matching.md §5.8`, `contracts.md §3.2`(`parse_logcat`) |
| S-1 | Phase 0 축약판: `DRAFT_NOTES.md`의 TODO 목록과 `REVIEW-OPEN.md`(사내 정보가 있어야 판단할 수 있는 항목)를 기준으로 확인 목록을 만들고, 사용자에게 샘플(Jira 키 2~3개, 카테고리별 logcat, 16/17 소스 경로, 빌드명)을 받아 `SITE_PROFILE.md` 작성. `REVIEW-OPEN.md` 항목은 처리 방식을 정하거나 사유와 함께 보류로 기록 | `CLAUDE.md`, `DRAFT_NOTES.md`, `REVIEW-OPEN.md`, `14-site.md §14.2·14.3` |
| S-2 | 사내 Claude Code 기능 확인(S1): 플러그인 로드, hooks, `${CLAUDE_PLUGIN_ROOT}`, MCP 도구 이름 형식, `@SITE_PROFILE.md` import. `DRAFT_NOTES.md`의 사외 실험 결과와 다른 것만 고친다 | `DRAFT_NOTES.md` 해당 절, 실패한 코드 파일 |
| S-3 | 사내 값 반영: `plugin/site-defaults.yaml` 작성(Jira 서버·**`jira.tools` 매핑**·read_tools·field_map·timezone, GHE 호스트, reviewers 형식), 이슈 DB `issue-db.config.yaml`(jira_key_regex, build_compare, allow_patterns 등) | `SITE_PROFILE.md`, `site-defaults.example.yaml`, `02-config.md` |
| S-4a | **기존 data 자산 연결** (`16-existing-assets.md §16.6`): 검증된 기존 파서를 파서 백엔드로 포팅(포팅 전 골든 저장 → 골든 테스트 통과), 기존 분류 `import` PR, 분석 스킬 `analyzers.data` 연결. 이후 S-4에서 data는 가져온 규칙을 실제 fixture로 검증만 한다 | `16-existing-assets.md`, 기존 자산 |
| S-4 | 실제 로그 반영 (카테고리별 세션 분리 권장): 운영 이슈 DB(뼈대)의 `parser-rules` placeholder를 실제 태그·문구로 바꾸는 PR. 합성 샘플 유형(`tests/fixtures/issue-db-sample/`의 정의) 중 실제로 쓸 것은 시그니처를 실제 문구로 고치고 **실제 마스킹 fixture 1개 이상**을 붙여 `source: import` 계획으로 운영 레포에 넣는다(`db_regress --all`·`db_verify rules` 통과까지 조정). 실제 로그 기반 추가 테스트는 `tests/site/`(SITE_PATHS)에 둔다. **완료 기준에 카테고리 시드 포함**: data 외 5개 카테고리마다 자주 나오는 유형 5~10개를 실제 마스킹 fixture와 함께 `source: import` 계획으로 넣는다(data는 S-4a의 기존 분류 import로 대신). 빈 DB로 파일럿을 시작하면 처리 건마다 새 유형 작성(시그니처·규칙·fixture·R1~R5)이 되어 기여자가 중도에 포기하기 쉽다 | `04-parser-matching.md`, `16-existing-assets.md §16.4`, 테스트 출력 |
| S-5 | 스모크 테스트: 실제 Jira + 로그로 `analyze --dry-run`, `record --dry-run`, 사내 샌드박스 이슈 DB에 실제 PR 1건. **오프라인 재현 평가(게이트)**: 이미 해결된 과거 Jira 20~30건(카테고리별 3건 이상)을 라벨셋 `tests/site/offline-eval.yaml`(Jira 키, 로그 경로, 정답 원인 ID 또는 `unresolved`)로 만들고 `tools/offline_eval.py`로 1위 정확도, 상위 3 포함률, 오탐률(정답이 unresolved인데 후보를 낸 비율)을 잰다. 기준(예: 1위 정확도 60%)은 S-1에서 사용자와 정하고, 미달이면 파일럿 전에 시그니처·규칙을 조정한다. 사람을 투입하기 전에 매칭 모델이 실제로 통하는지 확인하는 단계다 | 실패 시 해당 `07-workflow.md` 절만 |
| S-6 | 남은 `REVIEW-OPEN.md` 항목 정리(처리 또는 보류 사유 기록). 운영 이슈 DB 확인: 합성 fixture(`origin: synthetic`) 0건, placeholder 규칙(`reason: placeholder`) 목록 보고 | `REVIEW-OPEN.md` |
| S-7 | **배포와 파일럿** (= `11-phases.md` Phase 14. 사내 보완 모드는 여기서 한다): `marketplace.json`으로 사내 마켓플레이스 등록(S2), 이슈 DB README에 설치/시작 가이드 링크. 파일럿: 카테고리별 오너가 실제 이슈 10~20건씩 처리, 첫 월간 리뷰. placeholder 규칙 확정, 시그니처 오탐/누락, 충돌(drift·ID 중복·`also_allowed` 빈도), 온보딩 시간, **PR까지 걸린 시간**(analyze 시작 → PR 생성, `state.json`·`plan.json`의 시각)과 **중도 취소 비율**(`discard`로 끝난 작업 / 시작한 작업 — 기여 부담의 지표), 분석 스킬 호출 비율과 토큰을 점검한 뒤 전체 확대. **완료 기준**: 파일럿 결과(처리 건수, 오탐/누락, 충돌, 온보딩 시간, PR 소요 시간, 취소 비율)를 보고하고 전체 확대 여부를 결정받는다 | `14-site.md` S2, `06-collaboration.md §6.6·6.9`, `01-architecture.md §3` |

**사내 토큰 절약 규칙** (사내 Claude Code가 지킬 것)
- 설계 문서를 통째로 읽지 않는다. 단계별 "읽을 것"만 읽고, 막힐 때 해당 절만 추가로 읽는다.
- 파일을 읽기 전에 스크립트·테스트를 먼저 돌리고, **실패한 부분만** 본다.
- 큰 로그는 읽지 않고 `parse_logcat cut`·`grep`으로 필요한 구간만 뽑는다.
- 수정은 좁은 범위로 하고, 전체 파일 재작성을 피한다.
- 단계가 끝나면 세션을 닫고, 다음 단계는 `SITE_PROFILE.md` 진행 상태에서 새로 시작한다 (긴 대화 누적 방지).

## 15.6 사외 ↔ 사내 반복

**사내 전용 경로 (`SITE_PATHS`)** — 사외 레포에는 없고 사내에서만 만드는 파일. 레포 루트의 `SITE_PATHS` 파일에 목록으로 둔다(사외 초안에도 이 목록 파일은 있다):

```
SITE_PROFILE.md
.draft-manifest.json
docs/site/
plugin/site-defaults.yaml
plugin/scripts/parser_backends/site/
plugin/scripts/adapters/site_*
tests/golden/
tests/site/
```

- `.local-draft`(사외 PC 전용 표식)는 반입 묶음에 없고, `import_draft.py`는 원본에 있어도 가져오지 않는다.

- 사내 코드는 위 경로에만 둔다. 사외 레포의 파일(예: `parse_logcat.py`)을 사내에서 직접 고쳐야 했다면 그 변경은 **사외로 옮길 요약**을 만들어 다음 사외 버전에 반영하고, 사내 사본은 임시로 취급한다.
- **재반입 절차** (통째로 교체 금지). 사내 플러그인 레포는 git으로 관리한다.
  1. `git switch -c draft-import/<날짜>`
  2. `tools/import_draft.py <새 사외 초안 경로>`: 반입 기준선 `.draft-manifest.json`(마지막으로 반입한 사외 초안의 버전 표시와 파일 경로·해시 목록)과 비교해서 처리한다.
     - `SITE_PATHS`에 있는 경로는 건드리지 않는다.
     - 기준선 이후 사내에서 고친 사외 파일(현재 해시 ≠ 기준선 해시)이 있으면 목록을 보여주고 **멈춘다** (사외 요약으로 옮기거나 되돌린 뒤 다시 실행).
     - 새 초안에 있는 파일은 덮어쓴다. 기준선에 있었는데 새 초안에 없는 파일은 사외에서 지운 것이므로 지운다.
     - 기준선에도 새 초안에도 없는 파일(사내에서 새로 만든 비-`SITE_PATHS` 파일)은 **지우지 않고** 목록으로 보고한다. 사내 전용이면 `SITE_PATHS`로 옮기라고 안내한다.
     - 끝나면 새 초안 기준으로 `.draft-manifest.json`을 다시 쓴다. 첫 반입이면 기준선 없이 전체를 복사하고 기준선을 만든다.
  3. `pytest`(골든 포함), `db_regress --all` 통과 확인 → main에 병합.
  4. 사외에서 설계가 바뀐 부분은 `14-site.md §14.5`대로 영향을 확인한다.
- `tools/import_draft.py`와 `SITE_PATHS`는 사외 초안(Phase D0)에서 만든다. `.gitignore`가 아니라 **목록 파일**로 관리한다(사내에서는 이 경로들을 커밋해야 하므로). `.draft-manifest.json`은 사내에서 `import_draft.py`가 쓰고 커밋한다.
- 사내에서 발견한 설계 문제는 사내 정보를 뺀 문장으로 요약해서 사외 문서(이 문서 세트)에 반영한다.
