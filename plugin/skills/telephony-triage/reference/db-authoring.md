# 이슈 DB 작성 지침 (새 원인·유형·시그니처·파서 규칙·fixture)

새 원인·유형을 만들거나 시그니처·파서 규칙·해결책을 바꿀 때 읽는다. 이 규칙들은 이슈 DB의 `CONTRIBUTING.md`와 같고,
`db_add apply`·`db_lint`·`db_verify`가 기계적으로 검사한다. 여기서 초안을 규칙에 맞게 만들면 stage에서 되돌아오지 않는다.

목차
1. 무엇을 추가할지 (op 고르기)
2. 작성 규칙
3. 파일 형식 (type.md, 원인, Jira 기록, 피드백)
4. 작업 계획과 op 표
5. 시그니처 의미와 매칭
6. 파서 규칙 (tags / ril / extractors)과 점검 절차
7. fixture 이름과 기대값
8. 검증 R1~R6과 `allow-cause`
9. 수정 상태와 해결책 검증
10. 카테고리 경계와 연관, 용어집
11. 상태 값, 브랜치, 기존 자산 연결

---

## 1. 무엇을 추가할지

| 상황 | 추가 대상 | op |
|---|---|---|
| 증상도 원인도 기존과 같음 | Jira 기록만 | `append` |
| 증상은 같고 원인이 다름 | 기존 유형에 새 원인 | `new-cause` |
| 증상 자체가 없음 | 새 유형 + 첫 원인 | `new-type` |
| 증상은 맞지만 원인 미확정 | `cause: unresolved` Jira 기록 | `unresolved` |
| 이미 있는 Jira를 다른 원인으로 | Jira 파일 이동 | `reclassify` |

- 새 유형을 만들기 전에 **전체 카테고리**에서 유사 유형 상위 3개를 보여준다: `db_add.py similar "<제목>" --db SNAP [--category <c>]`.
  비슷한 증상이 있으면 새 원인으로 넣는 쪽을 권한다.
- 원인이 확정되지 않았으면 원인을 만들지 않고 `unresolved`. 추정만으로 원인을 만들지 않는다.
- 어느 카테고리에도 맞지 않으면 가장 가까운 카테고리 + `tags`로 넣는 안과 새 카테고리 제안 초안을 함께 보여준다. 새 카테고리는
  메인테이너의 직접 편집 PR(`category/<key>`)로만 생긴다(한두 건이면 기존 카테고리로, 같은 성격 유형이 3개 이상 쌓이면 검토).

## 2. 작성 규칙

| 항목 | 규칙 | 좋은 예 | 나쁜 예 |
|---|---|---|---|
| 유형 `title` | **증상**, "~하지 않음 / ~됨", 30자 이내, GLOSSARY 표준어 | SETUP_DATA_CALL이 발생하지 않음 / 통화 중 콜이 끊김 | DataNetworkController 버그 / APN 문제 |
| 유형 `summary` | 증상 한 문장 | 데이터 연결이 필요한데 RIL로 SETUP_DATA_CALL 요청이 나가지 않는다 | (빈칸) |
| 원인 `title` | **원인** 명사구, 20자 이내 | Roaming disabled / IMS 미등록 / APN 불일치 | 설정 문제인 듯 |
| 원인 `description` | 왜 그 증상이 나는지 한 문장 | 로밍 중인데 데이터 로밍 설정이 꺼져 있음 | |
| `resolution` | **행동 지시 1~2문장**, "~한다"로 끝. 워크어라운드면 앞에 `[WA]` | 데이터 로밍 설정을 켠다 / `[WA]` 비행기 모드를 껐다 켠다 | 확인 필요 / 수정함 |
| `resolution_type` | `user-setting \| carrier-config \| framework-bug \| vendor-ril \| modem \| network \| hw` | | etc |
| `fix.status` | 새 원인은 `open \| fix-submitted \| wont-fix \| not-a-bug`만. `fix-submitted`면 `ref`+`fixed_in`(브랜치 필수, 빌드 선택). **`fixed`로 시작 불가** | | 검증 없이 fixed |
| `resolution_verification` | 새 원인·`resolution` 바뀐 원인은 `unverified`. `verified`는 같은 계획의 `verify-resolution`(evidence 필수)뿐 | `{status: verified, evidence: [ABC-222]}` | 근거 없이 verified, 기록 대상 Jira 자신을 evidence로 |
| `recovery_signatures` | 해결되면 나타나는 **이 원인에 특정한** 정상 흐름. 계기가 풀리는 이벤트 + 정상 동작을 `sequence`로. 코드·설정 수정 유형은 권장 | 데이터 설정 ON → 이후 SETUP_DATA_CALL 요청 | 원인 시그니처의 부정, 정상 로그 어디에나 맞는 동작(SETUP_DATA_CALL만) |
| `scenario_signatures` | 재현 시나리오 수행 흔적. 코드·설정 수정 유형은 `fixed` 전환 전 scenario/recovery 중 하나 필수 | 데이터 연결 시도 평가 로그, 발신 요청 로그 | 원인 시그니처 복사 |
| 시그니처 | 증상용/원인용 분리. **새 유형·원인은 판별 시그니처 필수**(예외: record에서 사용자가 명시한 원인 `signatures_pending`). **새 유형의 증상 시그니처는 예외 없음.** 마스킹된 로그에서 실제 확인한 문구로만. 원본 식별자 패턴 금지. 반복되는 복잡한 패턴은 extractor + `must_event` | `must_event: [{event: data_evaluation_rejected, fields: {reasons: '.*ROAMING_DISABLED.*'}}]` | `.*error.*`, 마스킹될 값에 의존, 특정 토큰 번호(`<CELL#1>`) 고정 |
| 유형 디렉토리 | `<유형 ID>-<dir_slug>`, slug는 영문 kebab-case | `DATA-001-no-setup-data-call` | `data이슈` |
| 로그 예시 | 마스킹 후 5~15줄, 본문 "원인별 상세"에만 | | frontmatter에 로그 원문 |
| fixture | 원인마다 양성 1개 이상, 판별에 필요한 최소 구간(20~100줄), 마스킹. 이름은 7절 | | 전체 logcat, 규칙 밖 이름 |
| `code_refs` | `<root 키>:<상대 경로>` + `symbol`(클래스#메서드 또는 함수). 절대 경로 금지. 버전마다 경로가 다르면 항목을 나누고 `android_versions` | `aosp:frameworks/opt/telephony/.../DataNetworkController.java` | `/home/user/android16/...` |
| 본문 재현 시나리오 | 원인별 상세에 동작 순서·조건. verify-fix가 사용자에게 보여준다 | 로밍 SIM 삽입 → 데이터 로밍 OFF → 데이터 앱 실행 | (빈칸) |
| Jira `note` | 사용자가 확인한 한 줄. 사람 이름·고객명·원본 식별자 금지 | 로밍 SIM 테스트 중 발생 | 테스터 홍길동 010-… |

## 3. 파일 형식

### 원인 — 계획 `new-cause`의 `cause` (plan.schema `causeBody`, 여기 없는 필드는 거부된다)

`id`·`status`는 쓰지 않는다(적용 때 할당, `active`). 빠진 필드는 `templates/cause.yaml` 기본값으로 채워진다.

```yaml
title: APN 불일치
description: 캐리어 설정의 APN과 SIM 프로파일이 달라 데이터 평가가 거부됨
signatures:                   # OR. 전역 키 = <원인 ID>/<sig id>
  - id: apn-mismatch
    must_event:
      - {id: rejected, event: data_evaluation_rejected, fields: {reasons: '.*NO_SUITABLE_DATA_PROFILE.*'}}
    window_sec: 60
recovery_signatures: []
scenario_signatures: []
# signatures_pending: true    # record에서 사용자가 명시할 때만
resolution: 캐리어 설정의 APN을 SIM 프로파일에 맞게 고친다
resolution_type: carrier-config
resolution_verification: {status: unverified}      # status는 unverified만. 사용자 진술만 있으면 method: "근거: 사용자 진술"
fix: {status: open, ref: null, fixed_in: []}       # open|fix-submitted|wont-fix|not-a-bug. verification·history는 쓰지 않는다
related: []
cp_evidence: null             # 모뎀 쪽 원인이면 DM/silent log 위치·CP 분석 요약 한 단락 (마스킹 대상)
android_versions: []          # 빈 목록 = 전 버전
code_refs: []                 # [{ref: aosp:<상대 경로>, symbol: Class#method, android_versions?: ["16"]}]
```

### 유형 — 계획 `new-type`의 `type` (허용 필드는 이것뿐)

```yaml
title: <증상>
summary: <증상 한 문장>
symptom_signatures:           # 필수, 1개 이상
  - {id: <kebab>, must_match: ['<정규식>'], must_not_match: [], window_sec: 60}
secondary_categories: []      # 선택
tags: []                      # 선택, kebab-case
```

### 본문(`body`) — 제목 줄은 스크립트가 쓴다
- `new-cause.body`와 `new-type.first_cause.body`: 원인 섹션의 **내용만**. `### <ID> <title>` 제목 줄은 `db_add`가 붙이므로 넣지 않는다.
  내용: `- **로그 예시**:`(마스킹 5~15줄 코드블록), `- **확인 방법**:`, `- **재현 시나리오**:`, `- **해결책**:`, `- **코드 위치**:`, `- **비고**:`.
- `new-type.body`: `## 증상`과 `## 증상 판별 방법`(마스킹 로그 예시)까지만. `## 원인별 상세`는 스크립트가 붙인다.

### 새 원인·유형에도 Jira 기록 op가 따로 필요하다
`new-cause`·`new-type`은 원인·유형만 만든다. 이 Jira의 기록은 **`append {cause: NEW-CAUSE-1}`**(temp_id 그대로)를 함께 넣어야 생긴다.
전형적인 순서: `add-parser-rule`(필요하면) → `new-cause` → `add-fixture {for: NEW-CAUSE-1}` → (`verify-resolution`) → `append {cause: NEW-CAUSE-1}` → (`allow-cause`).

### Jira 기록 `jira/<KEY>.yaml` (op가 만든다)
`key, cause(<원인 ID>|unresolved), date, occurred_on?, model, sw, android_version, carrier?, analyzed_by, note?`.
Jira 요약·설명·코멘트 원문은 어디에도 저장하지 않는다. 재분류는 `reclassify`(파일 이동, note에 `reclassified from <이전>`).

### 피드백 `feedback/<YYYY-MM>/<KEY>-<YYYYMMDDTHHMM>.yaml` (계획 `feedback`에서 만든다)
`{jira, date, by, suggested: [{cause, signature(전역 키), score}], decision: accepted|chose-other|new-cause|new-type|unresolved|manual, final}`.
record는 `suggested: []`, `decision: manual`(수락률·1위 정확도 통계에서 제외).

## 4. 작업 계획과 op 표

위치 `WD/<작업 키>/plan.json`(커밋하지 않음). 필드: `source`(analyze·record·import·fix-submitted·verify-fix·validate-cause·review·move),
`schema_version`, `started_at`, `base_sha`, `jira`(없는 흐름은 null), `operations`, `extra_samples`, `feedback`, `commit_message`,
`pr_notes`(선택, 확인 화면·PR 본문에 붙는 한 줄 설명들), `pr {number, branch, head_sha}`, `included_pending`. 이 밖의 필드는 스키마가 거부한다.
schema 오류 메시지가 잘려 원인이 안 보이면 `python3 -c` 로 `jsonschema`에 `SNAP/schema/plan.schema.json`을 걸어 직접 확인한다.
- 새 원인·유형은 **임시 ID**(`NEW-CAUSE-<n>`, `NEW-TYPE-<n>`)로 쓴다. 적용 때 최신 main 기준 다음 빈 번호로 바뀌고 계획 안 참조(op 필드,
  fixture 경로, 피드백, 커밋 메시지)가 모두 치환된다.
- op는 **순서대로** 적용된다. 같은 대상의 뒤 op가 앞 결과를 바꿀 수 있다(`new-cause` → `verify-resolution`).

| op | 필수 필드 | 규칙 |
|---|---|---|
| `append` | `cause` | 그 원인 유형 디렉토리에 Jira 파일. 같은 Jira가 main에 있으면 중단 |
| `unresolved` | `type` | `cause: unresolved` Jira 파일 |
| `new-cause` | `temp_id`, `type`, `cause`, `body` | `resolution_verification: unverified`로 생성. `fixed` 금지. `signatures`가 비면 `signatures_pending: true` 필요, **source: record만** |
| `new-type` | `temp_id`, `category`, `type`, `first_cause`(`temp_id`·`cause`·`body` 포함), `body`, `dir_slug` | `type.symptom_signatures` 필수(모든 source). 첫 원인은 new-cause 규칙 |
| `reclassify` | `jira`, `from`, `to` | Jira가 main에 **있어야** 함. `to`가 `<유형 ID>:unresolved`면 유형 병합 |
| `update-fix` | `cause`, `fix` (+`history`) | 병합. open으로 되돌리면 현재 verification·ref·fixed_in을 `verification_history`로(`history.result`: failed\|reverted). `fixed`로 바꾸기 금지, `fixed`→`fix-submitted` 거부. `ref`는 `fix_ref_regex` |
| `add-related` | `a`, `b` | 양쪽 `related`에 함께 |
| `add-code-ref` | `cause`, `code_ref {ref, symbol, android_versions?}` | 추가만(기존 항목 수정 없음) |
| `add-parser-rule` | `file`(tags.yaml\|ril.yaml\|extractors.yaml), `rule` | 키가 없어야 함. 이력 필드(`added_for`, `added_on`, `reason`) 필수 |
| `update-parser-rule` | `file`, `key`, `rule` | 키가 있어야 함. 기능 필드 변경 + `reason`·`added_on` 갱신 |
| `update-signature` | `owner`, `kind`(symptom\|cause\|recovery\|scenario), `sig_id`, `signature` | 같은 sig_id면 교체, 없으면 추가. pending 원인에 cause 시그니처가 생기면 pending 해제 |
| `set-resolution` | `cause`, `resolution` | 검증 상태 unverified로 초기화 |
| `verify-resolution` | `cause`, `verification {status: verified, method, evidence[]}` | evidence: 그 원인의 Jira 기록으로 존재하는 키 또는 존재하는 `resolved` fixture. `new-cause`/`set-resolution` **뒤에**. pending 원인 거부. record는 `jira.key` 자신을 evidence로 못 씀 |
| `verify-fix` | `cause`, `result`, `verification {build, date, by, fixture(passed만)}` | passed: `fixed_in`에 그 빌드 필요 → fixed. failed: open + 이력. partial: 상태 유지 + 이력 |
| `set-status` | `id`, `status`(active\|deprecated\|merged-into:<ID>) | 같은 종류끼리. temp_id 대상 가능 |
| `add-fixture` | `for`, `kind`, `path` (+`build`: fixed·recurrence) | `path`는 WD의 마스킹된 파일(`parse_logcat cut` 결과). 이름·번호는 적용 때 정해진다. `negative`의 `for`는 유형 ID |
| `allow-cause` | `fixture`, `cause` | 그 fixture `.expect.yaml`의 `also_allowed`에 추가. 대상 fixture는 양성·recurrence·extra·unresolved 기대값만. 같은 유형 원인·자기 자신 불가. 다른 카테고리 fixture면 그 오너가 리뷰어 |

**drift**(`stage`가 base_sha 이후 main 변경을 볼 때): append·unresolved·add-*·new-cause는 대상이 active가 아니게 됨, new-type은 같은 제목·증상의
유형이 생김, reclassify는 Jira의 cause가 from이 아님, update-fix·verify-fix는 대상 `fix` 변경, set/verify-resolution은 resolution·검증 변경,
update-signature는 같은 sig_id 변경, 파서 규칙은 키 추가/기능 필드 변경, set-status는 status 변경, allow-cause는 fixture 기대값 변경.
항목마다 **계획 값 유지 / main 값 유지(op 삭제) / 직접 입력**을 받는다.

## 5. 시그니처 의미와 매칭

| 필드 | 의미 |
|---|---|
| `must_match: [p...]` | AND. 윈도우 안에 각 정규식이 1줄 이상. 대상 문자열은 `TAG: msg`, `search` |
| `must_event: [{event, fields}]` | AND. 윈도우 안에 각 이벤트 1개 이상. `fields` 값은 정규식 `fullmatch`. 생략하면 존재만 |
| `must_not_match: [p]` | 같은 윈도우에 하나라도 맞으면 불충족 |
| `window_sec` | 조건을 모두 만족하는 길이 `window_sec` 구간이 하나라도 있으면 충족 |
| `same_phone` (기본 true) | 모든 조건이 같은 `phone_id`로 충족. `null`은 와일드카드. DDS 전환처럼 슬롯을 가로지르는 원인만 false |
| `sequence: [id...]` | `must_match`·`must_event` 항목의 `id` 순서대로 첫 충족 시각이 단조 증가 |
| 시그니처 여러 개 | OR |

- 분석 모드: 모든 active 유형의 S → **S=1 유형의 원인만** C. 회귀·검증 모드(`--regress`, db_regress, db_verify): 파일 전체,
  **모든 active 원인의 C를 독립 평가**, bonus 0, 피드백 가중치 끔, 판정은 S/C만.
- 점수(참고): `base = 0.4·S + 0.6·C` + 근접·키워드 보너스(분석 모드만), 피드백 수락률 가중. 신뢰도는 `scoring.confidence`.
- 매처·extractor는 **마스킹된 텍스트**에 돈다. 시그니처는 마스킹 이후 문구 기준으로 쓰고, 토큰은 종류(`<CELL#\d+>`)로만 쓴다.
- 정규식 안전: 중첩 수량자(`(a+)+`), 길이 제한 없는 역참조는 `db_lint`가 거부한다.

## 6. 파서 규칙 (이슈 DB `parser-rules/`)

엔진(`parse_logcat.py`)은 플러그인, 규칙은 이슈 DB에 있다. 그래서 새 유형은 **이슈 DB PR 하나로 유형 + 파서 규칙 + fixture가 함께** 들어간다.
항목은 키로 식별(tags: `tag`/`tag_regex`, ril: `name`, extractors: `id`)하고 이력 필드 `added_for`, `added_on`, `reason`을 가진다.

```yaml
# tags.yaml
- {tag_regex: '^DNC-\d+$', category: data, added_for: DATA-001, added_on: 2026-09-28, reason: 초기}
# ril.yaml (requests / unsolicited)
- {name: SETUP_DATA_CALL, category: data, timeout_ms: 30000, added_for: DATA-001, added_on: ..., reason: ...}
# extractors.yaml
- id: data-evaluation-rejected          # kebab-case, 바꾸지 않는다 (시그니처가 참조)
  tag_regex: '^DNC-\d+$'
  patterns: ['<평가 결과 로그>.*reasons=\[(?P<reasons>[^\]]*)\]']   # 버전별 문구 차이는 여러 패턴
  event: data_evaluation_rejected       # 접두어 없음. builtin./ext. 접두어는 만들 수 없다
  fields: [reasons]
  added_for: NEW-CAUSE-1
  added_on: <오늘>
  reason: <왜>
```

이벤트 이름 공간: extractor 이벤트(접두어 없음, 팀 확장 지점), 파서 백엔드 내장 `builtin.<category>.<이름>`, 어댑터 `ext.<category>.<이름>`
(이슈 DB `external_parsers`에 고정된 카테고리만). RIL 페어링(`ril.yaml` requests에 있는 요청만)은 엔진 예약 이벤트
`ril_error {request, serial, error}`, `ril_timeout {request, serial, latency_ms, timeout_ms}`, `ril_no_response {request, serial, timeout_ms}`를
낸다(extractor가 이 이름을 쓸 수 없다. 필드 값은 문자열).

**새 원인·유형을 계획할 때 점검** (부족하면 op 초안을 만들어 승인받는다):

| 점검 | 부족하면 |
|---|---|
| 새 시그니처가 참조하는 태그가 `tags.yaml`에 있나 | `add-parser-rule tags.yaml` — 없으면 파서가 그 줄을 버려 매칭이 안 된다 |
| 시그니처의 RIL 요청/unsol이 `ril.yaml`에 있나 | `add-parser-rule ril.yaml` (이름, 카테고리, timeout) |
| 구조화된 값(cause 코드, reason, state)이 필요한가 | `add-parser-rule extractors.yaml` 또는 기존 extractor에 패턴 추가(`update-parser-rule`) |
| 원인 fixture가 있나 | `parse_logcat.py cut`으로 판별 근거 주변을 잘라 `add-fixture kind: positive` |
| 전체 fixture 회귀 | stage가 `db_regress --all`. 기존 기대값이 바뀌면 차단·보고 |

- 규칙만으로 표현이 안 되면 원인은 추가하되, 플러그인 레포용 **엔진 개선 요청 초안**(필요 기능, 예시 로그(마스킹), 대상 원인 ID)을 보여준다.
- 기존 extractor를 바꾸면 그것을 쓰는 모든 원인의 fixture 회귀가 통과해야 하고, R5(이벤트 diff)가 "승인 필요"가 될 수 있다.
  `parser-rules/` 변경은 메인테이너 리뷰 필수다.

**fixture 자르기**
- 근거 기반(기존 원인): `parse_logcat.py cut <log> --evidence <match.json> --out WD/<KEY>/fixtures/cut-<n>.log --rules SNAP/parser-rules [--tz --year]`
- 시각 기반(새 원인·유형, resolved/fixed): `parse_logcat.py cut <log> --around <ISO 시각> --seconds 30 --out ...`
- cut은 항상 마스킹된 파일만 쓴다. 자른 fixture가 새 시그니처를 충족하는지는 초안 검증 R1·R2가 본다.

## 7. fixture 이름과 기대값

위치 `<유형 디렉토리>/fixtures/`. 이름은 적용 때 정해진다(번호는 최신 main 기준 다음 빈 번호).

| kind | 파일명 | 기본 기대값 |
|---|---|---|
| positive | `<원인 ID>.log`, `<원인 ID>.<n≥2>.log` | 그 원인 C=1, `also_allowed` 외 다른 모든 active 원인 C=0 |
| fixed | `<원인 ID>.fixed.<build>.log` | `expect_not: <원인 ID>` |
| resolved | `<원인 ID>.resolved.<n≥1>.log` | `expect_not: <원인 ID>` |
| recurrence | `<원인 ID>.recurrence.<build>.log` | 양성과 같음 |
| negative | `<유형 ID>.none.log`, `.none.<n≥2>.log` | 이슈 DB 전체에서 S=1 유형 없음 |
| extra | `<원인 ID>.extra.<n≥1>.log` | 양성과 같음 |

- `.expect.yaml`(같은 이름): `expect_top`, `expect_not`, `also_allowed`, `occurred_at`, `origin: synthetic`.
- `signatures_pending` 원인의 양성 fixture는 `"<유형 ID>:unresolved"` 기대값으로 회귀에 든다.
- `also_allowed`는 **같은 로그에 실제로 두 현상이 있을 때만** 쓴다(예: 데이터 fixture에 등록 거절도 실제로 있음).
- 경로는 유형 디렉토리 기준 상대 경로(`fixtures/DATA-001-03.fixed.BUILD_X.log`)로 참조한다.

## 8. 검증 R1~R6과 `allow-cause`

`db_verify.py rules --plan <plan> --draft <draft>`(초안) / stage 안의 `--plan`(적용 후). 판정은 모두 회귀·검증 모드.

| # | 검사 | 통과 기준 |
|---|---|---|
| R1 | 파서: 대상 시그니처의 태그·이벤트·필드가 양성 fixture에서 실제 추출. 흔적 검사: 새 scenario는 그 원인 양성 fixture에서 충족, scenario·recovery가 그 카테고리 음성 fixture **전부**에서 충족되면 실패 | 추출됨 |
| R2 | 양성: 대상 원인의 양성·recurrence·extra fixture | 그 원인 C=1, 다른 모든 active 원인 C=0(also_allowed 제외) |
| R3 | 음성: (원인) 음성 fixture, 같은 카테고리 다른 원인 양성 fixture(다른 유형 포함), 대상 원인의 fixed·resolved. (증상) 이슈 DB **모든** 음성 fixture | 원인 C=0 / 유형 S=0 |
| R4 | 교차 회귀: 전체 fixture | 모든 기대값 유지 |
| R5 | 이벤트 diff(파서 규칙 변경 시) | 기존 이벤트 사라짐·변경 없음(추가만). 아니면 **needs-approval**(종료 코드 3, 메인테이너 승인) |
| R6 | 추가 표본(선택): `extra_samples` + `--extra`/`--extra-normal` | 같은 증상 로그는 대상 원인 매칭, 정상 로그는 S=0. fail이어도 사용자가 진행을 고를 수 있다 |

- 상태: `pass | fail | needs-approval | skipped`. `skipped`는 사유 필수(`해당 없음`, `fixture 없음`, `음성 fixture 없음`,
  `시그니처 없음(pending)`). **`fixture 없음`·`음성 fixture 없음`은 통과가 아니다** — "검증 못 함 — 리뷰 대상"으로 표시한다.
- 해결책만 바뀌면 R1~R5는 `skipped: 해당 없음`, 검증 상태만 unverified로.
- **R3·R4가 다른 유형의 양성 fixture에서 새 시그니처가 C=1이 됐다고 할 때**(결과에 `allow-cause` 초안이 딸려 온다):
  - (a) **시그니처 좁히기**: 그 fixture와 걸린 시그니처 전역 키를 보여주고, 대상 원인 fixture에만 있는 조건(`must_not_match`, 더 구체적인
    `fields`, `sequence`)을 더한 안을 제시한다. 다시 초안 검증.
  - (b) **허용**: 그 로그에 실제로 두 현상이 다 있으면 `allow-cause {fixture, cause}`를 계획에 넣는다. 그 fixture의 `.expect.yaml` 변경이
    확인 화면 변경 파일에 나오고, 그 카테고리 오너가 리뷰어에 추가된다. 그 오너가 이유를 알 수 있게 계획 `pr_notes`에
    `allow-cause: <fixture>에 <현상>이 실제로 함께 있음 (<근거 로그 한 줄, 마스킹>)`을 넣는다.
  - 사용자가 고른다. 몰래 좁히지도, 몰래 허용하지도 않는다. 고르기 전에는 push하지 않는다.
- 음성 fixture에 걸린 경우(R3)는 허용 선택지가 없다 — 시그니처를 좁힌다.

## 9. 수정 상태와 해결책 검증

| `fix.status` | 의미 | 필수 |
|---|---|---|
| open | 수정 필요, 아직 안 됨 | — |
| fix-submitted | 수정 CL 머지, 검증 대기 | `ref`, `fixed_in[{branch, build?}]` |
| fixed | 수정이 **검증까지** 완료 | + 빌드 있는 `fixed_in`, `verification(result: passed)`. 코드·설정 수정 유형은 scenario/recovery |
| wont-fix | 수정하지 않기로 | 본문 비고에 사유 |
| not-a-bug | 단말 수정 대상 아님 | — |

매처의 수정 판단(빌드 비교 `build_compare`, **"이후"는 같은 빌드 포함 ≥**): fixed & SW<fixed_in → 이미 수정됨 / fixed & SW≥ → **회귀 의심** /
fix-submitted & SW< → 수정 대기 빌드 / fix-submitted & SW≥ → **수정 미흡 의심** / 빌드 없음·규칙 없음 → 판단 불가 / open → 미수정.

해결책 검증: `unverified`로 시작, `verify-resolution`으로만 verified. 근거는 (1) 해결책 적용 뒤 재현 안 된 **다른** Jira, 또는
(2) `db_verify resolution` passed 로그(`resolved` fixture). 사용자 진술뿐이면 unverified + "근거: 사용자 진술". 미검증 해결책은 리포트·README에 "⚠ 미검증".

## 10. 카테고리 경계와 연관

주 카테고리는 **사용자가 겪는 증상** 기준이다.

| 카테고리 | 범위 |
|---|---|
| data | PDN/데이터 연결, APN, 데이터 콜 setup/teardown, 데이터 retry |
| call | 음성/영상 통화 발신·수신·유지·종료 (CS, VoLTE, VoNR, VoWiFi) |
| network | 망 등록, 서비스 상태, RAT 전환, 셀 선택, 신호 |
| sim | SIM 인식, 가입자 정보, SIM 파일, 멀티 SIM/eSIM |
| sms | SMS/MMS 송수신 (CS SMS, SMS over IMS) |
| ims | IMS 서비스 자체: IMS PDN, 등록/재등록, capability, 설정 |

- "VoLTE 콜이 안 걸림"인데 원인이 IMS 미등록 → 주 카테고리 **call**, 원인 `related: [IMS-…]`, 유형 `secondary_categories: [ims]`.
- 증상 자체가 "IMS 등록이 안 됨" → ims. "SMS over IMS 전송 실패" → sms(원인이 IMS 등록이면 related).
- `related`는 양방향(`add-related`가 둘 다 갱신). `secondary_categories`가 있으면 그 카테고리 오너도 리뷰어.
- 용어: 이슈 DB `GLOSSARY.md`의 표준어를 쓴다(예: "콜이 끊김"(call drop)과 "콜 연결 실패"(call fail) 구분). lint가 금지 동의어를 경고한다.

## 11. 상태 값, 브랜치, 기존 자산 연결

- 유형·원인 `status`: `active | deprecated | merged-into:<ID>`. ID는 main에 들어간 뒤 바꾸지 않는다. 병합·폐기는 status로(삭제 금지).
- 원인 `signatures_pending: true`: record에서 사용자가 명시할 때만. lint 경고, 매칭 불가(후보 유형의 `pending_causes`로만 표시),
  해결책 unverified 고정, 월간 리뷰 대상. `update-signature`로 cause 시그니처가 생기면 해제.
- `verification_history[]`: `{result: passed|failed|partial|reverted, build, date, by, jira?, fixture?, ref?, fixed_in?, note}`, 최신이 위.
- 브랜치(원격 이름, 로컬에는 `tt/<이름>`만): `issue/<KEY>`(analyze, record), `fix-submit/<원인 ID>`, `verify-fix/<원인 ID>-<build>`,
  `verify-res/<원인 ID>-<YYYYMMDD>`, `review/<category>-<YYYY-MM>`, `move/<옛>-to-<새>`, `import/<category>-<n>`. 직접 편집 전용:
  `chore/fix-db-<문제 ID>`, `migrate/schema-v<N>`, `category/<key>`. PR 하나에 Jira 하나(예외: analyze PR의 pending 피드백).
- **Jira 도구 매핑** `jira.tools`: 논리 동작 `get_issue`(필수), `search_issues`·`get_comments`(선택) → 실제 도구 전체 이름. 스킬은 도구 이름을
  직접 쓰지 않는다. `read_tools`(guard 허용 목록)가 그 값을 포함해야 한다. 매핑이 비었으면 추측하지 말고 setup 안내.
- **파서 백엔드**(`site-defaults.yaml`의 `parser.backend: site | reference`): 파싱만 하고, 마스킹·extractor·태그 매핑은 `parse_logcat.py`.
  이슈 DB `parser_backend`와 다르면 쓰기 불가(`config.py check`), 분석은 경고 후 진행("백엔드 불일치 — 결과가 팀 기준과 다를 수 있음").
- **기존 분류 가져오기**(`source: import`): record 규칙과 같되 새 유형·원인 모두 시그니처 필수(pending 불가), PR당 유형 10개 이하, 피드백 없음,
  해결책 unverified로 시작(근거 Jira가 있으면 같은 계획의 `verify-resolution`), 브랜치 `import/<category>-<n>`, 카테고리 오너 리뷰 필수.
- **분석 스킬**(`analyzers.<category>`: `skill`, `when: ask|after_match|always_for_category`, `inputs`): 결과는 리포트 보조 정보일 뿐
  분류·점수·검증에 쓰지 않는다. 스킬이 이슈 DB에 없는 원인을 말해도 그것만으로 원인을 만들지 않는다 — 사용자가 고르면 `new-cause` 흐름(시그니처 초안·검증 포함).
