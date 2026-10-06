# 사내 보완 단계별 읽을 것 (pack)

`python3 tools/context_pack.py S-n`이 `읽을 것`의 항목을 이어서 출력한다. 항목은 `경로` 또는 `경로 §절`(여러 절은 `§14.2·14.3`). `CLAUDE.md`와 `SITE_PROFILE.md`는 자동 로드(import)되므로 넣지 않는다. 할 일은 `docs/design/15-local-draft.md §15.5`.

| pack | 읽을 것 | 비고 |
|---|---|---|
| S-0 | `docs/design/04-parser-matching.md §5.8`, `docs/design/contracts.md §3.2` | 선택. 절차는 `docs/development/S0_PROBE_CHECKLIST.md`. `contracts.md §3.2`는 `parse_logcat` 행만 본다 |
| S-1 | `docs/design/12-principles.md`, `DRAFT_NOTES.md`, `REVIEW-OPEN.md`, `docs/design/14-site.md §14.2·14.3` | 이력 `docs/history/draft-notes-*.md`는 읽지 않는다. TODO(SITE)는 `python3 tools/list_site_todos.py` |
| S-2 | `DRAFT_NOTES.md`, `tests/skill_evals/README.md` | 실패한 코드 파일을 더 읽는다 |
| S-3 | `plugin/site-defaults.example.yaml`, `docs/design/02-config.md` | |
| S-4a | `docs/design/16-existing-assets.md` | 기존 자산(파서·분류·분석 스킬) 추가 |
| S-4 | `docs/design/04-parser-matching.md`, `docs/design/16-existing-assets.md §16.4` | 테스트 출력 추가 |
| S-5 | — | 실패 시 해당 `07-workflow.md` 절만 |
| S-6 | `REVIEW-OPEN.md` | |
| S-7 | `docs/design/14-site.md §14.2`, `docs/design/06-collaboration.md §6.6·6.9`, `docs/design/01-architecture.md §3` | `14-site.md §14.2`는 S2 행만 본다 |
