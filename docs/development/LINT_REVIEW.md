# 린트 검토 표 (ruff 0.17.4)

`python3 tools/lint.py`(규칙 묶음 `pyproject.toml [tool.ruff]`)가 0건이 되도록 고치지 않고 남긴 지적의 곳마다 사유다. 끈 규칙의 사유는
pyproject 주석에 한 줄씩 있다. 자동 수정은 `ruff check --fix --diff`(unsafe 제외)로 diff를 보고 hunk마다 검토해 적용한다 —
`tools/lint.py`는 `--fix`를 받지 않는다. 줄 번호는 이 표를 쓴 커밋 기준이다(바뀌면 `ruff check --select <규칙> --ignore ""`로 다시 찾는다).

분류: (가) 같은 반복 안에서 바로 부르는 클로저 — 오탐, `# noqa: B023 — 사유` / (나) 반복 밖까지 남는 클로저 — 기본 인자로 값을 묶음(동작 같음).

## 표 1. B023 (반복 변수를 묶지 않은 클로저) 18건

| 곳 | 변수 | 분류 | 처리 |
|---|---|---|---|
| `plugin/scripts/db_verify.py:508·509·509·510` (4) | `category`·`cid` | (가) `run.fixtures(pred)`는 리스트 내포로 그 자리에서 거른다 | noqa |
| `plugin/scripts/dbadd/drift.py:155·155·156·156` (4) | `op`·`section`·`key` | (가) `find`를 바로 아래 줄(`find(base), find(onto)`)에서만 부른다 | noqa(155는 E731과 함께) |
| `tests/helpers/skill_eval_env.py:360` | `holder` | (가) `Workspace.push_main(edit)`이 `edit(other)`를 바로 부른다 | noqa |
| `tests/skill_evals/grade.py:2973` | `env` | (가) `re.sub`가 바로 부른다 | noqa |
| `tests/test_jira_fields.py:183` | `body` | (가) `re.sub`가 바로 부른다 | noqa |
| `tests/test_site_checks.py:588` | `code` | (나) `monkeypatch.setattr(sc.Ctx, "run", …)`로 클래스에 남는다(지금은 같은 반복에서 불려 값이 맞다) | `*, _code=code` 키워드 전용 기본 인자로 묶음(위치 인자 3개면 TypeError인 것도 같다) |
| `tools/bench_scale.py:271` | `argv` | (가) `_timed(fn)`이 바로 부른다 | noqa |
| `tools/module_measure.py:296` | `ess` | (가) 안쪽 `rec`는 같은 반복의 299~314줄에서만 부른다 | noqa |
| `tools/s0_suggest.py:128` | `it` | (가) 다음 줄 `any(hit(t) …)`가 바로 다 쓴다 | noqa |
| `tools/s0_suggest.py:159·159·160` (3) | `k`·`w` | (가) 사전에서 하나를 골라 `[p]()`로 바로 부른다 | noqa |

## 표 2. PLW1510 (`subprocess.run`에 `check=` 없음) 126건 — 고치지 않음

`check=True`로 바꾸면 실패가 `CalledProcessError`가 되어 지금의 종료 코드·메시지·degraded 처리가 바뀐다. 아래 사유로 그대로 둔다.
사유: **R1** `returncode`를 바로 보고 실패면 예외·None·경고·실패 행으로 바꾼다 / **R2** `CompletedProcess`를 돌려주는 래퍼 — 부르는 쪽이
`returncode`를 본다 / **R3** 실패 허용(최선 노력) — 실패면 빈 값으로 이어 가고 통과로 보이지 않는다 / **R4** 시험: 종료 코드를 assert로
보거나 실패(hook 거부 등)를 일부러 본다.

| 파일 (줄) | 사유 |
|---|---|
| `plugin/scripts/common/buildname.py` (32) · `dbpath.py` (23) · `history.py` (31) · `jobstatus.py` (114) · `gitscope.py` (32, 150) · `checks.py` (132) · `modulefilter.py` (773) | R1 |
| `plugin/scripts/common/ghcli.py` (26) | R2 (시간 초과·OSError도 CompletedProcess로 바꾼다) |
| `plugin/scripts/common/mcptools.py` (150) | R3 Windows `taskkill` 정리 — 실패해도 `proc.kill()`로 이어 간다 |
| `plugin/scripts/config.py` (577, 601, 784) · `db_migrate.py` (203) · `mask_pii.py` (58, 71) · `parse_logcat.py` (319) · `job_status.py` (189) · `skill_patch.py` (240) · `dbpr/worktree.py` (25, `check` 인자) | R1 |
| `plugin/scripts/db_verify.py` (110) · `skill_patch.py` (372) | R2 |
| `plugin/scripts/guard.py` (428) | R2 `_git` — 부르는 쪽이 `returncode`를 보거나 빈 출력을 "없음"으로 읽는다(git이 실패하는 곳이면 그 git 명령도 실패하고, 규칙 3·4는 pre-commit hook이 다시 본다. migrate 브랜치 예외는 빈 출력이어도 ask) |
| `plugin/scripts/db_precommit.py` (73) | R3 브랜치 이름을 못 읽으면 빈 문자열 → migrate 예외 없음(더 엄격한 쪽) |
| `plugin/scripts/job_status.py` (161) | R3 `claude --version` 표시용 — 못 읽으면 "확인 불가" |
| `tools/make_bundle.py` (101, 115, 145, 430, 453, 506, 532) · `import_draft.py` (121) · `make_module_repo.py` (46) · `module_measure.py` (62) · `related_tests.py` (116, 416, 422) · `s0_stats.py` (38) · `bench_scale.py` (295) · `site_checks.py` (598) · `site_step.py` (953) | R1 |
| `tools/offline_eval.py` (100) | R2 |
| `tools/hook_probes.py` (113) | R3 출력(결정)이 결과다 — guard가 죽으면 결정이 None으로 표에 드러나고 종료 1 |
| `tools/site_checks.py` (2025) · `site_step.py` (115) | R3 `ls-tree`·`git` 실패면 빈 집합·빈 문자열 → 파일 없음·모름으로 보고 |
| `tests/helpers/runner.py` (233) · `workspace.py` (40, 235) · `tests/skill_evals/run.py` (437) · `grade.py` (170, 1804, 3291) · `trigger_real.py` (47, 실패면 오류(미실행) — 음성으로 세지 않는다) | R1 |
| `tests/helpers/runner.py` (151) | R2 (시험이 `returncode`를 본다) |
| `tests/skill_evals/grade.py` (3274) | R3 `numstat` — 실패면 빈 목록 → 같은 검사의 `adds`가 비어 실패 |
| 시험 래퍼·호출 (R4): `test_hooks.py` (49, 170) · `test_mocks.py` (51, 136, 166, 195, 224, 272, 281, 287, 291, 505, 516, 668) · `test_masking.py` (58) · `test_match_signatures.py` (49, 493) · `test_parse_logcat.py` (80) · `test_platform_guard.py` (115) · `test_platform_profile.py` (56) · `test_provenance_db.py` (45) · `test_site_checks.py` (41, 155) · `test_site_step.py` (29) · `test_skill_patch.py` (72, 237) · `test_import_draft.py` (45, 245) · `test_fixture_residual.py` (23) · `test_commands.py` (409) · `test_db_summary.py` (258, 609) · `test_boundary.py` (45, 72) · `test_code_roots.py` (166) · `test_context_pack.py` (42) · `test_db_build.py` (83) · `test_db_review.py` (48, 203) · `test_job_status.py` (355) · `test_make_bundle.py` (512) · `test_mask_parity.py` (41) · `test_module_coverage.py` (93) · `test_modulefilter.py` (391, 401) · `test_ofono_skeleton.py` (387, 396, 403) · `test_platforms.py` (203) · `test_reference_cli.py` (164) · `test_related_tests.py` (14, 110) · `test_s0_stats.py` (20, 58) · `test_s0_suggest.py` (59, 133) · `test_safety.py` (188, 210) · `test_show_guard.py` (746) · `test_skill_evals.py` (1001, 3788) · `test_team_stats.py` (43, 58, 66) · `test_trackers.py` (898, 910) · `test_triage.py` (803) · `test_triage_reuse.py` (300) · `test_usage_stats.py` (411, 536) | R4 |

`tools/lint.py`의 ruff 호출은 `check=False`를 밝혀 이 표에 넣지 않는다(종료 코드를 그대로 돌려준다).

## 표 3. BLE001 (`except Exception`) 14건 — 고치지 않음

| 곳 | 사유 |
|---|---|
| `plugin/scripts/common/provenance.py:43` `env_info` | 기록용 런타임 정보 — 못 읽으면 `unknown`(분석·판정에 쓰지 않는다) |
| `plugin/scripts/common/skillpath.py:123` `resolve` | degraded: 설치 스킬을 못 찾은 것으로(`path: None`·사유) — 분석 스킬 없이 이어 간다 |
| `plugin/scripts/common/userconfig.py:658` `redact_remote` | 표시용 가림 — 실패하면 값 대신 `<원격>`(원격 URL·자격증명을 내보내지 않는 쪽) |
| `plugin/scripts/common/userconfig.py:726` `_merged_each` | 합치기가 실패한 플랫폼 프로필은 건너뛴다(docstring 계약). 검토 메모: 그 프로필의 문제는 이 목록에 안 나온다 |
| `plugin/scripts/common/userconfig.py:763·803·824·922` `module_skills_problems`·`analyzer_problems`·`implicit_module_switches`·`read_roots` | 계약 "예외 없음"의 문구·목록 수집기 — 손상된 값에서 모은 데까지 돌려준다. 검토 메모: 문제 목록이 덜 나올 수 있다 |
| `plugin/scripts/common/userconfig.py:861` `deep_source_problem` | 계약 "예외 없음" — 사유를 못 만들면 None, 부르는 쪽(driver)은 "설정 오류"로 막는다 |
| `plugin/scripts/db_pr.py:289` | stage는 이미 성공 — summary 실패를 `summary_error`와 다시 부를 명령으로 알린다 |
| `plugin/scripts/db_pr.py:312` | PR은 이미 만들어짐 — discard 실패를 종료 2와 다음 할 일로 알린다(publish를 다시 하지 않게) |
| `plugin/scripts/usage_stats.py:547` | 손상된 config는 환경 오류(종료 2) |
| `tools/make_bundle.py:584` | 검사 코드 자체의 오류를 `error`로 — 통과로 보지 않는다 |
| `tools/make_bundle.py:685` | 예기치 못한 오류를 트레이스백 대신 종료 2 |

## 표 4. 파일 단위 예외 (`per-file-ignores`)

한 곳만 걸려 확인한 것. 파일 단위로 끈 규칙은 그 파일의 같은 규칙 새 지적이 보이지 않으므로 그 파일을 바꿀 때 다시 본다.
정확성 규칙 F821·F811은 파일이 아니라 그 줄의 `# noqa`로 좁혀 새 지적이 가려지지 않는다.

| 파일 | 규칙 | 확인 |
|---|---|---|
| `tools/bench_scale.py:174` (줄 noqa) | F821 | `del events` 앞 줄에서 `_timed(lambda: … events …)`가 바로 부른다 |
| `tools/bench_scale.py` | SIM115 | 파일 핸들 여러 개를 `try/finally`에서 닫는다 |
| `plugin/scripts/common/masking.py:414` (줄 noqa) | F811 | 타입 별칭 `Masker = Callable[...]`를 같은 이름의 클래스가 대신한다(`from __future__ import annotations`라 주석은 글) |
| `plugin/scripts/common/stepanchor.py` | PLR0124 | `out != out`은 NaN 검사 |
| `tests/test_platform_profile.py` | B005 | `str.strip`이 아닌 `PhoneRules.strip` |
| `tests/test_partial_match.py` · `tests/test_safety.py` · `tools/site_audit.py` | F841 | 쓰지 않는 계산값(`worst`)·적재만 하는 `import_module`(`parse`)·쓰지 않는 목록(`now`) — 부작용 없음 |
