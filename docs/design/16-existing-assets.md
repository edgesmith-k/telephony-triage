# 16. 기존 사내 자산 활용

사내에 이미 있는 것을 다시 만들지 않고 연결한다. 연결 작업은 **사내에서** 하고, 사외 초안에는 "연결할 자리"와 모의 구현만 만든다 (`15-local-draft.md`).

## 16.1 이미 설정된 Jira MCP 재사용

플러그인은 Jira MCP를 번들하지 않고, 사용자의 Claude Code에 **이미 등록된 서버**를 쓴다.

- **등록 범위**: 플러그인 레포에서 연 세션에서 보여야 하므로 사용자 범위(user scope) 등록이 필요하다. setup이 서버를 못 찾으면 "다른 프로젝트에만 등록돼 있을 수 있음"과 사용자 범위 등록 방법을 안내한다.
- **서버 이름**: 사람마다 다를 수 있으므로 사용자 config `tracker.mcp_server`로 처리한다 (`02-config.md`).
- **도구 이름 매핑** (`tracker.tools`): MCP 구현마다 도구 이름과 응답 형식이 다르므로, 스킬은 도구 이름을 직접 쓰지 않고 **논리 동작**으로 부른다.

  ```yaml
  tracker:
    kind: jira                            # jira | github (18-trackers.md)
    mcp_server: <서버 이름>
    tools:                                # 논리 동작 → 실제 도구 전체 이름
      get_issue: mcp__<server>__<tool>    # 필수
      search_issues: mcp__<server>__<tool> # 선택 (없으면 search 관련 기능은 키 입력만)
      get_comments: mcp__<server>__<tool>  # 선택 (get_issue가 코멘트를 주면 생략)
    read_tools: [...]                     # guard 허용 목록 = tools 값 + 사용자가 추가 확인한 읽기 도구
    field_map: {...}                      # 응답 필드 → 분석 항목 (기존)
    write_tools:                          # 선택. Jira 쓰기는 코멘트 추가 1종뿐 (07-workflow.md §Step 9)
      add_comment: {tool: mcp__<server>__<tool>, key_arg: <이슈 키 인자>, body_arg: <본문 인자>, extra_args: {}, format: jira-wiki}  # read_tools에 넣지 않는다, TODO(SITE:S23)
  ```
  - setup이 서버의 도구 목록에서 이름으로 후보를 골라 채우고(get/issue, search, comment 계열), **사용자가 확인**한다.
  - 코멘트 도구(`write_tools.add_comment`)는 setup이 고르지 않는 팀 기본값이다. 도구 이름·인자를 매핑해 두면 스킬은 `issue_post.py approve` 출력의 도구·인자만 쓰고, guard가 승인 기록(본문 해시·키·30분·1회)과 대조한 뒤 `ask`로 허용한다. 그 밖의 Jira 쓰기(필드 수정·상태 전환·이슈 생성·첨부)는 매핑할 곳이 없고 거부된다.
  - 팀 공용 기본값은 `plugin/site-defaults.yaml`의 `tracker.tools`/`tracker.field_map`에 둔다. 팀이 같은 MCP 구현을 쓰면 개인 설정은 서버 이름만 확인하면 된다.
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
     ├─ reference/  ← 사외 초안의 최소 구현 (모의 환경 테스트용; 구현은 platforms/android/backend.py, 이 경로는 BACKEND 재수출)
     └─ <p>_reference/ ← android 밖 플랫폼의 기본 백엔드 (예: ofono_reference = platforms/ofono/backend.py 재수출, 형식 가정 placeholder)
```

**백엔드 이름 공간(플랫폼별, `17-platforms.md`)**: `reference`·`site`는 android 백엔드다(`ParserBackend.platform` 기본 `"android"`). 다른 플랫폼의 백엔드는 `<플랫폼>_reference`(사외 기본, `SPEC.default_backend`)와 사내 포팅본(예: `<플랫폼>_site`, 사내 전용 `SITE_PATHS`)처럼 이름에 플랫폼을 붙이고 클래스 속성 `platform`에 그 플랫폼 이름을 둔다. 선택은 기본 플랫폼이면 `parser.backend`, 그 밖은 `parser.by_platform.<플랫폼>`(없으면 `SPEC.default_backend`)이고, 불러온 백엔드의 `platform`이 파싱 플랫폼과 다르면 종료 코드 2다. 플랫폼마다 이슈 DB가 따로이므로 그 DB의 `parser_backend.name`도 그 플랫폼 백엔드 이름이다 — 옛 플러그인(플랫폼 선언을 모름)이 oFono DB를 android로 오인해도 백엔드 이름 불일치로 쓰기가 막힌다.

**백엔드 인터페이스** (사외에서 정의, `contracts.md`에 계약 추가)
- `parse(paths, tz, year, window) -> events[]`: 포맷 처리, 시간 정렬, RIL 요청/응답 페어링, 윈도우 자르기
- `builtin_events() -> [이름]`: 코드에 들어 있는 검증된 판별 로직이 내는 이벤트 목록. 이벤트 이름은 `builtin.<category>.<이름>`
- `version() -> str`: 백엔드 버전 (골든·회귀 기준 고정)
- 공통 후처리는 플러그인이 한다: 마스킹(extractor 전), `parser-rules` extractor 실행(`builtin` 이벤트와 합침), 태그 → 카테고리 매핑.
- 백엔드 선택: `site-defaults.yaml`의 `parser.backend: site | reference` (사내는 `site`). 이슈 DB의 `issue-db.config.yaml`의 `parser_backend: {name, min_version}`(`02-config.md §5.3`)과 맞아야 한다. 이름이 다르거나 버전이 낮으면 `config.py check`가 쓰기를 막고(분석은 경고 후 진행), `db_regress`도 결과가 사람마다 달라지지 않도록 멈춘다.
- **이벤트 존재 검사**: `db_lint`는 시그니처의 `must_event: builtin.*`이 현재 백엔드의 `builtin_events()`에 있는지 검사한다(없으면 오류).
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
   - **합성 줄 보충(예외)**: 사내 첨부가 대부분 logcat 덤프라 bugreport 캡처 흔적에만 기대는 판별 경로는 실제 로그에 나오지 않는다. **실제 로그에 없는 판별 경로에 한해서만** 실제 로그에 합성 줄을 보충해 케이스를 만들 수 있고, 그 케이스에는 `synthetic` 표식과 사유를 남긴다(그 골든 JSON `tests/golden/<이름>.golden.json` 최상위에 `"synthetic": {"reason": "<왜 실제 로그에 없는지>"}`, `reason` 필수 — 사내는 `site_checks.py` `s4a.golden`이, 모의 골든은 `tests/test_golden.py`가 검사하고, `test_golden.py --update`는 이 키를 남긴다). 나머지 판별은 모두 실제 로그 기준이다. 골든 비교는 `events`·백엔드 버전만 보므로 이 키가 비교를 바꾸지 않고, 최상위 메타데이터라 골든 변조 점검(`s4a.golden_mutation`)도 바꾸지 않는다(이벤트 안의 같은 이름 필드는 기대값이라 바꾼다).
2. 기존 출력 → 이벤트 형식 변환 규칙(매핑표)을 정하고 사용자 확인을 받는다.
3. 포팅한 백엔드의 결과가 변환된 골든과 **같은지** 비교하는 테스트(`tests/test_golden.py`)를 둔다. 다르면 포팅 버그다. 같은 로그의 원본/마스킹 입력에서 builtin 이벤트 이름과 마스킹 대상이 아닌 필드가 같은지도 검사한다.
   - 사내 골든 테스트(`tests/golden/test_*.py`)는 백엔드를 `real_site_backend` 픽스처(`tests/conftest.py`, `runner.real_site_backend()`)로 받는다. `conftest.py`가 세션 시작 때 임시 플러그인 루트의 `parser_backends`(그 `site/`는 모의 백엔드)를 먼저 불러 두므로 `import parser_backends.site`는 모의를 준다. 픽스처는 실제 `plugin/scripts/parser_backends/site/`를 `parser_backends.site_real`이라는 다른 이름으로 불러와 모의를 쓰는 테스트와 한 세션에서 서로 가리지 않는다(없으면 건너뜀).
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
   - **Jira 기록은 선택**이다. 기존 자료에 Jira 키가 딸려 있어도 import PR에는 넣지 않는 것을 기본으로 한다(Jira를 대량으로 읽으면 사내 토큰이 많이 든다). 필요하면 나중에 `record --cause <원인 ID>`로 건별로 추가한다. 넣을 때는 `tracker.tools.get_issue`로 메타데이터를 채우고, Jira 중복 검사를 거친다.
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
    inputs: [events_json, log_paths, top_candidates, issue_summary]
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

### 16.5.1 분석 스킬 만들기 (분석 스킬이 없는 카테고리)

리포트의 `심층 분석: 해당 없음(1위 카테고리에 분석 스킬 설정 없음)`은 정상 상태다(줄 끝에 이 안내 위치를 붙인다). 분석 스킬은 필요할 때만 만든다. 이슈 DB 독자용 요약은 뼈대의 `docs/analyzer-skills.md`(`tools/make_db_skeleton.py`)에 있다.

- **만들 때**: 다음이 있고 **유지할 오너가 있을 때만** 만든다 — (a) 시그니처(정규식·이벤트·순서)로 표현하기 어려운 판단 순서(여러 단계의 조건 분기, 값 비교), (b) 따라가야 하는 코드 경로, (c) 이슈를 거듭하며 쌓인 점검 목록. 오너가 없거나 시그니처·파서 규칙으로 표현되면 만들지 않는다(규칙은 결정적이고 fixture 회귀로 검증된다, `12-principles.md`).
- **구조**: `SKILL.md`(공통 절차: 입력 읽기 → 판단 순서 → 출력) + `references/<유형 ID>.md`(이슈 유형별 점검 목록·코드 경로, 그 유형일 때만 읽는다) + `analyzer.md`(입출력 계약). 계약은 위 §16.5와 `07-workflow.md §Step 5-1`에 맞춘다:
  - 입력: `inputs`의 `events_json`(마스킹된 이벤트 JSON **경로**), `log_paths`, `top_candidates`(`[{type, cause, score, confidence}]`), `issue_summary`(마스킹된 한두 줄). 원문 로그를 통째로 받지 않는다.
  - 출력: 리포트 `심층 분석 (<스킬>)` 칸에 붙을 요약, 다른 원인이면 `분석 스킬 의견: <원인 ID — 근거>`, 규칙이 필요하면 `규칙 제안:` 줄 아래에 한 줄에 하나씩(제안만 한다). 마스킹된 값만 쓴다. 모의 예: `tests/mocks/skills/data-analyzer/`.
    - 이슈 DB 규칙: `- [이슈 DB] add-parser-rule file=<parser-rules 파일> rule=<규칙> — 근거: <로그 줄·이유>` 또는 `- [이슈 DB] update-signature cause=<원인 ID> … — 근거: …`
    - 분석 스킬 자체 개선(점검 목록·코드 경로 보완): `- [스킬] … — 근거: …`
  - 처리(`07-workflow.md §Step 7`): 분류 확정 뒤 한 번 묻는다(여러 개 가능: 줄마다 선택지 + `모두` + `받지 않음(기본 — 확인 안 한 제안은 반영하지 않으려고)` — 기본값과 그 이유는 질문 머리가 아니라 그 선택지에 표시한다). 고른 `[이슈 DB]` 줄은 스킬이 `db-authoring.md` 점검을 거친 계획 op 초안으로 만들어 보이고, 승인한 것만 `plan.json`에 들어가 다른 작성 op와 같은 초안 검증(`db_verify rules --plan --draft`)·stage 검사를 거친다. 고른 `[스킬]` 줄은 계획·PR·Jira 코멘트에 넣지 않고, 스킬이 그 줄이 가리키는 분석 스킬 파일(Step 5-1 Skill 결과의 스킬 디렉토리 기준)을 읽어 제안을 반영한 사본을 `JOB/skill-suggestions/<스킬 이름>/<rel>`에 쓰고, `skill_patch.py`가 담당자용 unified diff `JOB/skill-suggestions/<스킬 이름>.patch`(경로 `a/<스킬 디렉토리 기준 상대 경로>`, `mask_pii`와 같은 마스킹)를 만들어 고정 안내 줄(`스킬 제안 patch(적용 안 함, 마스킹됨): <경로> — …`)과 파일별 +/− 줄 수를 낸다(스킬은 글자 그대로 보이고 표시 보조 hook이 본다). 담당자가 검토해 자기 스킬 소스에 `git apply`한다. 스킬 디렉토리를 모르거나 파일을 읽지 못하면, 또는 경로가 스킬 디렉토리 밖이거나 마스킹 뒤 원본(임시 사본)에 `git apply --check`가 실패하면(마스킹이 문맥 줄을 바꾼 경우) patch 없이 담당자 메모로만 보인다(`reference/skill-patch.md`). 스크립트는 `규칙 제안:` 줄 자체는 읽지 않는다(사본만 비교한다).
- **description**: telephony-triage 스킬의 트리거 설명(Jira·logcat 분석 요청)과 겹치지 않게 쓴다 — "telephony-triage analyze Step 5-1에서 `analyzers.<카테고리>`로만 부른다"처럼 호출 경로를 좁힌다. 겹치면 사용자의 분석 요청이 이 스킬로 새어 본 흐름(lock·스냅샷·확인 화면)을 건너뛴다.
- **파일을 바꾸지 않는다**: 분석 스킬은 이슈 DB·작업 계획·로그·자기 references를 고치지 않고 규칙을 제안만 한다(`규칙 제안:`). 넣을지는 Step 7에서 사용자가 정한다. `[스킬]` 제안으로 telephony-triage가 만드는 patch도 분석 스킬 디렉토리에 쓰거나 적용하지 않는다 — 적용은 담당자가 한다.
- **검증**: 해결된 실제 이슈(마스킹된 로그)로 스킬 있음/없음을 같은 모델로 비교한다(`10-skill-eval.md` 방식: 1순위 결과 — 의견이 맞는 원인을 가리키는지·제안 규칙이 R1~R5를 통과하는지, 2순위 토큰). 나아지지 않으면 연결하지 않는다.
- **연결·교체·끄기**: 키는 `analyzers.<카테고리>`(`skill`·`when`·`inputs`, `contracts.md §기존 자산 연결 계약`). 팀 기본값은 `site-defaults.yaml`, 개인은 사용자 config(`~/.telephony-triage/config.yaml`, `02-config.md §4`)에 같은 키를 두면 덮어쓴다. `skill`을 바꾸면 교체, `when: never`면 끄기, 한 번만 건너뛰려면 analyze `--no-analyzer`.

## 16.6 사외 초안과 사내 작업

- **사외 (Phase D0·2 추가분)**: 파서 백엔드 인터페이스(`base.py`)와 **reference 백엔드**(공통 처리는 제품 수준, builtin 판별 없음), 모의 site 백엔드(`builtin.data.*` 이벤트 1~2개를 내는 가짜), 골든 테스트 틀(`tests/test_golden.py`, 모의 골든으로 동작 확인), 어댑터 예시, 모의 분석 스킬(`tests/mocks/skills/data-analyzer/`), 모의 Jira MCP의 비표준 도구 이름. 모두 테스트 헬퍼 플러그인 루트(`site-defaults.example.yaml` 복사본, `15-local-draft.md §15.1`)에서 돈다.
- **사내 (S-4a, S-4 전에)**:
  1. `tracker.tools` 매핑 확정 (S-3에서 해도 됨)
  2. 기존 파서 포팅: **포팅 전 골든 출력 저장** → 이벤트 매핑표 확인 → `parser_backends/site/`로 포팅 → 골든 테스트 통과 → `parser.backend: site` → `db_regress --all`. (포팅이 어려우면 어댑터)
  3. 기존 분류 가져오기: 매핑표 확인 → `import` PR
  4. 분석 스킬 연결: `analyzers.data` 설정, 실제 이슈 1건으로 dry-run
  - 이렇게 하면 S-4에서 **data 카테고리는 규칙을 새로 찾지 않고** 가져온 것을 실제 fixture로 검증만 하면 된다. 다른 카테고리만 S-4 원래 절차로 한다.
