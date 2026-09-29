# 월간 리뷰 가이드 (카테고리 오너)

> 월 1회, 카테고리 오너가 한다 (`06-collaboration.md §6.6`).

## 1. 리포트 만들기

```
/telephony-triage:review [category]
```

- 로컬에서 리포트만 만든다. **push하지 않는다.**
- 인자가 없으면 CODEOWNERS 기준으로 사용자가 오너인 카테고리를 묻는다.

## 2. 리포트 항목과 조치

| 항목 | 기준 (`issue-db.config.yaml`) | 조치 |
|---|---|---|
| 시그니처 없는 원인 | `signatures_pending: true` | 판별 시그니처 추가 (`update-signature`, R1~R5 통과 필요) |
| fixture 없는 원인 | 양성 fixture 없음 (R1·R2가 `skipped: fixture 없음`) | 로그를 받아 fixture 추가 |
| 오래된 원인 미확정 | `unresolved`가 `quality.unresolved_max_days` 초과 | 원인 확정 또는 담당자 지정 |
| 품질 낮은 시그니처 | 수락률 < `quality.low_acceptance_rate` | 시그니처 좁히기 또는 삭제 |
| 중복 후보 | 서로 다른 유형의 증상 시그니처가 같은 fixture에 동시 매칭 | `merged-into`로 병합 |
| 오래 안 쓰인 원인 | `quality.stale_months` 동안 Jira 없음 | 유지 또는 `status: deprecated` |
| 지원 종료 버전 | `android_versions`가 비어 있지 않고 모두 지원 목록 밖 | `status: deprecated` |
| 수정 필요 누적 | `fix.status: open`이면서 Jira가 많음 | 근본 수정 우선순위 제안 |
| 수정 상태 누락 | `fix-submitted`인데 `ref`/`fixed_in` 없음, `fixed`인데 `verification`/빌드 없음 | 보완 |
| fixed 전환 불가 | 코드·설정 수정 유형인데 `scenario_signatures`·`recovery_signatures`가 모두 없음 | 시그니처 추가 |
| 빌드 없는 fix-submitted | `fixed_in`에 빌드 없음 | `fix-submitted` 커맨드로 빌드 추가 |
| 해결책 미검증 방치 | `unverified`가 `quality.unverified_max_days` 초과 | 검증 담당자 지정 |
| 사용자 진술만 있는 해결책 | `method` 또는 Jira `note`에 "근거: 사용자 진술" | 근거를 받아 `verify-resolution` 또는 유지 판단 |
| 수정 검증 대기 방치 | `fix-submitted`가 `quality.fix_submitted_max_days` 초과 | `verify-fix` 요청 |
| 수정 검증 실패·부분 통과 이력 | `verification_history`에 `failed`/`partial` | 근본 원인 재검토 |
| `also_allowed` 누적 | 한 fixture에 3개 이상, 또는 한 원인이 5개 이상의 fixture에서 허용 | 시그니처 범위·fixture 구간 재검토 |
| 급증 | 최근 30일이 이전 90일 월평균 × `quality.surge_ratio` 이상 | 원인 조사 |

## 3. 정리 PR 올리는 두 가지 방법

브랜치는 `review/<category>-<YYYY-MM>`이다.

### (a) 직접 편집

1. 자기 로컬 브랜치를 만들고 `type.md` 등을 직접 고친다
2. `db_build --write`로 생성 파일을 다시 만든다
3. `/telephony-triage:validate` 통과
4. `TT_PUBLISH_TOKEN=manual git push --force-with-lease`

머지 전에 main이 바뀌면 `CONTRIBUTING.md §5`의 재동기화 절차를 직접 한다.

### (b) 계획 파일로 올리기 (권장)

리포트의 조치를 **작업 계획**(`source: review`)으로 적어 도구 경로로 올린다. Claude Code가 계획 작성을 돕는다 (`<work_dir>/review-<category>-<YYYY-MM>/plan.json`). 별도 커맨드는 없다.

쓸 수 있는 op: `set-status`, `update-signature`, `reclassify`, `set-resolution`, `allow-cause`, `add-fixture`.

이 방법은 최신 main 위에 계획을 다시 적용하므로 텍스트 충돌이 없고, 머지 전에 main이 바뀌면 `sync-pr`로 다시 맞출 수 있다.

## 4. 병합 (유형·원인)

- **유형 병합**: 흡수되는 유형을 `status: merged-into:<유형 ID>`로 두고, 그 원인들은 흡수하는 유형의 원인으로 **새 ID를 받아** 옮긴다. 옛 원인에는 `status: merged-into:<새 원인 ID>`를 남긴다. Jira 파일은 새 유형 디렉토리로 옮기고 `cause`를 새 ID로 바꾼다.
- **원인 병합**: 옛 원인 `status: merged-into:<원인 ID>` + Jira `cause` 갱신.
- 브랜치는 `move/<옛 ID>-to-<새 ID>`, 계획 `source: move`, op 조합은 `new-cause` → `add-fixture` → `set-status` → `reclassify`다.
  1. `new-cause`: 옛 원인 내용(제목·설명·시그니처·해결책·`resolution_type`·`android_versions`·`code_refs`)을 복사하고 `temp_id`를 붙인다.
  2. `add-fixture`: `for`는 그 `temp_id`, `path`에 옛 fixture의 **이슈 DB 기준 경로**(예: `data/DATA-002-.../fixtures/DATA-002-01.log`)를 쓰면 새 원인 이름으로 복사된다.
  3. `set-status`: 옛 원인은 `merged-into:<temp_id>`, 유형 병합이면 옛 유형은 `merged-into:<유형 ID>`.
  4. `reclassify`: 옛 원인의 Jira마다 `from: <옛 원인 ID>`, `to: <temp_id>`. 파일이 새 유형 디렉토리로 옮겨진다.
     옛 유형의 원인 미확정 Jira는 `from: unresolved`, `to: <흡수하는 유형 ID>:unresolved`로 옮긴다(원인 미확정 그대로).
- **삭제하지 않는다.** 옛 fixture와 유형 파일은 남고 회귀에서 빠진다(active만 대상). `search`가 옛 ID를 새 ID로 연결해 보여준다(`merged-into:` 체인, 사후 정리 커밋의 `Renumbered:` 트레일러).
