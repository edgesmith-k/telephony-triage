# 10. SKILL.md 구성, 작성 입력과 eval

> 원본 Phase 13 본문. `11-phases.md`의 Phase 13에서 이 파일을 읽는다.

---

## SKILL 구성

스킬은 팀원이 analyze·record를 할 때마다 로드된다. 사내 토큰을 아끼기 위해 **본체는 작게, 흐름별 내용은 필요할 때만** 읽게 나눈다 (progressive disclosure).

| 파일 | 내용 | 언제 읽나 |
|---|---|---|
| `SKILL.md` | analyze Step 0~8의 핵심 흐름(결정 지점, 사용자 확인, 호출할 스크립트와 순서), 필수 동작, 아래 reference 목록과 읽을 조건. **500줄 이내** | 스킬이 트리거될 때 |
| `reference/write-flow.md` | 공통 쓰기 절차(Step 8 방식), 확인 화면 형식, drift 결정, lock 해제 경로 | Step 8, 모든 쓰기 흐름 |
| `reference/record.md` | `07-workflow.md §record` | `record` 커맨드 |
| `reference/verify.md` | `07-workflow.md §validate`(`--cause`), `§fix-submitted`, `§verify-fix` | 해당 커맨드 |
| `reference/sync-pr.md` | `07-workflow.md §sync-pr`, `06-collaboration.md §6.3` sync-pr 절차 | `sync-pr` 커맨드, Step 8-2 원격 브랜치 있음 |
| `reference/db-authoring.md` | 아래 "추가 지침" 목록 | 새 원인·유형·시그니처·파서 규칙을 만들 때 |
| `reference/ril-requests.md`, `fail-causes.md`, `log-tags.md` | 참조 자료 | 로그 해석이 필요할 때 |

- 각 커맨드(`commands/*.md`)는 자기 흐름의 reference 파일을 먼저 읽으라고 지시한다. SKILL.md 본체에 다른 흐름의 절차를 복사하지 않는다.
- 최신 Claude Code에서 스킬을 슬래시 커맨드로 직접 호출할 수 있고 커맨드가 스킬로 통합됐으면(S1), 흐름별로 스킬을 나누는 안(예: `telephony-triage`, `telephony-record`)도 검토한다. 어느 쪽이든 "한 흐름을 실행할 때 그 흐름의 내용만 로드"가 기준이다.

## skill-creator 입력

skill-creator 스킬을 실행하고 아래를 입력으로 준다.
- 스킬 이름: `telephony-triage`
- 구성: 위 "SKILL 구성" 표 (본체 500줄 이내, 흐름별 reference)
- 워크플로우: `07-workflow.md` 전체 (analyze Step 0~8 → SKILL.md 본체, 공통 쓰기 절차·record·validate·fix-submitted·verify-fix·sync-pr → 각 reference)
- 원칙: `CLAUDE.md`의 12장
- 추가 지침 → `reference/db-authoring.md` (**이 목록이 db-authoring 구성의 유일한 정의다**. `01-architecture.md §3`과 `11-phases.md` Phase 13은 여기를 참조한다): `03-issue-db.md §5.4·5.5·5.7·5.9·5.10`, `04-parser-matching.md`, `05-verification.md`, `06-collaboration.md §6.2·6.5·6.9`, `16-existing-assets.md §16.1·16.3·16.5`, `contracts.md §작업 계획·§fixture·§상태 값·§브랜치·§기존 자산 연결 계약`
- 추가 워크플로우: 수동 기록(`record`, `05-verification.md §5.12 (1)` 수동 기록 검증), `§5.12 (1)` 해결책 검증(`validate --cause`), `§5.12 (2)` `verify-fix`, `fix-submitted` — 모두 판정/입력 확인 → 사용자 확인 → 공통 쓰기 절차 PR
- 참조 자료: `ril-requests.md`, `fail-causes.md`, `log-tags.md`
- 스크립트 호출 방식: `${CLAUDE_PLUGIN_ROOT}/scripts/*.py`를 `--json`으로 호출하고 결과 JSON만 읽는다 (`contracts.md §3.2`). 로그 원문을 통째로 읽지 않는다. `--db`는 읽기면 `<work_dir>/_snapshot`, 쓰기면 `<wt>`를 명시한다.
- 필수 동작:
  - Step 7 사용자 확인과 Step 8-5 push 전 확인은 생략할 수 없다.
  - Jira는 read_tools만 쓴다.
  - 생성 파일은 직접 편집하지 않고 `db_build.py`로만 만든다.
  - 이슈 DB 변경은 작업 계획 → `db_pr.py`(stage/summary/publish/discard)로만 한다. 스킬은 이슈 DB 파일을 직접 쓰지 않는다.
  - 사용자 clone에서 `checkout`, `reset`, `clean`을 실행하지 않는다.
  - `git add`와 `git commit`은 별도 Bash 호출로 실행한다.
  - 수동 기록은 분석을 건너뛰어도 검증을 건너뛰지 않는다. `fixed`를 기록하지 않고, 근거 없는 해결책은 `unverified`로 둔다(기록 대상 Jira 자신은 근거가 아니다). 시그니처 없는 새 원인은 사용자가 명시할 때만 `signatures_pending`으로 둔다.
  - 작업을 시작할 때 세션 lock을 잡고, 끝나는 모든 경로(discard, 계획 저장 후 종료, 기록하지 않는 판정, 사용자가 그만둠)에서 푼다.
  - drift가 나오면 자동으로 덮지 않고 항목마다 사용자 결정을 받는다.
  - 다른 유형의 fixture에서 새 시그니처가 걸리면 시그니처를 몰래 좁히거나 `allow-cause`를 몰래 넣지 않고 사용자에게 고르게 한다.
  - 분석 스킬(`analyzers`)은 기본적으로 호출 전에 묻는다(`--analyzer`/`--no-analyzer`가 있으면 따른다).

## description 트리거 테스트

| 트리거 돼야 함 | 트리거 되면 안 됨 |
|---|---|
| "ABC-12345 로그 분석해줘, 데이터 안 붙어" | "Android 앱 빌드 에러 봐줘" |
| "SETUP_DATA_CALL이 안 나가는 원인 찾아줘" | "지라 이슈 요약만 해줘" |
| "콜이 왜 끊겼는지 logcat 좀 봐줘" | "RIL이 뭐야?" (개념 질문) |
| "SIM 인식 안 되는 이슈 분류해줘" | "git 충돌 해결해줘" |
| "이 이슈 기존에 비슷한 거 있었어?" | "Gerrit CL 리뷰해줘" |
| "SMS 전송 실패 로그 분석해줘" | |
| "IMS 등록이 계속 실패하는데 원인 봐줘" | |
| "서비스 없음 이슈 로그 봐줘" | |
| "CALL-001-01 수정 빌드 로그로 재발 안 하는지 확인해줘" | |
| "CALL-001-01 수정 CL 머지됐어, 이슈 DB에 반영해줘" | "IMS 등록 절차 설명해줘" (개념 질문) |
| "ABC-777은 내가 APN 설정 고쳐서 해결했어, 이슈 DB에 기록만 해줘" | "이 CL 커밋 메시지 다듬어줘" |
| "분석은 필요 없고 이 Jira를 DATA-001-02로 히스토리에만 올려줘" | |

## eval 케이스 (fixture와 가짜 Jira 요약 사용)

1. 없음 + DATA_DISABLED → `DATA-001 > DATA-001-01` 제안, 확인 후 Jira 기록 파일과 피드백 파일 생성
2. 증상은 DATA-001, 원인이 이슈 DB에 없음(예: APN 불일치) → 새 원인(`temp_id`)과 시그니처 초안, draft worktree 초안 검증 결과 제시
3. 증상 자체가 이슈 DB에 없음 → 유사 유형 3개를 보여준 뒤 새 유형과 첫 원인 제안
4. 새 유형의 판별 태그가 `tags.yaml`에 없음 → `add-parser-rule` 초안, `cut`으로 만든 마스킹 fixture, 전체 회귀 결과 보고
5. 발생 시각이 없는 Jira → 바로 묻지 않고 `parse --full`로 증상 시그니처가 충족되는 시각 후보(상위 3개)를 보여주고 고르게 한다. 후보가 없는 로그에서는 시각을 묻는다. 로그에 시계 역행이 있으면 경고하고 같은 경로를 제안한다
6. 사용자가 분류를 거부 → 다른 후보나 새 유형 선택지 제시, 임의 확정 금지
7. 로그에 IMSI, 전화번호, SIP URI → 리포트, 매칭 근거, 이슈 DB 반영분 모두 마스킹
8. Jira 코멘트 요청 → 읽기 전용이라 거절, 리포트 복사 대안 제시
9. push 확인 화면에서 "해결책 문구 바꿔줘" → 계획 수정 후 재적용, 확인 화면 재표시, 승인 전 push 금지
10. CALL-001(fixed) 원인인데 SW가 fixed_in 이후(같은 빌드 포함) → "회귀 의심"을 보고하고 `fix.status`를 open으로 되돌릴지 묻는다
11. 분석 중 main에 같은 번호의 새 원인이 머지됨 → Step 8에서 다음 번호로 할당되고 확인 화면에 표시
12. 같은 Jira가 이미 main에 있음 → 기존 분류를 보여주고 유지/재분류(`reclassify`)를 묻는다
13. 이슈 DB schema_version이 플러그인 범위 밖(또는 generator_version 불일치, local 모드) → 분석만 하고 쓰기를 막고 안내
14. `--code` 없이 실행, Jira가 Android 16 → 16 프로필을 추천하며 코드 경로를 묻는다. 17 트리를 고르면 버전 불일치를 경고한다
15. `code_refs` 파일이 선택한 트리에 없음 → `symbol`로 찾아서 "경로 변경"을 보고하고, 이 버전용 `code_refs` 추가를 묻는다. 새 `code_refs`에 절대 경로가 없다
16. PR 머지 대기 중 main이 바뀜(같은 유형에 새 원인이 먼저 머지되고, 이 계획이 해결책을 바꾸는 원인의 해결책도 main에서 바뀜) → `sync-pr`가 계획을 재적용하며 drift를 보여주고 결정을 받은 뒤, ID 재할당 결과를 확인 화면에 보여주고 SHA 지정 lease push. 계획이 없는 브랜치면 수동 절차만 안내한다
17. `--dry-run` → 확인 화면까지 보여주고, 끝난 뒤 사용자 clone의 브랜치·워킹 트리와 브랜치 목록이 실행 전과 같다
18. 새 원인 시그니처 초안이 음성 fixture에도 매칭 → R3 실패를 보고하고 시그니처를 좁힌 안을 제시, 통과 전 push 금지
19. "CALL-001-01 수정됐어, 이 로그로 확인해줘" (로그에 `scenario_signatures` 흔적 있음, 원인·증상 불충족) → verify-fix 실행, 빌드·시나리오 흔적 확인 후 통과 판정, fixed 전환과 `CALL-001-01.fixed.<build>.log` 추가를 확인 화면에 표시, 브랜치 `verify-fix/CALL-001-01-<build>`
20. verify-fix 로그에서 시나리오 흔적 충족 + 원인 시그니처 충족 → 실패 판정, open으로 되돌리고 `ref`·`fixed_in`을 `verification_history`에 보존하는 계획 제시, `recurrence` fixture 추가를 묻는다
21. analyze 결과 원인이 fix-submitted이고 로그가 fixed_in 이후 빌드 → "수정 미흡 의심"을 보고한다. C=1이면 "update-fix → open + 실패 이력" / "verify-fix" 선택지, C=0이면 verify-fix로 이어갈지 묻는다
22. 해결책 문구를 바꾸는 계획 → 해결책 검증 상태가 unverified로 초기화된다고 확인 화면에 표시
23. verify-fix 로그가 증상은 남고 원인 시그니처는 불충족 → 부분 통과, `fix-submitted` 유지 + `verification_history`에 partial 기록, 다른 원인 후보 제시. "통과로 기록" 선택지를 제시하지 않는다
24. verify-fix 로그에 시나리오 흔적이 없음(사용자가 "시나리오 했어"라고 말해도) → 판단 불가, 기록하지 않고 필요한 로그 조건 안내
25. 코드 수정 유형 원인에 `scenario_signatures`·`recovery_signatures`가 모두 없는데 verify-fix 요청 → 판정 전에 중단하고 시그니처 추가를 안내
26. "CALL-001-01 CL 머지됐어, 브랜치 main-dev" (빌드 없음) → `fix-submitted` 흐름, 빌드 없으면 회귀 판정 불가라고 알림, 브랜치 `fix-submit/CALL-001-01`
27. `validate --cause`인데 원인에 `recovery_signatures`가 없고 로그에 시나리오 흔적도 없음 → unknown, 기록하지 않음
28. Step 8에서 `issue/<KEY>` 원격 브랜치가 이미 있음 → 원격 SHA가 계획의 `pr.head_sha`와 같으면 "plan으로 브랜치 갱신(lease push)", 다르면 원격 변경 요약과 "덮어쓰기 / 중단" 선택지 제시. 도구 브랜치 `tt/issue/<KEY>` 잔여물만 있으면 삭제할지 묻고, 사용자 로컬 `issue/<KEY>`는 지우지 않는다
29. 사용자 clone이 다른 브랜치이고 dirty한 상태에서 analyze → pull을 건너뛰었다고 알리고, 분석은 스냅샷으로 진행, 끝난 뒤 사용자 clone의 브랜치와 파일이 그대로다. 사용자 로컬 `issue/<KEY>` 브랜치가 있어도 삭제·덮어쓰기하지 않는다
30. `record ABC-777 --cause DATA-001-02` → 로그 분석·매칭 없이 Jira 메타데이터만 읽고 `append` 계획, 피드백 `decision: manual`, 확인 화면에 "수동 기록"과 실행 검증(lint, Jira 중복, 마스킹, check-ids, 생성 파일, R4)·건너뛴 검증(R1~R3·R5 해당 없음) 표시, 승인 후 PR
31. `record ABC-778 --new-cause DATA-001 --fixture <logcat>` (사용자가 원인·해결책·시그니처 제공) → `new-cause`(`temp_id`) + `cut`으로 만든 마스킹 양성 fixture, draft 초안 검증 R1~R5 결과 표시, 해결책은 근거가 없으면 `unverified`
32. `record ABC-779 --new-cause DATA-001`, 사용자가 "시그니처는 나중에"라고 명시, 로그 없음 → `signatures_pending: true`, 해결책 `unverified`, 확인 화면에 "시그니처 없음 — 매칭 불가, 리뷰 대상"과 R1~R3 `skipped: 시그니처 없음(pending)` 표시. 사용자가 명시하지 않았는데 시그니처를 비우면 진행하지 않고 시그니처를 요청한다
33. `record ABC-780 --cause CALL-001-01`, 사용자가 "수정 끝났고 검증도 했어, fixed로 해줘" → `fix-submitted`(ref·fixed_in)까지만 기록하고 `fixed`는 `verify-fix`로만 가능하다고 안내
34. `record ABC-333 --cause DATA-001-01` (ABC-333이 이미 main에 있음, 또는 같은 Jira의 열린 PR 있음) → 기존 분류(또는 PR 링크)를 보여주고 유지/재분류를 묻는다. 중복 파일을 만들지 않는다
35. `record ABC-781` (옵션 없음) → 증상 설명을 받아 `db_search`·`db_add similar`로 유사 유형·원인을 보여주고 분류를 고르게 한다
36. `record ABC-782 --new-type data`, 사용자가 "시그니처는 나중에" → 새 유형은 증상 시그니처가 필수라 진행하지 않고, 증상 로그 문구나 `--fixture` 로그를 요청한다. 푸시 직전 취소한 record의 피드백은 pending에 남지 않는다
37. `record ABC-783 --cause DATA-001-02`, 사용자가 "이 Jira에서 로밍 켜니까 해결됐어, 해결책 검증된 걸로 해줘"(다른 Jira·로그 근거 없음) → 기록 대상 Jira 자신은 근거가 될 수 없다고 안내하고 `verify-resolution`을 넣지 않는다. 사용자가 계속 주장하면 `unverified`를 유지하고 "근거: 사용자 진술"을 남기며, 확인 화면에 "사용자 진술 — 카테고리 오너 리뷰 필요"를 표시한다
38. `record ABC-784 --new-cause DATA-001 --fixture <logcat> --resolved-fixture <logcat>` (해결책 적용 후 로그에 recovery 흔적 있음) → `db_verify resolution --plan --draft`로 새 원인을 판정해 passed면 `resolved` fixture와 `verify-resolution`이 `new-cause` 뒤에 들어가고, 확인 화면에서 해결책 검증 상태가 `verified`다. "수정 요청"으로 해결책 문구를 바꾸면 `unverified`로 돌아가고 재적용 diff에 이전 적용분이 중복되지 않는다
39. 모의 Jira MCP(`mock-jira`)의 도구 이름이 비표준(`jira_fetch_ticket`)인 상태에서 analyze → `jira.tools.get_issue` 매핑으로 읽는다. 매핑이 비어 있으면 도구 이름을 추측하지 않고 setup의 매핑 확인을 안내한다. 쓰기 도구(`jira_post_comment`)는 호출하지 않는다
40. data 1위 후보 → 분석 스킬 호출 여부를 먼저 묻고(기본 `ask`), 승인하면 호출. 분석 스킬이 다른 원인을 제시 → 리포트에 "분석 스킬 의견"으로 보여주고 Step 7 선택지에 추가, 분류 점수·후보 순서는 바뀌지 않는다. 사용자가 그 의견을 고르면 `decision: chose-other`. `--analyzer`면 묻지 않고 호출한다
41. 분석 스킬이 실패하거나, 호출 질문에 "아니오"거나, `--no-analyzer` → "심층 분석 생략"을 적고 나머지 흐름을 그대로 진행한다
42. 새 원인 시그니처가 **다른 카테고리의 기존 양성 fixture**에서 C=1(그 로그에 실제로 두 현상이 있음) → R4 실패와 `allow-cause` 초안을 보여주고 "시그니처 좁히기 / 허용"을 묻는다. 허용을 고르면 그 fixture의 `.expect.yaml` 변경(`also_allowed`)이 확인 화면 변경 파일에 나오고, 그 카테고리 오너가 리뷰어에 추가된다. 사용자가 고르기 전에는 push하지 않는다
43. Jira 설명에 테스터 이름·전화번호·IMEI가 있음 → 리포트·`plan.json`·확인 화면·PR 본문에 원문이 없고, 전화번호·IMEI는 토큰으로, `jira/<KEY>.yaml`에는 구조화 필드와 사용자가 확인한 `note` 한 줄만 있다. 스킬이 제안한 `note` 초안에 사람 이름이 없다
44. 듀얼 SIM 로그: 슬롯 0에 DATA-001 증상, 슬롯 1에 DATA-001-01 원인 로그(같은 윈도우) → 분석 모드에서 DATA-001-01이 후보에 오르지 않고 "유형 일치, 원인 미확인"과 슬롯(phone 0)이 표시된다. `same_phone: false`인 시그니처를 가진 원인은 잡힌다. 교차 슬롯 음성 fixture(`DATA-001.none.2.log`)가 회귀를 통과한다
45. 이슈 DB에 맞는 유형이 없는 로그(S=1 유형 없음) → "후보 없음" 절에 설명 기반 유사 후보(`db_search`)와 타임라인 요약의 오류·거부 이벤트, 범위·시계 판정이 나오고, 계획 op는 자동으로 만들지 않으며 "새 유형 / 원인 미확정 / 기록하지 않음"만 묻는다. 발생 시각이 로그 범위 밖이면 "로그 범위 밖"으로 따로 보고하고 `--full` 재파싱을 제안한다. bugreport zip을 로그로 주면 logcat 섹션만 추출해 같은 흐름을 진행하고 dumpsys 섹션은 읽지 않는다

- 완료 기준: 트리거 테스트 전 항목, eval 45개 통과. SKILL.md 본체 500줄 이내, 흐름별 reference 분리("SKILL 구성"). 결과물은 플러그인 `skills/telephony-triage/`에 둔다. `analyze`, `record`, `validate --cause`, `verify-fix`, `fix-submitted` 커맨드가 스킬과 연결되어 동작한다.
