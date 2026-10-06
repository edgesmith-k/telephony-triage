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
| RF-9 정리·문서 | 열림: E 후보 삭제(사용자 승인), `PLUGIN_IMPROVEMENT_HANDOFF.md` 경로 삭제(사용자 승인), `docs/ARCHITECTURE.md` 확정. README·plugin.json 점검·새 세션 리허설은 W11·W12에서 함 |

## 남은 R 항목 (인계 문서 R1~R15 중 열린 것만)

- **R12** context 중복: command와 reference의 sync-pr 절차 등 단일 원본화 (일부는 RF-1에서 해결, 잔여 점검)
- **R13** 실제 plugin 통합 평가: tool trace 채점은 완료, 설치 통합 평가·실패 4건(5·22·29·44)·트리거 recall은 사내 S-2
- **R14** UX: 분석 전용·추가 로그·입력 해시 재사용 완료, 부분 재분석·가설 수정 상태는 열림
- **R15** 규모: 측정·O1 bisect·O4 find-symbol 사전 필터 완료. 색인·범위 제한은 보류 (`tools/bench_scale.py`)

R1~R11은 완료.

## 인용되는 결정

- **RF-2**: 경계 검사 규칙 a~d와 반입 절차의 근거 (위 표).
- **(b)** 자동 게시 단계(RF-8)는 `confidence`가 아니라 별도 품질 게이트(사내 held-out 검증·오탐 기준)를 통과할 때만 채택한다. `confidence`는 규칙 일치 구간일 뿐이다 (`04-parser-matching.md`).
- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐이다. `export_external.py`는 만들지 않는다.

## 본문 링크

- `docs/history/architecture-review-2026-10.md`
- `docs/history/improvement-handoff-2026-10.md` (R1~R15 표, I0~I6)
