# 16. 기존 사내 자산 활용

사내에 이미 있는 것을 다시 만들지 않고 연결한다. 연결 작업은 **사내에서** 하고, 사외 초안에는 "연결할 자리"와 모의 구현만 만든다 (`15-local-draft.md`).

## 16.1 이미 설정된 Jira MCP 재사용

플러그인은 Jira MCP를 번들하지 않고, 사용자의 Claude Code에 **이미 등록된 서버**를 쓴다.

- **등록 범위**: 플러그인 레포에서 연 세션에서 보여야 하므로 사용자 범위(user scope) 등록이 필요하다. setup이 서버를 못 찾으면 "다른 프로젝트에만 등록돼 있을 수 있음"과 사용자 범위 등록 방법을 안내한다.
- **서버 이름**: 사람마다 다를 수 있으므로 사용자 config `jira.mcp_server`로 처리한다 (`02-config.md`).
- **도구 이름 매핑** (`jira.tools`): MCP 구현마다 도구 이름과 응답 형식이 다르므로, 스킬은 도구 이름을 직접 쓰지 않고 **논리 동작**으로 부른다.

  ```yaml
  jira:
    mcp_server: <서버 이름>
    tools:                                # 논리 동작 → 실제 도구 전체 이름
      get_issue: mcp__<server>__<tool>    # 필수
      search_issues: mcp__<server>__<tool> # 선택 (없으면 search 관련 기능은 키 입력만)
      get_comments: mcp__<server>__<tool>  # 선택 (get_issue가 코멘트를 주면 생략)
    read_tools: [...]                     # guard 허용 목록 = tools 값 + 사용자가 추가 확인한 읽기 도구
    field_map: {...}                      # 응답 필드 → 분석 항목 (기존)
  ```
  - setup이 서버의 도구 목록에서 이름으로 후보를 골라 채우고(get/issue, search, comment 계열), **사용자가 확인**한다.
  - 팀 공용 기본값은 `plugin/site-defaults.yaml`의 `jira.tools`/`jira.field_map`에 둔다. 팀이 같은 MCP 구현을 쓰면 개인 설정은 서버 이름만 확인하면 된다.
  - 응답 형식 차이는 `field_map`의 경로 표기(예: `fields.customfield_10001`, `fields.components[].name`)로 흡수한다. 경로로 표현이 안 되면 `plugin/scripts/adapters/jira_<구현>.py`에 변환 함수를 둔다.
- 사외 모의 Jira MCP(`mock-jira`)는 도구 이름을 일부러 비표준(`jira_fetch_ticket` 등, `15-local-draft.md §15.2`)으로 만들어 매핑 경로를 반드시 거치게 한다.

## 16.2 기존 data 분석 자산 (파서 스크립트 + 이슈 분류 + 분석 스킬)

사내에 data 카테고리용 **로그 파서 스크립트, 이슈 분류, 분석 스킬**이 있다. 세 가지로 활용한다.

| 활용 | 무엇을 | 어디에 | 시점 |
|---|---|---|---|
| **C. 파서 본체로 포팅** | 검증된 기존 파서를 플러그인의 파서 백엔드로 포팅하고, 골든 테스트로 동작을 보존한다 (포팅이 어려우면 어댑터) | 파서 백엔드 (16.3) | 사내 S-4a |
| **A. 분류 가져오기** | 기존 이슈 분류(카테고리·원인·해결책)와 파서의 판별 규칙을 이슈 DB의 data 유형·원인·시그니처 초안으로 옮긴다 | 이슈 DB (`source: import` 계획, 16.4) | 사내 S-4a |
| **B. 심층 분석 연결** | 매칭이 끝난 뒤 data 카테고리면 기존 분석 스킬을 불러 상세 해석을 리포트에 붙인다 | analyze Step 5 뒤 (16.5) | 사내 S-4a, 이후 계속 |

원칙: **분류·회귀·검증의 기준은 항상 결정적인 스크립트 출력**(파서 이벤트, 시그니처 매칭)이다. 분석 스킬(LLM)의 결과는 리포트 보조 정보로만 쓰고, 분류 확정이나 R1~R5, verify-fix 판정에 쓰지 않는다.

## 16.3 파서 백엔드: 기존 검증된 파서를 본체로 포팅 (C)

사내에서 쓰던 로그 파서는 **검증된 자산**이다. 플러그인 파서를 새로 만들지 않고, 이 파서를 **파서 백엔드(본체)** 로 포팅한다. 사외 초안은 공통 처리(reference 백엔드)만 제품 수준으로 만들고, data 판별 로직은 만들지 않는다.

```
parse_logcat.py (플러그인 진입점, contracts.md §3.2 계약 유지)
 └─ 파서 백엔드 인터페이스 (plugin/scripts/parser_backends/base.py)
     ├─ site/       ← 기존 검증된 파서를 포팅 (사내 전용, 사외 레포에 없음)
     └─ reference/  ← 사외 초안의 최소 구현 (모의 환경 테스트용; 구현은 platforms/android/backend.py, 이 경로는 shim)
```

**백엔드 인터페이스** (사외에서 정의, `contracts.md`에 계약 추가)
- `parse(paths, tz, year, window) -> events[]`: 포맷 처리, 시간 정렬, RIL 요청/응답 페어링, 윈도우 자르기
- `builtin_events() -> [이름]`: 코드에 들어 있는 검증된 판별 로직이 내는 이벤트 목록. 이벤트 이름은 `builtin.<category>.<이름>`
- `version() -> str`: 백엔드 버전 (골든·회귀 기준 고정)
- 공통 후처리는 플러그인이 한다: 마스킹(extractor 전), `parser-rules` extractor 실행(`builtin` 이벤트와 합침), 태그 → 카테고리 매핑.
- 백엔드 선택: `site-defaults.yaml`의 `parser.backend: site | reference` (사내는 `site`). 이슈 DB의 `issue-db.config.yaml`의 `parser_backend: {name, min_version}`(`02-config.md §5.3`)과 맞아야 한다. 이름이 다르거나 버전이 낮으면 `config.py check`가 쓰기를 막고(분석은 경고 후 진행), `db_regress`도 결과가 사람마다 달라지지 않도록 멈춘다.
- **이벤트 존재 검사**: `db_lint`는 시그니처의 `must_event: builtin.*`이 현재 백엔드의 `builtin_events()`에 있는지 검사한다(없으면 오류). 매칭 캐시 해시에 백엔드 이름·버전을 포함한다 (`06-collaboration.md §6.8`).
- **reference 백엔드의 역할**: 공통 처리(포맷, 연도·타임존, RIL 페어링, 윈도우)는 **제품 수준**이다(Phase 2 완료 기준). "최소"인 것은 builtin 판별 로직이 없다는 점뿐이다. site 백엔드는 공통 처리를 직접 하거나(기존 파서에 있으면), reference의 공통 처리를 재사용하고 builtin 판별만 더할 수 있다.

**포팅 원칙**
- 기존 파서의 **검증된 판별 로직은 코드에 그대로 두고** `builtin.*` 이벤트로 노출한다. 시그니처는 `must_event: builtin.data.<이름>`으로 참조한다.
- **새로 생기는 유형은 코드가 아니라 `parser-rules`(tags/ril/extractors)로 추가**한다 (`04-parser-matching.md §5.8`). 그래야 팀원이 PR만으로 파서를 발전시킬 수 있다. 기존 로직을 고치는 것은 백엔드 코드 변경이며 메인테이너 리뷰와 골든 갱신 절차를 거친다.
- 출력은 이벤트 형식(`{ts, tag, msg, event, fields, category_hint, source: backend:site}`)으로 맞춘다. 같은 입력이면 항상 같은 출력이어야 한다 (시각·순서·난수 정규화).
- data 외 카테고리(call, network, sim, sms, ims)는 기존 파서가 공통 처리(포맷, RIL 페어링)만 제공하면 되고, 판별은 `parser-rules`로 한다. 기존 파서에 공통 처리가 없으면 reference 백엔드의 공통 처리를 가져다 쓴다.
- **마스킹과의 관계**: 백엔드는 원본 로그(분석)와 마스킹된 fixture(회귀) 양쪽에서 돈다. 기존 판별 로직이 값 비교(셀 변경, 같은 번호 재시도 등)를 하면, 번호 토큰 마스킹(`08-safety.md §8`, `<CELL#1>` ≠ `<CELL#2>`)으로 비교 관계가 보존되는지 확인한다. 값 자체(예: 특정 셀 ID 범위)에 의존하는 로직은 builtin 이벤트의 판별에서 빼고, 필요하면 마스킹 전 단계에서 판별 결과만 이벤트 필드(마스킹 대상이 아닌 값)로 남긴다.

**골든 테스트 (검증된 동작 보존의 핵심)**
1. **포팅 전에** 실제 로그 N개(카테고리별, 정상 포함, data는 기존 파서가 판별하는 경우를 모두 포함)를 기존 파서로 돌려 출력을 저장한다: `tests/golden/<이름>.orig.json` (사내 전용, `SITE_PATHS`).
   - 기존 파서를 **원본 로그와 번호 토큰 마스킹 로그 양쪽**으로 돌려 판별 결과가 같은지 먼저 본다. 다르면 그 판별은 마스킹에 민감한 것이므로, 포팅 시 위 "마스킹과의 관계"대로 처리하고 사용자에게 보고한다.
   - 골든 비교는 마스킹된 로그 기준으로 한다(이슈 DB fixture와 같은 조건).
2. 기존 출력 → 이벤트 형식 변환 규칙(매핑표)을 정하고 사용자 확인을 받는다.
3. 포팅한 백엔드의 결과가 변환된 골든과 **같은지** 비교하는 테스트(`tests/test_golden.py`)를 둔다. 다르면 포팅 버그다. 같은 로그의 원본/마스킹 입력에서 builtin 이벤트 이름과 마스킹 대상이 아닌 필드가 같은지도 검사한다.
4. 의도적으로 바꾼 부분(정렬, 필드 이름 등)은 사용자 승인 후에만 골든을 갱신하고 이유를 `SITE_PROFILE.md`에 기록한다.
5. 이후 백엔드 코드를 바꿀 때마다 골든 테스트 + `db_regress --all` + R5 이벤트 diff를 돌린다.

**대안: 어댑터 방식** (포팅이 어려울 때만)
기존 파서를 수정할 수 없거나 다른 언어라서 포팅 비용이 크면, 기존 파서를 그대로 실행하고 출력만 변환한다.

```yaml
# plugin/site-defaults.yaml (사내 전용)
external_parsers:
  data:
    command: ["python3", "${CLAUDE_PLUGIN_ROOT}/scripts/adapters/site_vendor/<기존 파서>.py", "{log}"]   # 개인 경로가 아니라 플러그인 안(SITE_PATHS)에 둔다. ${CLAUDE_PLUGIN_ROOT}는 parse_logcat.py가 자기 설치 위치로 치환
    output: json
    adapter: site_data_existing     # plugin/scripts/adapters/site_data_existing.py (SITE_PATHS)
    version: <버전 또는 파일 해시>
    mode: merge                     # merge | replace
    timeout_sec: 120
```
이벤트 이름은 `ext.<category>.<이름>`. 결정성·버전 고정·골든 테스트는 포팅 방식과 같다.

어댑터를 쓰는 카테고리는 이슈 DB에도 고정한다 (`contracts.md §기존 자산 연결 계약`):

```yaml
# issue-db.config.yaml
external_parsers:
  data: {adapter: site_data_existing, min_version: <버전>}
```

- 여기 있는 카테고리의 어댑터가 사용자 환경에 없거나 버전이 낮으면 파서 백엔드 불일치와 같이 처리한다: 쓰기 불가(`external-parser-mismatch`), `db_regress` 종료 코드 2, 분석은 경고 후 진행. 사람마다 회귀 결과가 달라지지 않게 하기 위해서다.
- `db_lint`는 이슈 DB `external_parsers`에 없는 카테고리의 `ext.*` 참조를 오류로 본다.
- `--no-external`은 분석 디버그용이고, 회귀·검증은 이 옵션을 받지 않는다.

- 3.1 책임: 백엔드 선택·공통 후처리는 `parse_logcat.py`, 백엔드 인터페이스·선택은 `plugin/scripts/parser_backends/`, 공통 처리 구현은 `plugin/scripts/platforms/android/`, 어댑터는 `plugin/scripts/adapters/`.

## 16.4 기존 분류 가져오기 (A)

기존 분류 자료(문서, 스킬의 지식 파일, 파서의 판별 규칙)를 이슈 DB의 data 유형·원인으로 옮긴다.

1. 사내 Claude Code가 기존 자료를 읽고 **매핑표**를 만들어 사용자 확인을 받는다: 기존 카테고리 → 이 설계의 유형(증상) / 원인, 해결책, 판별 규칙 → 시그니처 초안(`must_event: builtin.data.*`, 어댑터 방식이면 `ext.data.*`, 또는 `must_match`).
   - 기존 분류가 "원인" 위주면 증상별로 묶어 유형을 만든다 (`03-issue-db.md §5.7` 작성 규칙: 유형은 증상, 원인은 원인).
2. 매핑표로 **`source: import` 계획**을 만든다. 규칙은 `record`와 같고 차이는 다음뿐이다.
   - 새 유형·원인 **모두 시그니처 필수** (pending 불가).
   - 한 PR에 유형 여러 개를 넣을 수 있다. 단, 한 PR은 **유형 10개 이하**로 나눈다 (리뷰 가능 크기).
   - 피드백 기록은 만들지 않는다.
   - 해결책은 `unverified`로 시작한다 (기존 자료에 검증 근거 Jira가 있으면 evidence로 넣어 verified).
   - **Jira 기록은 선택**이다. 기존 자료에 Jira 키가 딸려 있어도 import PR에는 넣지 않는 것을 기본으로 한다(Jira를 대량으로 읽으면 사내 토큰이 많이 든다). 필요하면 나중에 `record --cause <원인 ID>`로 건별로 추가한다. 넣을 때는 `jira.tools.get_issue`로 메타데이터를 채우고, Jira 중복 검사를 거친다.
3. 실제 로그(백엔드 builtin 이벤트 포함)로 R1~R5를 돌린다. 양성 fixture가 없는 원인은 `skipped: fixture 없음`으로 두고 리뷰 대상에 올린다.
4. data 카테고리 오너 리뷰 후 머지한다. 브랜치는 `import/<category>-<n>`.

계획 `source` 값 `import`와 브랜치 접두어 `import/`는 `contracts.md §작업 계획·§브랜치·§상태 값`에 있다.

## 16.5 심층 분석 연결 (B)

```yaml
# plugin/site-defaults.yaml 또는 사용자 config
analyzers:
  data:
    skill: <기존 data 분석 스킬 이름>
    when: ask                    # 기본값. ask(1위가 data일 때 묻기) | always(묻지 않고 호출) | never
    inputs: [events_json, log_paths, top_candidates, jira_summary]
    max_tokens_hint: medium
```

- analyze Step 5(코드 분석) 뒤, Step 6 리포트 전에 호출한다. 입력은 파서 이벤트 JSON 경로, 로그 경로, 상위 후보, Jira 요약이다. 원문 로그를 통째로 넘기지 않는다.
- 결과는 리포트의 **"심층 분석 (<스킬 이름>)"** 절에 붙인다. 분류 후보·점수·확정에는 영향을 주지 않는다. 분석 스킬이 다른 원인을 제시하면 "분석 스킬 의견: <내용>"으로 보여주고, 사용자가 Step 7에서 그 원인을 고를 수 있게 한다 (고르면 `decision: chose-other`).
- 스킬이 없거나 실패해도 analyze는 계속한다 ("심층 분석 생략: <사유>").
- **마스킹**: 분석 스킬에는 마스킹된 이벤트와(원문이 필요하면) 로그 경로만 넘긴다. 스킬 출력은 리포트에 넣기 전에 `mask_pii`를 적용하고, PR 본문에는 요약 한두 줄만 넣는다(원문 인용 금지).
- 분석 스킬이 이슈 DB에 없는 원인을 제시하면, 사용자가 고를 때 `new-cause` 흐름(시그니처 초안·검증 포함)으로 간다. 스킬 의견만으로 원인을 만들지 않는다.
- 기본값 `ask`는 1위 후보가 그 카테고리일 때 "심층 분석을 실행할까요? (토큰 추가 사용)"를 묻는다. 사내 토큰이 적으므로 파일럿 동안은 `ask`로 두고, 호출 비율과 유용성을 Phase 14에서 본 뒤 `always`로 바꿀지 정한다.
- analyze 옵션: `--analyzer`는 묻지 않고 호출, `--no-analyzer`는 호출하지 않는다.
- 다른 카테고리도 같은 방식으로 분석 스킬을 붙일 수 있다.
- 분석 스킬은 1위 후보가 있을 때만 호출된다. 후보 없음·원인 미확인일 때의 Claude 가설은 별도 단계인 **탐색 분석**(`07-workflow.md §Step 5-2`, `explore.when`)이 맡는다. 사내에 범용 로그 분석 스킬이 있어도 v1은 탐색 분석을 스킬 본문(`reference/explore.md`)으로 하고, 그 스킬 연결은 S-4a에서 필요성을 본 뒤 정한다.

## 16.6 사외 초안과 사내 작업

- **사외 (Phase D0·2 추가분)**: 파서 백엔드 인터페이스(`base.py`)와 **reference 백엔드**(공통 처리는 제품 수준, builtin 판별 없음), 모의 site 백엔드(`builtin.data.*` 이벤트 1~2개를 내는 가짜), 골든 테스트 틀(`tests/test_golden.py`, 모의 골든으로 동작 확인), 어댑터 예시, 모의 분석 스킬(`tests/mocks/skills/data-analyzer/`), 모의 Jira MCP의 비표준 도구 이름. 모두 테스트 헬퍼 플러그인 루트(`site-defaults.example.yaml` 복사본, `15-local-draft.md §15.1`)에서 돈다.
- **사내 (S-4a, S-4 전에)**:
  1. `jira.tools` 매핑 확정 (S-3에서 해도 됨)
  2. 기존 파서 포팅: **포팅 전 골든 출력 저장** → 이벤트 매핑표 확인 → `parser_backends/site/`로 포팅 → 골든 테스트 통과 → `parser.backend: site` → `db_regress --all`. (포팅이 어려우면 어댑터)
  3. 기존 분류 가져오기: 매핑표 확인 → `import` PR
  4. 분석 스킬 연결: `analyzers.data` 설정, 실제 이슈 1건으로 dry-run
  - 이렇게 하면 S-4에서 **data 카테고리는 규칙을 새로 찾지 않고** 가져온 것을 실제 fixture로 검증만 하면 된다. 다른 카테고리만 S-4 원래 절차로 한다.
