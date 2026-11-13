# 10/30 변경 리뷰 인계 (커밋 전, 브랜치 `ccr-d022623a-2f4vdx`)

> **결과(10/31): 리뷰 완료.** P0 0. P1 3건 수정 — 모두 `triagelib/pick.py` 이어 하는 작업 판정: ① 명시 플랫폼이 로그 형식과 다를 때 답으로 정하지 않은 이어 하는 작업이 묻지 않고 명시를 덮음(D2) ② ①을 고치자 닿게 된 기존 결함: 플랫폼을 바로잡은 뒤 이어 하는 작업이 둘이면 플랫폼 질문과 다음 질문이 끝없이 번갈아 나옴 ③ ②의 첫 수정이 만든 회귀: 다른 플랫폼으로 옮긴 뒤 남은 옛 답이 D2를 덮음 → 저장된 답은 그 질문이 KEY의 가장 늦은 활동일 때만 쓴다(17 §11-3). 남긴 P2 17건은 `REIMPORT_NOTES_1030.md` §4 "10/31 재리뷰에서 더한 것". 테스트(묶음 5개): 2,351 통과, 실패 1(`test_show_guard::test_hook_replay_counts_without_content` — HEAD에서도 같은 실패, 원인은 이 PC `/tmp`에 남은 옛 `tt-ws-*` 폴더, 삭제는 사용자 허가 대기). `gen_contracts`·`sync_schemas`·`check_boundary --mode external`·3.10 compile 통과.

새 대화에서 이번 변경을 **선입견 없이** 리뷰하고, P0·P1을 고친 뒤 사용자 승인을 받아 커밋·push하기 위한 자료.
기준: `a06ca61`(= main, PR #71 병합) 위의 **커밋 안 된 작업 트리**. `git status` / `git diff HEAD`로 본다(수정 47파일 + 새 파일 11개, 이 문서 포함).

## 리뷰 방법

- 이 문서에는 **요청과 사용자 결정**만 적었다. 구현이 맞는지는 적지 않았다. 구현자·이전 리뷰의 판단(설계 문서 문구, 반입 노트, 코드 주석)은 검증할 주장으로 보고 **코드와 테스트를 직접 읽는다**.
- 항목마다: (1) 요청을 해결하는가 (2) 결정 범위를 넘거나 모자라지 않은가 (3) 새 결함·회귀 (4) 새 테스트가 수정 전 코드에서 실패하는가 (5) 문서·`contracts.md`가 코드와 맞는가.
- 등급: P0 안전 위반(이슈 DB push·병합 승인, guard, 마스킹, fail-closed, main 보호), P1 기능 결함·계약 불일치, P2 그 밖. 결정 (r): P0·P1만 고치고 P2는 `REIMPORT_NOTES_1030.md` §4에 남긴다. 수정 절차는 결정 (p)(계획 → 수정 → 별도 리뷰 → 테스트).
- 먼저 `CLAUDE.md`, `docs/design/12-principles.md`를 읽는다. `docs/history/`는 읽지 않는다.
- 사내 환경: Python **3.10.12**, Ubuntu 20.04. Android만 켠 설치는 **동작·출력이 바이트 단위로 같아야** 한다.
- 디스크가 빠듯하다: pytest는 `-p no:cacheprovider`, `TMPDIR`을 세션 scratchpad 아래로 두고 끝나면 비운다. `/tmp`의 옛 `tt-*` 폴더 삭제는 사용자 허가 대기 중이라 지우지 않는다. 전체 테스트는 파일 묶음으로 나눠 돌린다.

## 사용자 요청 (10/30, 원문 요지)

1. "oFono도 확장 가능하게 틀 만들어주라. oFono 외에 여러 데몬도 같이 돌고 있어."
   - 사용자 답: 이슈 DB는 **oFono DB 하나에 모든 데몬** / 로그는 **한 스트림에 섞여서** / **데몬마다 소스 있음** / **데몬 사이 요청·응답 짝 필요**.
2. "(이슈 DB에 맞는 규칙이) 없는 경우 스킬로 가정해서 이슈 분석하는 것도 android와 다른 스킬로 동작해야 해" → 사용자 선택: **5-1 심층 분석(분석 스킬)과 5-2 탐색 분석(참고 자료) 둘 다 플랫폼별**.
3. "이슈 시작할 때 선택하게 하던지, 아니면 로그나 지라를 보고 판단하는 건 어때" → 사용자 선택: **로그로 자동 + 애매하면 질문**.

## 사용자 결정

- **데몬 틀** (17 §9, K12~K15)
  - 구성요소 계약은 `platforms/base.py` 공통 타입(`Component`·`MsgView`), ofono만 `block_keys`로 사용. android SPEC 불변.
  - 데몬 목록은 site-defaults `platform.others.ofono.components.<이름>`.
  - 메시지 하위 형식 hook과 `split_tag`(기본 꺼짐).
  - 데몬 사이 짝은 site가 이름 짓는 `kind: regex` 프로토콜(기본 꺼짐), 짝 키 serial, **대화 키(conv)는 넣지 않음**.
  - `platform_version`은 하나, 데몬별 버전은 참고 출력(`component_versions`). `ofono` 주 루트 계속 필수.
  - `ofono_reference` 0.0.2. S24~S28 행 확장(새 S 번호 없음).
- **가설 분석 분리** (17 §10, K16·K17)
  - 최상위 `analyzers` = 항상 Android. 다른 플랫폼은 `platforms.<p>.analyzers`(site-defaults와 사용자 config 모두), **Android로 대체하지 않음**(없으면 5-1 제안 안 함, 리포트 "해당 없음").
  - site-defaults `platforms.android` → 종료 2. guard 규칙 12는 모든 플랫폼·두 층의 분석 스킬 `source` 보호.
  - 5-2는 내장 `reference/platforms/<p>/`(ofono는 placeholder `log-guide.md`), `triage.py explore`가 Android 아닐 때만 `platform`·`refs` 출력. 사이트 지식 스킬 연결은 미룸. Android 참고 자료 머리말은 그대로. **SKILL.md는 바꾸지 않음**(크기 상한 9,063B).
- **플랫폼 자동 판단** (17 §11, K18)
  - 켠 플랫폼 2개 이상 + 명시 없음일 때만. 명시 = `--answer platform=` > `--platform` > `TT_PLATFORM`. 사용자 config `platform`은 기본값이라 분명한 로그 형식이 우선(D1).
  - 명시와 로그 형식이 다르면 lock 전에 한 번 묻기(D2). Jira 대응표 `platform.detect.tracker_field`는 기본 꺼짐, TODO(SITE:S28·S32)(D3).
  - 일부 파일 형식 모름 + 나머지 일치 → 진행 + 알림(D4). 기본과 다르면 출력에 `platform`(D5). 알림은 `notes` + report.md 한 줄(D6).
  - 포함: Jira 원문이 기본 플랫폼 work_dir에 저장되던 버그 수정.
- **eval**: 73·74 정의, 63에 단언 추가, 46·47 재측정 대상 — **실행은 나중**(사용자). `offsite_results.json`에 73·74는 `none`.
- 그 밖: `tools/list_site_todos.py`가 `TODO(SITE:S24·S25)`처럼 묶은 표시를 항목마다 셈.

## 바뀐 파일 (직접 확인할 것)

| 주제 | 주요 파일 | 새 테스트 |
|---|---|---|
| 데몬 틀 | `platforms/base.py`·`__init__.py`, `platforms/ofono/{__init__,backend,msgformat,pairing}.py`, `parse_logcat.py`(`_mask_record`), `code_roots.py`, `tools/make_db_skeleton.py`, `tests/helpers/make_variant_dbs.py`, fixture `journal-multi.log` | `test_ofono_components.py`, `test_code_roots.py` |
| 가설 분석 | `common/userconfig.py`, `platforms/session.py`, `guard.py`, `triage.py`, `triagelib/{core,report,driver}.py`, `skill_patch.py`, `reference/explore.md`, `reference/platforms/ofono/log-guide.md` | `test_platform_analyzers.py` |
| 자동 판단 | `platforms/sniff.py`, `triagelib/pick.py`, `triage.py`, `triagelib/driver.py`, `schemas/output/analysis.schema.json` | `test_platform_detect.py` |
| eval | `tests/skill_evals/{evals.json,grade.py,README.md,offsite_results.json,jira/MOCK-9073.yaml}` | `test_skill_evals.py` |
| 문서 | `17-platforms.md`(§9~§11, K12~K18), 02·07·08·10·14·16, `contracts.md`(+생성 `contracts-cli.md`), README, `site-defaults.example.yaml`(주석만), 샘플 DB `docs/analyzer-skills.md`, `REIMPORT_NOTES_1030.md`, `DRAFT_NOTES.md`(결정 (t)) | — |

## 검증 사실 (커밋 전)

- 전체 pytest(묶음으로 나눔): 2,346 통과, 실패 2. `test_show_guard::test_hook_replay_counts_without_content`(수정 전 HEAD에서도 같은 실패, 환경 의존)와 `test_repo_offsite_results_is_generated_record`(73·74 기록 누락 → 기록 추가 뒤 관련 54개 통과).
- `gen_contracts.py --check`·`sync_schemas.py --check`·`check_boundary.py --mode external` 통과. 3.10은 `py_compile`만(3.10에 pytest·yaml 없음).
- 이전 리뷰 2회는 일부러 결과를 적지 않는다. 새 리뷰가 끝난 뒤 비교하려면 `REIMPORT_NOTES_1030.md` §4(남긴 P2)를 본다.

## 리뷰 뒤 할 일

1. P0·P1 수정 → 관련 테스트 → 전체 테스트(묶음) → 이 문서 맨 위에 결과 한 줄.
2. 사용자에게 변경 요약·검증 결과·커밋 메시지를 보이고 **승인받은 뒤** 커밋·push(`git push -u origin ccr-d022623a-2f4vdx`). 새 PR을 만들지는 사용자에게 묻는다(PR #71은 병합됨).
3. 설명 페이지(이번 변경 기준): https://claude.ai/artifact/GBkx6UXAMxZrM75hxrbAsG — 레포 `docs/materials/`에 넣을지는 사용자 결정 대기.
