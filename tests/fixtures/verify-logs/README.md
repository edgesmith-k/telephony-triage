# db_verify 입력 로그 (Phase 10)

`tests/helpers/make_variant_dbs.py`가 `tests/mocks/scenarios/verify-call-*.yaml`에서 만든다(마스킹됨). 이슈 DB가 아니다.
대상은 `tests/fixtures/issue-db-verify/`의 CALL-001-01(fix-submitted, fixed_in MOCKB77_U2_20260920)이다.

| 파일 | 내용 | `db_verify fix --cause CALL-001-01` |
|---|---|---|
| `call-fixed.log` | 등록 정상, 등록 상태로 발신, 통화 ACTIVE | passed |
| `call-recurrence.log` | 등록 실패 뒤 미등록 발신, cause 17 | failed |
| `call-partial.log` | 등록 상태로 발신했지만 망 거절 cause 31 (CALL-001-02) | partial |
| `call-noscenario.log` | 등록만 있고 발신 없음 | unknown |
