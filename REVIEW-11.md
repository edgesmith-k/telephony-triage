# 11차 변경안 — 10차 문서 세트 동작 검토(U1~U17) 반영

기준: 10차 문서 세트(`telephony-triage-docs-v10.zip`). 검토 항목 U1~U17 (🔴5, 🟡12). 사내 정보가 필요한 항목은 없어 `REVIEW-OPEN.md`는 0건 유지.
관점: 쓰기 경로(lock·worktree·drift·승인 해시·hook)는 10차까지로 충분하다고 보고, **분석 정확도(텔레포니 특성)**, **운영 부담**, **보안(저장되는 정보와 실행 경로)** 세 축에서 검토했다.

적용 방법: 아래 항목을 순서대로 반영하고, 끝나면 `CHANGES.md`에 "11차 변경" 절로 옮긴다.
개수 변화: hook 7 → **8**(Write/Edit 차단), eval 42 → **45**(43 Jira 텍스트 마스킹, 44 슬롯 구분, 45 후보 없음 폴백), placeholder 레지스트리 S19 → **S21**(S20 phoneId 표기, S21 bugreport 구조), git hook 1 → **2**(`pre-push` 추가). 커맨드 12, 검증 단계 6(R1~R6), 계획 `source` 9는 그대로.

---

## 🔴

### U1. Jira 텍스트 마스킹과 최소 저장

문제: 마스킹 표(`08-safety.md §8`)는 logcat 형식 기준이다. Jira 요약·설명·코멘트는 `plan.json`, PR 본문, `jira/<KEY>.yaml`의 `note`, 피드백, 리포트에 그대로 들어간다. Jira 설명에는 테스터 이름, 고객 전화번호, IMEI가 자유 텍스트로 자주 적히고, **사람 이름은 마스킹 항목에 없다.**

결정:
- 이슈 DB와 PR 본문에는 Jira의 **구조화 필드**(`model`, `sw`, `android_version`, `carrier`, `occurred_on`)와 **사용자가 확인한 한 줄 요약**(`note`)만 저장한다. Jira 요약·설명·코멘트 원문은 이슈 DB·PR·피드백에 저장하지 않는다.
- Jira에서 읽은 모든 텍스트는 리포트·계획·PR 본문에 넣기 전에 `mask_pii`를 거친다(문맥 규칙은 같고, `field_map`으로 뽑은 텍스트 필드 전체가 대상). `note` 초안은 스킬이 Jira 요약에서 만들되 **사용자가 확인한 문장**만 쓰고, 마스킹을 거친다. `db_lint`는 `jira/*.yaml`의 `note`와 원인 본문에 대해서도 원본 식별자 패턴을 검사한다.
- 계획 `jira`에 원문 필드(`summary`, `description`)를 두지 않는다. 키워드 보너스 계산은 Step 2에서 메모리에 있는 마스킹된 텍스트로만 한다.

반영 위치: `08-safety.md §8`(새 소절 "Jira 텍스트"), `07-workflow.md §Step 2·6·8-7`(PR 본문), `03-issue-db.md §5.4 (2)`(`note` 규칙), `contracts.md §작업 계획`(`jira` 필드 주석), `01-architecture.md §3.1`(`db_lint` 행), `11-phases.md` Phase 4 완료 기준, `10-skill-eval.md` eval 43.

### U2. Write/Edit 도구 차단 (hook 8)

문제: "워킹 트리 불변 원칙"은 Bash의 git 명령만 막는다. Claude가 Write/Edit/MultiEdit 도구로 `issue_db.path` 아래 파일을 직접 고치는 것은 아무것도 막지 않는다.

결정: PreToolUse hook 8 — matcher `Write|Edit|MultiEdit|NotebookEdit`. `guard.py`가 대상 경로가 config의 `issue_db.path`(사용자 clone) 안이면 **deny**한다. `<work_dir>` 아래(worktree `wt/`·`draft/`, 스냅샷)는 대상이 아니다(도구가 만든 작업 트리는 `db_pr`가 관리하고 스킬이 파일을 직접 쓸 일이 없지만, 테스트 fixture 작성 등 개발 세션의 편의를 위해 막지 않는다). 메시지: "이슈 DB clone은 도구가 직접 고치지 않는다. 직접 편집은 사용자가 한다".

반영 위치: `08-safety.md §9` 표(8번)와 "Hook은 8종", `11-phases.md` Phase 8 할 일·완료 기준, `GUIDE.md §7`.

### U3. `pre-push` hook과 서버 측 강제 명시

문제: push 강제(main 차단, 승인 프롬프트)는 Claude hook의 최선 노력 명령 파싱에만 의존한다. `python -c`나 스크립트 안의 push는 못 본다. 또 `core.hooksPath=.githooks`는 이슈 DB main에 커밋된 스크립트를 모든 기여자 PC에서 실행하므로, 서버 측 브랜치 보호가 없으면 main 쓰기 권한이 곧 팀 전체 PC의 코드 실행 권한이다.

결정:
- 이슈 DB에 `.githooks/pre-push` 추가(메인테이너 소유). (a) 대상 ref가 `refs/heads/<base_branch>`면 거부. (b) 환경변수 `TT_PUBLISH_TOKEN`이 없거나 `<work_dir>/<작업 키>/state.json`의 `approved_hash`와 다르면 거부. 토큰은 `db_pr publish`가 자기 `git push` 호출에만 넣는다. 직접 편집 기여자의 push는 `validate` 통과 후 `TT_PUBLISH_TOKEN=manual`로 허용한다(`CONTRIBUTING.md`에 명시. 목적은 사고 방지이지 권한 통제가 아니다).
- `06-collaboration.md §6.1`에 명시: **로컬 장치(Claude hook, git hook)는 모두 우회 가능하다. main 직접 push 금지와 CODEOWNERS 필수 리뷰는 GHE 브랜치 보호로 서버에서 강제되어야 하며, 이것이 없으면 `.githooks/`가 코드 실행 경로가 된다.** S5에 "브랜치 보호 설정 권한" 확인 추가.

반영 위치: `03-issue-db.md §5.2`(트리), `06-collaboration.md §6.1`, `08-safety.md §9`(문단), `contracts.md §3.2` `db_pr.py` 세부 `publish`, `11-phases.md` Phase 1(스텁)·Phase 8(실제), `14-site.md` S5.

### U4. 듀얼 SIM 슬롯 구분 (`phone_id`)과 RIL 페어링 키

문제: 태그는 `DNC-<phoneId>`처럼 슬롯을 달고 나오지만 시그니처·매처에 슬롯 조건이 없다. SIM1의 증상과 SIM2의 원인 로그가 같은 윈도우에 있으면 S=1, C=1로 잘못 잡힌다. RIL 페어링도 serial만 쓰면 phone 프로세스 재시작이나 슬롯별 serial 충돌에서 잘못 짝지어진다.

결정:
- 파서 이벤트에 `phone_id`(정수 또는 `null`)를 추가한다. 추출원: 태그 접미사(`DNC-1`), 메시지 접두어(`[PHONE1]`, `[SUB1]` 등, 형식은 S20에서 확인), 없으면 `null`.
- 시그니처 선택 필드 `same_phone: true`(기본값). `true`면 그 시그니처의 모든 조건이 **같은 `phone_id`** 의 이벤트로 충족되어야 한다. `phone_id: null` 이벤트는 와일드카드(어느 슬롯과도 맞음). DDS 전환처럼 슬롯을 가로지르는 원인은 `same_phone: false`로 둔다. 회귀·검증 모드도 같다.
- 리포트에 판별된 슬롯을 표시하고, Jira에 슬롯 정보가 있으면(`field_map.sim_slot`, 선택) 다르면 경고한다.
- RIL 페어링 키는 `(pid, phone_id, serial)`. `phone_id`를 못 뽑으면 `(pid, serial)`.
- 샘플 이슈 DB에 **교차 슬롯 음성 fixture** 1개(`DATA-001.none.2.log`: 슬롯 0의 증상 + 슬롯 1의 원인 로그)를 넣는다.

반영 위치: `04-parser-matching.md §5.8 (2)`(이벤트 필드)·`§5.11 (1)`(표), `07-workflow.md §Step 3·6`, `03-issue-db.md §5.4 (1)`(예시 주석), `contracts.md §3.2`(`parse_logcat` 출력), `14-site.md` S20, `11-phases.md` Phase 1·2·3, `10-skill-eval.md` eval 44.

### U5. 시그니처 순서 조건 (`sequence`)

문제: `must_match`/`must_event`는 "윈도우 안에 모두 있음"만 본다. "설정 OFF → 이후 SETUP_DATA_CALL 없음"과 "SETUP_DATA_CALL 실패 → 이후 설정 OFF"를 구분할 수 없다.

결정: 시그니처 선택 필드 `sequence: [<조건 id>, <조건 id>, ...]`. `must_match`·`must_event` 항목에 선택 `id`를 붙이고, `sequence`에 나열한 순서대로 **첫 충족 시각이 단조 증가**해야 충족이다. 없는 시그니처는 그대로 동작한다(호환). S/C 불리언 판정과 점수 계산은 바뀌지 않는다. `db_lint`는 `sequence`의 id가 같은 시그니처 안의 조건 id인지, 중복이 없는지 검사한다. `must_not_match`는 `sequence`에 넣을 수 없다.

반영 위치: `04-parser-matching.md §5.11 (1)`, `03-issue-db.md §5.4 (1)`(예시), `01-architecture.md §3.1`(`db_lint`), `11-phases.md` Phase 1(샘플 시그니처 1개에 사용)·3·5.

---

## 🟡

### U6. 로그 범위 밖·시계 오류 판정

문제: radio 버퍼가 작아 Jira 발생 시각 ±5분이 파일 밖인 경우가 흔한데, 지금은 "매칭 없음"으로 나와 시그니처 문제로 오해된다. 단말 시계가 틀린 로그(NITZ 전, 재부팅 직후)도 윈도우가 통째로 빗나간다.

결정: `parse_logcat parse`가 출력에 `coverage: {first_ts, last_ts, window_in_range: true|partial|false, clock_anomalies: [{ts, kind: backward|jump, delta_sec}]}`를 넣는다. `window_in_range: false`면 Step 3에서 "로그 범위 밖(파일: A~B, 발생: T)"으로 보고하고 `--full`로 다시 파싱할지 묻는다. `clock_anomalies`가 있으면 경고하고 U8의 증상 스캔을 제안한다. 리포트에 범위·이상 여부를 적는다.

반영 위치: `contracts.md §3.2`(`parse_logcat` 출력), `07-workflow.md §Step 3·6`, `11-phases.md` Phase 2 완료 기준.

### U7. 후보 없음 폴백

문제: 모든 유형이 S=0이면 리포트가 비어 있고 Step 7로 넘어간다. 초기 DB가 비어 있어 가장 흔한 경우인데 도구가 주는 가치가 없다.

결정: Step 4에서 S=1인 유형이 없으면 Step 6 리포트에 "후보 없음" 절을 만든다: (a) Jira 요약 키워드(마스킹된 텍스트)로 `db_search`를 돌린 결과 상위 3개, (b) `tags.yaml` 카테고리별 타임라인 요약(±5분, 원문이 아니라 이벤트 요약)에서 눈에 띄는 오류·거부·타임아웃 이벤트 목록, (c) U6의 범위·시계 판정. **점수·검증에 쓰지 않고 계획 op를 자동으로 만들지 않는다.** Step 7은 "새 유형 / 원인 미확정(가장 가까운 유형) / 기록하지 않음"만 제시한다. 원문 전체를 컨텍스트에 넣지 않는다는 원칙은 유지한다.

반영 위치: `07-workflow.md §Step 4·6·7`, `10-skill-eval.md` eval 45.

### U8. 발생 시각이 없을 때 증상 스캔

결정: Step 2에서 발생 시각을 못 찾으면 바로 묻지 않고, 먼저 `parse --full`로 파일 전체를 파싱해 증상 시그니처가 충족되는 시각 후보(상위 3개)를 보여주고 고르게 한다. 후보가 없으면 묻는다. 시계 이상(U6)이 있을 때도 같은 경로를 제안한다. `--full` 결과는 후보 선택에만 쓰고, 분석은 선택한 시각 ±5분으로 다시 자른다.

반영 위치: `07-workflow.md §Step 2`, `10-skill-eval.md` eval 5.

### U9. bugreport에서 logcat 섹션 추출

문제: 실제 Jira 첨부는 대부분 bugreport(zip 또는 txt)인데 v1은 logcat 파일만 받는다. 범위표에서 "bugreport 전체 파싱"은 제외 항목이다.

결정: **범위 변경**(전체 파싱은 여전히 제외). `parse_logcat.py extract-bugreport <zip|txt> --out <dir>`가 logcat 섹션(`SYSTEM LOG`, `RADIO LOG`, `EVENT LOG`는 제외)만 파일로 잘라 내고, 헤더의 `Build fingerprint`·`Build:` 줄만 `build.json`으로 낸다. **dumpsys 등 다른 섹션은 읽지 않는다**(전화번호·ICCID가 구조화된 형태로 있어 마스킹 규칙이 못 잡는 형식이 있음). analyze·record·verify-fix의 logcat 인자에 bugreport를 주면(확장자 `.zip` 또는 파일 머리의 `== dumpstate`) Step 3 전에 자동으로 추출한다. `build.json`의 fingerprint는 Step 2-1(대상 버전)과 verify-fix 빌드 확인의 후보로 쓴다. 섹션 헤더 형식은 S21에서 확인한다.

반영 위치: `CLAUDE.md` 1장 범위표, `contracts.md §3.2`(`parse_logcat`), `07-workflow.md §Step 2-1·3·verify-fix 3번`, `09-commands.md`(analyze 설명), `14-site.md` S21, `11-phases.md` Phase 2.

### U10. CP 근거 필드

문제: CP 로그 파싱은 v1 제외가 맞지만, 원인이 모뎀 쪽일 때 근거를 적을 곳이 없어 이슈 DB가 "RIL 에러 응답"에서 멈추고 root cause가 쌓이지 않는다.

결정: 원인 필드 `cp_evidence`(선택, 자유 텍스트 한 단락): DM/silent log 위치·구간, CP 분석 요약, 관련 CP 티켓. 매칭·검증에 쓰지 않는다. 마스킹 대상이고 `db_lint`가 원본 식별자 패턴을 검사한다. README 원인 행에 "CP 근거 있음" 표시.

반영 위치: `03-issue-db.md §5.4 (1)`(예시)·`§5.7 (3)`(템플릿), `01-architecture.md §3.1`(`db_lint`·`db_build`).

### U11. 정규식 ReDoS 검사와 매처 타임아웃

문제: `parser-rules`와 시그니처의 정규식은 PR로 누구나 넣고, 모든 기여자의 매처·pre-commit·CI에서 전체 로그에 실행된다.

결정: `db_lint`가 중첩 수량자(`(a+)+`, `(a|a)*` 류)와 길이 제한 없는 역참조를 거부한다(정적 검사, 보수적). 매처·extractor는 패턴당 실행 시간 상한 `matcher.pattern_timeout_ms`(`issue-db.config.yaml`, 기본 2000)를 두고, 초과하면 그 시그니처를 `error`로 보고하고 분석은 계속한다(회귀에서는 실패).

반영 위치: `02-config.md §5.3`(`matcher`), `04-parser-matching.md §5.8 (4)`, `01-architecture.md §3.1`(`db_lint`), `11-phases.md` Phase 3·5.

### U12. 자격증명 성격 값 마스킹

결정: 마스킹 표에 행 추가 — SIP `Authorization`/`WWW-Authenticate` 헤더의 `response=`, `nonce=`, `cnonce=`, AKA `RES`/`AUTN`/`AUTS`, 그리고 키 이름 문맥(`password`, `passwd`, `secret`, `token`, `key`)의 값 → `<CRED#n>`. IMS 카테고리 fixture에 REGISTER 로그가 들어가므로 필요하다.

반영 위치: `08-safety.md §8` 표, `11-phases.md` Phase 4 완료 기준.

### U13. 작업 디렉토리 보존 기간과 권한

문제: `work_dir`의 `plan.json`은 PR 후에도 무기한 남고(`sync-pr`용) Jira 내용이 있다.

결정: setup이 `work_dir`와 `~/.telephony-triage/`를 권한 700으로 만든다. `db_pr cleanup --older-than <days>`(기본 90)를 추가: 계획의 PR이 닫혔거나(`gh pr view --json state`) 머지됐고 `staged_at`·파일 mtime이 기준보다 오래된 작업 디렉토리를 지운다. `sync`가 끝날 때 후보 목록을 보여주고 사용자 확인 후 지운다(자동 삭제 없음).

반영 위치: `02-config.md §4`(setup 1번), `contracts.md §3.2`(`db_pr cleanup`), `09-commands.md`(`sync` 행), `11-phases.md` Phase 12.

### U14. 사내 선행 확인 S-0 (선택)

문제: Phase 1~13이 모두 합성 로그 위에서 만들어지고, "시그니처 매칭이 실제 logcat에서 통하는가"는 S-4에서 처음 확인된다. 통계 숫자라도 사외로 가져가는 것은 반출 규정 대상이고, 현재 라이프사이클은 일방향(사외 → 반입)이라 중간에 사내 세션을 끼울 자리가 없다.

결정: `15-local-draft.md §15.5`에 **S-0(선택, 사외 Phase 3 완료 이후 언제든)** 추가: 사외 초안의 reference 파서·매처만 사내로 가져가 Claude 없이 Python으로 실제 로그 3~5개에 돌린다. 태그 빈도, RIL 페어링 성공률, 시각 파싱 실패율, `coverage` 판정을 `SITE_PROFILE.md`에만 기록한다. 사외로는 **정성 결론만**("페어링 방식 재검토 필요", "태그 접미사 형식 다름") 가져간다. 반출 규정 확인은 사용자 책임.

반영 위치: `15-local-draft.md §15.3·15.5`, `11-phases.md` Phase 3(비고), `GUIDE.md §4`.

### U15. 파일럿 전 오프라인 재현 평가

결정: S-5와 S-7 사이에 게이트 추가. 이미 해결된 과거 Jira 20~30건(카테고리별 3건 이상)을 라벨셋(`tests/site/offline-eval.yaml`: Jira 키, 로그 경로, 정답 원인 ID)으로 만들고 `tools/offline_eval.py`가 `analyze --dry-run --jira-file` 경로로 1위 정확도, 상위 3 포함률, 오탐률(정답이 unresolved인데 후보를 낸 비율)을 낸다. 기준(예: 1위 정확도 60%)은 S-1에서 사용자와 정한다. 미달이면 파일럿 전에 시그니처·규칙을 조정한다. 사외에서는 합성 라벨셋으로 도구만 시험한다.

반영 위치: `15-local-draft.md §15.5`(S-5 행), `11-phases.md` Phase 12(도구)·Phase 14, `01-architecture.md §3`(`tools/offline_eval.py`), `GUIDE.md §4`.

### U16. 카테고리 시드와 파일럿 지표

결정: S-4 완료 기준에 "카테고리별 자주 나오는 유형 5~10개를 `source: import` 계획으로 시드"를 추가한다(data는 S-4a의 기존 분류 import로 대신). 파일럿 지표에 **PR까지 걸린 시간**(analyze 시작 → PR 생성, `state.json`의 시각으로 계산)과 **중도 취소 비율**(`discard`로 끝난 작업 / 시작한 작업)을 추가한다.

반영 위치: `15-local-draft.md §15.5`(S-4·S-7), `11-phases.md` Phase 14, `06-collaboration.md §6.7`(STATS에 두 지표는 넣지 않음 — 로컬 `work_dir` 기준이라 사용자별 집계는 `review`가 아니라 파일럿 담당자가 수집).

### U17. 개수·참조 정합

- hook 7종 → 8종, eval 42 → 45, S19 → S21, git hook `pre-commit` → `pre-commit`·`pre-push`. 모든 문서의 개수 문구를 갱신한다.
- `01-architecture.md §3` 트리에 `tools/offline_eval.py`, 이슈 DB 트리에 `.githooks/pre-push`, `tests/site/offline-eval.yaml`(SITE_PATHS 안).

## 🟢

- `GUIDE.md §6` 시나리오 1에 "로그 범위 밖" 안내와 bugreport 입력 한 줄.
- `CLAUDE.md` 문서 지도의 eval 개수.
