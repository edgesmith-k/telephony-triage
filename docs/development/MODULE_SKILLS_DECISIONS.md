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
- **Q2 바꿈(11/05 사용자, B1 설계 중)**: 기존 설치 스킬이 있으면 레포 주소가 있어도 **사용자 설정으로 그 스킬을 쓸 수 있게** 한다. 카테고리별로 고르는 opt-in(기본은 모듈 문서): `[platforms.<p>.]analyzers.<cat>`에 기존 `skill`과 함께 고르는 키를 둔다(형태는 B1 설계). 주소가 없으면 `skill`을 쓰는 예전 Q2 동작은 그대로. 설정만으로 정해져 캐시·출력 결정성 유지, 설정이 없으면 출력 그대로. OpenCode(I)에는 Skill 도구가 없어 이 선택은 Claude Code판에서만 — I에서 보고 방식을 정한다.
- **첨부 로그 기준(11/05 사용자)**: 모듈별 로그 필터·모듈 문서·평가 사례는 사용자가 첨부한 실제 로그(oFono syslog 2개, Android logcat 1개)를 기준으로 만든다. "사내랑 안 맞는 것은 사내에서 바꾼다." 그래서 로그에 나온 데몬·태그·ofonod 소스 파일·RIL 요청·D-Bus 이름·줄 모양을 placeholder 대신 실제 값(출처 R)으로 쓰고, 로그에 없는 것만 자리 표시로 둔다. 테스트 fixture·평가 사례 로그는 **마스킹한 실제 발췌**(에피소드 구간만, 호스트·일련번호·IMSI/ICCID/EID·제품 코드 등은 토큰으로)를 쓸 수 있다 — 마스킹 안 한 줄은 쓰지 않는다(CLAUDE.md "마스킹된 로그만"). fixture-origin 점검 변경은 설계에서 보이고 확인받는다. 레포가 비공개라 마스킹 발췌를 브랜치에 올려도 된다(11/05 사용자 확인).
- Q8(A1 시작 때): `db_pr merge --approved` 생략 허용 — `merge-offer.json`의 head를 쓰고, PR head가 다르면 거부, `sync-pr`이 head를 갱신.

## 진행 방식 (11/04 사용자)

- **단계마다 리뷰 1회.** 확인된 P0·P1은 그 단계에서 한 번 고치고 테스트·기계 검증(말뭉치·오라클 등)으로 확인한다 — 고친 것을 다시 리뷰하지 않는다. P2만 미뤄 결과 노트 "반입 뒤 후보"에 적는다(결정 (r) 그대로, (p)의 "P0·P1이면 다시"를 대신한다). A1에서 guard 리뷰가 6회 넘게 돈 것을 끊기 위해.
- **guard 규칙 11에 남은 P1**(예전부터 있던 우회 빈틈): 쉬운 3개 — 디렉토리 스택 tilde(`cd ~-`·`~N`), 명령 낱말에 붙은 입력 리디렉션(`git</dev/null push`), 공백 없는 `bash<<EOF` — 는 **A2 직후·C0 전**에 고친다(A2도 guard.py를 고쳐서 그 뒤). 셸 구조 빈틈(루프 되돌이·while 조건·함수 본문 cd·짧은 경로의 링크 뒤 `..`)은 G 또는 반입 뒤.
- **C0부터 OpenCode·GLM 제약을 스킬 형식에 반영**한다(출력 16K·문맥 202K·Claude hook 없음) — I에서 스킬을 다시 고치지 않게.

- **일정 단축(11/05 사용자, 네 가지 모두)**: ① **E 개선 흐름은 이번 반입 뒤 다음 묶음**으로 — 그동안 모듈 문서는 GHE 웹 PR(+1 브랜치 보호)로 고치고 받을 때 점검(B1)은 그대로. ② **C1·D를 한 워크플로에서 병렬**로(Android 모듈 경계 Q9는 첨부 로그 기준 초안, 사내에서 조정). ③ **B1·B2를 묶어** 한 번에 구현·리뷰·검증(리뷰 관점을 늘려 보완). ④ **Q7 바꿈**: G 재측정은 쓰기 흐름 33개(병렬), 81개 전체는 반입 뒤 사내에서. 조건: "성능이나 버그는 최대한 없게" — 단계마다 리뷰·반박 검증·전체 테스트는 줄이지 않는다. 계획 I 1단계(OpenCode 규격·실험)는 H와 나란히(11/05 사용자).
- **사내 토큰 최소(11/05 사용자: "사내는 토큰이 얼마 없어")**: 사외에서 확인할 수 있는 것은 모두 사외에서 하고, 사내 단계는 LLM 없이 도는 스크립트로 만든다. 그래서 ④를 고친다 — **81개 전체 재측정도 사외 G에서**(skill eval 실행기에 병렬 옵션을 더해 시간을 줄인다, 유료 실행은 그때 승인). MS-1은 스크립트만(`make_module_repo`·`site_step.py modules check`). MS-2의 사내 Android 스킬 합치기는 선택 — 합치기 전에는 설치 스킬 선택(Q2 바꿈)으로 그대로 쓴다. 실제 이슈 eval은 선택·소수. 사내에서 이름이 안 맞는 것은 LLM 없이 사내 로그를 넣으면 모듈별 줄 수와 모르는 데몬·태그를 보여 주는 스크립트로 찾아 `modules.yaml` PR로 고친다(B2·C1 범위). 계획 I의 사내 확인은 환경마다 짧은 확인 실행 1회. 반입 뒤 사내 site eval(IMPL §4.8 8번, 지금 11개+)은 이번 묶음 변경이 닿는 것만 고르는 목록을 사외에서 만들어 반입 노트에 넣는다(바뀐 파일 → eval 대응, 나머지는 "영향 없음"으로 기록) — 사내 재점검(S-4a·O-3·S-6)·pytest·골든·샌드박스 PR은 스크립트라 토큰이 들지 않는다.

## I. OpenCode·사내 GLM판 (H 다음)

- 사내에 OpenCode가 배포돼 있다. **버전은 1.19.5**(11/03 사용자) — 규격 확인·빈 플러그인 실험은 이 버전 기준으로 한다. 모델은 GLM 5.3 또는 5.2(11/03 사용자, 어느 쪽인지 확인 중)이고, max 설정 기준 컨텍스트 202K 토큰·최대 출력 16K 토큰이다(11/03 사용자). 도구 호출·접속 방식은 사용자가 확인 중이다.
- Claude Code판과 **최대한 함께 간다**. 다만 사내 모델이 약해 공통 부분을 망칠 수 있다는 걱정이 있으므로: 한 레포에서 **공통 코어**(Python 스크립트·계약·테스트·이슈 DB·모듈 스킬 레포)는 같이 쓰고 PR + 전체 테스트·골든·안전 테스트(+ 코어를 바꾸면 Claude판 핵심 eval 일부)를 통과해야 바뀐다. **겉**(Claude판 스킬·커맨드·hook / GLM판 OpenCode 커맨드·플러그인·GLM용 짧은 프롬프트)은 나눈다. GLM판은 코어를 반입 묶음 라벨로 고정해 쓴다. 플러그인 개발은 사외(Claude), 사내 GLM은 실행 위주.
- **실행 환경은 셋이다(11/05 사용자)**: Claude Code + Claude, **Claude Code + 사내 모델**(게이트웨이로 모델만 바꿔 띄움), OpenCode + GLM. 두 번째는 hook·guard·Skill 도구가 그대로 있어 설치 스킬 선택(Q2 바꿈)도 되지만 모델 한도(출력 16K·문맥 202K)와 약한 모델 위험은 GLM과 같다 — 그래서 안전은 스크립트가 지키고, 모델에 주는 입력(모듈 문서·타임라인)은 작게 거른다. `module_eval`은 `ANTHROPIC_*` 환경을 자식에 넘기므로 `--model <사내 모델>`·비용 미보고 시 `--no-require-cost`로 잴 수 있다(사내에서 확인). I에서 세 환경을 모두 표로 다룬다.
- 첫 단계: OpenCode 규격 확인(11/05 확인: 이 환경에서 `opencode.ai` 문서 접근 가능, npm `opencode-ai@1.19.5` 받기 가능)과 빈 플러그인 실험(MCP·Bash·편집 차단이 확실한지, 질문 도구, 스킬 로딩, `opencode run` 출력), GLM 도구 호출 확인. GLM으로 하는 실행·eval은 사내.
