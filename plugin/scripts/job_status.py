#!/usr/bin/env python3
"""job_status.py — 작업 상태 한 화면 (읽기 전용, 로컬 기록만, contracts.md §3.2).

    job_status.py [<KEY>] [--format json|markdown] [--doctor] [--platform <이름>] [--plugin-root <dir>] [--json]

`<work_dir>/<KEY>/`의 기록(plan.json·state.json·stage.json·pr.json·analysis.json·triage-state.json·post*)과
`session.lock`, `<work_dir>/snapshot.json`, `wt/` 안의 git 읽기로 "어디까지 했는지"를 한 화면으로 낸다.
단계(`none`·`started`·`needs-input`·`needs-input-past`·`analyzed`·`plan-saved`·`staged`·`summary-shown`·`committed`·
`pushed-no-pr`·`pr-created`, 손상·형식 이상 파일이면 `unknown`; sync-pr 재적용은 "재동기화 중", wt git을 못 읽으면 "확인 불가(git 읽기 실패)")·막힌 것·다음 할 일·관련 파일. 줄마다 확신도(`now`·`recorded`·`unknown`).
원격(PR 상태·원격 브랜치)은 보지 않는다(`원격 최신성: 확인하지 않음`). 사용자 승인 여부는 기록이 없어 늘 `unknown`이다.

읽기 전용: mkdir·파일 쓰기·fetch·gh·lock 획득·갱신·git 쓰기(write-tree·승인 해시 재계산·worktree prune) 없음.
손상 lock·JSON은 고치지 않고 막힌 것·경고로 보인다. 읽지 않는 것: `issue_raw.json`, `steps-pasted.txt` 내용,
로그, `events.json`, needs_input 질문 문구(상태 파일에는 `pending {kind, asked_at}`만 있다). `trace.jsonl`은 끝 256KB의
마지막 끝 행만 본다: triage `error`·db_pr `stage{result: error}`로 끝났으면 막힌 것 `last-run-error`(메시지는 마스킹·URL 자격증명 가림).

`<KEY>`를 생략하면 lock을 잡은 작업, 없으면 작업 디렉토리가 하나일 때 그 작업. 여럿이면 최근 순 후보(최대 5개,
`{candidates: [{key, stage, at}]}`)를 내고 종료 코드 0.

출력: 기본 `--format json`(한 줄) `{key, platform, target, stage{id, label, confidence, at?, evidence?}, blockers[{code,
label, confidence, at?, evidence?, next?}], must_show[], next, approval{approved_hash_prefix, staged_at, user_approval}, post, lock{held,
mine, job, command, age_sec, expired, same_session}, files, warnings[], last_question?{kind, asked_at, live}}`(`last_question`은
단계가 질문 단계가 아닌데 `pending`이 있을 때). 지금 기다리는 질문이 단계를 앞서도 `state.json`이 있으면 stage·pr.json 막힌 것을 본다.
`--format markdown`은 대상 → 단계 → 막힌 것 → 다음 할 일 → 관련 파일(≤3KB 보장: 넘으면 뒤쪽 줄을 빼고
`- … 생략 N줄(근거·경고·파일 등, JSON 출력)`, 그래도 넘으면 줄마다 자르고 뒤에서부터 줄을 뺀다, `--json`과 함께 못 쓴다).

`--doctor`(opt-in, 관리자 전달용 진단 한 장): 화면 뒤에 `### 진단` 절(≤1,024B, 전체 ≤4,096B) — 버전(플러그인 지문
`common.versions.plugin_fingerprint`·설치 폴더 이름·Claude Code·Python·PyYAML·jsonschema)과 `config.py doctor --format json`(하위
프로세스, 150초 제한 — gh 인증 확인 때문에 몇 초~최대 2분)의 개수·fail·warn 행(fail 먼저, 내용·다음은 가림). JSON은 `diagnosis{plugin{
fingerprint, dir, version}, claude_code, python, deps, doctor{exit, counts, rows(ok 아닌 행)}}`(doctor 실행 실패면 `doctor{exit, error}`).
작업 상태를 못 내는 사용 오류(config·work_dir 없음, 키 형식 불일치, 플랫폼 불일치)여도 `--doctor`면 종료 0으로 `작업 상태: 확인 불가
— <사유>`(JSON `status_error`)와 진단을 낸다(site-defaults 없음·인자 오류는 그대로 2).

종료 코드: 0 = 화면을 냈다(막힌 것이 있어도), 2 = 사용·환경 오류(site-defaults·사용자 config 없음, 키 형식 불일치,
플랫폼 불일치(분석·작업이 다른 플랫폼), work_dir 없음, 인자 오류 — `--doctor`면 앞의 넷은 0).
"""

from __future__ import annotations

import argparse
import json
import os
import platform as platform_mod
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import compat, jobstatus, masking, session_lock, site_defaults, userconfig, versions, yamlio  # noqa: E402
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
    parser.add_argument("--doctor", action="store_true",
                        help="관리자 전달용 진단(버전·환경 점검 doctor의 fail·warn 행)을 덧붙인다 — gh 인증 확인으로 몇 초~최대 2분")
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


DIAG_MAX = 1024                  # --doctor 진단 절 바이트 상한(앞 빈 줄 포함). 기존 화면 ≤3,072B와 합쳐 ≤4,096B
DOCTOR_TIMEOUT = 150
DIAG_HEAD = "### 진단 (관리자 전달용 — 이 화면을 그대로 보낸다. 로그 원문·자격증명 없음)"


def _claude_code_version() -> str:
    """`CLAUDE_CODE_EXECPATH`(Claude Code가 하위 프로세스에 준다), 없으면 PATH의 `claude`의 `--version`. 못 읽으면 확인 불가."""
    exe = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=10).stdout if exe else ""
    except (OSError, subprocess.SubprocessError):
        out = ""
    m = re.search(r"(\d+\.\d+\.\d+)\S*\s*\(Claude Code\)", out or "")
    return m.group(1) if m else "확인 불가"


def _deps() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        schema = version("jsonschema")
    except PackageNotFoundError:
        schema = "없음"
    return f"PyYAML {getattr(yaml, '__version__', '?')}·jsonschema {schema}"


def diagnosis(args, platform: str | None) -> dict:
    """관리자 전달용 진단: 버전(플러그인 지문·Claude Code·Python·의존성)과 `config.py doctor`의 ok 아닌 행(가림)."""
    root = Path(args.plugin_root) if args.plugin_root else SCRIPTS.parent
    try:
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    cmd = [sys.executable, str(SCRIPTS / "config.py"), "doctor", "--format", "json"]
    cmd += ["--platform", platform] if platform else []
    cmd += ["--plugin-root", str(args.plugin_root)] if args.plugin_root else []
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=DOCTOR_TIMEOUT)
        code = proc.returncode
        data = json.loads(proc.stdout) if code in (0, 1) else None
    except subprocess.TimeoutExpired:
        code, data = "시간 초과", None
    except (OSError, ValueError):
        code, data = None, None
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        rows = [{"check": str(r.get("check")), "status": str(r.get("status")), "detail": masking.mask_brief(r.get("detail")),
                 **({"next": masking.mask_brief(r["next"], 160)} if r.get("next") else {})}
                for r in data["rows"] if isinstance(r, dict) and r.get("status") != "ok"]
        rows.sort(key=lambda r: {"fail": 0, "warn": 1}.get(r["status"], 2))
        doctor = {"exit": code, "counts": data.get("counts"), "rows": rows}
    else:
        doctor = {"exit": code, "error": f"환경 점검 실행 실패(종료 {code})"}
    try:
        fingerprint = versions.plugin_fingerprint(root)
    except OSError as exc:      # 읽을 수 없는 파일이 있어도 진단은 낸다
        fingerprint = f"확인 불가 — {type(exc).__name__}"
    return {"plugin": {"fingerprint": fingerprint, "dir": root.name,
                       "version": manifest.get("version") if isinstance(manifest, dict) else None},
            "claude_code": _claude_code_version(), "python": platform_mod.python_version(), "deps": _deps(),
            "doctor": doctor}


def diagnosis_markdown(diag: dict) -> str:
    """진단 절(앞 빈 줄 포함 ≤ DIAG_MAX). 표는 fail·warn 행만(fail 먼저). 넘치면 뒤 행부터 빼고 `- … 외 n행` 줄."""
    p, d = diag["plugin"], diag["doctor"]
    ver = f", version {p['version']}" if p.get("version") else ""
    lines = ["", DIAG_HEAD,
             f"- [현재] 버전: 플러그인 지문 {p['fingerprint']}(설치 폴더 {jobstatus._clip(p['dir'], 60)}{ver}) · Claude Code "
             f"{diag['claude_code']} · Python {diag['python']} · {diag['deps']}"]
    if d.get("error"):
        lines.append(f"- [현재] {d['error']}")
        rows = []
    else:
        c = d.get("counts") or {}
        lines.append("- [현재] 환경 점검(doctor): " + " · ".join(f"{k} {c.get(k, 0)}" for k in ("ok", "warn", "fail", "skip")))
        rows = [r for r in d["rows"] if r["status"] in ("fail", "warn")]
    cell = lambda t: str(t).replace("|", "\\|")  # noqa: E731
    table = [f"| {cell(r['check'])} | {r['status']} | {cell(r['detail'])} | {cell(r.get('next', ''))} |" for r in rows]

    def text(n: int) -> str:
        body = lines + (["", "| 점검 | 상태 | 내용 | 다음 |", "|---|---|---|---|"] + table[:n] if n else [])
        if n < len(table):
            body.append(f"- … 외 {len(table) - n}행 — config.py doctor --format markdown")
        return "\n".join(body) + "\n"

    n = len(table)
    while n and len(text(n).encode("utf-8")) > DIAG_MAX:
        n -= 1
    return text(n)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(Path(args.plugin_root) if args.plugin_root else None)
    if args.format == "markdown" and args.json:
        print("job_status.py: --format markdown은 --json과 함께 쓸 수 없다.", file=sys.stderr)
        return USAGE
    try:
        doc = run(args, defaults)
    except (Usage, yamlio.YamlFileError) as exc:
        if not args.doctor:
            print(f"job_status.py: {exc}", file=sys.stderr)
            return USAGE
        doc = {"status_error": masking.mask_brief(exc, 240)}     # 진단은 작업 상태를 못 내도 낸다
    except Exception as exc:  # noqa: BLE001 — 예상 밖 오류(손상된 key_regex 등)도 --doctor면 진단은 낸다
        if not args.doctor:
            raise
        doc = {"status_error": f"확인 불가 — {type(exc).__name__}"}
    if args.doctor:
        doc["diagnosis"] = diagnosis(args, doc.get("platform") or args.platform)
    if args.format == "markdown":
        head = (f"## 작업 상태 — 확인 불가\n\n- 작업 상태: 확인 불가 — {doc['status_error']}\n" if "status_error" in doc
                else jobstatus.markdown(doc))
        print(head + (diagnosis_markdown(doc["diagnosis"]) if args.doctor else ""), end="")
    else:
        print(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
