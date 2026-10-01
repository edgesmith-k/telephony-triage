# Repository Guidelines

## Project Structure & Module Organization

This repository develops the telephony-triage Claude plugin; the operational issue database is a separate repository.
- `plugin/scripts/`: Python CLIs, shared utilities in `common/`, parser backends, adapters, and migrations.
- `plugin/commands/`, `plugin/hooks/`, and `plugin/skills/`: plugin commands, safety hooks, and triage instructions.
- `docs/design/`: architecture and workflow specifications. `contracts.md` is the authoritative source for shared contracts.
- `tests/`: pytest modules, synthetic issue databases and logs in `fixtures/`, mocks, helpers, and skill evaluations.
- `tools/`: database scaffolding, draft import, site checks, and offline evaluation utilities.

## Build, Test, and Development Commands

Run from the repository root, preferably on Ubuntu as specified by the architecture. Python tests require pytest, PyYAML, and jsonschema (`pip install pyyaml jsonschema pytest`; no lock file yet); use `python3` below or your environment's equivalent.
- `python3 -m pytest -q tests`: run the automated suite.
- `python3 -m pytest -q tests/test_parse_logcat.py`: run focused parser tests.
- `python3 plugin/scripts/db_lint.py --db <db-path> --all`: validate an issue database.
- `python3 plugin/scripts/db_build.py --db <db-path> --verify`: check generated database files without rewriting them.
- `python3 tools/offline_eval.py <labelset.yaml> --db <db-path>`: measure parser/matcher accuracy offline.

There is no conventional application build step. Consult each CLI's `--help` before using commands that write files.

## Coding Style & Naming Conventions

Match existing Python style: four-space indentation, type annotations, `snake_case` functions/modules, and `UPPER_CASE` constants. Keep CLI parsing and exit codes consistent with `docs/design/contracts.md`. Use UTF-8 and LF endings. No repository-wide formatter configuration is present; follow neighboring code. Generate database indexes through `db_build.py` rather than editing them manually.

## Testing Guidelines

Name modules `tests/test_<component>.py` and functions `test_<behavior>`. Add behavioral coverage for parser, masking, schema, and workflow changes. Use synthetic or masked fixtures only. Review snapshot diffs before accepting updates. No numeric coverage threshold is configured. For skill changes, follow `tests/skill_evals/README.md`; keep evaluation workspaces uncommitted.

## Commit & Pull Request Guidelines

History uses descriptive, often Korean, phase-based subjects such as `Phase 12: ...`; follow that pattern for phase work. Keep commits scoped. PRs should explain behavior changes, reference relevant design sections or issues, and report validation results and skipped checks. Include fixture or generated-output diffs when relevant. Update `docs/history/CHANGES.md` for substantive changes.

## Security & Configuration

Read `CLAUDE.md` (mode header, §11.0, §12) for development mode and phase guidance, then the state file: `DRAFT_NOTES.md` in the external draft repo ("active tracks" table says what to do next) or `SITE_PROFILE.md` in the in-house repo. Do not read `docs/history/`. Claude-only features (plugin loading, hooks, skill-creator, `/telephony-triage:*` commands) are unavailable to other agents; limit work to scripts, tests, and docs. Resuming on another PC: `GUIDE.md` §4-1. Keep site-specific values in `SITE_PROFILE.md` and local configuration; use `plugin/site-defaults.example.yaml` as the template. Never commit raw log identifiers, credentials, or internal site data. Preserve Jira read-only access and obtain explicit approval before publishing changes.
