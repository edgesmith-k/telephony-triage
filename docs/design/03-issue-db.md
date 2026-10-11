# 03. 이슈 DB 레포 (`telephony-issue-db`)

> 원본 5.1, 5.2, 5.4, 5.5, 5.6, 5.7, 5.9, 5.10. config는 `02-config.md §5.3`, 파서·매칭은 `04-parser-matching.md`, 검증은 `05-verification.md`.
> 작업 계획 op, fixture 명명, 상태 값, renumber 참조는 `contracts.md`에만 있다.

---

### 5.1 분류 계층: 카테고리 > 이슈 유형(증상) > 원인

```
Data
└─ DATA-001  SETUP_DATA_CALL이 발생하지 않음                ← 이슈 유형 = 증상
   ├─ DATA-001-01  Data disabled    → 모바일 데이터 설정을 켠다   [not-a-bug]  Jira 2건
   └─ DATA-001-02  Roaming disabled → 데이터 로밍 설정을 켠다     [not-a-bug]  Jira 1건
Call
└─ CALL-001  VoLTE가 동작하지 않음
   └─ CALL-001-01  IMS 미등록 (carrier config VoLTE off) → ...  [fixed: BUILD_X]  ↔ IMS-001-01
Network
└─ NETWORK-001  서비스가 잡히지 않음
   └─ ...
SIM
└─ SIM-001   SIM이 인식되지 않음
   └─ ...
SMS
└─ SMS-001   SMS가 전송되지 않음
   └─ ...
IMS
└─ IMS-001   IMS 등록이 되지 않음
   └─ IMS-001-01 ...  ↔ CALL-001-01
```

- **이슈 유형**은 사용자가 보는 증상이고, 증상 시그니처로 판별한다.
- **원인**은 같은 증상 아래의 서로 다른 원인이다. 원인마다 판별 시그니처, 해결책, 수정 상태를 가진다.
- **Jira 기록**은 Jira 한 건당 파일 하나이고, 반드시 원인 하나를 가리킨다. 원인 미확정이면 `cause: unresolved`로 둔다.
- 다른 카테고리와 걸친 원인은 `related`와 `secondary_categories`로 연결한다 (5.10).

**카테고리 경계** (주 카테고리는 항상 **사용자가 겪는 증상** 기준)

| 카테고리 | 범위 | 예 |
|---|---|---|
| data | PDN/데이터 연결, APN, 데이터 콜 setup/teardown, 데이터 retry | SETUP_DATA_CALL 미발생, 데이터 연결 끊김 |
| call | 음성/영상 통화의 발신·수신·유지·종료 (CS, VoLTE, VoNR, VoWiFi 모두) | 콜 연결 실패, 통화 중 끊김, VoLTE 발신 불가 |
| network | 망 등록, 서비스 상태, RAT 전환, 셀 선택, 신호 | 서비스 없음, 5G 표시 안 됨, 등록 거절 |
| sim | SIM 인식, 가입자 정보, SIM 파일, 멀티 SIM/eSIM | SIM 미인식, PIN/PUK, SIM refresh |
| sms | SMS/MMS 송수신 (CS SMS, SMS over IMS 모두) | SMS 전송 실패, 수신 안 됨, 중복 수신 |
| ims | IMS 서비스 자체: IMS PDN, 등록/재등록, 기능 활성화(capability), 설정 | IMS 등록 안 됨, VoLTE 기능 비활성, IMS 재등록 반복 |

- "VoLTE 콜이 안 걸림"의 원인이 IMS 미등록이면 **주 카테고리는 call**이고, 원인에 `related: [IMS-001-xx]`, 유형에 `secondary_categories: [ims]`를 넣는다.
- 증상 자체가 "IMS 등록이 안 됨"처럼 IMS 상태면 **ims**다.
- "SMS over IMS 전송 실패"는 **sms**, 원인이 IMS 등록이면 `related`로 ims에 연결한다.
- 경계 기준은 `GLOSSARY.md`에도 그대로 둔다.

### 5.2 디렉토리 구조

```
telephony-issue-db/
├── README.md                          # [생성] 전체 인덱스 (5.6)
├── STATS.md                           # [생성] 통계 (06-collaboration.md §6.7)
├── .gitignore                         # .cache/
├── .gitattributes                     # * text=auto eol=lf (생성 결과 결정성, 아래)
├── .githooks/pre-commit               # git pre-commit hook (06-collaboration.md §6.3) — 메인테이너 소유
├── .githooks/pre-push                 # main 직접 push·승인 토큰 없는 push 거부 (08-safety.md §9) — 메인테이너 소유
├── issue-db.config.yaml               # 02-config.md §5.3
├── CONTRIBUTING.md                    # 기여 규칙 (5.7 + 06-collaboration.md §6.2 요약)
├── GLOSSARY.md                        # 카테고리별 표준 용어, 카테고리 경계, 검색 별칭(search 전용) (06-collaboration.md §6.9)
├── docs/
│   ├── getting-started.md             # 10분 온보딩 (06-collaboration.md §6.9)
│   ├── review-guide.md                # 월간 리뷰 절차 (06-collaboration.md §6.6)
│   └── branch-protection.md           # 브랜치 보호 설정 기록 (06-collaboration.md §6.1)
├── schema/
│   ├── type.schema.json
│   ├── jira.schema.json
│   ├── feedback.schema.json
│   ├── plan.schema.json               # 작업 계획 (contracts.md §작업 계획)
│   └── parser-rules.schema.json
├── templates/
│   ├── type.md                        # 새 유형
│   ├── cause.yaml                     # 새 원인
│   └── jira.yaml                      # Jira 기록
├── parser-rules/                      # 로그 파서 규칙 (04-parser-matching.md §5.8)
│   ├── tags.yaml
│   ├── ril.yaml
│   ├── extractors.yaml
│   └── CHANGELOG.md                   # [생성] 규칙 항목의 added_for/added_on/reason에서 생성
├── data/
│   ├── README.md                      # [생성] 카테고리 상세 인덱스
│   └── DATA-001-no-setup-data-call/   # 유형 디렉토리
│       ├── type.md                    # 유형 + 원인 정의
│       ├── jira/
│       │   ├── ABC-111.yaml           # Jira 한 건 = 파일 하나
│       │   ├── ABC-222.yaml
│       │   └── ABC-333.yaml
│       └── fixtures/                  # 이름 규칙: contracts.md §fixture
│           ├── DATA-001-01.log        # 양성 fixture (마스킹된 최소 logcat)
│           ├── DATA-001-02.log
│           ├── DATA-001.none.log      # (선택) 음성 fixture
│           └── DATA-001.none.expect.yaml
├── call/
├── network/
├── sim/
├── sms/
├── ims/
├── feedback/                          # 분석 제안 수락/거절 기록 (06-collaboration.md §6.5)
│   └── 2026-09/ABC-12345-20260927T1830.yaml
└── .github/
    ├── CODEOWNERS
    └── pull_request_template.md       # 리뷰어 머지 체크리스트 (06-collaboration.md §6.3)
    # workflows/는 Actions 사용 시에만 추가 (13-actions.md)
```

- **[생성]** 표시 파일은 `db_build.py`만 만든다. 사람이 직접 고치지 않는다. 현재는 **CI가 없는 로컬 모드**이므로 생성 파일을 각자의 PR에 포함한다 (`06-collaboration.md §6.2`, `§6.3`).
- 유형 디렉토리 이름은 `<유형 ID>-<영문 kebab-case 요약>`이다.
- `DATA-001.none.expect.yaml`은 기본 기대값(`expect_top: none`)과 같으면 생략할 수 있다. 위 예는 `occurred_at`을 적는 경우다. 양성 fixture의 `.expect.yaml`은 다른 유형의 원인이 같이 잡혀도 되는 경우(`also_allowed`)에 만든다 (`contracts.md §fixture`).

**생성 결과의 결정성** — 같은 데이터면 누가 만들어도 바이트 단위로 같아야 한다.
- 현재 시각을 쓰지 않는다. "최종 갱신"과 "최근 30일" 같은 기준일은 이슈 DB 안의 가장 최근 Jira `date`로 정한다.
- 정렬: 카테고리는 `categories` 순서, 유형·원인은 ID 순, Jira는 `date` 내림차순 후 키 오름차순, 동률은 항상 ID/키 오름차순.
- 숫자 포맷: 비율은 소수 둘째 자리 반올림 문자열(`0.73`), 건수는 정수.
- 줄 끝 LF, 파일 끝 개행 1개, UTF-8.
- 생성기 버전은 `issue-db.config.yaml`의 `generator_version`과 플러그인 `GENERATOR_VERSION`이 같아야 한다. 다르면 `db_build.py`는 `--write`를 거부(종료 코드 2)하고 플러그인 업데이트(또는 메인테이너의 버전 올림 PR)를 안내한다. 쓰기 차단 범위는 `06-collaboration.md §6.4`. 생성 결과가 바뀌는 플러그인 변경은 항상 `GENERATOR_VERSION`을 올린다.

### 5.4 파일 형식

#### (1) 유형 파일 `type.md`

frontmatter는 기계용(인덱스, 매칭), 본문은 사람용 상세 설명이다. **Jira 목록은 여기에 넣지 않는다** (충돌 방지, `06-collaboration.md §6.2`). 아래 태그·문구·심볼은 예시이며 Phase 0에서 확인하고 Phase 1에서 반영한다. 허용 값은 `contracts.md §상태 값`.

```markdown
---
id: DATA-001
category: data
secondary_categories: []
title: SETUP_DATA_CALL이 발생하지 않음
summary: 데이터 연결이 필요한 상황인데 RIL로 SETUP_DATA_CALL 요청이 나가지 않는다
status: active                         # active | deprecated | merged-into:<유형 ID>
symptom_signatures:                    # 증상 판별 (04-parser-matching.md §5.11)
  - id: no-setup-data-call-request     # 전역 키: DATA-001/no-setup-data-call-request
    must_event:
      - {event: data_evaluation_rejected}
    must_not_match: ['RILJ.*>\s*SETUP_DATA_CALL']
    window_sec: 60
causes:
  - id: DATA-001-01
    status: active                     # active | deprecated | merged-into:<원인 ID>
    title: Data disabled
    description: 사용자 모바일 데이터 설정이 꺼져 있어 데이터 평가가 거부됨
    signatures:                        # 원인 판별. 여러 개면 OR (04-parser-matching.md §5.11)
      - id: data-disabled              # 전역 키: DATA-001-01/data-disabled
        must_event:
          - {id: setting-off, event: data_setting_changed, fields: {enabled: 'false'}}   # id는 sequence용 (선택)
          - {id: rejected, event: data_evaluation_rejected, fields: {reasons: '.*DATA_DISABLED.*'}}
        sequence: [setting-off, rejected]   # 선택. 설정 OFF가 거부보다 먼저여야 충족 (04-parser-matching.md §5.11 (1))
        same_phone: true               # 선택, 기본 true. 같은 슬롯(phone_id)의 이벤트로만 충족
        window_sec: 60
    recovery_signatures: []            # 해결 후 이 원인에 특정한 정상 흐름. 예: 데이터 설정 ON → SETUP_DATA_CALL 요청 (sequence). 음성 fixture 전부에 맞으면 R1 실패 (05-verification.md)
    scenario_signatures: []            # 재현 시나리오를 수행한 흔적. 예: 데이터 연결을 시도한 평가 로그 (05-verification.md §5.12 (2))
    resolution: 모바일 데이터 설정을 켠다
    resolution_type: user-setting      # user-setting | carrier-config | framework-bug | vendor-ril | modem | network | hw
    resolution_verification:           # 해결책 검증 (05-verification.md §5.12 (1))
      status: verified                 # unverified | verified
      method: 설정을 켠 뒤 재현되지 않음 확인
      evidence: [ABC-222]              # Jira 키 또는 fixture 경로(유형 디렉토리 기준, contracts.md §fixture)
      by: <GHE 아이디>
      date: 2026-09-15
    fix:
      status: not-a-bug                # open | fix-submitted | fixed | wont-fix | not-a-bug
      ref: null                        # Gerrit CL 또는 커밋 (형식: issue-db.config.yaml fix_ref_regex)
      fixed_in: []                     # [{branch: <브랜치, 필수>, build: <빌드, 선택>}]
      verification: null               # fixed일 때 필수. 코드 수정 검증 기록 (05-verification.md §5.12 (2))
      verification_history: []         # 이전 검증·되돌림 기록, 최신이 위 (형식: contracts.md §상태 값)
    related: []                        # 다른 원인 ID (카테고리 무관, 양방향)
    cp_evidence: null                  # 선택, 자유 텍스트 한 단락. 원인이 모뎀 쪽일 때 DM/silent log 위치·구간, CP 분석 요약, CP 티켓. 매칭·검증에 쓰지 않음. 마스킹 대상 (08-safety.md §8)
    android_versions: ["16", "17"]     # 빈 목록([])이면 전 버전
    code_refs:                         # <root 키>:<루트 기준 상대 경로>
      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/data/DataNetworkController.java
        symbol: DataNetworkController#<평가 메서드, Phase 0에서 확인>   # 파일이 옮겨져도 찾을 수 있게
      - ref: vendor_ril:<상대 경로>
        symbol: <함수명>
        android_versions: ["16"]       # 이 경로가 유효한 버전 (생략하거나 빈 목록이면 전 버전)
  - id: DATA-001-02
    status: active
    title: Roaming disabled
    description: 로밍 중인데 데이터 로밍 설정이 꺼져 있음
    signatures:
      - id: roaming-disabled
        must_event:
          - {event: data_evaluation_rejected, fields: {reasons: '.*ROAMING_DISABLED.*'}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 데이터 로밍 설정을 켠다
    resolution_type: user-setting
    resolution_verification: {status: unverified}
    fix: {status: not-a-bug, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    android_versions: ["16", "17"]
    code_refs: []
tags: [data-evaluation]
---

## 증상
## 증상 판별 방법 (예시 로그, 마스킹)

## 원인별 상세
### DATA-001-01 Data disabled
- 로그 예시 / 확인 방법 / 재현 시나리오 / 해결책 / 코드 위치 / 비고
### DATA-001-02 Roaming disabled
- 로그 예시 / 확인 방법 / 재현 시나리오 / 해결책 / 코드 위치 / 비고
```

- `android_versions: []`는 **전 버전**이다. 매처와 README는 "전 버전"으로 보여주고, 지원 종료 판단(`06-collaboration.md §6.6`)에서는 제외한다.
- `signatures_pending: true`(선택, **원인에만**): 수동 기록(`record`)에서 사용자가 원인 판별 시그니처를 아직 쓰지 않겠다고 명시한 경우에만 붙는다. 이때 원인 `signatures`가 비어 있어도 된다. **유형의 증상 시그니처는 예외 없이 필수**다 (없으면 analyze가 그 유형을 찾을 수 없으므로). 증상만 잡혀도 pending 원인이 "시그니처 없는 기존 원인"으로 후보에 함께 나온다. `db_lint` 경고, 월간 리뷰 "시그니처 없는 원인"에 나오고, 매처는 이 원인을 **판별할 수 없다**(후보 유형에 속하면 참고용 `pending_causes`로만 보여준다). 원인은 `resolution_verification: unverified`로 고정된다. 양성 fixture는 회귀에 남고 기대값은 `"<유형 ID>:unresolved"`다(`contracts.md §fixture`). `update-signature`로 판별 시그니처가 생기면 지워진다. `sync-pr`는 record 계획을 그대로 재적용하므로 pending이 유지된다 (`contracts.md §작업 계획` op 표, `§상태 값`).
- `cp_evidence`(선택, 원인만): CP 로그 파싱은 v1 범위 밖이지만, 원인이 모뎀 쪽이면 근거를 적을 곳이 있어야 이슈 DB가 "RIL 에러 응답"에서 멈추지 않는다. 자유 텍스트 한 단락으로 DM/silent log 위치·구간, CP 분석 요약, 관련 CP 티켓을 적는다. 매칭·검증에 쓰지 않고, README 원인 행에 "CP 근거"로 표시한다. 마스킹 대상이고 `db_lint`가 원본 식별자 패턴을 검사한다.
- `scenario_signatures`는 "재현 시나리오를 수행했다"는 로그 흔적이다 (예: 데이터 연결 시도, 발신 요청). 원인·증상 판별에는 쓰지 않고, verify-fix와 해결책 검증에서 로그가 유효한지 판단하는 데 쓴다. 의미는 다른 시그니처와 같다 (`04-parser-matching.md §5.11 (1)`).

#### (2) Jira 기록 `jira/<JIRA-KEY>.yaml`

```yaml
key: ABC-333                           # 형식: issue-db.config.yaml jira_key_regex (14-site.md S16)
cause: DATA-001-02                     # 원인 미확정이면 unresolved
date: 2026-09-20                       # 분류한 날 (생성 결과의 기준일 계산에 씀, 5.2)
occurred_on: 2026-09-18                # 선택. Jira 발생 시각의 날짜 (통계의 최근 N일·급증에 씀, 06-collaboration.md §6.7)
model: <모델>
sw: <빌드>
android_version: "16"
carrier: <캐리어>                      # 선택
analyzed_by: <GHE 아이디>
failed_step: 3 | Enable data           # 선택, 한 줄(≤200자). 마스킹된 실패 스텝 (아래)
note: 로밍 SIM 테스트 중 발생          # 선택, 한 줄. 사용자가 확인한 요약만 (아래)
```

- **저장하는 Jira 정보는 위 구조화 필드와 `note`, 선택 `failed_step`뿐이다.** Jira 요약·설명·코멘트 원문은 이슈 DB·PR 본문·피드백 어디에도 저장하지 않는다. `note`는 스킬이 마스킹된 Jira 요약에서 한 문장 초안을 만들고 **사용자가 확인한 문장**을 쓴다. 사람 이름·고객명은 넣지 않는다. `db_lint`가 `note`의 원본 식별자 패턴을 검사한다 (`08-safety.md §8.1`).

- `failed_step`(선택)은 실패한 테스트 스텝 한 줄이다. 마스킹을 거쳐 공백을 정리하고 200자로 자른 값만 저장하고(`db_add`), `db_lint`가 `note`처럼 원본 식별자 패턴을 검사한다. Jira 필드·설명·시험 절차·`--failed-step`·`--steps-file`에서 자동으로 얻은 값(`07-workflow.md §Step 2`)은 Step 8 확인 화면의 diff에 보이고 **사용자가 지울 수 있다**. 없으면 키를 만들지 않는다. 점수(S/C)·분류·회귀·검증에는 쓰지 않는 보조 정보다(검색 키워드, 카테고리 README의 "자주 실패한 스텝", 그리고 **스텝 기준 우선 유형**의 한 출처로 쓴다: 같은 스텝이 한 유형에 `step_focus.min_records`건 이상 쌓이면 그 스텝으로 분석할 때 그 유형이 순위에서 우선한다, `04-parser-matching.md §5.11 (2)`). `issue-db.config.yaml`의 `scoring.step_focus_bonus_max`·`step_focus {min_records, map}`은 메인테이너가 관리하고 `db_lint`가 값·정규식·유형·카테고리를 검사한다.
- `occurred_on`은 analyze·record가 Jira 발생 시각(`jira.field_map.occurred_at`, `jira.timezone`)에서 채운다. 모르면 생략하고, 통계는 `date`로 대신한다. 과거 이슈를 한꺼번에 기록해도 통계가 분류일에 몰리지 않게 하기 위해서다.
- 파일명이 Jira 키이므로 이슈 DB 전체에서 같은 Jira는 하나만 존재한다. `db_lint.py`가 전체 중복을 검사한다.
- 재분류는 `reclassify` op로 한다: 파일을 다른 유형 디렉토리로 **이동**하고 `cause`를 바꾼 뒤, `note`에 `reclassified from <이전 원인 ID>`를 남긴다 (`contracts.md §작업 계획`).

#### (3) 피드백 기록 `feedback/<YYYY-MM>/<JIRA-KEY>-<timestamp>.yaml`

```yaml
jira: ABC-12345
date: 2026-09-27T18:30+09:00           # 계획의 feedback.date (Step 7 저장 시각). 파일명 timestamp도 같은 값. 재적용해도 바뀌지 않는다
by: <GHE 아이디>
suggested:                             # 매처가 제시한 후보 (순위순). signature는 전역 키
  - {cause: DATA-001-02, signature: DATA-001-02/roaming-disabled, score: 0.92}
  - {cause: DATA-001-01, signature: DATA-001-01/data-disabled,    score: 0.41}
decision: accepted                     # accepted | chose-other | new-cause | new-type | unresolved | manual
final: DATA-001-02
```

- analyze의 `suggested`는 `db_pr stage`가 `JOB/match.json` 후보(`cause`가 있는 것, 순위순 `{cause, signature, score}`)로 채운다. 계획에는 `[]`로 두고, 직접 적은 값이 match.json과 다르면 stage가 거부한다. match.json이 없으면 `[]` 그대로다(`contracts.md §3.2` `stage`).
- 수동 기록(`record`)은 `decision: manual`, `suggested: []`로 쓴다. 매처가 제시한 후보가 없으므로 **시그니처 수락률·1위 정확도 통계에서 제외**한다 (`06-collaboration.md §6.5`).

- 분석이 PR로 끝나면 같은 PR에 들어간다. 항상 새 파일이므로 충돌하지 않는다.
- **pending 피드백**: `decision: manual`(record) 피드백은 취소 시 보관하지 않고 버린다. `--dry-run`은 어떤 흐름이든 pending을 만들지 않는다(연습용 샘플 Jira의 피드백이 실제 PR에 섞이지 않게). 그 밖에는 사용자가 push를 취소하면 `final`이 **이미 main에 있는 원인 ID이거나 `unresolved`일 때만** `~/.telephony-triage/pending-feedback/`에 보관한다 (새 원인/유형은 존재하지 않는 ID를 가리키므로 버린다).
  - 보관된 피드백은 **analyze 계획의 PR에만** 함께 올린다(Step 8, 그 계획의 `sync-pr` 재적용). `db_pr stage`는 계획 `source`가 `analyze`일 때만 pending을 포함한다(`contracts.md §3.2` `db_pr.py` 세부). `record`, `verify-fix`, `validate --cause`, `fix-submitted`, 리뷰 PR 같은 analyze가 아닌 계획에는 넣지 않는다. 이것은 "PR 하나에 Jira 하나" 규칙의 예외다 (`contracts.md §브랜치`).
  - 같은 Jira의 작업 계획을 **만들거나 재개하면**(analyze 새로 시작·이어서 하기, record 모두) 그 Jira의 pending 피드백은 지운다 (그 계획의 피드백이 대신한다. 옛 pending과 새 피드백이 같은 PR에 이중으로 들어가지 않게).
  - push가 성공하면 PR에 포함된 pending 파일을 `<work_dir>/<작업 키>/included_pending/`으로 옮기고 작업 계획의 `included_pending`에 PR 번호와 함께 기록한다 (`db_pr publish`). `sync-pr`로 재적용할 때 이 사본을 다시 포함한다.

#### (4) 작업 계획 `plan.json` (로컬 전용, 커밋하지 않음)

analyze Step 7까지의 결정은 이슈 DB를 바로 바꾸지 않고 **작업 계획**으로 저장한다. Step 8에서 최신 main 위에 이 계획을 적용한다. 형식, op 표, 임시 ID 규칙은 **`contracts.md §작업 계획`** 에만 있다. 스키마는 `schema/plan.schema.json`.

### 5.5 규칙 요약

- 유형 ID는 `<id_prefix>-<3자리>`, 원인 ID는 `<유형 ID>-<2자리>`다. `id_prefix`는 `issue-db.config.yaml`의 카테고리 설정을 따른다.
- **ID는 한 번 main에 들어가면 바꾸지 않는다.** 머지 전에는 적용 시점 할당(`sync-pr` 재적용 포함)으로 바뀔 수 있다 (`06-collaboration.md §6.2`).
- **유일한 예외**: 머지 간격 때문에 main에 같은 ID가 두 번 들어온 경우, 나중에 추가된 쪽을 사후 정리 PR로 다음 빈 ID로 옮긴다. v1은 메인테이너가 직접 편집으로 한다 (`06-collaboration.md §6.3` 사후 lint 정리 정책).
- 폐기와 병합은 삭제하지 않고 `status`로 표시한다: 유형은 `deprecated | merged-into:<유형 ID>`, 원인은 `deprecated | merged-into:<원인 ID>`. 매처는 `active`만 후보로 쓰고, `search`는 옛 ID를 새 ID로 연결해서 보여준다 (연결 출처: `contracts.md §renumber 참조`).
- README의 `1-1`, `1-2` 같은 번호는 표시용이며 순서에서 자동 생성된다.
- 시그니처 의미는 `04-parser-matching.md §5.11`을 따른다.
- **증상 문장 검색**: `search`는 문장을 그대로 받아 질의 전체의 부분 일치(옛 동작)를 먼저 보이고, 이어서 단어로 쪼개 찾는다. 불용어("이런 이슈 있었어")·조사·부정 접두("안붙어")를 떼고, `GLOSSARY.md`의 `## 검색 별칭`(메인테이너 리뷰)으로 별칭을 더한다. 위치별 가중치(ID·제목·태그 > 요약·원인 설명·해결책 > 증상 본문·상위 유형·Jira)로 맞은 단어 수·점수 순위를 낸다. 이 순위는 검색용이며 분류·매칭에는 쓰지 않는다.

### 5.6 README 인덱스 (사람이 보는 화면)

`db_build.py`가 `type.md`와 `jira/*.yaml`로부터 생성한다. Jira 키는 `jira_base_url` 링크로, 유형 제목은 해당 `type.md` 링크로 만든다.

루트 `README.md` 예:

```markdown
# Telephony Issue DB

> 자동 생성 파일입니다. 직접 수정하지 마세요. (`db_build.py`, generator v1)
> 기준일: 2026-09-27 · schema v1 · [통계](STATS.md) · [시작하기](docs/getting-started.md) · [기여 방법](CONTRIBUTING.md)

## 요약
| 카테고리 | 이슈 유형 | 원인 | Jira | 수정 필요(open) |
|---|---|---|---|---|
| [Data](#data) | 2 | 5 | 18 | 1 |
| [Call](#call) | 2 | 4 | 9 | 2 |
| [Network](#network) | 1 | 1 | 1 | 0 |
| [SIM](#sim) | 1 | 2 | 3 | 0 |
| [SMS](#sms) | 1 | 1 | 2 | 0 |
| [IMS](#ims) | 1 | 2 | 4 | 1 |

## 최근 추가 (10건)
| 날짜 | Jira | 분류 |
|---|---|---|
| 2026-09-20 | ABC-333 | DATA-001-02 Roaming disabled |

---

## Data

### 1. [SETUP_DATA_CALL이 발생하지 않음](data/DATA-001-no-setup-data-call/type.md) `DATA-001`
데이터 연결이 필요한 상황인데 RIL로 SETUP_DATA_CALL 요청이 나가지 않는다

| # | 원인 | 해결책 | 유형 | 수정 상태 | Jira |
|---|---|---|---|---|---|
| 1-1 | Data disabled | 모바일 데이터 설정을 켠다 | user-setting | not-a-bug | 2건: [ABC-111](…), [ABC-222](…) |
| 1-2 | Roaming disabled | 데이터 로밍 설정을 켠다 ⚠ 미검증 | user-setting | not-a-bug | 1건: [ABC-333](…) |

원인 미확정: [ABC-444](…)

- 자주 실패한 스텝: Data 켜기 (3건); Roaming 켜기 (1건)

## Call

### 1. [VoLTE가 동작하지 않음](call/CALL-001-volte-not-working/type.md) `CALL-001`
| # | 원인 | 해결책 | 유형 | 수정 상태 | Jira |
|---|---|---|---|---|---|
| 1-1 | IMS 미등록 ↔ IMS-001-01 | ... | carrier-config | fixed ✅ BUILD_X 검증 | 3건: … |

## Network
...

## SIM
...

## SMS
...

## IMS
...

## 보관
(deprecated / merged-into 유형과 원인. 옛 ID → 새 ID 표 포함)
```

- 유형에 `failed_step`이 있는 Jira 기록이 있으면 카테고리 README 유형 절 끝에 `- 자주 실패한 스텝: <스텝> (N건); …` 한 줄을 더한다(공백·대소문자를 무시해 묶고, 많은 순 → 키 순 상위 3개, 표시는 묶음 안 원문의 최솟값 80자). 하나도 없으면 줄을 만들지 않는다. STATS는 바뀌지 않는다.

- 카테고리는 **건수가 0이어도** 요약표 행과 섹션을 남기고, 섹션에는 "아직 등록된 이슈가 없습니다"를 쓴다.
- Jira는 최근 `jira_inline_max`건만 표에 링크하고, 전체 건수와 유형 디렉토리의 `jira/` 링크를 함께 둔다.
- `related`가 있으면 원인 셀에 `↔ <원인 ID>`로 표시한다.
- 해결책이 미검증이면 해결책 셀에 `⚠ 미검증`을 붙인다. 수정 상태 셀은 `fix-submitted ⏳ <브랜치>[:<빌드>]`, `fixed ✅ <빌드> 검증`처럼 검증 여부를 함께 보여준다.
- 카테고리 `README.md`는 같은 표에 증상 시그니처 요약, `code_refs`, `android_versions`(빈 목록은 "전 버전")를 추가한 상세판이다.

### 5.7 신규 유형/원인 추가 지침 (필수 준수)

새 이슈 유형이나 원인은 **플러그인이 추가하든 사람이 추가하든** 아래 형식을 따른다. 이 지침은 `CONTRIBUTING.md`와 `reference/db-authoring.md`에 그대로 넣는다.

#### (1) 무엇을 추가할지 판단

| 상황 | 추가 대상 | 계획 op |
|---|---|---|
| 증상도 원인도 기존과 같음 | Jira 기록만 추가 | `append` |
| 증상은 같고 원인이 다름 | 기존 유형에 **새 원인** | `new-cause` |
| 증상 자체가 기존에 없음 | **새 유형** + 첫 원인 | `new-type` |
| 증상은 맞지만 원인 미확정 | `cause: unresolved`인 Jira 기록 | `unresolved` |
| 이미 있는 Jira를 다른 원인으로 | Jira 파일 이동 | `reclassify` |

- 사용자가 이미 스스로 해결해서 분석 없이 히스토리만 남길 때는 `/telephony-triage:record`로 같은 op를 만든다 (`07-workflow.md §record`). 판단 기준과 작성 규칙은 이 절과 같다.

- 새 유형을 만들기 전에 **전체 카테고리**에서 제목 유사도, 용어집 표준어, 증상 시그니처 중복을 검사하고 유사 유형 상위 3개를 보여준다 (`db_add.py similar`). 비슷한 증상이 있으면 새 원인으로 넣는다.
- 카테고리가 애매하면 5.1의 **카테고리 경계** 표에 따라 주 카테고리를 정하고, 나머지는 `secondary_categories`와 `related`로 연결한다 (5.10). 어디에도 맞지 않으면 `06-collaboration.md §6.10`.
- 전체 op 목록은 `contracts.md §작업 계획`.

#### (2) 작성 규칙

| 항목 | 규칙 | 좋은 예 | 나쁜 예 |
|---|---|---|---|
| 유형 `title` | **증상**, "~하지 않음 / ~됨" 형태, 30자 이내, GLOSSARY 표준어 사용 | SETUP_DATA_CALL이 발생하지 않음 / VoLTE가 동작하지 않음 / 통화 중 콜이 끊김 | DataNetworkController 버그 / APN 문제 |
| 유형 `summary` | 증상 한 문장 | 데이터 연결이 필요한 상황인데 RIL로 SETUP_DATA_CALL 요청이 나가지 않는다 | (비워둠) |
| 원인 `title` | **원인** 명사구, 20자 이내 | Data disabled / Roaming disabled / IMS 미등록 | 설정 문제인 듯 |
| 원인 `description` | 왜 그 증상이 나는지 한 문장 | 로밍 중인데 데이터 로밍 설정이 꺼져 있음 | |
| `resolution` | **행동 지시 1~2문장**, "~한다"로 끝냄. 워크어라운드면 앞에 `[WA]` | 데이터 로밍 설정을 켠다 / `[WA]` 비행기 모드를 껐다 켠다 | 확인 필요 / 수정함 |
| `resolution_type` | 허용 값 중 하나 (`contracts.md §상태 값`) | user-setting, carrier-config, framework-bug, vendor-ril, modem, network, hw | etc |
| `fix.status` | 허용 값 중 하나. `fix-submitted`면 `ref`와 `fixed_in`(브랜치 필수, 빌드 선택) 필수, `fixed`면 여기에 더해 `verification`(result: passed) 필수. **새 원인은 `fixed`로 시작할 수 없다** (verify-fix를 거쳐야 함, 검사 범위는 5.9 아래) | fix-submitted + CL 링크 + 브랜치[:빌드] | 검증 없이 fixed |
| `resolution_verification` | 새 원인과 `resolution`을 바꾼 원인은 `unverified`로 시작. `verified`로 바꾸는 것은 `verify-resolution` op뿐이고 evidence(Jira 또는 `resolved` fixture) 필수. 같은 계획에서 `new-cause` 뒤에 `verify-resolution`이 오면 새 원인도 `verified`로 들어갈 수 있다. 기록 대상 Jira 자신은 evidence가 될 수 없고, 사용자 진술뿐이면 `unverified` + "근거: 사용자 진술"(새 원인은 `method`, 기존 원인은 Jira `note`) | `{status: verified, evidence: [ABC-222]}` | 근거 없이 verified, 기록하는 Jira 자신을 evidence로 |
| `recovery_signatures` | 해결되면 나타나야 하는 **이 원인에 특정한** 정상 흐름. 원인의 계기가 풀리는 이벤트와 정상 동작을 `sequence`로 묶는다. 그 카테고리 음성 fixture(정상 로그) 전부에 맞으면 R1 흔적 검사에서 실패한다(`05-verification.md §5.12 (1)`). 코드·설정 수정 유형(framework-bug, vendor-ril, modem, carrier-config)은 권장 | `must_event: [{id: on, event: data_setting_changed, fields: {enabled: 'true'}}]` + `must_match: [{id: setup, pattern: 'RILJ.*>\s*SETUP_DATA_CALL'}]`, `sequence: [on, setup]` | 원인 시그니처의 단순 부정, 정상 로그면 어디에나 맞는 동작만(예: `SETUP_DATA_CALL` 요청만) |
| `scenario_signatures` | 재현 시나리오 수행 흔적. 코드·설정 수정 유형은 **`fixed` 전환 전에 `scenario_signatures`나 `recovery_signatures` 중 하나가 필수** (`05-verification.md §5.12 (2)`) | 데이터 연결 시도 평가 로그, 발신 요청 로그 | 원인 시그니처 복사 |
| 시그니처 | 증상용/원인용 분리. **새 유형/원인은 판별 시그니처 필수**. 예외는 `record`에서 사용자가 명시한 **원인의** `signatures_pending: true`뿐이다(경고, 리뷰 대상, 원인 판별 불가, 해결책 unverified 고정. `sync-pr` 재적용에서는 유지된다). **새 유형의 증상 시그니처는 예외 없이 필수**. **마스킹된 로그 기준으로** 실제 확인한 문구로만 작성. 원본 식별자(IMSI, 전화번호, 셀 ID 등) 패턴 금지(`db_lint`, extractor 패턴 포함). 반복되는 복잡한 패턴은 extractor + `must_event` | `must_event: data_evaluation_rejected` | `.*error.*` 같은 광범위 패턴, 마스킹될 값에 의존, 시그니처를 비운 채 pending 표시 없음 |
| Jira 기록 | `templates/jira.yaml`의 필수 필드 모두 기입 | | key만 기입 |
| 유형 디렉토리명 | `<유형 ID>-<영문 kebab-case 요약>` | `DATA-001-no-setup-data-call` | `data이슈` |
| 로그 예시 | 마스킹 후 5~15줄, 본문 "원인별 상세"에만 | | frontmatter에 로그 원문 |
| fixture | 원인마다 양성 1개 이상(없으면 `db_lint` 경고, R1·R2 `skipped: fixture 없음`, 리뷰 대상), 판별에 필요한 최소 구간(20~100줄), 마스킹. 이름은 `contracts.md §fixture` | `fixtures/DATA-001-02.log` | 전체 logcat, `DATA-001-02-fixed.log` 같은 규칙 밖 이름 |
| `code_refs` | `<root 키>:<상대 경로>` + `symbol`(클래스#메서드 또는 함수명). 절대 경로 금지. 버전마다 경로가 다르면 항목을 나누고 `android_versions`로 구분 | `aosp:frameworks/opt/telephony/.../DataNetworkController.java` + symbol | `/home/user/android16/frameworks/...` |
| 본문 재현 시나리오 | 원인별 상세에 "재현 시나리오"(동작 순서, 조건)를 적는다. verify-fix가 이것을 사용자에게 보여준다 | 로밍 SIM 삽입 → 데이터 로밍 OFF → 데이터 사용 앱 실행 | (비워둠) |

- 원인이 확정되지 않았으면 원인을 만들지 않고 `unresolved`로 기록한다. 추정만으로 원인을 만들지 않는다.

#### (3) 템플릿

`db_add.py`는 **반드시 `templates/`로만** 생성한다.

`templates/type.md`:

````markdown
---
id: {{TYPE_ID}}
category: {{CATEGORY}}
secondary_categories: []
title: {{증상, ~하지 않음/~됨}}
summary: {{증상 한 문장}}
status: active
symptom_signatures:
  - id: {{kebab-case}}
    must_match: ['{{정규식}}']          # 또는 must_event
    must_not_match: []
    window_sec: 60
causes:
  - id: {{TYPE_ID}}-01
    status: active
    title: {{원인 명사구}}
    description: {{원인 한 문장}}
    signatures:
      - id: {{kebab-case}}
        must_match: ['{{정규식}}']      # 또는 must_event
        window_sec: 60
    recovery_signatures: []           # framework-bug/vendor-ril/modem/carrier-config면 권장
    scenario_signatures: []           # 위 유형은 fixed 전환 전 recovery/scenario 중 하나 필수
    # signatures_pending: true      # record에서 사용자가 명시할 때만. signatures를 비울 수 있음 (contracts.md §상태 값)
    resolution: {{행동 지시, ~한다}}
    resolution_type: {{user-setting|carrier-config|framework-bug|vendor-ril|modem|network|hw}}
    resolution_verification: {status: unverified}
    fix: {status: {{open|fix-submitted|wont-fix|not-a-bug}}, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null                 # 모뎀 쪽 원인이면 CP 근거 요약 (선택, 마스킹 대상)
    android_versions: []              # 빈 목록 = 전 버전
    code_refs: []
tags: []
---

## 증상
{{사용자 관점 증상, 재현 조건}}

## 증상 판별 방법
{{증상 시그니처 설명 + 마스킹된 로그 예시}}

## 원인별 상세
### {{TYPE_ID}}-01 {{원인 title}}
- **로그 예시**:
  ```
  {{마스킹된 로그 5~15줄}}
  ```
- **확인 방법**: {{어떤 로그/설정/코드를 보면 이 원인으로 확정되는지}}
- **재현 시나리오**: {{동작 순서와 조건}}
- **해결책**: {{resolution 상세}}
- **코드 위치**: {{code_refs 설명}}
- **비고**: {{버전/캐리어 특이사항}}
````

`templates/cause.yaml`:

```yaml
  - id: {{TYPE_ID}}-{{NN}}
    status: active
    title: {{원인 명사구}}
    description: {{원인 한 문장}}
    signatures:
      - id: {{kebab-case}}
        must_match: ['{{정규식}}']
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: {{행동 지시, ~한다}}
    resolution_type: {{...}}
    resolution_verification: {status: unverified}
    fix: {status: {{...}}, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    android_versions: []
    code_refs: []
```

새 원인을 추가할 때는 `causes`에 위 블록을 원인 ID 순서대로 넣고, 본문 "원인별 상세"에도 `### <원인 ID> <title>` 섹션을 같은 순서로 추가한다. `db_add.py`는 type.md를 **파싱해서 엔티티 단위로 다시 쓴다** (텍스트 끝에 붙이지 않는다). 본문 섹션은 `### <ID>` 제목으로 식별한다.

`templates/jira.yaml`:

```yaml
key: {{JIRA-KEY}}
cause: {{원인 ID | unresolved}}
date: {{YYYY-MM-DD}}
occurred_on: {{선택, 발생 날짜 YYYY-MM-DD}}
model: {{모델}}
sw: {{빌드}}
android_version: "{{버전}}"
carrier: {{선택}}
analyzed_by: {{GHE 아이디}}
note: {{선택, 한 줄}}
```

#### (4) 추가 후 체크리스트

`db_pr.py stage`(→ drift 검사 → `db_add apply` 후 검사)가 자동으로 확인한다. analyze와 `record`가 같은 검사를 거친다. 사람이 직접 편집해서 기여할 때는 git pre-commit hook(`db_precommit.py`)이 변경분(`--staged`)에 같은 검사를 호출하고, **push 전에 `/telephony-triage:validate`를 실행**해서 전체 회귀와 R1~R5를 확인한다. 담당 스크립트는 괄호 안과 같다.

- [ ] 계획 대상이 계획을 만든 뒤 main에서 바뀌지 않았음, 바뀌었으면 사용자가 결정함 (drift, `db_pr stage`, `contracts.md §작업 계획`)
- [ ] 스키마 검증 통과 (`db_lint`)
- [ ] ID 형식, 접두어, ID 중복 없음, 최신 main 기준 번호 충돌 없음 (`db_lint`, `db_add check-ids`)
- [ ] 같은 Jira 키가 이슈 DB 전체에 하나뿐 (`db_lint`)
- [ ] 작성 규칙과 용어집 검사, 경고 수준 (`db_lint`)
- [ ] 시그니처와 extractor 패턴에 원본 식별자 패턴 없음 (`db_lint`)
- [ ] 새 유형에 증상 시그니처가 있음(필수, 없으면 오류). 새 원인에 판별 시그니처가 있음. 없으면 원인에 `signatures_pending: true`가 있어야 하고(경고), 그 원인은 `resolution_verification: unverified` (`db_lint`)
- [ ] 유사 유형 검사 결과를 사용자에게 보여줌, 새 유형일 때 (`db_add similar`)
- [ ] `related`가 가리키는 원인 ID가 실제로 존재하고 양방향 (`db_lint`)
- [ ] `code_refs`가 `<root 키>:<상대 경로>` 형식이고 root 키가 `code_root_keys`에 있음, 절대 경로 없음 (`db_lint`)
- [ ] `fix.ref`가 `fix_ref_regex`에 맞음 (`db_lint`)
- [ ] 시그니처의 `builtin.*` 참조가 현재 백엔드 `builtin_events()`에, `ext.<category>.*` 참조가 이슈 DB `external_parsers`에 있음 (`db_lint`)
- [ ] 파서 규칙 갱신 (`04-parser-matching.md §5.8`): 필요한 태그/RIL/extractor 존재, 원인별 양성 fixture 존재, fixture 파일명이 규칙에 맞음 (`db_lint`)
- [ ] **전체 fixture 회귀 통과** (`db_regress --all`)
- [ ] 규칙·해결책 변경이면 `05-verification.md §5.12 (1)` 검증 R1~R5 통과 (`db_verify rules`)
- [ ] 새 원인·`resolution` 변경 원인은 `resolution_verification.status: unverified`. 예외는 같은 계획의 `verify-resolution`(evidence 있음)이 적용된 경우뿐이다(근거 없는 verified 금지. `db_pr stage`는 계획을, 계획이 없는 lint는 evidence 존재를 본다). `fixed`는 `verification` 있음, 새 원인 fixed 금지(5.9 아래 범위) (`db_lint`)
- [ ] `.expect.yaml`의 `also_allowed`가 대상 원인 자신·같은 유형 원인·없는 ID를 가리키지 않음 (`db_lint`)
- [ ] `verify-resolution`의 evidence Jira 키가 형식에 맞고 그 원인의 Jira 기록으로 존재하며, fixture 경로가 존재함 (`db_add apply`, `db_lint`)
- [ ] renumber가 있었으면 옛 ID 잔존 없음 (`db_lint --residual`)
- [ ] 마스킹 검사 통과 (`mask_pii --check`)
- [ ] 생성 파일이 `db_build.py` 결과와 정확히 같음, `.cache/`는 커밋 대상에 없음 (`db_build --verify`)

### 5.9 해결 상태와 회귀 판단

원인마다 `fix`로 수정 여부를 추적한다. 허용 값은 `contracts.md §상태 값`.

| `fix.status` | 의미 | 필수 필드 |
|---|---|---|
| open | 원인은 확인됐고 코드/설정 수정이 필요한데 아직 안 됨 | — |
| fix-submitted | 수정 CL이 머지됐고 검증 대기 | `ref`(CL/커밋), `fixed_in`(브랜치 필수, 빌드 선택) |
| fixed | 수정이 **검증까지** 완료 (`05-verification.md §5.12 (2)`) | `ref`, `fixed_in`(빌드 있는 항목 1개 이상, verify-fix 통과의 전제), `verification`(result: passed). 코드·설정 수정 유형은 `scenario_signatures` 또는 `recovery_signatures` |
| wont-fix | 수정하지 않기로 결정 | 본문 비고에 사유 |
| not-a-bug | 사용자 설정/네트워크 등 단말 수정 대상 아님 | — |

분석 시 매처는 원인 후보의 `fix`와 Jira의 `sw`를 비교해서 판단을 붙인다. 비교 규칙은 `issue-db.config.yaml`의 `build_compare`를 쓴다. **"이후"는 같은 빌드를 포함한다(≥)**. `fixed_in`에 빌드가 없으면 비교하지 않고 "판단 불가"로 둔다.

| 조건 | 판단 | 리포트 문구 |
|---|---|---|
| fixed, Jira SW < fixed_in | 이미 수정됨 | "BUILD_X에서 수정됨. 빌드 업데이트 후 재확인 권고" |
| fixed, Jira SW ≥ fixed_in | **회귀 의심** | "수정 빌드 이후(같은 빌드 포함)에서 재발. 회귀 가능성" |
| fixed 또는 fix-submitted, 같은 브랜치 규칙이 없거나 파싱 불가, `fixed_in`에 빌드 없음 | 판단 불가 | 두 값을 나란히 보여주고 사용자에게 판단을 맡긴다 |
| fix-submitted, Jira SW < fixed_in | 수정 대기 빌드 | "수정 CL 반영 전 빌드. 업데이트 후 verify-fix 권고" |
| fix-submitted, Jira SW ≥ fixed_in | **수정 미흡 의심** | "수정 반영 빌드에서 발생. verify-fix 실패 가능성" |
| open | 미수정 | "미수정 원인. 기존 Jira N건" |

- **회귀 의심**(fixed): Step 7에서 사용자 확인 후 `update-fix` op로 `fix.status`를 `open`으로 되돌릴지 묻는다.
- **수정 미흡 의심**(fix-submitted): 원인 시그니처가 충족(C=1)됐으면 재발 근거가 이미 있으므로, Step 7에서 두 선택지를 준다: "`update-fix` → open + 실패 이력 기록"(`history: {result: failed, build, jira}`. 이 로그를 `recurrence` fixture로 추가할지 함께 묻는다) / "이 로그로 `verify-fix` 실행". C=0이면 verify-fix만 제안한다.
- **open으로 되돌릴 때**(`update-fix`, `verify-fix` 실패 공통): 현재 `verification`, `ref`, `fixed_in`을 `verification_history`에 한 항목으로 보존(`result`: verify-fix 실패나 `update-fix`의 `history.result: failed`면 `failed`, 그 밖에 이전 검증이 있으면 `passed`, 없으면 `reverted`)한 뒤 `verification: null`, `ref: null`, `fixed_in: []`로 비운다.
- **수동 기록의 수정 상태**: `record`로 "이미 고쳤다"고 기록해도 `fix-submitted`(`ref`·`fixed_in` 필수)까지만 가능하다. `fixed`는 `verify-fix`로만 한다.
- **fix-submitted 등록**: 수정 CL이 머지되면 누구든 `/telephony-triage:fix-submitted <원인 ID> --ref <CL> --fixed-in <branch>[:<build>]`를 실행한다 (`07-workflow.md §fix-submitted`). 브랜치는 `fix-submit/<원인 ID>`, 커밋 메시지는 `[<원인 ID>] fix-submitted: <ref>`. 빌드가 아직 없으면 브랜치만 넣고, 나중에 같은 커맨드로 빌드를 추가한다. `fixed`로의 전환은 `05-verification.md §5.12 (2)` `verify-fix`로만 한다.

**"새 원인 fixed 금지" 검사 범위** (`db_lint`)
- base ref가 있을 때(`--changed <ref>`의 merge-base, `--staged`의 HEAD, `db_pr stage`의 origin/<base>)만 검사한다. 대상은 **base에 없던 원인** 중 `fix.status: fixed`인 것이다.
- base ref가 없는 검사(`--all`, `--ref`), 레포 초기 커밋(Phase 1 샘플 포함), `migrate/...` 브랜치의 마이그레이션 결과는 예외다.

### 5.10 카테고리 간 연관

- 주 카테고리는 **사용자가 겪는 증상**으로 정한다.
- 다른 카테고리가 원인 쪽이면 원인에 `related: [<다른 원인 ID>]`를 넣고, 유형에 `secondary_categories`를 넣는다. `related`는 양방향으로 넣는다 (`add-related` op는 양쪽을 함께 갱신한다).
- `search`와 매처는 `secondary_categories`와 `related`도 탐색한다. 리포트에는 "관련: SIM-002-01 SIM refresh"처럼 보여준다.
- `secondary_categories`가 있는 유형은 해당 카테고리 오너도 리뷰어로 지정한다 (`gh pr create --reviewer`, 계산 방법은 `02-config.md §5.3` 리뷰어 계산).
