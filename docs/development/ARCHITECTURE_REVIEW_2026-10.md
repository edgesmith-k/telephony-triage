# 아키텍처 리뷰 2026-10 — 남은 항목

본문(분석 §A~X, RF 상세)은 `docs/history/architecture-review-2026-10.md`(읽지 않는다. 필요한 RF 절만 `grep -n "^### RF-"`로 찾는다). 이 파일은 남은 일과 인용되는 앵커만 둔다.

## RF 색인 (RF-n = 리팩터링 단계, 개발 Phase D0~14와 별개)

| RF | 상태 |
|---|---|
| RF-0 기준선·쓰기 안전 | 완료 |
| RF-1 토큰·컨텍스트 | 완료 (행동 평가 후속은 사내 S-2). 파생 이벤트 `msg` 복사 제거는 보류(W11, 스냅샷 재생성 사용자 승인) |
| RF-2 사외/사내 경계 | 완료 (2026-10-03). `tools/check_boundary.py`, `import_draft.py` staging·rollback, `plugin/schemas/`, `.github/workflows/external.yml`. pre-commit 연결은 선택, 안 함 |
| RF-3 코어/플랫폼 분리 | 완료 (android 백엔드 이동). 남은 것은 RF-4로 |
| RF-4 Android 버전 어댑터 | 일부 (`platform:` 키·`platforms.load()`). 남음: 이슈 DB 층(`phone_id_patterns`·`ril.yaml tags`), `migrate_code_refs`, `--index` |
| RF-5 oFono 등 다중 플랫폼 | 사내 환경을 안 뒤(반입 뒤) |
| RF-6 커넥터 | 사내 환경을 안 뒤(반입 뒤) |
| RF-7 워크플로 엔진 | 분석 전용·`--more-logs`·입력 해시 재사용 완료 (X1~X4) |
| RF-8 자동화 | 사내 환경을 안 뒤(반입 뒤). 아래 결정 (b) |
| RF-9 정리·문서 | 열림: E 후보 삭제(사용자 승인), `docs/ARCHITECTURE.md` 확정. README·plugin.json 점검·새 세션 리허설은 W11·W12에서 함 |

## 남은 R 항목 (인계 문서 R1~R15 중 열린 것만)

- **R12** context 중복: command와 reference의 sync-pr 절차 등 단일 원본화 (일부는 RF-1에서 해결, 잔여 점검)
- **R13** 실제 plugin 통합 평가: tool trace 채점은 완료, 설치 통합 평가·실패 4건(5·22·29·44)·트리거 recall은 사내 S-2
- **R14** UX: 분석 전용·추가 로그·입력 해시 재사용 완료, 부분 재분석·가설 수정 상태는 열림
- **R15** 규모: 측정·O1 bisect·O4 find-symbol 사전 필터 완료. 색인·범위 제한은 보류 (`tools/bench_scale.py`)

R1~R11은 완료.

## 반입 전 리뷰(10/07) 남은 항목

`docs/development/REVIEW_2026-10-07.md`의 R-1~R-35는 V1~V7에서 완료(`REVIEW_FIX_PLAN_2026-10.md §4`). 반입 뒤로 넘긴 것은 그 문서의 "권고(반입 뒤)"·"보류/기각" 절에 위치·제안이 있다.

| 항목 | 언제 |
|---|---|
| R-36 작업 상태 JSON 원자 쓰기·손상 처리 | 반입 뒤 |
| R-37 `db_build --verify` 지워진 카테고리 README | 반입 뒤 |
| R-38 중복 로직 통합(git 래퍼·`UsageError`·`SITE_PATHS` 로더·`_db`) | 사내 첫 안정 뒤 |
| R-39 파서 후속(RIL pid 교대, `cut`·`coverage` 백엔드 우회 등) | S-4a·S10 뒤 |
| R-40 성능(결합 O(N×M), parse 출력 크기, find-symbol walk, DB YAML 로드 0.69~1.09s·`source_hash` 전체 읽기 — V7 측정) | 사내 로그·DB 크기로 재측정 뒤 |
| R-41 offline_eval 지표 정의 | S-5 |
| R-42 사용자 clone 변경 Bash 경로 + guard `git -c alias.x=push`·표 밖 래퍼(`eval`·`su -c` 등) | 사내 사용 패턴 본 뒤 |
| R-43 setup read_tools 축소 | S-3 |
| R-44 analyze 질문 수 | 사내 파일럿 뒤 |
| R-45 문서 구조(write-flow §4 → contracts, `triage.py` 표 셀) | 급하지 않음 |
| R-46 drift 검사 확장·`analysis.schema.json` 닫기 | 사내 문서 변경 시작 뒤 |
| R-47 테스트 속도(`Workspace()` 템플릿) | 사내 CI 기준 뒤 |
| V 후속: S-7 pack 40.8KB 축소, `import_draft` zip 직접 입력, `triage.py run` mode가 `--dry-run`에도 `write`, eval 45 "extract-bugreport" 단언 문구, 다중 파일 연도는 경고만(D2), `default_buffer`·unparsed 50% 설정화(S21·S7) | 반입 뒤 |
| 버전·빌드별 로그 형식(10/07 위임 결정): 형식 너그럽게(선택 필드·섹션 헤더 패턴 목록)는 S-0에서 실제 차이(`s0_stats`·`S0_PROBE_CHECKLIST`)를 본 뒤. 빌드별 로그 프로필(`platform.log` 조건 목록, 선택 키는 bugreport `build.json` fingerprint)은 `platform:` 한 벌이 안 맞을 때만(RF-4 잔여). Jira 버전 불일치 원인의 **순위 내리기는 안 함**(기본 `android_versions: []`라 거의 안 발동, 새 버전의 진짜 일치를 내리는 역효과) — 표시는 반입 전에 함 | S-0 뒤 |
| 보류: A2 setup stdio MCP 직접 실행(S-2 뒤), A3 외부 파서 어댑터 층(S-4a 뒤), A7 `failedstep` 다중 형식(S22 뒤), A13 `fix_exec_bits.py`, B7 wheelhouse(사내 반입 규정) | 표시한 단계 뒤 |

## 인용되는 결정

- **RF-2**: 경계 검사 규칙 a~d와 반입 절차의 근거 (위 표).
- **(b)** 자동 게시 단계(RF-8)는 `confidence`가 아니라 별도 품질 게이트(사내 held-out 검증·오탐 기준)를 통과할 때만 채택한다. `confidence`는 규칙 일치 구간일 뿐이다 (`04-parser-matching.md`).
- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐이다. `export_external.py`는 만들지 않는다.

## 본문 링크

- `docs/history/architecture-review-2026-10.md`
- `docs/history/improvement-handoff-2026-10.md` (R1~R15 표, I0~I6)
