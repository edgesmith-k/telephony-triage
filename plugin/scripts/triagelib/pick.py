"""이슈 시작 때 플랫폼 정하기 (17-platforms §11, K18) — `triage.py main`이 `resolve` 뒤·`Driver` 전(work_dir·lock·JOB 전)에 부른다.

켠 플랫폼이 2개 이상이고 `--offline-db`가 아닐 때만 한다. 그 밖(android 단독 등)은 **아무것도 읽지 않고** 돌아간다(출력 바이트 동일).

- 명시: `--answer platform=<p>`(최우선, `args.answer`에서 빼서 `answers`·입력 해시에 넣지 않는다 — Driver가 `platform_answer`만 남긴다) > `--platform` > `TT_PLATFORM`.
  사용자 config `platform`·site `platform.name`은 기본값이라 하나로 정해진 로그 형식이 이긴다(결정 D1).
- 명시가 있고 로그 형식이 하나로 정해졌는데 다르면 한 번 묻는다(D2). 답으로 정해 질문에서 멈춘 이어 하는 작업(`pending`+`platform_answer`,
  그 질문이 KEY의 가장 늦은 활동일 때 — 아래)이 명시나 로그 형식과 같을 때만 묻지 않고 잇는다(답 없이 이어 하는 작업은 로그 형식과 같아도 묻는다).
- 명시가 없으면 표 = {로그 형식(하나로 정해졌을 때), Jira 대응표(`platform.detect.tracker_field`, 기본 꺼짐), 이어 하는 작업}:
  1개 → 그 플랫폼(노트), 2개 이상 → `needs_input platform`, 0개 → 로그가 없으면 lock 전 `logs` 질문(켠 플랫폼 log_dir 모두),
  로그는 있는데 정하지 못하면 `needs_input platform`. 형식 미확인 파일은 빼고 센다(노트, D4).
- 이어 하는 작업: 켠 플랫폼마다 `<work_dir>/<KEY>/triage-state.json`에 `pending`(직전 실행이 질문으로 끝남)이 있는 곳, 로그를 주지
  않았거나 `--more-logs`면 이전 로그(`logs`·`job.logs`)가 있는 곳도. 읽기만 한다. 그 작업에 `pending`과 `platform_answer`(앞선
  실행이 `--answer platform=`으로 정함, Driver가 lock 뒤 남긴다)가 함께 있으면 답으로 정한 작업이다. 답은 그 질문이 이 KEY의
  가장 늦은 활동일 때만 쓴다(답으로 정한 작업 가운데 질문이 가장 늦은 하나이고, 다른 켠 플랫폼 작업의 마지막 질문·완료가 모두
  그보다 이를 때 — 같은 초는 막고 시각 없는 작업은 막지 않는다). 그러면 로그 형식·Jira보다 앞선다(스킬이 다음 호출에서
  `--answer platform=`을 빼도 다시 묻지 않는다). 답을 쓰지 않으면 이어 하는 작업이 하나일 때만 그 작업(답 없는 작업처럼), 여럿이면 없음.

결과: 진행이면 None(`args.platform_name`·`platform_cfg`를 바꾸고 `args.platform_pick`·`platform_implicit`를 단다), 질문이면 출력 dict.
질문 문구에는 경로·파일 이름·트래커 값을 넣지 않는다(파일은 `f<순번>`, 플랫폼은 라벨만).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import platforms
from common import userconfig
from common.exitcodes import USAGE
from platforms import session as platform_session
from platforms import sniff as platform_sniff

from .core import PLATFORM_ANSWER, STATE_FILE, Fail, NeedsInput

KIND = "platform"
LOGS_QUESTION = "분석할 logcat/bugreport 경로가 없다. 고르거나 입력받아 --logs로 다시 실행한다."   # Driver.logs와 같은 문구


def work_dir(defaults: dict, user: dict | None, name: str) -> Path:
    cfg = userconfig.merged(defaults, user) if name == userconfig.TOP_PROFILE else \
        userconfig.merged(defaults, user, platform=name)
    return Path(str(userconfig.get(cfg, "work_dir"))).expanduser()


def _take_answer(args, names: list[str]) -> str | None:
    """`--answer platform=<p>`를 꺼내 `args.answer`에서 뺀다(마지막 값). 켜지지 않은 이름이면 종료 코드 2."""
    value, kept = None, []
    for item in args.answer or []:
        kind, sep, val = item.partition("=")
        if sep and kind.strip() == KIND:
            value = val.strip()
        else:
            kept.append(item)
    if value is None:
        return None
    args.answer = kept or None
    if value not in names:
        raise Fail(USAGE, f"--answer platform: 플랫폼 '{value}'이(가) 켜져 있지 않습니다 (platform.enabled: {', '.join(names)}).")
    return value


def _state(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _at(record, field: str) -> str:
    """기록의 ISO 시각(`core._now()`), 없으면 ""."""
    value = record.get(field) if isinstance(record, dict) else None
    return value if isinstance(value, str) else ""


def _resume(defaults, user, names, key, earlier_logs: bool) -> tuple[str | None, bool]:
    """`(이어 하는 작업의 플랫폼 | None, 앞선 답을 쓰는가)`. 답은 그 질문이 이 KEY의 가장 늦은 활동일 때만 쓴다: 답으로 정한 작업
    (`pending`+`platform_answer`) 가운데 `pending.asked_at`이 가장 늦은 하나(같으면 없음)이고, 다른 켠 플랫폼 작업의 마지막 질문
    (`pending.asked_at`)·완료(`job.runs[-1].at`)가 모두 그보다 이를 때 — 같은 초는 막고(한 번 더 묻고, 다음 질문이 더 늦어 반복 없음),
    시각 없는 작업은 막지 않는다(막으면 끝나지 않는다). 그 밖은 답을 쓰지 않는다: 이어 하는 작업이 하나면 답 없는 작업처럼 그 작업,
    여럿이면 없음. 시각은 `core._now()` ISO UTC 초라 문자열 순서 = 시간 순서."""
    if key is None:
        return None, False
    hits, answered, seen = [], [], {}
    for name in names:
        state = _state(work_dir(defaults, user, name) / key / STATE_FILE)
        if not state:
            continue
        job = state.get("job") if isinstance(state.get("job"), dict) else {}
        pending = state.get("pending")
        runs = job.get("runs") if isinstance(job.get("runs"), list) else []
        asked = _at(pending, "asked_at")
        seen[name] = max(asked, _at(runs[-1] if runs else None, "at"))
        if pending or (earlier_logs and (state.get("logs") or job.get("logs"))):
            hits.append(name)
        if pending and state.get(PLATFORM_ANSWER) == name:
            answered.append((asked, name))
    if answered:
        asked, best = max(answered)
        if [at for at, _ in answered].count(asked) == 1 and \
                all(not at or (asked and at < asked) for name, at in seen.items() if name != best):
            return best, True
    return (hits[0], False) if len(hits) == 1 else (None, False)


def _scalar(value) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _jira(args, defaults, user, implicit, key) -> tuple[str | None, str | None]:
    """Jira 대응표 표: `(플랫폼 | None, 필드 경로)`. 기본 꺼짐. 원문 값은 내보내지 않는다."""
    rules = platforms.detect_rules(defaults)
    if not rules:
        return None, None
    import jira_fields     # 대응표를 켠 설치만 불러온다

    source = args.issue_file or args.issue_raw
    path = Path(source).expanduser() if source else (work_dir(defaults, user, implicit) / key / "issue_raw.json" if key else None)
    if path is None or not path.is_file():
        return None, rules["path"]
    try:
        data = jira_fields._read(path)
    except Exception:  # noqa: BLE001 — 읽지 못하면 표 없음(추출 단계가 오류를 알린다)
        return None, rules["path"]
    value = jira_fields.lookup(data, rules["path"])
    mapped = {rules["values"].get(_scalar(v)) for v in (value if isinstance(value, list) else [value])} - {None}
    return (mapped.pop() if len(mapped) == 1 else None), rules["path"]


def _label(name: str) -> str:
    return platforms.label(name)


def _ask(args, key, question: str, options: list[dict], kind: str = KIND) -> dict:
    return {"status": "needs_input", "key": key or args.key, "needs_input": NeedsInput(kind, question, options).payload,
            "lock_owner": None}


def _options(first: list[tuple[str, str]], names: list[str], implicit: str) -> list[dict]:
    """먼저 낼 `(이름, 출처 라벨)` 뒤로 나머지 켠 플랫폼(기본 선택에 "(기본)")."""
    out, seen = [], set()
    for name, tag in first + [(n, "") for n in names]:
        if name in seen:
            continue
        seen.add(name)
        tags = [t for t in (tag, "기본" if name == implicit else "") if t]
        out.append({"value": name, "label": _label(name) + (f" ({', '.join(tags)})" if tags else "")})
    return out


def _ask_logs(args, defaults, user, names, key) -> dict:
    """lock 전 `logs` 질문. 읽지 못하는 폴더·도중에 사라진 파일은 건너뛴다(후보일 뿐 — 없으면 빈 선택지로 묻는다)."""
    found = []
    for name in names:
        cfg = userconfig.merged(defaults, user) if name == userconfig.TOP_PROFILE else \
            userconfig.merged(defaults, user, platform=name)
        log_dir = userconfig.get(cfg, "log_dir")
        folder = Path(str(log_dir)).expanduser() if log_dir else None
        try:
            if folder is None or not folder.is_dir():
                continue
            entries = list(folder.iterdir())
        except OSError:
            continue
        for p in entries:
            try:
                if p.is_file():
                    found.append((p.stat().st_mtime, str(p), f"{p.name} ({_label(name)})"))
            except OSError:
                continue
    found.sort(key=lambda t: (-t[0], t[1]))
    return _ask(args, key, LOGS_QUESTION, [{"value": f, "label": label} for _, f, label in found[:10]], kind="logs")


def _files_detail(found: dict, names: list[str]) -> str:
    parts = []
    for f in found["files"]:
        what = "·".join(_label(n) for n in f["match"]) if f["match"] else "형식 미확인"
        parts.append(f"f{f['index']} {what}")
    return ", ".join(parts)


SOURCES = {"logs": "로그 형식", "jira": "Jira", "resume": "이어 하는 작업", "answer": "답"}


def _use(args, defaults, name: str, source: str, implicit: str, *, unknown: int = 0, field: str | None = None,
         answered: bool = False) -> None:
    if name != args.platform_name:
        args.platform_name, args.platform_cfg = platform_session.resolve(defaults, name)
    label = _label(name)
    instead = f" (기본 {_label(implicit)} 대신)" if name != implicit else ""
    reason = {"logs": "로그 형식으로 선택", "jira": f"Jira {field} 값으로 선택", "resume": "이어 하는 작업의 플랫폼",
              "answer": "답한 플랫폼"}[source]
    note = {"logs": f"로그 형식으로 {label} 선택{instead}",
            "jira": f"Jira {field} 값으로 {label} 선택{instead}",
            "resume": f"이어 하는 작업의 플랫폼({label})으로 계속{instead}",
            "answer": f"답한 플랫폼({label})으로 분석{instead}"}[source]
    if unknown:
        note += f" — 형식 미확인 파일 {unknown}개는 판별에서 뺐다"
    args.platform_pick = {"platform": name, "source": source, "note": note, "line": f"플랫폼: {label} ({reason})"}
    if source == "answer" or answered:     # Driver가 상태 `platform_answer`로 남긴다
        args.platform_pick["answered"] = True
    return None


def choose(args, defaults: dict, key: str | None) -> dict | None:
    """플랫폼을 정한다. 진행이면 None, 질문이면 출력 dict. 오류는 `Fail`(종료 코드 2). `key`는 작업 키(경로 안전, 없으면 None)."""
    if getattr(args, "offline_db", None) is not None:
        return None
    try:
        names = platforms.enabled(defaults)
        if len(names) < 2:
            return None
        platforms.detect_rules(defaults)      # 잘못된 대응표는 어느 경우든 종료 코드 2
    except platforms.PlatformConfigError as exc:
        raise Fail(USAGE, str(exc)) from exc
    user = userconfig.load_user()
    implicit = platform_session.implicit(defaults, user)
    args.platform_implicit = implicit
    args.platform_pick = None
    try:
        answer = _take_answer(args, names)
        if answer:
            return _use(args, defaults, answer, "answer", implicit)
        logs = list(args.logs or args.more_logs or [])
        if any(not Path(p).expanduser().is_file() for p in logs):
            return None          # 없는 로그 파일은 Driver가 종료 코드 2로 알린다(지금 동작)
        found = platform_sniff.sniff([Path(p).expanduser().resolve() for p in logs], names) if logs else None
        fmt = found["platforms"][0] if found and len(found["platforms"]) == 1 else None
        unknown = found["unknown"] if found else 0
        resume, answered = _resume(defaults, user, names, key, earlier_logs=not logs or bool(args.more_logs))
        explicit = args.platform or os.environ.get(platforms.ENV)
        if explicit:
            chosen = args.platform_name
            if fmt is None or fmt == chosen:
                return None      # 명시대로(지금 동작)
            if answered and resume in (fmt, chosen):    # 앞서 답으로 정한 작업만 다시 묻지 않는다(D2 한 번)
                return _use(args, defaults, resume, "resume", implicit, answered=True)
            return _ask(args, key, f"지정한 플랫폼은 {_label(chosen)}인데 로그 형식은 {_label(fmt)}다. 어느 플랫폼으로 분석할까?",
                        [{"value": chosen, "label": f"{_label(chosen)} (지정)"},
                         {"value": fmt, "label": f"{_label(fmt)} (로그 형식)"}])
        if answered:             # 앞서 답으로 정한 작업이 이어지는 중 — 로그 형식·Jira로 다시 묻지 않는다
            return _use(args, defaults, resume, "resume", implicit, answered=True)
        if not logs and not resume:
            return _ask_logs(args, defaults, user, names, key)
        jira, field = _jira(args, defaults, user, implicit, key)
        votes = [(s, n) for s, n in (("logs", fmt), ("jira", jira), ("resume", resume)) if n]
        distinct = list(dict.fromkeys(n for _, n in votes))
        if len(distinct) == 1:
            return _use(args, defaults, distinct[0], votes[0][0], implicit,
                        unknown=unknown if votes[0][0] == "logs" else 0, field=field)
        if distinct:
            detail = ", ".join(f"{SOURCES[s]}{(' ' + field) if s == 'jira' else ''}: {_label(n)}" for s, n in votes)
            return _ask(args, key, f"플랫폼 단서가 서로 다르다({detail}). 어느 플랫폼으로 분석할까?",
                        _options([(n, SOURCES[s]) for s, n in votes], names, implicit))
        why = f"파일마다 형식이 다르다: {_files_detail(found, names)}" if found["platforms"] else "로그 형식을 알 수 없다"
        return _ask(args, key, f"로그 형식으로 플랫폼을 정하지 못했다({why}). 어느 플랫폼으로 분석할까?",
                    _options([(n, "로그 형식") for n in found["platforms"]], names, implicit))
    except platforms.PlatformConfigError as exc:
        raise Fail(USAGE, str(exc)) from exc
