# 04. 로그 파서 규칙과 시그니처 매칭

> 원본 5.8, 5.11. fixture 명명·기대값 표는 `contracts.md §fixture`에만 있다.

---

### 5.8 로그 파서 규칙 (새 유형/원인 추가 시 필수 갱신)

#### (1) 원칙: 엔진과 규칙을 분리한다

- `parse_logcat.py`(플러그인)는 **엔진**만 가진다: 포맷 파싱(연도·타임존은 `--tz`/`--year` 인자), 윈도우 자르기, RIL 페어링, 줄 단위 마스킹(`--mask`, extractor 실행 전), extractor 실행기, fixture 최소 구간 자르기(`cut`).
- 수집할 태그, RIL 목록, 이벤트 추출 규칙은 **이슈 DB의 `parser-rules/`** 에 둔다. 파서는 실행할 때 `--rules <db>/parser-rules`를 읽는다. analyze에서 `<db>`는 읽기 스냅샷 `<work_dir>/_snapshot`이다 (`07-workflow.md §Step 1`).
- 새 유형이 추가될 때 플러그인을 다시 배포하지 않고 **이슈 DB PR 하나로 유형 + 파서 규칙 + fixture가 함께** 반영된다. 팀원은 이슈 DB만 최신화하면 된다 (`sync` 또는 analyze Step 1).
- 엔진을 고쳐야 할 때만 플러그인 PR로 간다. 예: 새 로그 포맷, 새 페어링 방식, 여러 줄 메시지 처리.

#### (2) 규칙 파일 형식

**이벤트 이름 공간** (`contracts.md §기존 자산 연결 계약`): 파서 출력 이벤트는 세 곳에서 온다.
- `parser-rules/extractors.yaml`이 만드는 이벤트: 접두어 없음 (예: `data_evaluation_rejected`). 팀원이 PR로 추가하는 확장 지점이다.
- 파서 백엔드의 **내장 판별 로직**(사내에서 포팅한 검증된 파서): `builtin.<category>.<이름>`. 목록은 백엔드의 `builtin_events()`. 바꾸려면 백엔드 코드 변경(메인테이너 리뷰 + 골든 갱신, `16-existing-assets.md §16.3`).
- 어댑터(외부 파서를 그대로 실행하는 대안): `ext.<category>.<이름>`. 이슈 DB `issue-db.config.yaml`의 `external_parsers`에 그 카테고리가 고정돼 있을 때만 시그니처에서 참조할 수 있다 (`db_lint`, `contracts.md §기존 자산 연결 계약`).
- 시그니처 `must_event`는 셋 모두 참조할 수 있다. extractor는 `builtin.`/`ext.` 접두어 이벤트를 만들 수 없다. 새 유형은 원칙적으로 extractor로 확장한다.

모든 규칙 항목은 **키로 식별**되고(`tags`는 `tag`/`tag_regex`, `ril`은 `name`, `extractors`는 `id`), 이력 필드 `added_for`, `added_on`, `reason`을 가진다. 나머지 필드는 **기능 필드**다. `CHANGELOG.md`는 이력 필드로 `db_build.py`가 생성한다 (끝에 한 줄씩 붙이는 파일은 동시 PR에서 항상 충돌하므로 두지 않는다).

`parser-rules/tags.yaml` (예시, Phase 0에서 실제 로그로 확인하고 Phase 1에서 반영):

```yaml
tags:
  # 태그는 정확한 이름(tag) 또는 정규식(tag_regex).
  # 데이터 스택은 Android 13+ 구조만 대상으로 한다: DNC-<phoneId>(DataNetworkController), DN-…(DataNetwork), DPM-<phoneId>(DataProfileManager), DRM-<phoneId>(DataRetryManager), DSM-<phoneId>(DataSettingsManager), DCM-<phoneId>(DataConfigManager), DSRM-<phoneId>(DataStallRecoveryManager).
  # 레거시 데이터 스택(DcTracker/DCT, DataConnection 등)은 고려하지 않는다.
  - {tag_regex: '^DNC-\d+$', category: data, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}
  - {tag_regex: '^DN-.+$',    category: data, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}
  - {tag_regex: '^DPM-\d+$', category: data, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}
  - {tag_regex: '^DRM-\d+$', category: data, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}
  - {tag_regex: '^DSM-\d+$', category: data, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}   # DataSettingsManager (data enabled/disabled 판별)
  - {tag_regex: '^DCM-\d+$', category: data, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}   # DataConfigManager
  - {tag_regex: '^DSRM-\d+$', category: data, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}  # DataStallRecoveryManager
  - {tag: RILJ,                                        category: common, added_for: -, added_on: 2026-09-27, reason: 초기}
  - {tag_regex: '^ImsPhone.*',                         category: call, added_for: CALL-001, added_on: 2026-09-27, reason: 초기}
  - {tag_regex: '^(SST|ServiceStateTracker)(-\d+)?$',  category: network, added_for: NETWORK-001, added_on: 2026-09-27, reason: 초기}
  - {tag: UiccController,                              category: sim, added_for: SIM-001, added_on: 2026-09-27, reason: 초기}
  - {tag_regex: '^(SMSVC|SubscriptionManagerService)$', category: sim, added_for: SIM-001, added_on: 2026-09-27, reason: 초기}
  - {tag: SmsDispatchersController,                    category: sms, added_for: SMS-001, added_on: 2026-09-27, reason: 초기}
  - {tag: InboundSmsHandler,                           category: sms, added_for: SMS-001, added_on: 2026-09-27, reason: 초기}
  - {tag_regex: '^Ims(Manager|Resolver|ServiceController|Registration).*', category: ims, added_for: IMS-001, added_on: 2026-09-27, reason: 초기}
```

`parser-rules/ril.yaml` (예시):

```yaml
requests:
  - {name: SETUP_DATA_CALL,      category: data, timeout_ms: 30000, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}
  - {name: DEACTIVATE_DATA_CALL, category: data, timeout_ms: 10000, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}
  - {name: DIAL,                 category: call, timeout_ms: 10000, added_for: CALL-001, added_on: 2026-09-27, reason: 초기}
  - {name: SEND_SMS,             category: sms,  timeout_ms: 30000, added_for: SMS-001, added_on: 2026-09-27, reason: 초기}
unsolicited:
  - {name: UNSOL_DATA_CALL_LIST_CHANGED,      category: data, added_for: DATA-001, added_on: 2026-09-27, reason: 초기}
  - {name: UNSOL_RESPONSE_CALL_STATE_CHANGED, category: call, added_for: CALL-001, added_on: 2026-09-27, reason: 초기}
  - {name: UNSOL_RESPONSE_NEW_SMS,            category: sms,  added_for: SMS-001, added_on: 2026-09-27, reason: 초기}
```

- IMS 등록 상태는 최신 단말에서 RIL보다 ImsService 쪽 로그로 보는 경우가 많다. RIL의 IMS 관련 요청/unsol은 레거시 경로이므로, 쓰는 단말이 있을 때만 추가한다.

`parser-rules/extractors.yaml` (예시, 문구는 Phase 0에서 확인하고 Phase 1에서 반영):

```yaml
extractors:
  - id: data-evaluation-rejected
    added_for: DATA-001-01
    added_on: 2026-09-27
    reason: 데이터 평가 거부 사유 추출
    tag_regex: '^DNC-\d+$'
    patterns:                           # 버전별 문구 차이는 여러 패턴으로
      - '<평가 결과 로그>.*reasons=\[(?P<reasons>[^\]]*)\]'
    event: data_evaluation_rejected
    fields: [reasons]
  - id: last-call-fail-cause
    added_for: CALL-001-01
    added_on: 2026-09-27
    reason: 통화 실패 원인 코드 추출
    tag: RILJ
    patterns: ['LAST_CALL_FAIL_CAUSE.*causeCode[=:]\s*(?P<cause>\d+)']   # 실제 출력 형식 확인 필요
    event: call_fail_cause
    fields: [cause]
```

추출된 이벤트는 파서 출력 JSON에 `{event, fields, ts, tag, msg, phone_id}`로 들어간다. `--mask`면 extractor는 **마스킹된 줄**에 돈다. 그래서 extractor 패턴도 마스킹 이후 텍스트 기준으로 쓰고, 원본 식별자 패턴은 `db_lint`가 금지한다.

**슬롯(`phone_id`)**: 듀얼 SIM 단말에서는 두 슬롯의 로그가 한 파일에 섞인다. 파서는 모든 이벤트에 `phone_id`(정수 또는 `null`)를 넣는다. 추출원은 순서대로 태그 접미사(`DNC-1` → 1), 메시지 접두어(`[PHONE1]`, `[SUB1]` 등, 실제 표기는 S20에서 확인), 없으면 `null`. 시그니처는 기본적으로 **같은 슬롯 안에서만** 충족된다 (5.11 (1) `same_phone`). RIL 페어링 키는 `(pid, phone_id, serial)`이고 `phone_id`를 못 뽑으면 `(pid, serial)`이다. phone 프로세스 재시작이나 슬롯별 serial 충돌로 요청·응답이 잘못 짝지어지는 것을 막기 위해 pid를 포함한다.

#### (3) 새 유형/원인 추가 시 파서 갱신 절차

analyze Step 7에서 새 원인/유형을 계획할 때 아래를 점검하고, 부족하면 `add-parser-rule`(새 키) 또는 `update-parser-rule`(기존 키) op 초안을 만들어 사용자 승인을 받는다. Step 8 적용 시 `db_add.py`가 다시 확인한다. op 정의는 `contracts.md §작업 계획`.

| 점검 | 부족할 때 |
|---|---|
| 새 시그니처가 참조하는 태그가 `tags.yaml`에 있는가 | 태그와 카테고리를 추가한다. 없으면 파서가 해당 로그를 버려서 매칭이 안 된다. |
| 시그니처에 나오는 RIL 요청/unsol이 `ril.yaml`에 있는가 | 요청 이름, 카테고리, timeout을 추가한다. |
| 판별에 구조화된 값(cause 코드, reason, state)이 필요한가 | `extractors.yaml`에 규칙을 추가하거나, 기존 extractor에 패턴을 더한다(`update-parser-rule`). |
| 원인 fixture가 있는가 | `parse_logcat.py cut`으로 이번 로그에서 판별 근거 주변 최소 구간을 잘라 마스킹된 파일로 만들고, `add-fixture`(`kind: positive`)로 계획에 넣는다. |
| 전체 fixture 회귀 | 5.11 (4) 기준으로 모든 fixture를 돌린다. 기존 fixture의 기대 결과가 바뀌면 차단하고 사용자에게 보고한다. |

- 규칙만으로 표현이 안 되면 원인은 추가하되, 플러그인 레포에 올릴 **엔진 개선 요청 초안**(필요 기능, 예시 로그, 대상 원인 ID)을 만들어 보여준다.

#### (4) 파서 규칙 작성 규칙

- 태그와 정규식은 실제 로그에서 확인한 문구로만 쓴다.
- extractor `id`는 kebab-case이고 바꾸지 않는다. 시그니처가 참조하기 때문이다.
- 기존 extractor를 수정하면 그것을 쓰는 모든 원인의 fixture 회귀가 통과해야 한다. `parser-rules/` 변경이 있으면 커밋 시점 회귀도 전체 fixture로 돈다 (`contracts.md §3.2` 범위 확장 규칙).
- `parser-rules/` 변경은 이슈 DB 메인테이너 리뷰가 필수다 (`06-collaboration.md §6.1`).
- **정규식 안전**: 규칙과 시그니처의 정규식은 모든 기여자의 매처·pre-commit·CI에서 전체 로그에 실행된다. `db_lint`는 중첩 수량자(`(a+)+`, `(a|a)*` 류)와 길이 제한 없는 역참조를 거부한다(정적 검사, 보수적). 매처와 extractor는 패턴당 실행 시간 상한 `matcher.pattern_timeout_ms`(`issue-db.config.yaml`, 기본 2000)를 두고, 초과하면 그 시그니처(또는 extractor)를 결과에 `error`로 표시하고 분석은 계속한다. 회귀·검증 모드에서는 실패로 본다.

### 5.11 시그니처 매칭 규칙

#### (1) 시그니처 의미

| 필드 | 의미 |
|---|---|
| `must_match: [p1, p2]` | **AND**. 윈도우 안에 각 정규식이 최소 1줄씩 매칭돼야 한다. 정규식은 `TAG: msg` 결합 문자열에 `search`로 적용한다. |
| `must_event: [{event, fields}]` | **AND**. 윈도우 안에 각 이벤트가 최소 1개 있어야 한다. `fields`의 값은 정규식이며 필드 값 전체에 `fullmatch`로 적용한다. `fields`를 생략하면 이벤트 존재만 본다. |
| `must_not_match: [p]` | 같은 윈도우 안에 하나라도 매칭되면 이 시그니처는 불충족이다. |
| `window_sec` | 슬라이딩 윈도우 길이. 분석 범위(분석 모드: 발생 시각 ±5분, `07-workflow.md §Step 3` / 회귀·검증 모드: 파일 전체) 안에서 조건을 모두 만족하는 길이 `window_sec`의 구간이 하나라도 있으면 충족이다. |
| `same_phone: true` (선택, 기본 `true`) | 시그니처의 모든 조건이 **같은 `phone_id`** 의 이벤트로 충족되어야 한다. `phone_id: null` 이벤트는 와일드카드다(어느 슬롯과도 맞음). DDS 전환처럼 슬롯을 가로지르는 원인은 `false`로 둔다. 회귀·검증 모드도 같다 (5.8 (2) 슬롯). |
| `sequence: [id1, id2, ...]` (선택) | 순서 조건. `must_match`·`must_event` 항목에 선택 `id`를 붙이고, 여기 나열한 순서대로 각 조건의 **첫 충족 시각이 단조 증가**해야 충족이다. "설정 OFF → 이후 SETUP_DATA_CALL 없음"과 "SETUP_DATA_CALL 실패 → 이후 설정 OFF"를 구분할 때 쓴다. 없으면 순서를 보지 않는다. `must_not_match`는 넣을 수 없다. `db_lint`가 id 존재·중복을 검사한다. |
| 한 원인/유형에 시그니처 여러 개 | **OR**. 하나라도 충족하면 그 원인/유형이 충족이다. |

- 시그니처 종류: `symptom_signatures`(유형), `signatures`(원인 판별), `recovery_signatures`(해결 후 정상 동작), `scenario_signatures`(재현 시나리오 수행 흔적). 뒤의 두 가지는 점수에 쓰지 않고 검증에만 쓴다 (`05-verification.md`).
- **원인 평가 범위** (모드별):
  - **분석 모드**(analyze Step 4): 2단계. 먼저 모든 active 유형의 S를 구하고, **S=1인 유형의 원인만** C를 평가한다. 리포트 후보는 증상이 확인된 유형 안에서만 나온다.
  - **회귀·검증 모드**(`--regress`, `db_regress`·`db_verify`): **모든 active 원인의 C를 S와 무관하게 독립 평가**한다. 그래서 다른 유형의 로그에서 원인 시그니처가 잘못 충족되는 것(S=0, C=1)을 R2(다른 원인 C=0), R3, R4가 잡는다 (아래 (4), `05-verification.md §5.12 (1)`).
- 시그니처 `id`는 소속 유형/원인 안에서 유일하다. **전역 키는 `<유형 ID 또는 원인 ID>/<sig id>`** 이고, 피드백과 통계는 전역 키를 쓴다.
- **매처와 extractor는 항상 마스킹된 텍스트에 대해 돈다.** 분석에서도 `parse_logcat.py parse --mask`로 각 줄을 extractor 실행 전에 마스킹한다 (`07-workflow.md §Step 3`). fixture도 마스킹돼 있고 마스킹은 멱등이므로 분석과 회귀가 같은 텍스트를 본다. `match_signatures.py`는 `masked: true`가 아닌 입력을 거부한다 (종료 코드 2).
- 그래서 시그니처와 extractor 패턴은 **마스킹된 로그 기준으로** 작성한다. 원본 식별자 패턴(15자리 숫자 IMSI, 전화번호 형식 등)은 `db_lint`가 금지한다. `<IMSI>`, `<CELL>` 같은 치환 토큰은 써도 된다.
- `signatures_pending: true`인 원인(`03-issue-db.md §5.4 (1)`)은 판별 시그니처가 없으므로 원인 매칭 대상이 아니다 (유형은 증상 시그니처가 필수라 항상 매칭 대상이다). 매처는 후보 유형에 속한 pending 원인을 점수 없이 `pending_causes`로 함께 내고, 리포트는 "시그니처 없는 기존 원인: <ID> <title>(참고)"로 보여준다.

#### (2) 점수

`issue-db.config.yaml`의 `scoring` 값을 쓴다.

```
S = 증상 시그니처 충족 시 1, 아니면 0
C = 원인 시그니처 충족 시 1, 아니면 0
base = symptom_weight × S + cause_weight × C
bonus = proximity_bonus_max × (1 - |근거 시각 - 발생 시각| / 분석 범위 절반)   # 0 이상으로 자름
      + keyword_bonus_max × (Jira 텍스트와 원인 title/tags 키워드 일치 비율)
score = min(1, base + bonus)
feedback_weight가 켜져 있고 해당 시그니처 표본 ≥ min_samples면: score × (0.5 + 0.5 × 수락률)
```

- 신뢰도: `score ≥ confidence.high` 높음, `≥ confidence.medium` 중간, 그 외 낮음.
- 증상만 충족(S=1, C=0)하면 "유형 일치, 원인 미확인" 후보로 표시한다.
- `status`가 `active`가 아닌 유형과 원인은 후보에서 제외한다.
- 수락률 = (그 시그니처가 **1위로 제시된** 피드백 중 `decision: accepted`인 건수) / (그 시그니처가 1위로 제시된 피드백 건수). 2위 이하로 제시된 경우는 분모에 넣지 않는다. `decision: manual`(수동 기록)은 제시된 후보가 없으므로 집계하지 않는다 (`06-collaboration.md §6.5`).
- 발생 시각과 근거 시각은 같은 기준(UTC)으로 바꿔서 비교한다 (`02-config.md §4` 시각 정렬).

#### (3) 캐시

매처는 `.cache/compiled.json`(`06-collaboration.md §6.8`)을 쓰되, 해시가 현재 이슈 DB(`--db`)와 다르면 메모리에서 다시 컴파일한다. 컴파일 함수는 `common/`에 있고 `db_build --cache-only`와 공유한다 (Phase 3에서 구현, 파일 캐시는 Phase 5).

#### (4) 회귀·검증 모드와 fixture 기대값

**회귀·검증 모드** (`match_signatures.py --regress`)
- 분석 범위 = **fixture 파일 전체** (발생 시각 기준으로 자르지 않는다).
- 원인 평가 = **모든 active 원인의 C를 독립 평가** (위 (1) 원인 평가 범위).
- bonus = **0** (proximity, keyword 모두).
- 피드백 가중치 **끔** (`--no-feedback-weight` 포함). 피드백이 쌓여도 규칙 변경 없이 회귀 결과가 바뀌지 않게 하기 위해서다.
- **판정은 S/C 값만으로 한다.** 점수(S=1, C=1 → 1.0 / S=0, C=1 → 0.6 / S=1, C=0 → 0.4)와 신뢰도는 결과표의 참고 값이고 판정에 쓰지 않는다. `scoring` 값(`cause_weight`, `confidence`)을 바꿔도 회귀·검증 결과가 바뀌지 않게 하기 위해서다 (`contracts.md §fixture` 기대값, `05-verification.md` R2·R3).
- `db_regress`, `db_verify`(rules, resolution, fix)는 항상 이 모드를 쓴다.

**기대값**: fixture 종류별 기본 기대값과 `.expect.yaml` 필드는 `contracts.md §fixture`에만 있다. 요약하면 양성은 "대상 원인 C=1, `also_allowed`를 제외한 다른 모든 active 원인 C=0"(이슈 DB 전체 기준), `fixed`/`resolved`는 `expect_not: <원인 ID>`(C=0), `recurrence`/`extra`는 양성과 같고, 음성(`none`)은 "S=1인 유형 없음"이다. 같은 로그에 실제로 다른 유형의 현상도 있으면 `.expect.yaml`의 `also_allowed`에 그 원인을 적는다(`allow-cause` op).

- `status`가 `active`가 아닌 원인의 fixture는 회귀에서 제외한다. `signatures_pending` 원인의 양성 fixture는 제외하지 않고 `"<유형 ID>:unresolved"` 기대값으로 돈다 (`contracts.md §fixture`).
- `.expect.yaml`의 `occurred_at`(선택)은 판정에 쓰지 않고, 결과 표에 참고로 보여준다.
