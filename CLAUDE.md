@SITE_PROFILE.md

# Telephony Triage Plugin — 개발 진입점

Android Telephony 이슈 도구: Jira 이슈와 logcat으로 원인·해결책을 분석하고 사내 GitHub 이슈 DB(`telephony-issue-db`)에 누적한다. v1 범위는 `01-architecture.md §1`.

> **작업 모드를 먼저 판별한다.** 처음 맞는 것을 쓴다:
> 1. **사용자가 모드를 말하면** 그 모드 ("사외 초안" / "사내 보완" / "사내 처음부터").
> 2. **`SITE_PROFILE.md`가 있으면 사내 모드.** 그 "진행 상태"의 모드·단계에서 잇는다.
> 3. **`.local-draft`가 있으면 사외 초안.** 사외 PC 전용 표식(반입 안 함, `15-local-draft.md §15.2`). `DRAFT_NOTES.md` "진행 상태"에서 잇는다.
> 4. **`DRAFT_NOTES.md`만 있으면 묻는다** (반입 때 같이 가므로 이것만으로 판별하지 않는다): 사외 초안 계속(`.local-draft` 생성) / 사내 보완 S-1 시작(`SITE_PROFILE.md` 생성, "모드: 사내 보완").
> 5. **모두 없으면 묻는다**: 사외 초안(Phase D0, `.local-draft` 생성) / 사내 처음부터(Phase 0).
>
> | 모드 | 시작 | 읽을 것 | 진행 상태 | 하지 않는 것 |
> |---|---|---|---|---|
> | 사외 초안 | D0 → 1~13 | `11-phases.md`의 **그 Phase 절**과 "읽을 문서" | `DRAFT_NOTES.md` | Phase 0, 14 |
> | 사내 보완 | S-1~S-7 (`15-local-draft.md §15.5`) | `context_pack.py S-n` 출력만 | `SITE_PROFILE.md` | **Phase 0·D0·1~13 재실행, `11-phases.md`·문서 전체 읽기** |
> | 사내 처음부터 | 0 → D0 → 1~14 | 사외 초안과 같음 | `SITE_PROFILE.md` | — |
>
> 위 import가 안 되는 환경(S1)이면 세션 시작 시 `SITE_PROFILE.md`를 먼저 읽는다.

매 세션 로드되므로 ≤4KB로 유지한다. 설계는 `docs/design/` (지도: `docs/design/README.md`. 표·정의가 다르면 `contracts.md`가 맞다). `docs/history/`는 읽지 않는다.

## 작업 방식 (상세 `11-phases.md §11.0`)

- Phase(S 단계) 하나씩 한다. 끝나면 완료 기준 점검 → 요약 → **사용자 확인** → 진행 상태 갱신. 확인 전에는 다음으로 가지 않는다.
- 코드·스킬·이슈 DB 동작을 만들거나 바꾸는 단계는 **`docs/design/12-principles.md`(원칙)** 를 먼저 읽는다.
- 플러그인 규격·hooks 스키마·GHE Actions 문법은 구현 전에 최신 공식 문서로, 접근할 수 없으면 빈 플러그인 실험(S1)으로 확인한다. 문서와 다르면 확인 결과를 따르고 사용자에게 보고한다.
- 사내 확인값은 `SITE_PROFILE.md`에만, 사내 코드·값은 `SITE_PATHS` 경로에만 둔다. 문서의 태그·로그 문구·심볼·서버 이름은 placeholder다(데이터 스택 태그 형식만 확정, `14-site.md §14.1`).
- `SKILL.md`와 `reference/`는 skill-creator로 쓰고 eval로 검증한다.

## 항상 지킬 것 (상세 `12-principles.md`)

- 분류 확정, 새 유형·원인, 시그니처·파서 규칙 추가, 수정 상태 변경은 **사용자 확인 후**에만.
- 이슈 DB push는 변경·diff·검증 결과·커밋 메시지를 보여주고 **승인받은 뒤에만**. main 직접 push 금지.
- 사용자의 이슈 DB clone은 브랜치도 파일도 바꾸지 않는다.
- 테스트·매칭·이슈 DB에는 마스킹된 로그만 쓴다. Jira는 읽기 전용.
- 생성 파일(README·STATS·CHANGELOG)은 `db_build.py`로만 만든다.
- 판정 기준은 스크립트 출력이다. LLM 결과는 리포트 보조. 건너뛴 검증을 통과로 표시하지 않는다.
- git 충돌·인증 실패·MCP 부재·버전 불일치는 우회하지 말고 보고한다.
