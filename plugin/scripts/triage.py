#!/usr/bin/env python3
"""triage.py — analyze Step 0~4 + Step 5 resolve 드라이버 (contracts.md §3.2, 07-workflow.md §analyze).

    triage.py run <KEY> [--logs <logcat|bugreport>...] [--jira-raw <json> | --jira-file <yaml>]
                  [--code <프로필|경로|키=경로,…|skip>] [--dry-run | --analysis-only] [--answer <kind>=<값>...]
                  [--tz <IANA>] [--year <YYYY>] [--minutes 5] [--refresh]
                  [--failed-step <한 줄>] [--steps-file <파일>] [--clock-offset <±시간>]
    triage.py run <KEY> --more-logs <logcat|bugreport>... [위 옵션]      # --logs와 함께 못 쓴다(종료 코드 2)
    triage.py run <KEY> --offline-db <path> --out <dir> --logs <logcat...> (--jira-meta <json> | --jira-file <yaml>)
    triage.py release <KEY>

결정적인 순서(키 검사 → lock → cleanup 후보 → 기존 계획 → 스냅샷·사후 lint·캐시 → 호환성 → Jira 추출 →
열린 PR → 코드 경로 → bugreport·파싱 → 매칭 → 후보별 DB 정보·code_refs resolve)를 기존 스크립트의 `main()`을
**같은 프로세스에서** 불러 수행한다. 스크립트의 계약(인자·출력·종료 코드)은 그대로이고, 이 파일은 순서와 요약만 맡는다.

출력 (`JOB` = `<work_dir>/<KEY>`, `--offline-db`면 `--out`)
- `JOB/analysis.json` (≤ 4KB): LLM이 읽는 유일한 분석 결과. stdout에도 같은 내용을 낸다.
- `JOB/report.md`: Step 6 리포트 초안(결정적인 칸은 채우고, 원인 설명·코드 위치는 `TODO(LLM)`로 둔다).
- `JOB/trace.jsonl`: 호출마다 `{ts, step, script, args, exit, ms, out_bytes, stderr}` 한 줄.
- `JOB/explore-input.json`: 후보 없음·원인 미확인(1위 C=0)이고 `explore.when`이 `never`가 아닐 때만. 탐색 분석 입력(마스킹된 값만:
  발생 시각·실패 스텝·앵커 머리·줄 수 상한 `explore.timeline_max_lines`). `run`은 타임라인을 만들지 않고 이전 `timeline.md`·입력 파일을 지운다.
- `triage.py explore <KEY> [--out <dir>]`: 사용자가 탐색 분석에 동의한 뒤(또는 `--explore`·`explore.when: always`) `JOB/explore-input.json`과
  `events.json`으로 `JOB/timeline.md`(마스킹된 요약 타임라인, 줄 수 상한 기본 200)를 만들고 `report.md`의 탐색 분석 줄을 갱신한다.
  출력 `{timeline, lines, total}`. 종료 코드 1 = 해당 없음(입력 파일 없음), 2 = 사용 오류·`events.json` 없음. lock·trace는 쓰지 않는다.
- `analysis.json`의 `must_show`(있을 때만, ≤4줄·줄당 ≤160자): 리포트 줄 중 사용자에게 꼭 보여야 하는 것(분석 전용·읽기 전용·1위 변화 재분석·실패 스텝·
  장비 시각 미사용·로그 범위 이상·범위 밖 오류·파서 규칙에 없는 태그). `report.md`의 줄과 같은 문구다.
- `JOB/analysis-cache.json`: 입력 해시(`request_hash`, 부분별 `parts`)가 같으면 파싱·매칭을 다시 하지 않고 이 core를 다시 보여 준다
  (RF-7, `07-workflow.md §입력 재사용`). `--offline-db`·`--refresh`·`needs_input`/오류 실행은 쓰지도 읽지도 않는다. 마스킹된 값만 담는다.
- `--analysis-only`(RF-7): 이슈 DB에 기록하지 않는 분석 전용 실행. `--dry-run`과 함께 못 쓴다(종료 코드 2). lock·스냅샷·Jira·코드·파싱·매칭·
  재사용은 그대로 하고, 쓰기 흐름의 질문·부작용(cleanup, 기존 계획 질문·pending 피드백 삭제, 열린 PR 확인)은 건너뛴다. 출력 `mode: "analysis-only"`
  (`read_only_reasons`·`open_prs` 없음, `plan`은 `{exists, source, pr_number}`만), ok로 끝나면 lock을 풀고 `lock_released: true`(`lock_owner` 없음).
  `--jira-file`은 `--dry-run` 없이도 받는다. 입력 해시에는 mode가 없어 이어서 보통 analyze를 하면 core를 재사용한다.
- `--more-logs <경로…>`(RF-7): 이전 분석의 로그(`triage-state.json`의 `job.logs`) 뒤에 로그를 더해 다시 분석한다(`--logs`와 함께 못 쓴다).
  순서는 이전 로그 뒤에 붙여 `f<순번>`이 안 바뀐다. 이미 있는 경로는 조용히, 내용(sha256)이 같은 다른 경로는 경고하고 건너뛴다. 이전 로그가 없거나
  `--offline-db`면 종료 코드 2. 로그 부분 해시가 바뀌어 Step 3~5를 합친 로그로 모두 다시 계산하고, 이전 `analysis.json`·`report.md`는
  `JOB/runs/<n>/`에 보관한다(최근 5개). `events.json`·`match.json`은 보관하지 않는다.
- 읽지 않는 파일: `events.json`(파서 출력), `match.json`(매처 출력, `parse_logcat cut --evidence` 입력),
  `jira.json`(마스킹된 Jira 추출 전체 — 코멘트 원문이 필요할 때만 읽는다), `jira_meta.json`, `triage-state.json`, `analysis-cache.json`.

`--failed-step`·`--steps-file`(선택)은 이 프로세스 안에서만 읽고 마스킹한다. 원문은 하위 스크립트 인자(→ `trace.jsonl`)와
`triage-state.json`에 쓰지 않는다. 결과는 `jira.json`·`jira_meta.json`·`analysis.json`의 `jira.failed_step`·`report.md`·
`timeline.md` 머리에 **있을 때만** 나온다(보조 정보, 점수·분류·검증에 쓰지 않는다). 없거나 읽지 못해도 출력은 이전과 같다.

사용자 결정이 필요한 곳에서는 멈추고 `{"status": "needs_input", "needs_input": {kind, question, options[], answer}}`를
낸다(종료 코드 0). 스킬이 사용자에게 묻고 `--answer <kind>=<값>`을 붙여 **같은 명령을 다시** 실행한다. 답과 진행 상태는
`JOB/triage-state.json`에 남고, 세션 lock owner가 같으면 다시 묻지 않는다(재실행은 멱등). kind:
`lock`(release-other|take-over|stop) · `plan`(resume|new) · `jira`(MCP 호출 후 재실행) ·
`year`(YYYY) · `reanalyze`(yes|no) · `open_pr`(continue|stop) · `logs`(`--logs`로 재실행) ·
`code`(프로필|경로|skip) · `code_confirm`(yes|skip) · `time`(ISO 시각) · `window`(full|keep) ·
`anchor`(off: 실패 스텝 앵커를 쓰지 않고 Jira 발생 시각 기준 범위로 분석, 아래).

질문 줄이기: 잔여 worktree·도구 브랜치는 묻지도 지우지도 않는다. `db_pr cleanup --dry-run`만 하고 대상이 있으면 `notes`로
알린다(상태 `cleanup_targets`, 정리는 `/telephony-triage:sync`). `--code`도 답도 없고 `code.auto_select`(사용자 config > site-defaults
> 기본 true)가 참이며 Jira 버전과 일치하는 프로필이 정확히 1개면 그 프로필을 `--code <프로필>`처럼 쓴다(출력 `code.auto: true`,
상태 `code_auto`, report.md 코드 줄에 표시). 경로가 무효면 전체 선택지로 묻는다.

실패 스텝 앵커(선택): 실패 스텝이 **어디를(시간 범위)·무엇을(우선 유형)** 볼지 정하고, **왜(S/C)** 는 로그 시그니처가 정한다.
앵커 우선순위 `--answer anchor=off`(끔) > 로그 스텝 마커(`failed_step.marker_patterns`가 있을 때 `parse_logcat markers`, 기본 꺼짐) >
`--steps-file`의 스텝 시각(**수동 시계 차 `--clock-offset`이 있을 때만**) > `--steps-file`의 스텝 순서(`step_order`: PASS 스텝의
흔적을 이슈 DB `step_events` 규칙으로 로그에서 찾아 마지막 일치 뒤를 실패 구간으로 본다, 시계 불필요) > Jira 발생 시각(±`--minutes`) >
증상 시각 스캔(`--answer time`). 시험 장비 시계는 단말 logcat 시계와 다를 수 있어, 시계 차를 모르면 장비 시각은 쓰지 않는다(경고).
마커·steps-file 앵커는 분석 범위와 근접 보너스의 중심에서 Jira 시각을 대신한다(`JOB/match_meta.json`, `jira_meta.json`은 그대로).
앵커 시각이 로그 범위 밖이면 경고하고 다음 출처로 넘어간다. 실패 스텝 문구는 앵커와 무관하게 우선 유형·키워드에 쓴다.
앵커가 없고 마커 패턴·steps-file도 없으면 출력은 이전과 같다.

종료 코드: 0 = 완료·needs_input·사용자 중단(`status: stopped`), 1 = Jira 키 형식 불일치(다시 묻는다),
2 = 사용·환경 오류(하위 스크립트 메시지를 그대로 낸다. lock을 잡았으면 풀고 끝낸다. `--analysis-only`와 `--dry-run`을 함께 준 경우도 여기).

이 파일은 CLI만 둔다. 구현은 `triagelib/`: `core`(상수·오류·`Runner`), `cache`(`State`·분석 캐시 믹스인), `anchor`(실패 스텝·
발생 시각·스텝 앵커 믹스인), `report`(analysis.json `fit`·스키마 검사·report.md·타임라인 믹스인), `driver`(`Driver`).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import events, site_defaults, userconfig  # noqa: E402
from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402
from triagelib.cache import State  # noqa: E402
from triagelib.core import (ANALYSIS_MAX, EXPLORE_DONE_LINE, EXPLORE_INPUT_FILE, STATE_FILE, TIMELINE_FILE,  # noqa: E402,F401
                            Fail, NeedsInput, Runner, Stopped, _clip)
from triagelib.driver import Driver  # noqa: E402
from triagelib.report import _unique_evidence, fit, schema_violation, timeline  # noqa: E402,F401 — 테스트가 쓴다


# -- CLI ------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triage.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--plugin-root", default=None)
    common.add_argument("--json", action="store_true", help="JSON 출력 (항상 JSON)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", parents=[common])
    p.add_argument("key", metavar="KEY")
    logs = p.add_mutually_exclusive_group()
    logs.add_argument("--logs", metavar="logcat|bugreport", nargs="+")
    logs.add_argument("--more-logs", metavar="logcat|bugreport", nargs="+", help="이전 분석의 로그 뒤에 로그를 더해 다시 분석(RF-7). --logs와 함께 못 쓴다")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--jira-raw", metavar="json")
    src.add_argument("--jira-file", metavar="yaml")
    src.add_argument("--jira-meta", metavar="json")
    p.add_argument("--code", metavar="프로필|경로|skip")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--analysis-only", action="store_true", help="이슈 DB에 기록하지 않는 분석 전용(cleanup·기존 계획·열린 PR 건너뜀, ok면 lock 해제). --dry-run과 함께 못 쓴다")
    p.add_argument("--answer", metavar="kind=값", action="append")
    p.add_argument("--tz")
    p.add_argument("--year", type=int)
    p.add_argument("--minutes", type=float)
    p.add_argument("--refresh", action="store_true", help="같은 세션에서도 스냅샷을 다시 만들고, 같은 입력의 분석 재사용(analysis-cache.json)도 끈다")
    p.add_argument("--offline-db", metavar="db")
    p.add_argument("--out", metavar="dir")
    p.add_argument("--failed-step", metavar="한 줄", help="실패 스텝 한 줄(선택, 보조 정보). 마스킹해서만 쓴다")
    p.add_argument("--steps-file", metavar="파일", help="시험 절차 첨부 파일(txt/csv/html/zip, 선택). 읽지 못하면 경고만 내고 진행")
    p.add_argument("--clock-offset", metavar="±시간", help="시험 장비 시각 → 단말 logcat 시각 시계 차(단말 = 장비 + 값). 예: +3m, -90s, +00:03:00, 180. "
                                          "없으면 steps-file의 장비 시각은 분석 구간에 쓰지 않는다")
    p = sub.add_parser("explore", parents=[common])
    p.add_argument("key", metavar="KEY")
    p.add_argument("--out", metavar="dir", help="`run --offline-db --out`의 JOB 디렉토리(없으면 <work_dir>/<KEY>)")
    p = sub.add_parser("release", parents=[common])
    p.add_argument("key", metavar="KEY")
    return parser


def _emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=1))


def cmd_release(args, defaults: dict) -> int:
    cfg = userconfig.merged(defaults)
    job = Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / args.key
    state = State(job / STATE_FILE)
    runner = Runner(args.plugin_root)
    if state.data.get("owner"):
        runner.env["TT_LOCK_OWNER"] = state.data["owner"]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.key) or not job.is_dir():
        _emit({"released": False, "note": "작업 디렉토리 없음"})
        return OK
    runner.open_trace(job / "trace.jsonl")
    try:
        _, data, _ = runner.call("end", "db_pr.py", ["lock", "release", args.key])
    except Fail as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    state.data["owner"] = None
    state.save()
    _emit(data)
    return OK


def cmd_explore(args, defaults: dict) -> int:
    """동의 뒤 탐색 타임라인 만들기: `JOB/explore-input.json`·`events.json` → `JOB/timeline.md`, report.md의 탐색 분석 줄 갱신.

    lock·trace·스냅샷은 건드리지 않는다. 종료 코드 0 = 완료, 1 = 해당 없음(입력 파일 없음: 후보 확정·`explore.when: never`·run 전),
    2 = 사용 오류(키 형식·작업 디렉토리·`events.json` 없음·입력 파일 손상).
    """
    cfg = userconfig.merged(defaults)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.key):
        print(f"Jira 키 형식이 아니다: {args.key}", file=sys.stderr)
        return USAGE
    job = Path(args.out).expanduser().resolve() if args.out else Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / args.key
    if not job.is_dir():
        print(f"작업 디렉토리가 없다: {job} — 먼저 triage.py run을 실행한다", file=sys.stderr)
        return USAGE
    input_path, events_path = job / EXPLORE_INPUT_FILE, job / "events.json"
    if not input_path.is_file():
        print(f"탐색 분석 해당 없음: {EXPLORE_INPUT_FILE}가 없다(후보 확정·explore.when: never·run 전)", file=sys.stderr)
        return CHECK_FAILED
    if not events_path.is_file():
        print(f"events.json이 없다: {events_path} — triage.py run을 다시 실행한다", file=sys.stderr)
        return USAGE
    try:
        spec = json.loads(input_path.read_text(encoding="utf-8"))
        events = json.loads(events_path.read_text(encoding="utf-8"))
        limit = spec.get("limit")
        if not isinstance(spec, dict) or not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit")
    except (OSError, ValueError) as exc:
        print(f"탐색 입력을 읽지 못했다({exc}) — triage.py run을 다시 실행한다", file=sys.stderr)
        return USAGE
    text, kept, total = timeline(args.key, events, spec.get("around"), limit, spec.get("failed_step"), spec.get("anchor"))
    (job / TIMELINE_FILE).write_text(text, encoding="utf-8", newline="\n")
    report = job / "report.md"
    if report.is_file():
        rows = report.read_text(encoding="utf-8").split("\n")
        for i, row in enumerate(rows):
            if row.startswith("- 탐색 분석"):
                rows[i] = EXPLORE_DONE_LINE.format(lines=kept, total=total)
        report.write_text("\n".join(rows), encoding="utf-8", newline="\n")
    _emit({"timeline": TIMELINE_FILE, "lines": kept, "total": total})
    return OK


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    if args.cmd == "release":
        return cmd_release(args, defaults)
    if args.cmd == "explore":
        return cmd_explore(args, defaults)
    driver = Driver(args, defaults)
    try:
        result = driver.execute()
    except NeedsInput as exc:
        driver.state.save()
        driver.run.note("needs_input", kind=exc.payload["kind"])
        out = {"status": "needs_input", "key": driver.key, "needs_input": exc.payload,
               "lock_owner": driver.run.env.get("TT_LOCK_OWNER")}
        violation = schema_violation(out)
        if violation:
            print(violation, file=sys.stderr)
            return USAGE
        _emit(out)
        return OK
    except Stopped as exc:
        driver.release()
        driver.run.note("stopped", reason=str(exc))
        out = {"status": "stopped", "key": driver.key, "reason": str(exc), "lock_released": driver.locked}
        violation = schema_violation(out)
        if violation:
            print(violation, file=sys.stderr)
            return USAGE
        _emit(out)
        return OK
    except Fail as exc:
        driver.release()
        driver.run.note("error", exit=exc.code, message=_clip(str(exc), 300))
        print(str(exc), file=sys.stderr)
        if exc.detail:
            _emit(exc.detail)
        return exc.code
    except Exception as exc:  # noqa: BLE001 — 모든 종료 경로에서 lock을 푼다 (12-principles)
        message = _clip(f"{type(exc).__name__}: {exc}", 300)
        had_lock = driver.locked
        try:
            released = driver.release()
        except Exception:  # noqa: BLE001 — 정리 중 오류가 원래 오류를 가리지 않게
            released = False
        try:
            driver.run.note("error", exit=USAGE, message=message)
        except Exception:  # noqa: BLE001
            pass
        tail = " — lock을 풀었다" if released else (f" — lock이 남았을 수 있다: triage.py release {driver.key}" if had_lock else "")
        print(f"triage.py 내부 오류(스크립트 버그로 보고): {message}{tail}", file=sys.stderr)
        return USAGE
    _emit(result)
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
