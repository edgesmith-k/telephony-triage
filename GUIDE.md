# telephony-triage 총정리 가이드

> 사람이 읽는 요약입니다. Claude Code가 따르는 상세 지침은 `CLAUDE.md`와 `docs/design/`에 있습니다.

## 1. 무엇을 만드나

| 구성 | 설명 |
|---|---|
| **플러그인** `telephony-triage` | Claude Code에 설치하는 도구. Jira + logcat으로 이슈를 분석하고, 결과를 이슈 DB에 PR로 올린다 |
| **이슈 DB** `telephony-issue-db` | 사내 GitHub 레포. 카테고리(data/call/network/sim/sms/ims) > 이슈 유형(증상) > 원인 + 해결책 + Jira 이력. README가 사람이 보는 목록 |

한 줄 흐름: **Jira + 로그 → 파서(이벤트) → 시그니처 매칭 → 원인·해결책 제시 → 사용자 확인 → 이슈 DB에 PR → 리뷰어 머지**

---

## 2. 전체 진행 순서

```
[사외 PC]                                  [사내]
Phase D0  모의 환경 구축                    S-1  사내 값 조사 → SITE_PROFILE.md
Phase 1~13 모의 환경으로 전부 구현           S-2  사내 Claude Code 동작 확인
반입 체크리스트                   ──반입──▶  S-3  사내 설정 입력 (site-defaults.yaml)
                                           S-4a 기존 자산 연결 (파서 포팅·분류 import·분석 스킬)
                                           S-4  나머지 카테고리 실제 로그 반영
                                           S-5  실전 시험 (dry-run, 샌드박스 PR)
                                           S-6  남은 검토 항목 정리
                                           S-7  배포 + 파일럿
```

원칙: **구현은 사외에서 최대한, 사내는 끼워 맞추기만.** 사내 값과 사내 코드는 `SITE_PATHS`에 적힌 경로(`site-defaults.yaml`, `SITE_PROFILE.md`, 포팅한 파서, 골든 등)에만 둡니다. 사외 코드를 다시 반입할 때는 **통째로 교체하지 말고** `tools/import_draft.py`로 덮어쓰면 이 경로들은 보존됩니다. 실행 환경은 **Ubuntu**입니다(다른 OS 미지원).

플러그인 코드는 사내/사외를 판별하지 않습니다. `plugin/site-defaults.yaml`(S-3에서 만들고 사내 깃헙에 커밋)이 있으면 그 값으로 동작하고, 없으면 모든 커맨드가 "사내 기본값 없음"으로 멈춥니다. 사외 테스트는 `site-defaults.example.yaml`을 복사한 임시 플러그인 루트로만 돌아갑니다.

---

## 3. 사외 PC에서 만들기

### 준비
1. `telephony-triage-docs.zip`을 풀어 빈 폴더(플러그인 레포 루트)에 둔다.
2. 그 폴더에서 Claude Code를 연다.

### 진행 (세션마다 한 Phase 정도)
| 입력 | 결과 |
|---|---|
| `사외 초안 모드로 Phase D0부터 시작해` | 가짜 Jira MCP(`mock-jira`), 가짜 GitHub(로컬 원격 + `gh` 흉내), 합성 logcat, 가짜 소스 트리, 가짜 기존 파서 백엔드·분석 스킬, 재반입 도구(`SITE_PATHS`, `import_draft.py`) |
| `다음 Phase 진행해` (반복) | Phase 1~13. 끝날 때마다 완료 기준 점검 후 확인 요청 |

- 파서는 **인터페이스 + 공통 처리(참고 구현)** 까지만 만든다. data 판별은 사내에서 검증된 기존 파서를 포팅해서 넣는다.
- SKILL.md는 Phase 13에서 skill-creator로 만들고 eval 45개를 모의 환경으로 통과시킨다.
- 진행 상태는 `DRAFT_NOTES.md`에 기록되므로 세션을 끊고 이어가도 된다. D0에서 사외 PC에만 두는 표식 `.local-draft`를 만들므로, 이후 세션은 모드를 다시 묻지 않는다.
- 합성 샘플 이슈 DB는 플러그인 레포 테스트 데이터(`tests/fixtures/issue-db-sample/`)로만 쓴다. 반입할 이슈 DB는 `tools/make_db_skeleton.py`로 만든 **뼈대**(합성 샘플 없음)다.

### 반입 전
```
반입 체크리스트(15-local-draft.md §15.4) 확인하고 DRAFT_NOTES.md 갱신해줘
```
- 테스트 전부 통과, `site-defaults.yaml` 없음, `.local-draft`·`.mcp.json`이 반입 묶음에 없음, 이슈 DB 뼈대 생성, `TODO(SITE:...)` 목록 정리를 확인한다.
- 사내 **외부 작성 코드 반입 규정**(오픈소스 의존성 승인 포함)을 확인한 뒤 플러그인 레포 + 이슈 DB 뼈대를 반입한다.

---

## 4. 사내에서 보완하기

### 미리 준비할 것
- Ubuntu PC (다른 OS는 지원하지 않음), Python 3.10+, git, `gh`
- 샘플 Jira 키 2~3개(카테고리가 다른 것), 카테고리별 실제 logcat 1개씩 + 정상 로그 1~2개(16/17)
- Android 16/17 소스 경로, 빌드명 예시 3~5개, GHE 주소·조직·팀 이름
- 샌드박스 이슈 DB 레포(빈 레포)
- **기존 자산**: 검증된 로그 파서 코드 경로, 파서가 판별하는 경우별 실제 로그, data 이슈 분류 자료, data 분석 스킬 이름
- Jira MCP가 **사용자 범위(user scope)** 로 등록돼 있는지

### 세션별 입력 (플러그인 레포 루트에서 Claude Code 열기)

첫 사내 세션에서 Claude가 "사외 초안 계속 / 사내 보완 시작"을 물으면 **사내 보완**을 고릅니다(이후에는 `SITE_PROFILE.md`로 자동 판별).
| 단계 | 입력 | 하는 일 |
|---|---|---|
| S-0 (선택) | `S-0 진행해줘` | 사외 Phase 3 이후 언제든. reference 파서·매처만 실제 로그 3~5개에 Python으로 돌려 태그 빈도·RIL 페어링 성공률·시각 파싱·슬롯 추출률을 `SITE_PROFILE.md`에 기록. 사외로는 정성 결론만 가져간다 |
| S-1 | `사내 보완 모드야. S-1 진행해줘` | TODO 목록 확인, 자료 받고 `SITE_PROFILE.md` 작성, 오프라인 평가 기준(1위 정확도 등) 합의 |
| S-2 | `S-2 진행해줘` | 플러그인 로드·hook·MCP 도구 이름 형식 확인, 다른 점만 수정 |
| S-3 | `S-3 진행해줘` | `site-defaults.yaml`(Jira 서버·도구 매핑·필드 매핑, GHE 등), 이슈 DB 설정 |
| S-4a | `S-4a 진행해줘` | **① 기존 파서 포팅**: 포팅 전 골든 출력 저장 → 이벤트 매핑 확인 → 사내 백엔드로 포팅 → 골든 테스트 통과. **② 기존 data 분류 import PR**. **③ 분석 스킬 연결** |
| S-4 | `S-4 진행해줘. 이번엔 call만` | 운영 이슈 DB의 placeholder 규칙을 실제 태그·문구로 바꾸고, 카테고리마다 자주 나오는 유형 5~10개를 실제 마스킹 fixture와 함께 `import` PR로 시드 (카테고리별로 세션 분리 권장) |
| S-5 | `S-5 진행해줘. 샌드박스는 <주소>` | 실제 Jira·로그로 dry-run, 샌드박스에 PR 1건. 과거 해결 Jira 20~30건 라벨셋으로 `tools/offline_eval.py` 정확도 게이트 |
| S-6 | `S-6 진행해줘` | 남은 `REVIEW-OPEN.md` 정리, 운영 이슈 DB에 합성 fixture·placeholder가 남았는지 확인 |
| S-7 | `S-7 진행해줘` | 마켓플레이스 등록, 카테고리별 파일럿(10~20건), 첫 월간 리뷰 → 전체 확대 결정 |

### 기존 파서 포팅의 핵심 (S-4a ①)
- **검증된 판별 로직은 코드 그대로** 두고 `builtin.data.*` 이벤트로 노출합니다. 시그니처가 이 이벤트를 참조합니다.
- **새로 생기는 유형은 코드가 아니라 규칙 파일**(`parser-rules`)로 추가합니다. 팀원이 PR만으로 파서를 발전시킬 수 있게 하기 위해서입니다.
- **포팅 전 골든 출력**을 저장하고, 포팅 후 결과가 같은지 테스트합니다. "검증된 파서"라는 가치를 지키는 장치입니다.
- 이슈 DB fixture는 마스킹돼 있습니다. 마스킹은 같은 값을 같은 번호(`<CELL#1>`)로 바꾸므로 값 비교 로직은 유지되지만, **원본과 마스킹 로그에서 판별이 같은지** 포팅 전에 확인합니다.
- 이슈 DB에 필요한 파서 백엔드 버전(`parser_backend`)이 기록되어, 팀원마다 결과가 달라지지 않습니다.
- 포팅이 어려우면(다른 언어 등) 기존 파서를 그대로 실행하고 출력만 변환하는 어댑터 방식으로 갑니다.

### 사내 토큰 절약
- 세션 시작은 `S-n 진행해줘`만. 진행 상태는 `SITE_PROFILE.md`에 있습니다.
- 로그는 채팅에 붙이지 말고 **파일 경로**로 줍니다.
- 에러는 "테스트 실패한 것만 봐줘".
- 단계가 끝나면 세션을 닫고 새로 엽니다.

### 사외 코드를 다시 반입할 때
1. 사내 레포에서 `git switch -c draft-import/<날짜>`
2. `tools/import_draft.py <새 사외 초안 경로>` (사내 전용 경로는 보존. 반입 기준선 `.draft-manifest.json`과 비교해서, 사내에서 고친 사외 파일이 있으면 멈추고, 사내에서 새로 만든 파일은 지우지 않고 알려줌)
3. 테스트(골든 포함)와 `db_regress --all` 통과 후 병합

### 막혔을 때
- 사내 환경 문제 → 사내에서 수정.
- 설계 문제 → `이 문제를 사내 정보 빼고 요약해줘` → 요약을 사외로 가져와 문서·코드 수정 → 재반입.

---

## 5. 설치와 첫 설정 (팀원 공통)

1. 사내 마켓플레이스에서 `telephony-triage` 설치
2. 이슈 DB 레포 clone
3. `/telephony-triage:setup`
   - GHE 아이디, 이슈 DB 경로, 로그 폴더, (선택) Android 16/17 소스 트리 프로필
   - 이미 등록된 Jira MCP를 찾아 도구 매핑을 확인 (팀 기본값이 있으면 확인만)
   - git pre-commit hook 설치, 매칭 캐시 생성
4. 연습: `/telephony-triage:analyze <샘플키> <로그> --dry-run` (아무것도 올리지 않음. gh 로그인 전에도 가능)

---

## 6. 사용법

### 커맨드 한눈에
| 커맨드 | 언제 |
|---|---|
| `analyze <JIRA> [로그...] [--code <프로필>] [--dry-run] [--analyzer \| --no-analyzer]` | 로그로 이슈 분석하고 분류·기록 |
| `record <JIRA> [--cause <ID> \| --new-cause <유형> \| --new-type <카테고리> \| --unresolved <유형>] [--fixture <로그>] [--resolved-fixture <로그>]` | 직접 해결한 이슈를 히스토리만 기록 |
| `search <키워드\|JIRA\|ID>` | 비슷한 이슈가 있었는지 찾기 |
| `fix-submitted <원인 ID> --ref <CL> --fixed-in <브랜치>[:<빌드>]` | 수정 CL이 머지됐을 때 |
| `verify-fix <원인 ID> <수정 빌드 로그>` | 수정 빌드에서 재발 안 하는지 확인 → fixed |
| `validate [--cause <원인 ID> <적용 후 로그>] [--extra <로그...>]` | 직접 편집 검사 / 해결책 효과 검증 |
| `sync-pr [브랜치]` | 내 PR이 머지 대기 중인데 main이 바뀌었을 때 (내 작업 계획을 최신 main에 다시 적용) |
| `sync`, `preview`, `review [카테고리]`, `setup` | 최신화, 생성 결과 미리보기, 월간 리뷰, 설정 |
| `migrate --to <N>` | (메인테이너) 자기 `migrate/schema-v<N>` 브랜치에서 스키마를 올림. PR은 직접 만든다 |

### 시나리오 1: 이슈 분석 (가장 흔함)
```
/telephony-triage:analyze ABC-12345 ~/logs/radio.txt ~/logs/main.txt
```
1. 이슈 DB 최신화 (분석은 별도 스냅샷에서, 내 clone은 main이고 깨끗할 때만 fast-forward)
2. Jira 읽기(텍스트는 즉시 마스킹, 원문은 저장 안 함) → 발생 시각(없으면 로그에서 증상 시각 후보 제시) → Android 버전 확인 → 코드 경로 선택(16/17 프로필 추천)
3. 로그 파싱(bugreport를 주면 logcat 섹션만 추출. 발생 시각이 로그 범위 밖이면 "로그 범위 밖"으로 따로 알림, 듀얼 SIM은 슬롯별로 판별) → 시그니처 매칭(맞는 유형이 없으면 "후보 없음" 절에 설명 기반 유사 후보와 타임라인 요약) → 코드 분석 → (data면) 분석 스킬 심층 분석을 할지 물어봄 (토큰 추가 사용)
4. 리포트: 분류 후보, 근거 로그, 원인, **해결책**, 수정 상태(이미 수정됨/회귀 의심), 기존 사례 Jira
5. "이 분류가 맞나요?" → 예 / 다른 원인 / 새 원인 / 새 유형 / 원인 미확정
6. 분석하는 동안 main이 바뀌어 내 계획이 건드리는 원인이 먼저 수정됐으면(drift) 항목마다 어느 값을 쓸지 물어봄
7. **push 전 확인 화면**(변경 파일, README 미리보기, 검증 결과, 커밋 메시지) → 승인 → PR
8. 카테고리 오너가 리뷰 후 머지

### 시나리오 2: 새 원인·새 유형 발견
- 5단계에서 "새 원인" 또는 "새 유형" 선택 → 제목·해결책·시그니처 초안 제시
- 필요한 파서 규칙 초안과 fixture(로그 최소 구간, 마스킹)를 함께 제시
- **자동 검증**: 새 규칙이 이 로그를 잡는지(R1·R2), 정상 로그를 잘못 잡지 않는지(R3), 기존 분류를 깨지 않는지(R4), 기존 이벤트를 바꾸지 않는지(R5)
- 새 시그니처가 **다른 카테고리의 기존 fixture**에서도 잡히면(그 로그에 실제로 두 현상이 있는 경우) "시그니처 좁히기 / 그 fixture에서 이 원인도 허용(`also_allowed`)"을 묻는다. 허용하면 그 카테고리 오너가 리뷰어로 붙는다
- 새 유형은 증상 시그니처가 필수. 새 원인은 원인 시그니처를 나중에 넣도록 보류할 수 있음(리뷰 대상)

### 시나리오 3: 직접 해결한 이슈 기록
```
/telephony-triage:record ABC-12345 --cause DATA-001-02
/telephony-triage:record ABC-12346          ← 대화형: 비슷한 유형을 보여주고 고르게 함
```
- 로그 분석 없이 기록. 검증과 PR 절차는 analyze와 같고, PR에 "수동 기록" 표시.
- "고쳤다"는 `fix-submitted`까지만. `fixed`는 verify-fix로만.
- 해결책 효과는 근거(다른 Jira 키, 적용 후 로그)가 있어야 "검증됨".

### 시나리오 4: 코드 수정 후 재발 확인
```
/telephony-triage:fix-submitted CALL-001-01 --ref <CL> --fixed-in main-dev:BUILD_X
/telephony-triage:verify-fix CALL-001-01 ~/logs/after_fix.txt
```
- 수정 빌드 이후 로그인지, 재현 시나리오를 수행한 로그인지 확인 후 판정: 통과(fixed) / 부분 통과 / 실패(open으로 되돌림) / 판단 불가
- 통과하면 수정 후 로그가 회귀 테스트에 추가되어, 이후 누가 규칙을 넓혀도 재발 판정이 깨지지 않음

### 시나리오 5: 기존 카테고리에 안 맞는 이슈
- 가장 가까운 카테고리에 태그와 함께 넣어 기록.
- 같은 성격이 3개 이상 쌓이면 메인테이너가 새 카테고리 PR.

### 팀 운영
| 누가 | 무엇을 |
|---|---|
| 기여자 | analyze/record로 PR. 머지 대기 중 main이 바뀌면 `sync-pr`(작업 계획이 작성자 PC에 있으므로 작성자가 실행). 직접 편집한 브랜치는 rebase → `db_build --write` → `validate` 후 push |
| 카테고리 오너 | 자기 카테고리 PR 리뷰(다른 카테고리가 내 fixture에 `also_allowed`를 넣은 PR 포함), 월 1회 `/telephony-triage:review <카테고리>` (미확정 누적, 품질 낮은 시그니처, 중복, 급증, 미검증 해결책, `also_allowed` 누적). 조치는 직접 편집하거나 Claude와 계획 파일을 만들어 PR |
| 메인테이너 | 파서 규칙·스키마·hook 변경 리뷰, 새 카테고리(`category/<key>` 직접 편집), 스키마 마이그레이션(`migrate/schema-v<N>` 브랜치에서 `migrate --to` 후 직접 PR), 사후 lint가 알린 ID 중복·Jira 중복 정리(수동) |
| 모두 | 이슈 DB README(카테고리별 유형·원인·해결책·Jira)와 STATS(Top 원인, 모델·SW별 분포, 수정 필요 순위) 확인 |

---

## 7. 지켜지는 안전장치 (자동)

- Jira는 **읽기만** (쓰기 도구 호출 차단)
- push 전 **항상 사용자 확인**, main 직접 push 차단
- 로그의 IMSI·전화번호·SIP URI·인증 값 등 **자동 마스킹**, 마스킹 안 된 커밋 차단. Jira 텍스트도 마스킹하고 원문은 저장하지 않음(구조화 필드 + 확인한 한 줄 요약만)
- 사용자의 이슈 DB clone은 **브랜치를 바꾸거나 파일을 고치지 않음** (작업은 임시 폴더에서, 최신화는 main이고 깨끗할 때 fast-forward만. Claude의 Write/Edit 도구로 clone 안 파일을 쓰는 것도 차단)
- `git pre-push` hook이 main 대상 push와 승인 토큰 없는 push를 거부. 단, 로컬 장치는 우회 가능하므로 **GHE 브랜치 보호(직접 push 금지, CODEOWNERS 필수 리뷰)가 서버에서 켜져 있어야 함**
- 검증을 건너뛴 항목은 **통과로 표시하지 않음**
- 한 사람이 동시에 두 작업을 하지 않음 (세션 lock. 이전 세션이 비정상 종료했으면 확인 후 해제)
- 분석 중에 main에서 바뀐 내용을 **자동으로 덮어쓰지 않음** (drift를 물어봄)

## 8. 문서 위치

| 보고 싶은 것 | 파일 |
|---|---|
| Claude Code 지침 진입점, 모드 판별 | `CLAUDE.md` |
| Phase별 할 일·완료 기준 | `docs/design/11-phases.md` |
| 사외 초안·사내 보완 절차 | `docs/design/15-local-draft.md` |
| 기존 Jira MCP·파서·분류·분석 스킬 활용 | `docs/design/16-existing-assets.md` |
| 사내 확인 항목 목록 | `docs/design/14-site.md` |
| 워크플로우 상세 | `docs/design/07-workflow.md` |
| 공통 규칙 원본 | `docs/design/contracts.md` |
| 사내 정보가 있어야 판단할 남은 항목 | `REVIEW-OPEN.md` |
| v1에서 뺀 설계(3-way replay 등) | `docs/design/99-deferred.md` |
| 11차 변경안(동작 검토 U1~U17, 이력) | `docs/history/REVIEW-11.md` |
| 변경 이력 | `CHANGES.md` |
