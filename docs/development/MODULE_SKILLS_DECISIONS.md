# H·I 사용자 결정 원문 (11/02~03)

`MODULE_SKILLS_PLAN.md`(계획)의 D1~D12가 가리키는 결정과 다음 작업 I의 결정이다. 사용자가 대화에서 정한 것만 적었다 — 구현이 맞는지는 적지 않았다. 바꾸려면 사용자 확인을 받는다.

## H. 모듈 스킬 레포와 +1 병합

- **D1** 이슈 DB에 맞는 후보가 없을 때의 가설(탐색 분석, Step 5-2)과 1위 후보가 있을 때의 심층 분석(Step 5-1)을 **모듈별**로 둔다: ① 탐색 모듈 문서, ② 심층 분석 스킬. 둘 다 만든다. **oFono와 Android 둘 다** — Android도 모듈별 기본 스킬을 새로 만들고, 사내에 이미 있는 Android 분석 스킬은 사내에서 합친다.
- **D2** 사내 GHE에 **모듈 스킬 레포 1개**. `<플랫폼>/_common/`(layers.md·components.md — 여러 모듈에 걸친 데몬·구성요소는 여기 한 번) + `<플랫폼>/<모듈>/`(explore.md = ①, SKILL.md = ②, analyzer.md = 입출력 계약, references/<유형 ID>.md, evals/ = 가정 이슈 시나리오), 루트 README.md·modules.yaml(플랫폼 → 모듈 → 경로·이슈 DB 카테고리·관련 데몬/태그).
- **D3** 모듈 디렉토리 이름 = 이슈 DB 카테고리(data·sim·network·call·sms·ims). 모뎀은 디렉토리 `modem`이고 modules.yaml에서 DB 카테고리 `common`에 연결한다.
- **D4** 받기: 도구가 관리하는 clone에 `<p>/_common` + 그 모듈만 sparse checkout, 쓸 때마다 최신 main(fetch + ff-only), 리포트에 스킬 커밋 SHA. 개인 clone은 건드리지 않는다.
- **D5** 모듈 고르기: Step 5-1은 1위 후보 카테고리, Step 5-2는 타임라인에 나온 데몬·태그의 카테고리와 Jira 요약 — 둘 이상이면 묻는다.
- **D6** 플러그인 내장 `reference/platforms/ofono/log-guide.md`에는 파서와 묶인 줄 모양만 남기고, 층·데몬 지식은 레포 `_common`으로 옮긴다.
- **D7** 개선: ②는 기존 `[스킬]` 제안 흐름, ①은 새로 — 원인을 확정·기록하는 Step 7에서 "탐색 문서에 보탤 점" 제안을 한 번. 고른 것을 도구 브랜치에 반영 → diff·스크립트 점검(형식·크기·`mask_pii --check`·로그 원문·사내 값·링크) 결과 + Claude 의견(참고, 판정은 스크립트) → **본인이 리뷰·승인한 뒤 push·PR**.
- **D8** **eval은 의무가 아니고 강력 추천**: 스킬 수정 push 전에 "eval을 돌리는 것을 강력히 추천합니다. 돌리지 않는 일이 쌓이면 모듈 스킬의 판단 일관성이 떨어질 수 있습니다" 같은 문구로 묻는다. 시나리오는 모듈당 2~3개(실패 층을 서로 다르게, 플랫폼마다 '아래 층 로그 없음' 함정 1개 이상, 여러 모듈 공통 데몬 줄 섞기). 판정 1순위 원인 층·데몬·근거 줄, 2순위 토큰, 안전 행은 실패 불가. 사외는 합성 로그·공개 표본 모양뿐이고, 실제 해결 이슈 검증은 사내. 참고 비용: eval 73 실측 1회 ≈ 총 40만 토큰(캐시 읽기 35.7만), 0.25달러, 1분(Sonnet 5.5).
- **D9** **병합 규칙(모듈 스킬 레포·이슈 DB 공통)**: 작성자 외 아무나 +1(GHE Approve가 지금 head 커밋에, Request changes 없음). 모듈 오너 지정 없음. 이슈 DB의 "push하고 바로 병합"(`issue_db.merge: self`, `publish --and-merge`)을 없앤다. "병합해줘" → `db_pr merge`가 +1을 확인하고 병합, 없으면 병합하지 않고 이유(승인 없음/승인이 이전 커밋/변경 요청)와 PR 링크. 리뷰어 지정은 **묻고** 승인하면 요청(쓰기라 매번 확인), 지정하지 않으면 아무나. +1 뒤 GHE 웹에서 직접 병합해도 된다 — 브랜치 보호(필수 승인 1·필수 검사·최신 브랜치 요구) 권장을 사내 안내에. eval 72는 새 흐름으로 다시.
- **D10** oFono 모듈 → 데몬. 데몬 이름은 레포에 그대로 넣는다(11/02 '표본은 구조만' 결정을 데몬 이름에 한해 바꿈 — 표본의 값·호스트·D-Bus 이름(`org.ofono.*` 제외)은 여전히 금지):

  | 모듈 | 데몬 |
  |---|---|
  | data | NMD, MOSE, ofonod(gprs·lte), DITD, exynos-ril |
  | sim | ofonod(sim), LPA, ipad, exynos-ril, MOSE |
  | network | ofonod(netreg), exynos-ril, PTD, MOSE |
  | call | ofonod(voicecall), exynos-ril, IMSSVC, MOSE |
  | sms | ofonod(sms), exynos-ril, IMSSVC, MOSE |
  | ims | IMSSVC, ENT, ofonod(ims), exynos-ril, MOSE |
  | modem | ofonod(modem), exynos-ril, DMD, RFSD, vcd, MOSE |

  location(GPS0·VRD) 제외, `exynos-ril`은 그대로. 공통 데몬: ofonod·exynos-ril·MOSE. 데몬 성격(표본 줄 내용 추정): NMD APN·인증·CLAT·프로필, MOSE D-Bus 도우미, DITD 라우팅(netlink), LPA eSIM 채널·EID, ipad eUICC 프로필 목록, PTD 무선·망 상태 이벤트, IMSSVC IMS 서비스·PDN·VoLTE·IMS 문자, ENT 사업자 entitlement(HTTP), DMD 모뎀 진단 로그 에이전트, RFSD 모뎀 NV 파일, vcd 모뎀 감시. 표본에 없는 사내 데몬은 사내에서 더한다.
- **D11** oFono 시나리오 초안: data ① APN 인증 거절(NMD → ofonod gprs 활성화 실패 → exynos-ril `SETUP_DATA_CALL failed`) ② 데이터 콜 성공·DITD 라우팅 실패 ③ ofonod 오류만·아래 RIL 줄 없음(지어내지 않기) / sim ① SIM_IO 실패 ② LPA 채널 열기 실패 ③ ipad 목록 조회 오류 / network ① 등록 거절 ② PTD RADIO_ON 없음 / call ① VoLTE 발신 실패(IMSSVC → voicecall) ② RIL DIAL 실패 / sms ① SEND_SMS 실패 ② IMS 문자 실패 / ims ① IMS 등록 실패 ② ENT entitlement 거절 / modem ① 모뎀 리셋 연쇄(증상 모듈이 아니라 모뎀이 원인) ② RFSD NV 쓰기 실패. Android는 같은 7개 모듈, 층은 앱·프레임워크 → RILJ → RIL HAL → 벤더 RIL → 모뎀, 구성요소 대응은 계획에서 초안 → 사용자 확인.
- **D12** 순서: 계획을 사용자에게 보이고 확인받은 뒤 구현(결정 (p)). 사외에서는 레포에 템플릿(`templates/module-skills/`)을 만들고, 사내에서 GHE 새 레포로 옮겨 site 설정에 주소. SKILL.md·reference는 skill-creator로 쓰고 eval로 검증(CLAUDE.md).

## 계획 확인 (11/03)

- `MODULE_SKILLS_PLAN.md` §6.1 Q1~Q7은 모두 추천안: Q1 5-1은 받은 파일 Read · Q2 사내 `analyzers.data.skill`은 레포 주소가 없을 때의 대체 경로로 남김 · Q3 사내 이행은 새 트랙 MS-1·MS-2 · Q4 5-2 후보가 둘 이상이면 늘 묻기 · Q5 런타임 `claude -p` eval 허용(읽기 도구만) · Q6 D6대로 옮기고 eval 73(주소 없음)으로 잼, 떨어지면 최소 층 사슬을 내장에 남김 · Q7 G에서 81개 전체 재측정 + 사람 판정.
- §6.3 기본안 Q10~Q25: 이의 없음.
- **Q2 바꿈(11/05 사용자, B1 설계 중)**: 기존 설치 스킬이 있으면 레포 주소가 있어도 **사용자 설정으로 그 스킬을 쓸 수 있게** 한다. 카테고리별로 고르는 opt-in(기본은 모듈 문서): `[platforms.<p>.]analyzers.<cat>`에 기존 `skill`과 함께 고르는 키를 둔다(형태는 B1 설계). 주소가 없으면 `skill`을 쓰는 예전 Q2 동작은 그대로. 설정만으로 정해져 캐시·출력 결정성 유지, 설정이 없으면 출력 그대로. OpenCode(I)에는 Skill 도구가 없어 이 선택은 Claude Code판에서만 — I에서 보고 방식을 정한다. (11/05 정정: OpenCode 1.19.5에는 자체 `skill` 도구가 있다. 아래 계획 I 1단계 결정대로 스크립트가 설치 스킬의 SKILL.md 경로를 풀어 모든 런타임에서 Read로 읽는다.)
- **첨부 로그 기준(11/05 사용자)**: 모듈별 로그 필터·모듈 문서·평가 사례는 사용자가 첨부한 실제 로그(oFono syslog 2개, Android logcat 1개)를 기준으로 만든다. "사내랑 안 맞는 것은 사내에서 바꾼다." 그래서 로그에 나온 데몬·태그·ofonod 소스 파일·RIL 요청·D-Bus 이름·줄 모양을 placeholder 대신 실제 값(출처 R)으로 쓰고, 로그에 없는 것만 자리 표시로 둔다. 테스트 fixture·평가 사례 로그는 **마스킹한 실제 발췌**(에피소드 구간만, 호스트·일련번호·IMSI/ICCID/EID·제품 코드 등은 토큰으로)를 쓸 수 있다 — 마스킹 안 한 줄은 쓰지 않는다(CLAUDE.md "마스킹된 로그만"). fixture-origin 점검 변경은 설계에서 보이고 확인받는다. 레포가 비공개라 마스킹 발췌를 브랜치에 올려도 된다(11/05 사용자 확인).
- Q8(A1 시작 때): `db_pr merge --approved` 생략 허용 — `merge-offer.json`의 head를 쓰고, PR head가 다르면 거부, `sync-pr`이 head를 갱신.

## 진행 방식 (11/04 사용자)

- **단계마다 리뷰 1회.** 확인된 P0·P1은 그 단계에서 한 번 고치고 테스트·기계 검증(말뭉치·오라클 등)으로 확인한다 — 고친 것을 다시 리뷰하지 않는다. P2만 미뤄 결과 노트 "반입 뒤 후보"에 적는다(결정 (r) 그대로, (p)의 "P0·P1이면 다시"를 대신한다). A1에서 guard 리뷰가 6회 넘게 돈 것을 끊기 위해.
- **guard 규칙 11에 남은 P1**(예전부터 있던 우회 빈틈): 쉬운 3개 — 디렉토리 스택 tilde(`cd ~-`·`~N`), 명령 낱말에 붙은 입력 리디렉션(`git</dev/null push`), 공백 없는 `bash<<EOF` — 는 **A2 직후·C0 전**에 고친다(A2도 guard.py를 고쳐서 그 뒤). 셸 구조 빈틈(루프 되돌이·while 조건·함수 본문 cd·짧은 경로의 링크 뒤 `..`)은 G 또는 반입 뒤.
- **C0부터 OpenCode·GLM 제약을 스킬 형식에 반영**한다(출력 16K·문맥 202K·Claude hook 없음) — I에서 스킬을 다시 고치지 않게.

- **일정 단축(11/05 사용자, 네 가지 모두)**: ① **E 개선 흐름은 이번 반입 뒤 다음 묶음**으로 — 그동안 모듈 문서는 GHE 웹 PR(+1 브랜치 보호)로 고치고 받을 때 점검(B1)은 그대로. ② **C1·D를 한 워크플로에서 병렬**로(Android 모듈 경계 Q9는 첨부 로그 기준 초안, 사내에서 조정). ③ **B1·B2를 묶어** 한 번에 구현·리뷰·검증(리뷰 관점을 늘려 보완). ④ **Q7 바꿈**: G 재측정은 쓰기 흐름 33개(병렬), 81개 전체는 반입 뒤 사내에서. 조건: "성능이나 버그는 최대한 없게" — 단계마다 리뷰·반박 검증·전체 테스트는 줄이지 않는다. 계획 I 1단계(OpenCode 규격·실험)는 H와 나란히(11/05 사용자).
- **사내 토큰 최소(11/05 사용자: "사내는 토큰이 얼마 없어")**: 사외에서 확인할 수 있는 것은 모두 사외에서 하고, 사내 단계는 LLM 없이 도는 스크립트로 만든다. 그래서 ④를 고친다 — **81개 전체 재측정도 사외 G에서**(skill eval 실행기에 병렬 옵션을 더해 시간을 줄인다, 유료 실행은 그때 승인). MS-1은 스크립트만(`make_module_repo`·`site_step.py modules check`). MS-2의 사내 Android 스킬 합치기는 선택 — 합치기 전에는 설치 스킬 선택(Q2 바꿈)으로 그대로 쓴다. 실제 이슈 eval은 선택·소수. 사내에서 이름이 안 맞는 것은 LLM 없이 사내 로그를 넣으면 모듈별 줄 수와 모르는 데몬·태그를 보여 주는 스크립트로 찾아 `modules.yaml` PR로 고친다(B2·C1 범위). 계획 I의 사내 확인은 환경마다 짧은 확인 실행 1회. 반입 뒤 사내 site eval(IMPL §4.8 8번, 지금 11개+)은 이번 묶음 변경이 닿는 것만 고르는 목록을 사외에서 만들어 반입 노트에 넣는다(바뀐 파일 → eval 대응, 나머지는 "영향 없음"으로 기록) — 사내 재점검(S-4a·O-3·S-6)·pytest·골든·샌드박스 PR은 스크립트라 토큰이 들지 않는다.

- **B1 설계 질문(11/05 사용자, 모두 추천안)**: ① guard 규칙 12(c)(`skill_patch --apply` ask 제거)와 `analyzers.<cat>.source` 폐지 경고는 E로 미룬다(`--apply`가 아직 있고 E가 대신하므로). ② 받을 때 점검(허용 이름·실행 비트·링크·자동으로 읽히는 이름·크기)은 레포 전체에 하고 실패하면 닫는다(오류에 파일 경로). ③ D-Bus 이름 점검은 B1에서 하지 않고 "건너뜀(E)"으로 기록(통과로 표시하지 않음) — 첨부 로그의 벤더 D-Bus 이름이 문서에 들어가므로 E에서 허용 목록을 데이터로 둔 문맥 검사로.

- **사내 모델로 쌓이는 기록·모듈 문서의 품질(11/05 사용자)**: "사내 문서는 사외로 가져 나올 수 없다 — 주기적으로 사내 Claude 모델로 점검하는 수밖에." 그래서 사외 재검토는 하지 않는다. 토큰 0인 보강 두 가지를 기본으로 넣는다: ① **출처 기록** — PR·커밋·기록 메모에 분석 환경·모델을 남겨 사내 모델이 만든 것만 골라낼 수 있게(B2·E), ② **근거 원문 검사** — 5-1·5-2 출력의 근거 줄이 입력 타임라인에 실제로 있는지 스크립트가 보고 없으면 사용자에게 표시(C0 채점의 S7 검사를 런타임에, B2). ③ **사내 Claude 정기 점검**은 토큰을 묶어 둔다: 지난 점검 뒤 사내 모델 출처로 들어온 것만 고르고, 먼저 토큰 0 검사(db_regress·시그니처 겹침·근거 원문·모듈 고정 사례 크기·형식)로 걸러, 걸린 것과 바뀐 모듈만 Claude로 본다(모듈 eval 고정 세트, 기록은 소수). 상한·주기는 F·G에서 `site_step.py` 명령으로 설계해 보인다.

- **유료 eval 미리 승인(11/05 사용자)**: G 전까지(B2 스킬 eval, C1+D 모듈 eval, 약한 모델 흉내 Haiku eval) **합계 $25** 안에서는 묻지 않고 돌린다. dry-run·실제 비용은 결과 노트에 남기고, 상한을 넘을 것 같으면 멈추고 묻는다. G 전체 재측정 81회는 그때 따로 묻는다.

- **월요일(11/9) 오전 목표(11/05 사용자)**: 설계 질문은 **추천안으로 바로 진행**하고 결정 기록에 남긴다(나중에 바꿀 수 있음). CLAUDE.md 확인 필수 항목(파서 규칙·이슈 DB 태그·시그니처 추가, 이슈 DB push)만 모아서 묻는다. **G 전체 재측정 81회도 상한 $80으로 미리 승인** — 묶음마다 결과를 남기고, 안전 위반이나 실패가 많으면 멈추고 묻는다.

- **첨부 로그 분석 결과 반영(11/05 사용자 확인)**: 첨부 로그(oFono 2·Android 1)에서 찾은 것을 샘플·변형·테스트 DB와 플러그인에 반영한다(운영 사내 DB는 나중에 사내 DB PR) — ① `tags.yaml` Android 벤더·프레임워크 태그(VCD·RIL·RILC는 common), ENT ims → network, PTD는 network 그대로 ② `ril.yaml` oFono 변형: SIM_IO·GET_NR_MODE·SIM_OPEN_CHANNEL·SET_UNSOL_CELL_INFO_LIST_RATE·SIGNAL_STRENGTH, Android UNSOL_DATA_CALL_LIST_UPDATED ③ 파서 코드: Android RIL 줄(`iccIO:`·`error <n>`·RilRequest/RadioConfig 태그), logcat phone id·`:` 든 태그, 벤더 IPC 오류 추출(`SIT_* RSP Error(RCM_E_*)`·`OnRequestComplete result≠0`), oFono 데몬별 레벨 보정, 값 0 오류 제외 ④ `fail-causes.md`: RadioError 숫자·ImsReasonInfo 121·RCM_E_*. 추천안 자동 적용: 모듈 문서·modules.yaml에 벤더 이름 허용(README·IMPL §1.6·상태 문장·D-Bus 검사 함께 고침), 모듈을 고르면 모델은 모듈 보기만 읽음(모듈 신호가 약하면 전환 질문 1회), Haiku 약한 모델 A/B는 $25 안에서. **마스킹 빈틈 M1~M8을 B2 전에 고친다**(분석에서 발견: syslog 호스트, 모뎀 hex 덤프 속 ICCID, APDU/SIM_IO 응답, base64 인증값, SETUP_DATA_CALL 위치 인자 비밀번호, GVariant 비밀번호, JSON 바이트 배열 IP, 빌드·제품 코드, SMSC·NAI 속 IMSI). 설계 에이전트가 "합성 로그만"으로 되돌린 것(UQ-1)은 사용자 지시 인용을 잘못 읽은 것이라 받아들이지 않는다 — **마스킹한 실제 발췌 허용은 그대로**, 단 M1~M8 반영 뒤의 마스킹으로 만들고 남은 식별자 검사를 통과한 것만.

- **B2 설계 질문(11/05, 추천안 자동 적용)**: ① 마스킹 M1~M11 커밋으로 생기는 골든·기대값 갱신은 **마스킹 토큰 교체와 events.json `mask_allow` 키뿐인 차이에 한해** 허용하고, 커밋 전에 차이 요약과 마스킹 관문 숫자를 사용자에게 보인다(그 밖의 차이나 샘플·변형 DB의 새 db_lint·mask_pii 지적이 있으면 멈춤, `tests/test_golden.py:13-14`). ② `tests/fixtures/module-filter/`에는 M 반영 뒤 마스킹으로 만든 첨부 로그 발췌를 두고, `tools/fixture_residual.py --against`(사업자 이름·벤더 장치 노드·빌드 시각·syslog 호스트도 거름)를 통과한 것만, fixture README에 파일별 출처 줄. `check_boundary.py`는 바꾸지 않는다. eval 78 fixture는 합성.

- **목표(11/05 사용자): 모듈별 스킬로 최소 토큰, 최대한 정확한 가설.** 장치: 모델은 모듈 보기만 읽고(전체 타임라인 대신), 받기 명령이 정한 파일만 Read, 문서·출력 바이트 상한, `check-output` 고정 칸, 근거 원문 검사, 모듈 선택 질문. 측정: 모듈 eval·Haiku 비교에서 1순위 통과와 함께 **토큰 차이를 모듈별로 기록**하고, 관문 "문서 있음 ≥ 없음·안전 위반 0"에 더해 **토큰은 문서 없음보다 늘지 않는 것을 목표**로 둔다(넘는 모듈은 결과 노트에 표시하고 문서를 줄인다). C1·D 설계와 G 측정 기준에 넣는다.

## I. OpenCode·사내 GLM판 (H 다음)

- **계획 I 1단계 결과(11/05, 추천안 자동 적용 — 사용자 "추천안으로 진행")**: 가짜 모델 서버 실험(비용 0)으로 확인. ① **OpenCode v1은 분석 전용(안 A)** — Jira 코멘트·이슈 DB push·`db_pr publish|merge`·리뷰어 요청·스킬 적용·module_eval은 OpenCode에서 막고 "정확한 명령"을 출력해 사용자가 직접 또는 Claude Code에서 실행(전체 쓰기 흐름 안 B는 사내 사용을 보고 나중에). ② 설치 스킬 선택(Q2 바꿈)은 스크립트가 SKILL.md 경로를 풀어 **모든 런타임에서 Read**로. ③ 확인 화면·must_show가 있는 흐름은 `tt-oc` 래퍼(run + 세션 이어가기), TUI는 자유 탐색만(표시 보장 없음). ④ 읽기 전용 module_eval 자식은 사내 인증 확인 뒤 `--bare`(실패 시 자동 대체). ⑤ GLM 프롬프트는 OpenCode 에이전트 프롬프트 1개(약 2KB) + C0 형식 공용 스킬, 사내 확인에서 실패한 곳만 GLM 전용. ⑥ OpenCode 설정은 허용 목록 백스톱을 프로젝트 설정에 넣고 `/etc/opencode` 예시를 함께 — 사내 관리자 배포는 다중 방어. ⑦ Claude Code + 사내 모델 수정(`claude_child` 게이트웨이 env 이어받기, 비용 미상)은 I-2에서. ⑧ OpenCode는 `task: deny` 전역. 그 밖 확인: OpenCode bash 권한 패턴은 우회 가능(보안 경계 아님) → guard.py를 `oc_adapter`로 재사용하고 실패 시 닫힘, `snapshot:false` 필수, 비대화 `run`은 질문 불가·`ask` 자동 거부, AGENTS.md가 CLAUDE.md보다 우선. 상세 scratchpad 계획 I brief.

- **OpenCode Jira 읽기(11/05 사용자 "사내 확인 뒤 설정으로 열기" — 사내에서 OpenCode에 Jira MCP를 붙여 쓰고 있음)**: 코드 상수 관문(`oc_adapter.JIRA_READ_RELEASED`)을 사내 확인 기반 설정으로 바꾼다. 반입 뒤 사용자가 `site_step.py runtime-check opencode --jira`를 한 번 돌린다(모델 호출 없음 — 가짜 모델 서버로 실제 opencode·실제 사내 Jira MCP를 거쳐 정상 티켓 1건·없는 티켓 1건을 읽고, 원문 격리·마스킹·오류 경로를 본다). 통과 기록이 있을 때만 사용자가 직접 `config.py set`으로 연다(OpenCode 안의 모델은 열 수 없다). 오류 응답(1.19.5는 MCP 오류에 after hook을 돌리지 않음)은 본문을 숨기는 처리를 찾고, 못 막으면 점검이 남는 것을 보여 주고 열 때 명시적으로 받아들이게 한다. 코멘트 쓰기는 v1에서 그대로 막는다.

- 사내에 OpenCode가 배포돼 있다. **버전은 1.19.5**(11/03 사용자) — 규격 확인·빈 플러그인 실험은 이 버전 기준으로 한다. 모델은 GLM 5.3 또는 5.2(11/03 사용자, 어느 쪽인지 확인 중)이고, max 설정 기준 컨텍스트 202K 토큰·최대 출력 16K 토큰이다(11/03 사용자). 도구 호출·접속 방식은 사용자가 확인 중이다.
- Claude Code판과 **최대한 함께 간다**. 다만 사내 모델이 약해 공통 부분을 망칠 수 있다는 걱정이 있으므로: 한 레포에서 **공통 코어**(Python 스크립트·계약·테스트·이슈 DB·모듈 스킬 레포)는 같이 쓰고 PR + 전체 테스트·골든·안전 테스트(+ 코어를 바꾸면 Claude판 핵심 eval 일부)를 통과해야 바뀐다. **겉**(Claude판 스킬·커맨드·hook / GLM판 OpenCode 커맨드·플러그인·GLM용 짧은 프롬프트)은 나눈다. GLM판은 코어를 반입 묶음 라벨로 고정해 쓴다. 플러그인 개발은 사외(Claude), 사내 GLM은 실행 위주.
- **실행 환경은 셋이다(11/05 사용자)**: Claude Code + Claude, **Claude Code + 사내 모델**(게이트웨이로 모델만 바꿔 띄움), OpenCode + GLM. 두 번째는 hook·guard·Skill 도구가 그대로 있어 설치 스킬 선택(Q2 바꿈)도 되지만 모델 한도(출력 16K·문맥 202K)와 약한 모델 위험은 GLM과 같다 — 그래서 안전은 스크립트가 지키고, 모델에 주는 입력(모듈 문서·타임라인)은 작게 거른다. `module_eval`은 `ANTHROPIC_*` 환경을 자식에 넘기므로 `--model <사내 모델>`·비용 미보고 시 `--no-require-cost`로 잴 수 있다(사내에서 확인). I에서 세 환경을 모두 표로 다룬다.
- 첫 단계: OpenCode 규격 확인(11/05 확인: 이 환경에서 `opencode.ai` 문서 접근 가능, npm `opencode-ai` 1.19.5 받기 가능)과 빈 플러그인 실험(MCP·Bash·편집 차단이 확실한지, 질문 도구, 스킬 로딩, `opencode run` 출력), GLM 도구 호출 확인. GLM으로 하는 실행·eval은 사내.
