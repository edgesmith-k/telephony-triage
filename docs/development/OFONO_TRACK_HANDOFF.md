# oFono 사내 트랙·다음 반입 묶음 인계 (10/31, 브랜치 `ccr-d022623a-2f4vdx`)

새 대화에서 이어 하기 위한 자료. 사외 초안 모드.

## 지금 상태

- 사내는 S-6까지 완료(`site_step.py` 기록). 사내 레포는 묶음 **import-20261018** 상태다.
- 사내가 요청한 사외 수정(10건 + 17건)은 **PR #71**(병합, main `a06ca61`)에 있다. 아직 묶음으로 넘어가지 않아 사내에는 없다.
- 10/30 oFono 여러 데몬·플랫폼별 가설 분석·플랫폼 자동 판단과 10/31 리뷰 수정은 **PR #72**(열림, 설명 페이지 `docs/materials/platform-flow.html` 포함). Android만 켠 설치는 동작·출력이 같다.

## 할 일 (사용자 결정 10/31)

1. ✅(10/31 완료, 결정 (p) 계획→수정→리뷰(P1 2 수정·재리뷰)→테스트) **`site_step.py`에 oFono 트랙 추가** — 지금 진행기는 S-1~S-7(Android 도입)만 다루고, oFono 사내 항목(`14-site.md` S24~S29, `OFONO_LOG_COLLECTION.md`)은 단계·점검에 연결돼 있지 않다(빈틈). **단계 이름과 완료 기준을 먼저 사용자와 확정**한 뒤 결정 (p)(계획 → 수정 → 별도 리뷰 → 테스트)로 만든다. Android S-7과 따로 진행되고, 사내에서 "계속"이 안내하게 한다.
2. PR #72(+ 트랙)를 병합할지 사용자에게 묻는다.
3. 최신 main에서 `python3 tools/make_bundle.py --label import-2026MMDD`(종료 3이 정상, 사람 확인 3건). `plugin.json` 설명의 "사외 초안" 정리가 먼저. 태그·push·사내 반입은 사용자(`docs/SITE_INSTALL.md` §8, 노트 `REIMPORT_NOTES_1021/1028/1030.md` 순서).
4. 사용자에게 확인: 사내가 S-5·S-6에서 새로 요청한 사외 수정이 10 + 17건 밖에 더 있는지(사내 정보 없는 문장으로).

## 확정 (10/31 사용자)

- 별도 목록·병행: Android S 단계와 따로. `SITE_PROFILE.md` 진행 상태에 `- oFono 단계: O-n`·`- oFono 완료: O-1 (날짜), …`. 명령은 그대로 단계 인자로 O-n(`check O-2`·`propose O-2`·`--done O-2`).
- 시작 조건: S-3 완료 기록 뒤(site-defaults가 있어야 O-2).
- 안내: `site_step.py`는 Android 현재 단계 + oFono 트랙이 시작됐으면 한 줄 안내(`site_step.py ofono`). Android가 모두 끝났으면 oFono 단계를 바로 보인다. 시작은 "oFono 설정 시작" → `site_step.py ofono`.
- 기준치: O-3 카테고리마다 실제 fixture 유형 3개 이상, O-4 실제 oFono 이슈 5건 이상·플랫폼 오판 0, offline_eval 게이트 없음.
- 아래 초안에서 바꾼 것: ident ↔ `tags.yaml` 점검은 DB가 생기는 O-3으로(O-2는 ident가 O-1 로그에 실제로 나오는지).

## oFono 트랙 초안 (위 확정으로 고침)

| 단계 | 할 일 | 자동 점검 후보 |
|---|---|---|
| O-1 로그·형식 | 수집 체크리스트대로 로그 수집, 줄 형식 확인(S24). 다르면 사외 `platforms/ofono/journal.py` 수정 요청(형식만 문장으로) | 사람 확인 + 실제 로그를 placeholder 형식이 읽는 비율 |
| O-2 설정 | site-defaults `platform.enabled`, `platform.others.ofono`(`components`·`protocols`·`source_tree`, S25~S27), 선택 `platforms.ofono.analyzers`·`platform.detect` | 설정 검증 통과, 데몬 ident가 oFono DB `tags.yaml`에 있음 |
| O-3 oFono 이슈 DB | `make_db_skeleton.py --platform ofono`, 첫 push(§9와 같게), 실제 마스킹 fixture로 시드(S28) | `platform: ofono` 선언, `db_lint`·`db_regress` 통과, 카테고리별 시드 |
| O-4 사용자·시험 | `config.py init --platform ofono`, 실제 이슈 몇 건 | doctor 통과, 자동 판단으로 oFono가 골라진 실행 기록 |

확인할 점: 트랙을 `STEPS` 뒤에 붙일지 별도 목록으로 둘지, `SITE_PROFILE.md` 진행 상태 줄 형식(`14-site.md §14.3`), 점검 id 이름(`o1.*` 등), S-7 전에도 시작할 수 있게 할지.

## 읽을 것

`tools/site_step.py`·`tools/site_checks.py`·`tools/context_pack.py`, `docs/design/15-local-draft.md §15.5`, `docs/design/14-site.md` S24~S29·§14.3, `docs/design/17-platforms.md` §6(플랫폼 하나 더하기)·§8·§9, `docs/development/OFONO_LOG_COLLECTION.md`, `docs/development/REIMPORT_NOTES_1030.md`.
