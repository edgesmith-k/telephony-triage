## push 전 확인: MOCK-7005 → DATA-001-04 SIM 미준비
구분: 수동 기록 (record)
브랜치: issue/MOCK-7005 (갱신) → PR 대상: main
리뷰어: 없음
열린 PR: 확인 못 함

### 변경 파일

| 구분 | 파일 | 변경 |
|---|---|---|
| 유형 | data/DATA-001-x/type.md | 수정 |
| 기타 | odd\|name.md | 신규 |

### ID 할당

- NEW-CAUSE-1 → DATA-001-04: 계획 당시 DATA-001-03 → DATA-001-04 (main에 먼저 머지된 원인)
- NEW-CAUSE-2 → DATA-001-05
- fixture: fixtures/DATA-001-04.log (positive, DATA-001-04)

### 수정 상태 변경

- CALL-001-01: fixed → open (이전 ref MOCKCL-12345·fixed_in MOCKB77_U2_20260920 → verification_history 보존, 결과 reverted)

### drift 결정 내역

- drift: DATA-001-02 resolution — 계획 값 유지 (계획 값: 켠다, main 값: 끈다)

### 추가 설명

- 로그·코드 분석: 하지 않음 (수동 기록)
- DATA-001-04: 시그니처 없음 — 매칭 불가, 리뷰 대상
- R5: 검증 못 함 — 리뷰 대상 (코드 없음)

### README 반영 미리보기

```
| 2026-09-29 | MOCK-7001 | DATA-001-02 |
```

### 주요 diff

````diff
+line 0
+line 1
+line 2
+line 3
+line 4
+line 5
+line 6
+line 7
+line 8
+line 9
+line 10
+line 11
+line 12
+line 13
+line 14
+line 15
+line 16
+line 17
+line 18
+line 19
+line 20
+line 21
+line 22
+line 23
+line 24
+line 25
+line 26
+line 27
+line 28
+line 29
+line 30
+line 31
+line 32
+line 33
+line 34
+line 35
+line 36
+line 37
+line 38
+line 39
+line 40
+line 41
+line 42
+line 43
+line 44
+line 45
+line 46
+line 47
+```
+끝
````
전체 80줄 중 50줄 — '전체 diff 보기'를 고르면 전체를 본다.

### 자동 검사 결과

- 스키마·lint ❌ (오류 2건, 경고 1건)
  - lint 오류: E-TITLE: a.md
  - lint 오류: E-ID: b.md
- ID·Jira 중복 ❌
  - 중복: DATA-001-04
- 마스킹 ❌
  - 마스킹 검출 3건
- fixture 회귀 ❌ (19/21)
  - 회귀 실패 fixture: f1.log
  - 회귀 실패 fixture: f2.log
- 생성 파일 ❌

### 검증 결과

| 규칙 | 결과 | 사유 |
|---|---|---|
| R1 | ✅ 통과 | 추출 확인 |
| R2 | ❌ 실패 | DATA-001-03: C=0 \| 양성 fixture |
| R3 | 건너뜀: 해당 없음 |  |
| R4 | 승인 필요 | 기존 이벤트 변경 |
| R5 | 검증 못 함 — 리뷰 대상 (코드 없음) |  |
| R6 | other | 알 수 없음 |

승인 필요: R4 — 메인테이너 승인 필수
해결책 검증 상태: DATA-001-04 — unverified(신규 원인 (new-cause))

### 커밋 메시지 / PR 제목

````
[DATA-001-04] record MOCK-7005: SIM 미준비

```
본문 펜스
```
````
PR 제목: [DATA-001-04] record MOCK-7005: SIM 미준비
push 불가: gh 인증 없음 (--dry-run)

approved_hash: 0123456789abcdef0123456789abcdef01234567
