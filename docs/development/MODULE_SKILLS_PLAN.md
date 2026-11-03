# 다음 작업 H — 모듈 스킬 레포와 +1 병합 (결정 기록, 11/02~03)

`DRAFT_NOTES.md` 남은 일 H·결정 (u). 지금 PR(11/02 재리뷰 수정)과 새 반입 묶음 **뒤**에 시작한다. 시작할 때 이 기록으로 계획 문서를 만들어 사용자 확인을 받는다(계획 → 확인 → 구현 → 별도 리뷰 → 테스트·eval). 아래는 사용자가 정한 것만이다 — 구현이 맞는지는 적지 않았다.

## 무엇을

- 이슈 DB에 맞는 후보가 없을 때의 가설(탐색 분석, Step 5-2)과 1위 후보가 있을 때의 심층 분석(Step 5-1)을 **모듈별**로 둔다: ① 탐색 모듈 문서, ② 심층 분석 스킬(판단 순서·점검 목록·코드 경로). 둘 다 만든다.
- **oFono와 Android 둘 다** 같은 방식이고, **Android도 모듈별 기본 스킬을 새로 만든다**(11/03 사용자). 사내에 이미 있는 Android 분석 스킬은 사내 S-4a에서 그 모듈 스킬에 합친다.
- Android 모듈→구성요소(로그 태그·AOSP 클래스·RIL 요청·벤더 RIL) 대응은 계획 때 AOSP 공개 개념·레포 샘플 DB `tags.yaml`·사외 Android 표본에서 초안을 만들어 사용자 확인을 받는다(모듈은 oFono와 같은 7개를 기본으로).

## 공유·갱신

- 사내 GHE에 **모듈 스킬 레포 1개**, 모듈별 디렉토리. ①은 그 모듈 디렉토리에 함께 둔다(플러그인 내장 `log-guide.md`는 공통 줄 모양·계층만).
- 필요한 모듈만 그때 받는다(도구가 관리하는 clone에 sparse checkout, 쓸 때마다 최신 main, 리포트에 스킬 커밋 SHA).
- 개선: ②는 `[스킬]` 제안(기존 흐름), ①은 원인을 확정·기록할 때 "탐색 문서에 보탤 점" 제안. 도구 브랜치에 반영 → diff·스크립트 점검 결과(형식·크기·`mask_pii --check`·로그 원문·사내 값·링크)와 Claude 의견(참고) → **본인이 리뷰·승인한 뒤 push·PR**. 개인 clone은 건드리지 않는다.

## 병합 규칙 (스킬 레포·이슈 DB 공통)

- **작성자 외 아무나 +1**(GHE Approve, 지금 head 커밋에, Request changes 없음). 모듈 오너 지정은 하지 않는다.
- 이슈 DB의 "push하고 바로 병합"(`issue_db.merge: self` 기본)을 없애고 이 규칙으로 바꾼다. eval 72 다시.
- "병합해줘" → `db_pr merge`가 +1을 확인하고 병합. +1이 없으면 병합하지 않고 이유·PR 링크를 보인다. 리뷰어 지정은 **묻고** 승인하면 요청, 지정하지 않으면 아무나.
- +1 뒤 GHE 웹에서 직접 병합해도 된다 — 브랜치 보호(필수 승인 1·필수 검사·최신 브랜치 요구) 권장을 사내 안내에.

## 모듈 → 데몬 (11/03 확정, 데몬 이름은 레포에 그대로 — 사용자)

| 모듈 | 데몬 |
|---|---|
| data | NMD, MOSE, ofonod(gprs·lte), DITD, exynos-ril |
| sim | ofonod(sim), LPA, ipad, exynos-ril, MOSE |
| network | ofonod(netreg), exynos-ril, PTD, MOSE |
| call | ofonod(voicecall), exynos-ril, IMSSVC, MOSE |
| sms | ofonod(sms), exynos-ril, IMSSVC, MOSE |
| ims | IMSSVC, ENT, ofonod(ims), exynos-ril, MOSE |
| modem(common) | ofonod(modem), exynos-ril, DMD, RFSD, vcd, MOSE |

- location(GPS0·VRD)은 넣지 않는다. 표본에 없는 사내 데몬은 S25에서 더한다.
- 표본의 그 밖 내용(값·호스트·D-Bus 이름 — `org.ofono.*` 제외)은 여전히 레포에 넣지 않는다.

## 검증 (11/03 사용자 확인)

- 모듈마다 `SKILL.md`·reference는 skill-creator로 쓰고 eval로 검증한다(CLAUDE.md). 모듈별로 **이슈를 가정한 합성 시나리오**를 만들어, 스킬이 그 원인을 찾아가는지(층을 따라 내려가 처음 실패한 데몬·근거 줄) 본다.
- 판정: 같은 모델로 스킬 있음/없음 비교(16 §16.5.1 — 나아지지 않으면 연결하지 않는다), 1순위 원인·근거, 2순위 토큰. 안전 행(마스킹된 값만·로그 원문 통째 인용 없음·파일 수정 없음·규칙은 제안만)은 실패 불가.
- 사외 한계: 합성 로그와 공개 표본 모양뿐이다. 실제 해결 이슈로 하는 검증은 사내(S-5 `offline_eval`, 해결된 Jira 20~30건).
- 규모(모듈 수 × 시나리오 × 있음/없음 × 반복)와 비용은 계획 문서에서 정한다.
