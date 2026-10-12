#!/usr/bin/env python3
"""job_status.py — 작업 상태 한 화면 (읽기 전용, 로컬 기록만, contracts.md §3.2).

    job_status.py [<KEY>] [--format json|markdown] [--platform <이름>] [--plugin-root <dir>] [--json]

`<work_dir>/<KEY>/`의 기록(plan.json·state.json·stage.json·pr.json·analysis.json·triage-state.json·post*)과
`session.lock`, `<work_dir>/snapshot.json`, `wt/` 안의 git 읽기로 "어디까지 했는지"를 한 화면으로 낸다.
단계(`none`·`started`·`needs-input`·`needs-input-past`·`analyzed`·`plan-saved`·`staged`·`summary-shown`·`committed`·
`pushed-no-pr`·`pr-created`, 손상·형식 이상 파일이면 `unknown`; sync-pr 재적용은 "재동기화 중", wt git을 못 읽으면 "확인 불가(git 읽기 실패)")·막힌 것·다음 할 일·관련 파일. 줄마다 확신도(`now`·`recorded`·`unknown`).
원격(PR 상태·원격 브랜치)은 보지 않는다(`원격 최신성: 확인하지 않음`). 사용자 승인 여부는 기록이 없어 늘 `unknown`이다.

읽기 전용: mkdir·파일 쓰기·fetch·gh·lock 획득·갱신·git 쓰기(write-tree·승인 해시 재계산·worktree prune) 없음.
손상 lock·JSON은 고치지 않고 막힌 것·경고로 보인다. 읽지 않는 것: `issue_raw.json`, `steps-pasted.txt` 내용,
로그, `events.json`, `trace.jsonl` 내용(크기만), needs_input 질문 문구(상태 파일에는 `pending {kind, asked_at}`만 있다).

`<KEY>`를 생략하면 lock을 잡은 작업, 없으면 작업 디렉토리가 하나일 때 그 작업. 여럿이면 최근 순 후보(최대 5개,
`{candidates: [{key, stage, at}]}`)를 내고 종료 코드 0.

출력: 기본 `--format json`(한 줄) `{key, platform, target, stage{id, label, confidence, at?, evidence?}, blockers[{code,
label, confidence, at?, evidence?, next?}], must_show[], next, approval{approved_hash_prefix, staged_at, user_approval}, post, lock{held,
mine, job, command, age_sec, expired, same_session}, files, warnings[], last_question?{kind, asked_at, live}}`(`last_question`은
단계가 질문 단계가 아닌데 `pending`이 있을 때). 지금 기다리는 질문이 단계를 앞서도 `state.json`이 있으면 stage·pr.json 막힌 것을 본다.
`--format markdown`은 대상 → 단계 → 막힌 것 → 다음 할 일 → 관련 파일(≤3KB 보장: 넘으면 뒤쪽 줄을 빼고
`- … 생략 N줄(근거·경고·파일 등, JSON 출력)`, 그래도 넘으면 줄마다 자르고 뒤에서부터 줄을 뺀다, `--json`과 함께 못 쓴다).

종료 코드: 0 = 화면을 냈다(막힌 것이 있어도), 2 = 사용·환경 오류(site-defaults·사용자 config 없음, 키 형식 불일치,
플랫폼 불일치(분석·작업이 다른 플랫폼), work_dir 없음, 인자 오류).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import compat, jobstatus, session_lock, site_defaults, userconfig, yamlio  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402
import platforms  # noqa: E402
from platforms import session as platform_session  # noqa: E402
import trackers  # noqa: E402


class Usage(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job_status.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("key", metavar="KEY", nargs="?", default=None, help="작업 키(생략하면 lock 작업·단일 작업·후보)")
    parser.add_argument("--format", choices=("json", "markdown"), default="json",
                        help="markdown: 대상·단계·막힌 것·다음 할 일·관련 파일 (기본 json, --json과 함께 못 쓴다)")
    platform_session.add_arg(parser)
    parser.add_argument("--plugin-root", default=None)
    parser.add_argument("--json", action="store_true", help="JSON 출력 (기본)")
    return parser


def _key(tracker, cfg_snap: Path, raw: str) -> str:
    """키 형식 검사(트래커 `parse_key`·경로 안전 형식·스냅샷 `tracker.key_regex`). 로컬 검사만."""
    db_cfg = compat.load_db_config(cfg_snap) if (cfg_snap / "issue-db.config.yaml").is_file() else {}
    block = db_cfg.get("tracker") if isinstance(db_cfg.get("tracker"), dict) else {}
    key_re = re.compile(str(block.get("key_regex") or tracker.default_key_regex))
    key = tracker.parse_key(raw) or raw
    if not tracker.safe_key_re.fullmatch(key) or not key_re.fullmatch(key):
        raise Usage(f"{tracker.label} 키 형식이 아니다: {key} — 키를 확인한 뒤 다시 실행한다")
    return key


def run(args, defaults: dict) -> dict:
    if userconfig.load_user() is None:
        raise Usage("사용자 config가 없다 — /telephony-triage:setup 을 먼저 한다")
    try:
        name, cfg = platform_session.resolve(defaults, args.platform)
        tracker = trackers.of(cfg)
    except (platforms.PlatformConfigError, trackers.TrackerConfigError) as exc:
        raise Usage(str(exc)) from exc
    work = Path(str(userconfig.get(cfg, "work_dir") or "")).expanduser()
    if not str(userconfig.get(cfg, "work_dir") or "") or not work.is_dir():
        raise Usage(f"work_dir가 없다: {work} — /telephony-triage:setup 으로 설정을 확인한다")
    if args.key is None:
        key = None
        try:
            held = session_lock.read(work)
        except session_lock.LockError:
            held = None
        job = (held or {}).get("job")
        if job and not job.startswith(("_", ".")) and tracker.safe_key_re.fullmatch(job) and (work / job).is_dir():
            key = job
        else:
            found = jobstatus.candidates(work, tracker.safe_key_re)
            if len(found) != 1:
                return {"platform": name, "work_dir": str(work), "candidates": found[:jobstatus.CANDIDATES_MAX],
                        "more": max(0, len(found) - jobstatus.CANDIDATES_MAX)}
            key = found[0]["key"]
    else:
        key = _key(tracker, work / session_lock.SNAPSHOT_DIR, args.key)
    try:
        return jobstatus.collect(work, key, cfg, defaults, platform=name, tracker=tracker.name)
    except jobstatus.StatusUsage as exc:
        raise Usage(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(Path(args.plugin_root) if args.plugin_root else None)
    try:
        if args.format == "markdown" and args.json:
            raise Usage("--format markdown은 --json과 함께 쓸 수 없다.")
        doc = run(args, defaults)
    except (Usage, yamlio.YamlFileError) as exc:
        print(f"job_status.py: {exc}", file=sys.stderr)
        return USAGE
    if args.format == "markdown":
        print(jobstatus.markdown(doc), end="")
    else:
        print(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
