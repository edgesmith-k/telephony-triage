# 리뷰 수정 트랙 V — 계획과 실행 틀 (2026-10-07)

- 근거: `docs/development/REVIEW_2026-10-07.md`(반입 전 레포 리뷰, R-1~R-47). 이 트랙은 그중 **차단 R-1 + 권고(반입 전) R-2~R-35**만 한다. R-36~R-47(반입 뒤)은 `ARCHITECTURE_REVIEW_2026-10.md` 색인으로 넘긴다(V 끝에서).
- 위치: W 트랙 뒤, Z(반입) 앞. W 끝(전체 테스트·eval·`make_bundle`)은 **V 끝과 합친다**.
- 실행 틀은 W와 같다: 역할 `IMPROVEMENT_PLAN_2026-10.md §1`, 한 건 순서 §2, 절차 §8. 이 문서는 다른 점만 적는다.
- **시작 문구**: 사용자가 "**리뷰 수정 진행**"이라고 하면 §4 진행 표의 ☐ 첫 VP(의존이 ✅인 것)를 §3 절차로 한다. 묻지 않고 시작한다.

## 1. 역할과 모델

| 역할 | 모델 | 하는 일 | 하지 않는 일 |
|---|---|---|---|
| **오케스트레이터** (메인 세션) | Opus 5.5 또는 Fable 5.1 | VP 선택, 입력 묶음(R 항목 번호 + 위치) 준비, 에이전트 호출, 결과 종합, 커밋·push, 표 갱신 | 직접 코드 작성(1~2줄 문서 수정 제외) |
| **계획** | Opus 5.5 (`Plan`) | VP 하나의 구현 계획: R 항목별 바꿀 파일·함수, 테스트, 동기화 문서, 결정 필요 항목 D1..Dn(선택지·권장) | 코드 수정 |
| **결정 위임** | Fable 5.1 (`Agent(model="fable")`) | D1..Dn 선택, 리뷰 권고 반영 범위, 범위 밖 발견 처리, 완료 승인. 근거 1~2줄 + 위험 최대 3개 | 파일 수정, 원칙상 사용자 승인 대상 대리 |
| **기술 자문** (선택) | Opus 5.5 | 결정이 코드 사실에 달릴 때 Fable 전에 사실 확인(예: "이 경로를 다른 호출자가 쓰는가"). 결과 파일을 Fable 입력에 붙인다 | 선택 |
| **실행** | Sonnet 5.5 — 아래 "Opus 실행" VP는 Opus 5.5 | 계획대로 구현 + 테스트 + 문서 동기화, `related_tests.py`(실행 없이)로 영향 보고 | 계획 밖 변경, 전체 테스트 |
| **리뷰** | 실행과 다른 모델: Sonnet 실행 → Opus 리뷰, Opus 실행 → Fable 리뷰 | diff 적대적 검토: 계약·종료 코드·마스킹·경계·원칙, R 항목의 "실패 시나리오"가 실제로 막혔는지. 차단 / 권고 / 통과 | 수정 |
| **테스트** | Haiku 4.5 | `python3 tools/related_tests.py --run` (+ 경계 VP는 `check_boundary`), 실패를 파일·테스트·원인 한 줄 표로 | 테스트 수정, 원인 추측 |

- **Opus 실행 VP**: V1(경계 모드 판별), V2(`import_draft` 목록 방식), V4(guard·jira_bridge 안전 경로), V7(R-35 삭제). 나머지는 Sonnet.
- 리뷰 차단이면 실행으로, 같은 VP 두 번 차단이면 계획으로.

## 2. 작업 묶음 (VP)

크기는 리뷰 문서 추정(테스트 포함 변경 줄 수). "관련 테스트"는 출발점이고 확정은 계획이 `related_tests.py`로 한다(`jira_bridge`·`mask_pii`·`db_add`·`precommit`·`offline_eval` 전용 테스트 파일은 없다 — 새로 만들지, 기존 파일에 넣을지는 계획이 정한다). 항목 세부(위치·제안)는 `REVIEW_2026-10-07.md`의 그 R 절만 읽는다.

| VP | 항목 | 크기 | 실행 | 관련 테스트 | 미리 보이는 결정(계획이 확정) |
|---|---|---|---|---|---|
| **V1 차단** | R-1 | ~35 | Opus | test_boundary, test_mocks, test_related_tests | 모드 판별 기준 파일(`.draft-manifest.json`·`SITE_PROFILE.md`) |
| **V2 반입 도구·경계** | R-19~R-24 | ~190 | Opus | test_import_draft, test_boundary, test_make_bundle | R-19 소스 목록: zip 직접 입력 / `git check-ignore`; R-21 보고만 / `--merge-site-paths`; R-22 버전 규칙 |
| **V3 문서·계약 drift** | R-25~R-31 | ~140(대부분 문서) | Sonnet | test_reference_cli, `gen_contracts.py --check`, test_context_pack | R-27 `ask\|always\|never` 통일(설계 변경); R-28 §3.2 제외 / 행 필터 |
| **V4 안전·hook·스킬** | R-2~R-8 | ~170 | Opus | test_hooks, test_safety, test_masking, test_checks, test_db_lint, test_reference_cli, test_commands | R-5 NUL 제거 후 검사 / `skipped_binary`로 실패; R-2 판정 접두사 출처 |
| **V5 S-0 도구·파서** | R-9~R-14 | ~215 | Sonnet | test_s0_stats, test_parse_logcat, test_platform_profile, test_commands(offline_eval) | R-11 부분 실패 기준(unparsed 50%) ; R-12 기본 버퍼 키 이름 |
| **V6 코어 오류 경로** | R-15~R-18 | ~185 | Sonnet | test_yamlio, test_db_lint, test_checks, test_db_pr, test_triage, test_db_migrate | R-18 `renumber` 브랜치 조건 |
| **V7 정리** | R-32~R-35 | +60 / −250 | Sonnet(R-35는 Opus) | test_db_migrate, test_platforms, test_db_build, test_sample_db, test_match_signatures | **R-35 캐시 삭제(설계 변경)**, R-34 생성 파일 바이트 변경 시 v1 직접 수정(결정 (d)) |
| **V 끝** | — | 0 | — | 전체 + eval | 아래 §3-8 |

**의존과 병렬**
- V1 → V2 (둘 다 `check_boundary`·`test_boundary`).
- V4·V5·V6은 서로 독립 → 사용자가 "V4·V5 같이"라고 하면 `EnterWorktree`로 병렬.
- V3은 V2 뒤(R-25·R-30이 `15-local-draft.md`·GUIDE를 V2와 함께 건드림).
- V7은 V3·V5·V6 뒤(R-33은 contracts·parser_backends, R-34는 db_build·db_summary, R-35는 match_signatures).
- 스킬·reference를 바꾸는 VP(V3 R-27, V4 R-7·R-8)는 완료 기준에 **해당 eval 번호 재실행(Sonnet)** 을 넣는다. 번호는 계획이 `tests/skill_evals/evals.json`에서 고른다.

## 3. "리뷰 수정 진행" 절차 (오케스트레이터)

`IMPROVEMENT_PLAN_2026-10.md §8`과 같고 다른 점만:

1. **선택**: §4에서 ☐ 첫 VP. 브랜치 `v/<VP>-<짧은이름>`(main에서). 상태 "계획 확인 중".
2. **계획** — `Agent(subagent_type="Plan", model="opus")`. 입력: 이 문서 §1·§2의 그 VP 행, `REVIEW_2026-10-07.md`의 해당 R 절 **번호 목록**, `CLAUDE.md`, `docs/design/12-principles.md`, R 절이 가리키는 파일 경로. 출력 형식: R 항목별 {바꿀 파일·함수, 새/수정 테스트, 동기화 문서, 완료 기준 = R 절의 "내용" 시나리오가 더는 재현되지 않음}, D1..Dn.
3. **결정** — D1..Dn을 `Agent(model="fable")`에 보낸다. 입력: 계획 요약 파일(scratchpad) + D 목록(선택지·권장·근거). 결정이 코드 사실에 달린 D는 먼저 Opus 기술 자문에게 사실만 확인시켜 그 결과 파일을 함께 준다. Fable이 "사용자 확인 필요"라고 하면 사용자에게 묻는다.
4. **실행** — §1 표의 모델. 입력: 확정 계획 + 결정 결과 파일 경로. 지시: 계획 밖 변경 금지, R 항목마다 회귀 테스트 1개 이상(R 절 "내용"의 실패 입력 그대로), 문서 동기화, 커밋은 하지 않음.
5. **리뷰** — §1 규칙의 다른 모델. 입력: `git diff main...`, 계획, 결정 결과, 해당 R 절. R 항목별 "막힘 / 안 막힘 / 부분" 표를 반드시 포함.
6. **테스트** — Haiku. `related_tests.py --run`. V1·V2는 `python3 tools/check_boundary.py --mode external`도. `full: true`면 오케스트레이터가 전체 `pytest -q --tb=short tests`.
7. **완료** — 요약(바뀐 파일, 테스트 수, R 항목별 상태, 리뷰 권고 처리)을 Fable에 보내 완료 승인 → 커밋(제목 앞 `V2: …`, R 번호를 본문에) → `git push -u <remote> <브랜치>` → §4 표·`DRAFT_NOTES.md` V 행 갱신, `REVIEW_2026-10-07.md` 해당 R 제목 끝에 `✅ V2`. PR → CI(boundary·3.11·3.14) 통과면 **main 병합까지 진행**(10/07 사용자 지정). 실패면 실행으로.
   - 테스트(10/07 사용자 지정): `related_tests.py`가 `full: true`면 로컬 전체 테스트를 백그라운드로 돌린다(약 19분, 결과 끝 몇 줄만 읽음). 실패는 알려진 Windows 환경 4건(gh 토큰·`:` 파일명·zip 모드·임시 경로 guard)과 메시지로 대조한다.
   - "끝까지 진행"이면 다음 VP를 묻지 않고 잇는다. 오케스트레이터 컨텍스트가 60%에 가까우면 VP 경계에서 멈추고 보고한다.
   - Plan 에이전트는 파일을 쓸 수 없다 → 계획은 `general-purpose`(Opus)에 "읽기 전용, plan.md만 쓴다"로 맡겨 오케스트레이터 컨텍스트를 아낀다.
8. **V 끝**: 전체 `pytest tests`, `db_regress --all`, `check_boundary`, `sync_schemas --check`, `gen_contracts.py --check`. eval은 `DRAFT_NOTES.md` 결정 (i)(변경 관련 최소): W 영향 미확인 목록(W2·W3·W4·W11) 중 V 이후에도 관련 있는 것만 계획이 골라 Sonnet으로, VP에서 이미 돌린 번호는 빼고. 전체 재실행은 사내 S-2. R-36~R-47을 `ARCHITECTURE_REVIEW_2026-10.md`에 "R-36~47(리뷰 10/07)" 한 줄 색인으로. 그 뒤 Z.

**공통 금지**(모든 에이전트): `IMPROVEMENT_PLAN_2026-10.md §8` 끝 문단 + `DRAFT_NOTES.md` 결정 (a)~(h)·W11 보류는 재논의하지 않음(새 근거는 "재검토 제안"으로 Fable에게) + Windows 환경 실패 4건은 실패로 세지 않음(Ubuntu CI 기준).

**사용자에게 직접 묻는 것**: main 병합·태그, 이슈 DB push, 결정 (i)를 넘는 eval 재실행(비용), Fable이 "사용자 확인 필요"로 돌린 것, `events.json` 스냅샷 대량 재생성.

## 4. 진행 표 (오케스트레이터가 갱신)

| ☐ | VP | 상태 | 브랜치·커밋 | 비고 |
|---|---|---|---|---|
| ✅ | V1 | ✅ 완료(10/07) | v/V1-boundary-mode · 커밋 `V1: …` | R-1. 위임 결정 D1 (b)·D2~D5 (a), D4는 가드 삭제 대신 `make_plugin_root` copytree에서 SITE_PATHS 제외(사내 백엔드 혼재도 해결). R-1 근거 정정(manifest 아님, SITE_PROFILE·site-defaults). 리뷰(Fable) 권고 3 반영. 전체 992 통과·4 실패(환경) |
| ✅ | V2 | ✅ 완료(10/07) | v/V2-bundle-tools · 커밋 `V2: …` | R-19~24. 위임 결정 D1 check-ignore(임시 bare git-dir)·D2 보고만·D3 `plugin.json` version 삭제·D4 보고만. 리뷰(Fable) 차단 1(`.gitignore` `build/`가 추적 fixture 무시 → 루트 앵커+테스트) 수정. 전체 1002 통과·4 실패(환경) |
| ✅ | V3 | ✅ 완료(10/07) | v/V3-docs-drift · 커밋 `V3: …` | R-25~31. 위임 결정 D1 A(`when`은 코드 값 `ask\|always\|never`, eval 0)·D2 a·D3 a(S-0 pack 75→23KB)·D4 A. 리뷰(Opus) 차단 1(GUIDE §4 설치 순서)·권고 8 반영, S-7 pack은 V 이후 후보. 관련 973 통과·4 실패(환경) |
| ☐ | V4 | **리뷰 반영 대기(WIP 커밋)** | v/V4-safety | R-2~8 구현 완료(31파일), 전체 1021 통과·4 실패(환경). 리뷰(Fable) 권고: 1 R-3 `sudo -Eu`·`env -C/x` 묶음 옵션, 2 R-6 PII_PROBES 추가(무하이픈 MSISDN·+82·ICCID), 3 R-7 `search.md`·`sync-pr.md` `S/` 정의 — `docs/development/v-handoff/v4-review.md`. 남은 일: 권고 1~3 반영(실행 Opus) → eval 1·28·30·43(Sonnet) → 완료 승인 → PR. 병합 전 v-handoff/ 삭제 |
| ☐ | V5 | 계획·결정 완료 | | `v-handoff/v5-plan.md`·`v5-decisions.md`(D11: golden 바뀌면 멈추고 사용자 승인). V4 커밋 뒤 실행(Sonnet) |
| ☐ | V6 | 대기 | | R-15~18, 독립 |
| ☐ | V7 | 대기 | | R-32~35, V3·V5·V6 뒤 |
| ☐ | V 끝 | 대기 | | 전체 테스트·eval(결정 (i) 최소)·색인 → Z |

상태 값은 W와 같다(`IMPROVEMENT_PLAN_2026-10.md §7` 끝).
