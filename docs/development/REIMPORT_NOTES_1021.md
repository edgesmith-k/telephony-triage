# 재반입 노트 — 10/21 사내 피드백 반영분 (PR #71)

사내 피드백 10건(10/21)을 사외에서 고친 묶음을 사내 레포에 넣을 때 볼 것. 절차는 `docs/SITE_INSTALL.md §8`, 이 문서는 이번 묶음에만 해당하는 것.

## 1. 반입 전에 (멈춤 방지)

- **사내에서 직접 넣은 문구를 먼저 되돌린다.** 사내에서 `plugin/skills/telephony-triage/SKILL.md`(5-1 괄호, Step 7 `규칙 제안:` 줄)와 `docs/design/16-existing-assets.md §16.5` 계약에 문구를 넣었다면, 기준선 뒤 사내에서 고친 사외 파일이라 `import_draft.py`가 종료 1로 멈춘다. 새 묶음에 같은 내용이 오타를 고친 정식 문구로 들어 있으므로 §8 "멈췄을 때" 첫 줄대로 마지막 반입 버전으로 되돌리고 커밋한 뒤 다시 실행한다.
  - 고친 오타: `ip`→`op`, `add-parse-rule`→`add-parser-rule`, `upate`→`update`. 줄 머리표는 `[이슈 DB]`·`[스킬]`.
- 골든·conftest·`test_parse_logcat.py`·`masking.py`를 임시로 고쳐 두었어도 같다. 되돌리고 새 묶음 것을 쓴다.

## 2. 반입 뒤 바뀌는 것

| 항목 | 사내에서 할 일 |
|---|---|
| 골든 합성 줄 예외(16 §16.6 1항) | 합성 줄을 보충한 케이스만 그 골든 JSON(`tests/golden/<이름>.golden.json`) **최상위**에 `"synthetic": {"reason": "<왜 실제 로그에 없는지>"}`. 사유가 비면 `site_checks.py` `s4a.golden`이 실패한다. `test_golden.py --update`가 이 키를 남긴다 |
| 실제 site 백엔드 로드 | 사내 골든 테스트는 `real_site_backend` 픽스처를 쓴다(`parser_backends.site_real`로 따로 불러옴). 파일 경로로 직접 불러오던 임시 코드는 빼도 된다 |
| `test_site_defaults_required` | 사내 레포(`plugin/site-defaults.yaml` 있음)에서 자동 skip. skip이 정상 |
| `cid` 마스킹 | `DataCallResponse`·`SetupDataCallResult {…}` 안의 `cid`(데이터 콜 id)는 더 이상 가리지 않는다. 그 밖의 `cid=`는 그대로 가린다. 마스킹 결과·픽스처에 그런 줄이 있으면 출력이 달라질 수 있다 |
| contracts 주석 | `token` 등 자격증명처럼 보이는 필드 이름에 대한 메모. 동작 변화 없음 |
| 운영 이슈 DB 첫 push | `SITE_INSTALL.md §9`(S-4a, 도입 담당자 한 번). `config.py set issue_db.path` 뒤 옛 스냅샷 정리 안내가 출력된다(§7 "이슈 DB 경로를 바꿨을 때") |
| 분석 스킬 만들기 | `16 §16.5.1` 신설. 이슈 DB 뼈대에 `docs/analyzer-skills.md`가 추가돼 **뼈대 zip 해시가 바뀐다**. 이미 만든 운영 이슈 DB에는 이 파일을 복사해 넣는다(이슈 DB 변경이므로 PR로) |
| 리포트 안내 | `심층 분석: 해당 없음(…)` 줄 끝에 `(만드는 법: 이슈 DB docs/analyzer-skills.md)` |
| 규칙 제안 → Step 7 | 분석 스킬의 `규칙 제안:` 줄을 분류 확정 뒤 한 번 묻는다. `[이슈 DB]` 줄은 op 초안 → 승인분만 계획에 넣어 `db_verify`까지, `[스킬]` 줄은 담당자 메모로만. 분석 스킬이 이 형식(16 §16.5)으로 쓰는지 확인 |

## 3. 테스트·eval

- `python3 -m pytest -q tests`. `tests/test_show_guard.py::test_hook_replay_counts_without_content`는 사외에서도 환경에 따라 실패한다(기대 2, 실제 1). 이것만 실패하면 병합해도 되고, 실패 줄은 사외로 전달한다.
- **SKILL.md(공통 규칙)가 바뀌었다** → §8 기준으로는 사내 대상 eval 11개(`pending.json` `site`)를 모두 다시 돌릴 대상이다. **이번에는 추후로 미룬다(10/21 사용자: 토큰 여유 없음).** 돌릴 때 이 반입분이 직접 닿는 것은 Step 5-1·7 흐름이다. hook은 바뀌지 않았다.
- 사외 eval도 이번 변경분은 아직 다시 돌리지 않았다(40·41만 영향, 중간에 멈춤).

## 4. 남은 P2 (반입 뒤 후보)

- 닫는 `}`가 없는 `DataCallResponse` 뒤의 `cid=`가 가려지지 않을 수 있다(객체 첫 `cid`까지만 제외하도록 줄였지만 완전하지 않음).
- 첫 push 예외를 `12-principles.md`·`08-safety.md`에서 `SITE_INSTALL §9`로 상호 참조.
