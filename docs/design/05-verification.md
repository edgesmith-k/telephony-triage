# 05. 검증

> 원본 5.12. CLI는 `contracts.md §3.2`, 판정·상태 값은 `contracts.md §상태 값`, fixture 이름은 `contracts.md §fixture`.
> 모든 판정은 회귀·검증 모드(`04-parser-matching.md §5.11 (4)`)로 한다. 사용자 흐름(worktree, 확인 화면, PR)은 `07-workflow.md`.

---

### 5.12 검증

검증은 두 종류다.

| 검증 | 언제 | 무엇을 확인 | 수단 |
|---|---|---|---|
| (1) 규칙·해결책 검증 | 새 유형/원인 추가, 시그니처·파서 규칙·해결책 변경 | 새 규칙이 의도한 로그를 잡는지, 기존 분류를 깨지 않는지, 해결책이 실제로 효과가 있는지 | analyze Step 7·8에서 자동 (`db_verify.py rules`), 직접 편집 시 `/telephony-triage:validate`, 해결책은 `validate --cause` |
| (2) 코드 수정 검증 | 원인에 대한 코드/설정 수정이 반영된 뒤 | 수정 빌드에서 이슈가 재발하지 않는지 | `/telephony-triage:verify-fix` |

#### (1) 규칙·해결책 변경 검증

대상 변경: 새 유형/원인, `symptom_signatures`·`signatures`·`recovery_signatures`·`scenario_signatures` 변경, `parser-rules/` 변경, `resolution` 변경.

**자동 검증** (`db_verify.py rules`) — 실행 시점:

| 시점 | 호출 | 대상 트리 |
|---|---|---|
| analyze Step 7 (초안) | `db_verify rules --plan <plan> --draft <work_dir>/<KEY>/draft` | origin/<base>에 계획을 적용한 임시 worktree. 검사 후 버린다 (Step 8 worktree와 별개) |
| analyze Step 8-4 (적용 후) | `db_pr stage`가 `db_verify rules --plan <plan> --db <wt>` 호출 (R6 포함) | Step 8 worktree |
| `record` (수동 기록) | 초안 `--draft`, 적용 후 `db_pr stage`. 아래 "수동 기록 검증" 표 | analyze와 같음 |
| `validate` (직접 편집) | `db_verify rules --changed origin/<base>` (merge-base 기준) | 사용자 clone (`--db`를 cwd 기준으로 정함) |
| git pre-commit | `db_verify rules --staged` | index |
| CI (Actions 모드) | `db_verify rules --changed origin/main` | PR checkout (`13-actions.md §13.2`) |

**검사 대상 계산** (R1·R2): 변경된 시그니처 + **변경된 extractor/태그/RIL 항목을 참조하는 시그니처**(의존 그래프). 의존 그래프는 시그니처의 `must_event` → extractor `event`, extractor `tag`/`tag_regex` → tags 항목, `must_match`의 RIL 요청 이름 → ril 항목으로 잇는다. 대상 원인 = 그 시그니처들이 속한 원인(유형 시그니처면 그 유형의 모든 원인). `signatures_pending` 원인은 판별 시그니처가 없으므로 R1·R2·R3 대상이 아니다(`skipped: 시그니처 없음(pending)`). 그 원인의 양성 fixture는 R4(회귀)에 `"<유형 ID>:unresolved"` 기대값으로 포함된다 (`contracts.md §fixture`). 새로 넣거나 바꾼 `scenario_signatures`·`recovery_signatures`는 R1의 흔적 검사 대상이다. **새로 넣거나 바꾼 `symptom_signatures`**(와 그것이 참조하는 규칙이 바뀐 증상 시그니처)는 R1(추출)과 R3(증상 음성 검사) 대상이다.
- 판정은 모두 회귀·검증 모드라서 원인 C는 증상(S)과 무관하게 모든 active 원인에 대해 평가된다 (`04-parser-matching.md §5.11 (1)`). 그래서 R3의 "다른 유형의 양성 fixture"에서도 대상 원인의 오탐이 드러난다.

| # | 검증 | 통과 기준 | 실패 시 |
|---|---|---|---|
| R1 | **파서 검증**: 대상 원인(증상 시그니처면 그 유형)의 양성 fixture를 새 규칙으로 파싱. **흔적 검사**: 새로 넣거나 바꾼 scenario/recovery 시그니처 | 대상 시그니처가 참조하는 태그·이벤트·필드가 실제로 추출됨. 흔적 시그니처는 scenario면 그 원인의 양성(재현) fixture에서 충족되고, 둘 다 그 카테고리 음성 fixture **전부**에서 충족되지는 않음(아무 로그에나 맞는 흔적 금지) | `fail`. 규칙·시그니처 초안 수정. 대상 원인에 양성 fixture가 없으면 `skipped: fixture 없음` + 리뷰 대상. 그 카테고리에 음성 fixture가 하나도 없으면 흔적 검사는 `skipped: 음성 fixture 없음` + 리뷰 대상(공허한 통과로 보지 않는다) |
| R2 | **양성 검증**: 대상 원인의 양성·`recurrence`·`extra` fixture | 그 원인이 C=1이고, 소속 유형이 S=1이며(S=0이면 `missing-symptom`), 그 fixture의 `also_allowed`를 제외한 다른 모든 active 원인이 C=0 (양성 기본 기대값과 같음. 점수·신뢰도는 쓰지 않는다). 시그니처·extractor 오류는 `fail` | `fail`. 시그니처 수정. 양성 fixture가 없으면 `skipped: fixture 없음` + 리뷰 대상 |
| R3 | **음성 검증**: (원인) 음성 fixture(`<유형 ID>.none*.log`), 같은 카테고리의 다른 원인 양성 fixture(다른 유형 포함), 대상 원인의 `fixed`·`resolved` fixture. (증상) 이슈 DB의 **모든** 음성 fixture | 원인: 대상 원인이 C=0 (그 fixture의 `also_allowed`에 대상 원인이 있으면 제외). 증상: 대상 유형이 S=0. 그 fixture에 대상 원인·유형 시그니처 또는 extractor·관측 오류가 있으면 판정 불가로 `fail`(C=0으로 보지 않는다). 다른 시그니처 오류는 `other_errors`로 표시만 | `fail`. 시그니처 좁히기. 결과에 걸린 fixture와 시그니처 전역 키를 보여준다. 다른 유형의 양성 fixture에서 걸렸으면 `allow-cause` 초안도 함께 낸다 |
| R4 | **교차 회귀**: 전체 fixture (`db_regress --all`) | 모든 fixture의 기대값(`contracts.md §fixture`)이 유지 | `fail`. 차단. 실패가 다른 유형 양성 fixture에서 대상 원인이 C=1이 된 것이면 그 fixture와 `allow-cause` 초안을 함께 내고, 사용자가 시그니처를 좁힐지 허용할지 고른다 (`07-workflow.md §Step 7`) |
| R5 | **이벤트 diff** (파서 규칙 변경 시): 전체 fixture를 변경 전/후 규칙으로 파싱해서 비교 (`db_regress --events-diff <base>`) | 기존 이벤트가 사라지거나 바뀌지 않음 (추가만 허용) | **`needs-approval`** (종료 코드 `3`). 영향 표를 확인 화면과 PR에 붙이고 메인테이너 승인을 리뷰 조건으로 둔다. pre-commit은 경고 후 통과 |
| R6 | **추가 표본** (선택): 계획의 `extra_samples` + `--extra` (같은 증상의 다른 로그 1~3개, 정상 로그 1~3개) | 같은 증상 로그는 대상 원인 매칭, 정상 로그는 S=0. 표본에 대상(정상 표본은 모든 유형의 증상, 그 밖에는 대상 원인·유형) 시그니처 또는 extractor·관측 오류가 있으면 판정 불가로 `fail`, 다른 시그니처 오류는 `other_errors`로 표시만 | 결과를 보여주고 판단 받음 (`fail`이어도 사용자가 진행을 고를 수 있다) |

- 결과 상태는 `pass | fail | needs-approval | skipped | not-implemented` (`contracts.md §상태 값`). `skipped`는 항상 사유를 붙인다(`해당 없음`, `fixture 없음`, `음성 fixture 없음`, `시그니처 없음(pending)`). **`skipped: fixture 없음`·`음성 fixture 없음`은 통과가 아니다.** 확인 화면과 PR 본문에 "검증 못 함"으로 표시하고 그 원인을 리뷰 대상(`06-collaboration.md §6.6` "fixture 없는 원인")으로 남긴다.
- 결과는 push 전 확인 화면(`07-workflow.md §Step 8-5`)과 PR 본문에 "검증 결과" 표로 넣는다.
- R6 표본은 기본적으로 이슈 DB에 넣지 않는다. 사용자가 원하면 마스킹해서 `extra` fixture(`<원인 ID>.extra.<n1>.log`) 또는 음성 fixture로 추가한다 (`add-fixture`).
- 해결책(`resolution`)만 바뀐 경우 R1~R5는 `skipped`(`해당 없음`)이고, 해결책 검증 상태만 `unverified`로 초기화한다 (`set-resolution`).
- Phase 7~9의 `db_verify rules`는 뼈대였다(R4만 실행, R1~R3·R5 `not-implemented`, R6 `skipped`). Phase 10부터 R1~R6이 모두 실제로 돌고 `not-implemented`는 나오지 않는다. 종료 코드 `3` 경로는 R5 또는 `TT_FORCE_VERIFY_EXIT=3`으로 시험한다 (`contracts.md §종료 코드`).
- R6 `fail`은 종료 코드에 넣지 않는다(위 표 "사용자가 진행을 고를 수 있다"). 대상 계산·항목 모으기·출력 세부는 `contracts.md §3.2` `db_verify.py` 세부.

**수동 기록 검증** (`/telephony-triage:record`, `07-workflow.md §record`)

수동 기록은 로그 분석과 매칭을 건너뛰지만 **검증은 건너뛰지 않는다.** 모든 검사는 analyze와 같은 `db_pr stage`에서 돈다.

| 조건 | 실행하는 검증 | 건너뛰면 표시 |
|---|---|---|
| 항상 | 스키마·lint(`03-issue-db.md §5.7 (4)` 체크리스트 전부), Jira 중복(main + 열린 PR, `db_pr preflight`), `check-ids`, 마스킹 검사, 생성 파일 `db_build --verify`, **전체 fixture 회귀(R4)** | — |
| 새 원인/유형 + 판별 시그니처 있음 | R1~R5 (`--draft` 초안, 적용 후 `--plan`) | fixture가 없으면 R1·R2 `skipped: fixture 없음` → 확인 화면 "검증 못 함", 원인이 리뷰 대상 |
| 기존 유형의 새 원인 + `signatures_pending: true` (사용자가 명시) | R4(`--fixture`를 주면 그 양성 fixture가 `"<유형 ID>:unresolved"` 기대값으로 포함), lint(경고: 시그니처 없음) | R1~R3 `skipped: 시그니처 없음(pending)`. 해결책은 `unverified` 고정. 월간 리뷰 "시그니처 없는 원인" |
| 새 유형 + 첫 원인 `signatures_pending: true` (증상 시그니처는 필수) | 증상 시그니처에 대해 R1·R3·R5(규칙 변경 시), R4. 증상 시그니처를 보여주는 로그(`--fixture`)는 첫 원인의 양성 fixture로 넣고 기대값 `"<유형 ID>:unresolved"`로 R4에서 증상 판별을 확인한다 | 원인 판별 R1~R3 `skipped: 시그니처 없음(pending)`. fixture가 없으면 증상 시그니처의 R1도 `skipped: fixture 없음` → "검증 못 함", 리뷰 대상 |
| 시그니처·파서 규칙 변경 포함 | R1~R5 (+R6 표본을 주면) | 위와 같음 |
| 기존 원인에 Jira만 추가(`append`) | 항상 항목만 | R1~R3·R5 `skipped: 해당 없음` |
| 사용자가 "수정 완료"라고 함 | `ref`·`fixed_in` 형식 검사(`fix_ref_regex`, `build_compare`) | `fix-submitted`까지만 기록. `fixed`는 `verify-fix`로만 |
| 사용자가 "해결책이 효과 있었다"고 함 | 근거가 있으면 `verify-resolution`(evidence: 기록 대상이 아닌 **다른** Jira 키, 또는 `--resolved-fixture`로 자른 `resolved` fixture + `db_verify resolution` passed. 새 원인이면 `db_verify resolution --plan <plan> --draft <dir>`로 계획을 적용한 트리에서 판정) | 근거가 없거나 기록 대상 Jira 자신뿐이면 `unverified`. 사용자가 그래도 효과를 주장하면 "근거: 사용자 진술"을 남기고(여전히 `unverified`. 새 원인은 `resolution_verification.method`, 기존 원인은 Jira 기록 `note`), 확인 화면·PR 본문에 "사용자 진술 — 카테고리 오너 리뷰 필요"로 표시한다 (`06-collaboration.md §6.6`) |

- 확인 화면과 PR 본문에는 **"수동 기록"** 라벨과 위 표에서 실행된 검증과 건너뛴 검증(사유 포함)을 모두 보여준다 (`db_pr summary`가 계획 `source: record`로 표시).
- 피드백은 `decision: manual`로 남기고 수락률 통계에서 제외한다 (`06-collaboration.md §6.5`).

**해결책 검증** (사람이 확인)
- 새 원인과 `resolution`이 바뀐 원인은 `resolution_verification.status: unverified`로 시작한다.
- 다음 중 하나로 확인되면 `verified`로 바꾼다 (`verify-resolution` op).
  - **Jira 근거**: 해결책을 적용한 뒤 재현되지 않음을 확인한 Jira (evidence에 Jira 키). `record`에서 기록하는 Jira 자신은 근거가 될 수 없다(그 Jira의 해결 진술은 사용자 진술이다).
  - **로그 근거**: `/telephony-triage:validate --cause <원인 ID> <적용 후 logcat...>` (`07-workflow.md §validate`), 또는 `record --resolved-fixture`(새 원인이면 `--plan --draft`로 계획을 적용한 트리에서 판정, `contracts.md §3.2`). `db_verify resolution` 판정:

    | 판정 | 조건 |
    |---|---|
    | **passed** | 원인 시그니처 불충족, 그리고 다음 중 하나: (a) `recovery_signatures`가 있고 충족 / (b) `recovery_signatures`가 없으면 증상 시그니처 불충족 **이고** `scenario_signatures` 충족 |
    | **failed** | 원인 시그니처 충족 |
    | **unknown** | 위 둘 다 아님: `recovery_signatures`도 `scenario_signatures`도 없는 원인, 시나리오 흔적 없음, 증상이 남음, 로그 구간 부족, 파서 관측 불완전(외부 파서 실패·해석 못 한 파일) |

    passed면 로그를 마스킹해서 `resolved` fixture(`fixtures/<원인 ID>.resolved.<n1>.log`)로 추가하고 evidence에 그 경로를 넣는다. unknown이면 필요한 조건(시그니처 추가 또는 로그 조건)을 안내하고 기록하지 않는다.
- `verified` 전환 PR은 원인 소속 카테고리 오너 리뷰가 필요하다.
- README와 분석 리포트는 미검증 해결책에 "⚠ 미검증"을 붙인다. 매처는 미검증이어도 후보로 쓴다 (분류는 로그 근거이므로).

#### (2) 코드 수정 검증 (verify-fix)

수정 상태 흐름:

```
open ──(수정 CL 머지, fix-submitted 커맨드)──▶ fix-submitted ──(verify-fix 통과)──▶ fixed
  ▲                                              │  ▲                                 │
  │                                              │  └──(부분 통과: 상태 유지, 이력 기록)
  └──────────────(verify-fix 실패)───────────────┘                                    │
  └─────────────(회귀: fixed_in 이후(같은 빌드 포함)에서 재발, Step 7 확인)──────────────┘
```

**전제: 시나리오 흔적**
- 코드·설정 수정 유형(`resolution_type`이 `framework-bug`, `vendor-ril`, `modem`, `carrier-config`)의 원인은 `fixed`로 바꾸기 전에 `scenario_signatures` 또는 `recovery_signatures` 중 **하나가 필수**다. 없으면 `db_verify fix`가 종료 코드 2와 다음 할 일(`update-signature` → R1 흔적 검사 통과 → 재실행)로 거부하고, `db_search`는 원인 항목에 `verify_fix_blocked`를 낸다 (`update-signature` op로 같은 PR에 넣을 수 있다. 이 경우 판정은 `db_verify fix --plan <p> --draft <dir>`로 시그니처를 적용한 트리에서 하고, R1(흔적 검사 포함)~R5가 함께 돈다. 흔적 시그니처가 R1 흔적 검사를 통과하지 못하면 판정 결과를 쓰지 않는다).
- `signatures_pending` 원인은 원인 시그니처가 없으므로 verify-fix를 할 수 없다. 먼저 `update-signature`로 판별 시그니처를 추가한다.
- "시나리오 흔적 충족" = `scenario_signatures`가 있으면 그것이 충족, 없으면 `recovery_signatures`가 충족. 판정은 시나리오 흔적 충족을 전제로 한다. **흔적이 없으면 판단 불가**다. 사용자 말만으로 흔적을 대신하지 않는다.
- 그 밖의 유형(`user-setting`, `network`, `hw`)은 두 시그니처가 없어도 되지만, 없으면 흔적 판정 대신 사용자 확인을 받고 그 사실을 `verification.note`에 남긴다.

**`/telephony-triage:verify-fix <원인 ID> <수정 빌드 logcat...> [--jira <검증 Jira>]`** (절차 전체는 `07-workflow.md §verify-fix`)
1. 원인의 `fix.status`가 `fix-submitted`(또는 재검증이면 `fixed`)인지 확인한다. 아니면 중단한다.
2. `fixed_in`에 빌드가 있는 항목이 없으면 중단하고 `fix-submitted` 커맨드로 빌드를 먼저 추가하라고 안내한다 (`verify-fix` passed의 전제, `contracts.md §작업 계획`). 로그의 빌드가 `fixed_in` 이후(≥, 같은 빌드 포함)인지 `build_compare`로 확인한다. 이전 빌드면 중단한다. 비교 규칙이 없거나 파싱 불가면 사용자에게 묻는다.
3. **시나리오 흔적 확인**: 위 전제대로 흔적을 찾아 원인 본문의 "재현 시나리오"와 함께 보여준다.
4. 판정 (`db_verify fix`):

   | 판정 | 조건 |
   |---|---|
   | **통과** (`passed`) | 시나리오 흔적 충족, 원인 시그니처 불충족, 증상 시그니처 불충족, `recovery_signatures`가 있으면 충족 |
   | **부분 통과** (`partial`) | 시나리오 흔적 충족, 원인 시그니처 불충족, 증상은 남아 있음 → 같은 증상의 다른 원인일 수 있음. 다른 원인 후보를 보여준다 |
   | **실패** (`failed`) | 원인 시그니처 충족 (재발) |
   | **판단 불가** (`unknown`) | 시나리오 흔적 없음, 로그 구간 부족, 파서 관측 불완전(외부 파서 실패·해석 못 한 파일) |

5. 결과로 작업 계획을 만든다 (`verify-fix` op, `contracts.md §작업 계획`).
   - **통과** → `fix.status: fixed`, `fix.verification` 기록. 수정 빌드 로그의 최소 구간을 마스킹해서 **수정 후 fixture** `fixtures/<원인 ID>.fixed.<build>.log`로 추가한다 (기본 기대값 `expect_not: <원인 ID>`, `.expect.yaml` 불필요).
   - **실패** → `fix.status: open`으로 되돌린다. 실패 기록(빌드, 재발 근거 요약)과 이전 `ref`·`fixed_in`을 `verification_history`에 보존하고 `ref`, `fixed_in`을 비운다 (`03-issue-db.md §5.9`). 재발 로그를 `recurrence` fixture(`fixtures/<원인 ID>.recurrence.<build>.log`)로 넣을지 묻는다.
   - **부분 통과** → `fix.status`는 **유지**하고(`fix-submitted`면 `fix-submitted`, 재검증 대상이 `fixed`면 `fixed` — 원인 시그니처가 불충족이므로 이 원인의 수정은 유효하다) `verification_history`에 `partial` 항목(빌드, 남은 증상, 다른 원인 후보)을 추가한다. 남은 증상은 `analyze`로 새 분석하도록 안내한다. **통과로 기록하는 선택지는 없다.**
   - **판단 불가** → 기록하지 않고 필요한 로그 조건(시나리오 수행 방법, 필요한 시그니처)을 안내한다.
6. Step 8과 같은 방식(`db_pr stage` → 확인 화면 → 커밋 → `db_pr publish`)으로 올린다. 브랜치는 `verify-fix/<원인 ID>-<build>` (`contracts.md §브랜치`). 확인 화면과 PR 본문에 판정 근거 로그(마스킹)와 시나리오 흔적을 넣는다.

`fix.verification` 형식:

```yaml
verification:
  result: passed                  # fixed일 때만 존재하므로 항상 passed
  build: <검증 빌드>
  date: 2026-10-05
  by: <GHE 아이디>
  jira: ABC-13000                 # 선택, 검증 Jira
  fixture: fixtures/DATA-001-03.fixed.BUILD_X.log   # 유형 디렉토리 기준 상대 경로
  scenario_evidence: DATA-001-03/data-connect-attempt   # 충족한 scenario/recovery 시그니처 전역 키
  note: 로밍 SIM 재현 시나리오 3회 수행, 재발 없음
```

- 실패·부분 통과·되돌림 기록은 `verification_history`에 쌓는다 (형식: `contracts.md §상태 값`).

**수정 후 감시** (자동)
- `fixed`·`resolved` fixture는 이후 모든 회귀(R3, R4)에 포함된다. 누군가 시그니처를 넓혀서 수정 빌드 로그까지 잡게 되면 차단된다.
- `fixed` 이후 같은 원인으로 분류되는 Jira의 SW가 `fixed_in` 이후(≥)면 `03-issue-db.md §5.9`의 **회귀 의심**으로 표시하고, Step 7에서 `fix.status`를 `open`으로 되돌릴지 묻는다. 되돌리면 이전 `verification`·`ref`·`fixed_in`은 `verification_history`로 옮긴다.
