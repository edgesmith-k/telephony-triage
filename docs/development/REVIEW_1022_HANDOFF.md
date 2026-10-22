# 10/21~22 변경 전체 리뷰 인계 (PR #71, 브랜치 `ccr-d022623a-2f4vdx`)


> **결과(10/22): 리뷰 완료.** P0 0. P1 수정 커밋 5f1a72a·4e59420·b6e2c8e·f0a2c9e, 남긴 P2와 테스트 결과는 `docs/history/draft-notes-2026-10.md` 10/22 전체 리뷰 줄.

다음 세션에서 이번 변경 전체를 리뷰하기 위한 요약. 기준: `origin/main..HEAD`(커밋 26개, 100파일, +3,972 −806, 마지막 ba11f49).
리뷰 방법(사용자 결정 (p)·(r)): 관점별 리뷰 → P0·P1만 고침, P2는 기록.

## 1. 바뀐 것 (주제별)

| 주제 | 커밋 | 요지 | 주요 파일 |
|---|---|---|---|
| 사내 피드백 10건 | 7e6d5bb~cac7033 | 골든 synthetic 표식, 실제 site 백엔드 픽스처, `test_site_defaults_required` 사내 skip, DataCallResponse `cid` 마스킹 제외, 첫 push 문서, 분석 스킬 만들기(16 §16.5.1·뼈대 `docs/analyzer-skills.md`), 리포트 안내 줄, 규칙 제안 → Step 7 | `common/masking.py`, `tests/conftest.py`, `SKILL.md`, 16·contracts·SITE_INSTALL |
| 규칙 제안 질문 | fe82874·76f9c56 | 여러 개 가능, 줄마다 선택지 + `모두` + `받지 않음(기본 — 확인 안 한 제안은 반영하지 않으려고)` | `SKILL.md:76`, 07·16 |
| `[스킬]` 제안 patch | 8a5b15d·30892eb·af3f6bc·0fa7151 | `skill_patch.py`(difflib·마스킹·사본 `git apply --check`) + show_guard `patch` 표시 의무(안내 줄 글자 그대로). 반영은 사용자 판단(dev 브랜치 → main PR) | `skill_patch.py`, `common/shown.py`, `show_guard.py`, `reference/skill-patch.md` |
| 스킬 소스 바로 적용 | 99d8231 | `analyzers.<cat>.source` 있으면 승인 뒤 `skill_patch.py --apply --sha`(작업 트리만, 커밋·push는 사용자). guard 규칙 12, meta에 source 고정 | `skill_patch.py`, `guard.py` |
| verify-fix 빌드 기준 | b99ec55·6080b64 | 모뎀 아닌 원인은 로그 빌드를 `fixed_in`과 비교 안 함(`build_check: not-compared`) + "이 빌드에 수정 패치가 들어 있나요?" 1회 확인. 모뎀은 기존 비교. `--bundle` → `verification.note`. `fixed_in` 빌드 기록은 계속 필요(스키마) | `db_verify.py`, `reference/verify.md`, 05·07 |
| 이슈 DB 본인 바로 병합 | 99d8231 | 확인 화면 선택지 `push하고 바로 병합 / push만(리뷰어에게) / 취소`(질문·권한 확인 1회), `publish --and-merge`, 검사·병합 가능 상태·메인테이너 경로·main 불변 확인, 대기 최대 420초(상한 480), `db_pr merge` 재시도. `issue_db.merge: self|review`(기본 self). guard 7 ask·11 raw merge deny·기록 보호. `CLAUDE.md` 한 줄 | `dbpr/merge.py`, `dbpr/publish.py`, `db_summary.py`, `guard.py`, `write-flow.md`, 06·08·12·SITE_INSTALL §9 |
| 카테고리 오너 제거 | ba11f49 | 샘플 CODEOWNERS 메인테이너 경로만 → `리뷰어: 없음`. 카테고리 오너가 리뷰어면 병합 선택지 없음. 오너 리뷰 요구 문구 → 상태 문구 | `db_summary.py`, `dbpr/merge.py`, fixture CODEOWNERS |
| eval | 8a5b15d·ba11f49 등 | eval 71(스킬 patch), 72(본인 병합, 배치 M) 추가. 기록 흐름 33개에 'push만' 응답, verify-fix 5개에 '패치 포함 예' 응답 | `evals.json`, `grade.py`(checks_k·checks_m), `skill_eval_env.py` |
| 자료 | 2ae88cc~c1df6b8 | 책·교육·소개·브리프·Step 7 그림(쉬운 설명) | `docs/book`, `docs/materials` |

## 2. 검증 상태

- 전체 pytest(10/22 중간): 2,118 통과, 실패 1(`test_show_guard::test_hook_replay_counts_without_content`, 변경 전부터 환경 의존). 마지막 커밋 뒤 전체는 돌리지 않았다 — 리뷰 전에 한 번 돌린다.
- 사외 eval: 10/21 전체 60개 pass 55·fail 5(표시 누락 P2: 15·40·46·63·69). 그 뒤 관련만 재실행 — 71(n4), 40·41(n3-q), 19·20·23·24·25(n5·n6), 기록 흐름 10개(1·9·16·20·26·28·36·48·61·67, n7), 72·42·37·32(n8) 모두 fail 0. **결정 (i) 예외(사용자 승인)**: hook·guard·확인 화면 변경에도 전체 재측정 안 함.
- `offsite_results.json`은 10/21 기준(71·72는 손으로 넣은 `none`). 재실행분 수동 채점·재생성은 **사용자 결정으로 나중에**.
- 리뷰: 기능마다 별도 리뷰 1~2회, P0 0. 반영한 P1: patch 마스킹 뒤 적용 불가·채점기 오판·`$P` 변수, 패치 포함 확인 질문, 병합 검사 없음 통과·기록 파일 보호·적용 대상 고정·대기 상한, 화면 문구 모순.

## 3. 리뷰 때 볼 것 (열린 점)

- **원칙 변경**: "리뷰어 승인" → 본인 병합 기본. 12-principles·06·08·`CLAUDE.md`·책이 일관한지, 안전장치(승인 해시, guard ask, main 직접 push 금지)가 약해지지 않았는지.
- **사내 GHE 미확인**: "필수 승인 0 + CODEOWNERS 리뷰 필수" 조합(TODO(SITE:S5)). 안 되면 `issue_db.merge: review`.
- `SKILL.md` Step 8은 아직 "승인 → publish --commit --and-discard"(write-flow로 위임, 빠뜨리면 push만 — fail-safe). 고치면 전체 재측정 대상.
- 남긴 P2(history 10/22): `--`/`++` 내용 줄의 +/− 개수, 사용자 git config 영향, 같은 내용 재실행 다음 턴 강제 안 함, `.git` 경로 사본, 큰 SK 복사, 경로 대소문자, 대형 diff 표시 의무 약함, ancestor 검사와 merge 사이 경쟁, `resolution_type` 없으면 비교 안 함, `--bundle` 값 검증 최소, eval 42 리뷰어 단언 엄격, 다른 카테고리 allow-cause는 월간 리뷰에서만 잡힘, DataCallResponse 닫힘 없을 때 cid, 첫 push 예외 상호 참조.
- eval 47 `match.json` 열람(10/21 부분 실행, 모델 편차).
- 재반입: `docs/development/REIMPORT_NOTES_1021.md`(사내에서 넣은 SKILL·16 문구 되돌리기, 뼈대 zip 해시 변경, CODEOWNERS·브랜치 보호 변경, 사내 eval은 추후).
