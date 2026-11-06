# DRAFT_NOTES 이력 (2026-11)

`DRAFT_NOTES.md`에서 옮긴 원문. 필요한 절만 찾아 읽는다.

## 11/03 진행 상태 원문 (H 시작 전)

- 모드: **사외 초안**. Phase D0·1~13·반입 전 보강 완료. 최신 묶음 **import-20261103**(main `77e2827`, 1102 대신). main 병합 PR #8~#79.
- 11/02~03 재리뷰 완료(#79, `REVIEW_1102_HANDOFF.md` 머리, 1102 §6). **다음: H — `MODULE_SKILLS_PLAN.md` 머리 "새 세션에서 이어 하기"**.
- 모델 Sonnet 5.5 기준(Opus 5.5 11개 실패 0). `TODO(SITE)`: `tools/list_site_todos.py`. REVIEW-OPEN 0. 사내 시작 **"사내 설정 시작"**(결정 (o)).
- 안내서: `docs/book/telephony-triage-book.html`(공유본 https://claude.ai/artifact/1jov1Et4dQUMauFr6aoxWG), 목록 `docs/materials/00-index.html`

## 11/03 이동: 결정 (m)·(n) 원문

- (m) 플랫폼 분리 (10/11, 사용자): 동작·원인·해결책이 달라 이슈 DB를 플랫폼별로(합치기 안 안 씀), 추가는 디렉토리 + `platform.enabled`, lock은 플랫폼별("사용자·이슈 DB(플랫폼)별 한 번에 한 작업"), RF-4 유지. `17-platforms.md` §7.
- (n) 트래커 범용화 (10/11, 사용자): 설정 `tracker.kind`(jira|github)·어댑터 `trackers/`, `issues/`·`platform_version(s)` 개명은 (d)로 v1 직접 수정, 옛 키는 감지만(fail-closed), DB kind 다르면 거부. `18-trackers.md` §7.
