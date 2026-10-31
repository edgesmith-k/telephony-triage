#!/usr/bin/env python3
"""사내 보완(S 단계) 진행기: "사내 설정 시작"이면 이것 하나로 지금 할 단계·읽을 것·자동 점검·물을 것을 낸다 (15-local-draft.md §15.5).

    python3 tools/site_step.py                          # 시작·이어 하기: 현재 단계 pack(첫 방문 전체, 이후 요약) + 자동 점검 + 물을 것
                                                        #   (종료 코드는 점검 결과: 남은 실패·건너뜀·사용자 필요가 있으면 1)
    python3 tools/site_step.py check [S-n] [--json] [--allow-api]   # 자동 점검(읽기 전용, docs/site/steps/S-n.json만 쓴다)
    python3 tools/site_step.py propose [S-n] [--set 키=값]...       # SITE_PROFILE 확인값 행·steps.yaml·초안의 diff(쓰지 않음)
    python3 tools/site_step.py propose ... --apply ID[,ID]         # 사용자가 승인한 항목만 쓴다(확인자 = git user.name)
    python3 tools/site_step.py evals [--batch N] [--baseline]       # S-2: 사내 대상 eval의 다음 배치 명령·추정 비용(실행하지 않음)
    python3 tools/site_step.py --done S-n [--waive 점검="사유"]...  # 사용자 확인 뒤: 점검 재실행 → 통과면 완료 기록·다음 단계
    python3 tools/site_step.py ofono                    # oFono 트랙(O-1~O-4) 시작·이어 하기, S-3 완료 뒤

- 순서는 S-1 → S-2 → S-3 → S-4a → S-4 → S-5 → S-6 → S-7(`STEPS`). S-0(선택)은 반입 전 일이라 넣지 않는다.
- oFono 트랙은 Android 단계와 따로 O-1 → O-2 → O-3 → O-4(`OFONO_STEPS`)다. "oFono 설정 시작"이면 `ofono`: S-3 완료 기록 뒤에만
  "진행 상태"에 `- oFono 단계: O-1`·`- oFono 완료: (없음)`을 넣는다(한 번). `check`·`propose`·`--done`은 단계 인자로 O-n을 받는다.
  인자 없는 실행은 Android 단계에 안내 한 줄(`oFono 트랙: O-n 진행 중 → …`)을 붙이고, Android가 모두 완료면 oFono 단계를 바로 보인다.
- 점검(`site_checks.py`)은 판정만 하고 단계를 넘기지 않는다. `--done`은 실패가 있으면 거부하고, 건너뜀·사용자 필요는
  `--waive`(사유는 SITE_PROFILE.md "설계 변경"·docs/site/evidence.md에 남는다 — 사유는 줄 끝, SITE_PROFILE에는 120자까지 +
  `…(전체: docs/site/evidence.md)`, 기록한 줄은 `--done` 출력에 보인다) 없이는 거부한다. 사용자 확인 없이 `--done`하지 않는다.
- `SITE_PROFILE.md`의 "진행 상태" `현재 단계`·`완료 단계`(oFono는 `oFono 단계`·`oFono 완료`) 줄과, 승인된 `propose --apply` 항목만
  고친다. 형식은 14-site.md §14.3.
- S-2 eval은 `tests/skill_evals/pending.json`의 사내 대상(`site`, 사내 모델이 사외 결과 모델과 다르면 `site_if_model_differs`도)만
  돌린다. 나머지는 사외 결과 기록(`offsite_results.json`, 점검 `s2.offsite`)으로 갈음한다.
- 새로 만들 때 트래커는 jira다(사내 결정: S30·S31 GitHub 트래커 항목은 해당 없음, S-3에서 `tracker.kind: jira`).
- 사외 초안 PC(`.local-draft`)에서는 SITE_PROFILE.md를 만들지 않는다(종료 2, 반입 전 경계 검사가 막는 파일이다).

종료 코드: 0 정상(점검은 통과·정보만), 1 점검 실패·건너뜀·사용자 필요(`--done` 거부 포함), 2 사용 오류(사외 PC, 모드·단계 불일치, 진행 상태 줄 없음,
S-3 완료 전 `ofono`, 시작 전 O-n).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True    # 사내 레포에 __pycache__를 남기지 않는다(아래 import 전)

import argparse  # noqa: E402
import difflib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
from datetime import date, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_pack  # noqa: E402
import site_checks as sc  # noqa: E402

STEPS = ["S-1", "S-2", "S-3", "S-4a", "S-4", "S-5", "S-6", "S-7"]
DONE = "완료"
CURRENT_RE = re.compile(r"(?m)^- 현재 단계: *(\S+).*$")
FINISHED_RE = re.compile(r"(?m)^- 완료 단계: *(.*)$")
MODE_RE = re.compile(r"(?m)^- 모드: *(.+?)\s*$")
GATE_LINE_RE = re.compile(r"(?m)^- S-5 게이트:.*$")
OFONO_STEPS = ["O-1", "O-2", "O-3", "O-4"]
OFONO_CURRENT_RE = re.compile(r"(?m)^- oFono 단계: *(\S+).*$")
OFONO_FINISHED_RE = re.compile(r"(?m)^- oFono 완료: *(.*)$")
S3_DONE_RE = re.compile(r"(?:^|,\s*)S-3 \(")           # `완료 단계` 값에 S-3 기록
OFONO_NOT_STARTED = "oFono 트랙이 시작되지 않았다 — S-3 완료 뒤 `python3 tools/site_step.py ofono`"
EVAL_BATCH = 5
BASELINE_EVALS = sc.BASELINE_EVALS     # 사내 토큰 기준선 eval(pending.json site의 부분집합, s2.pending)


class Usage(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _base(root: Path) -> str:
    sha = _git(root, "rev-parse", "--short", "HEAD")
    return f"{sha or '<커밋>'} ({date.today().isoformat()} 반입본)"


def skeleton(root: Path) -> str:
    """14-site.md §14.3 형식의 빈 SITE_PROFILE.md(사내 보완, 현재 단계 S-1, 트래커 jira)."""
    return f"""# SITE_PROFILE (사내 전용, 반출 금지)

## 진행 상태
- 모드: 사내 보완
- 현재 단계: S-1
- 완료 단계: (없음)
- 트래커: jira (S30·S31 GitHub 트래커 항목은 해당 없음, S-3에서 `tracker.kind: jira`)
- 기준 문서 세트: {_base(root)}
- 진행: `python3 tools/site_step.py`(지금 단계·점검) → `check` 보고·사용자 확인 → `--done <단계>`

## 확인값
| # | 항목 | 확인값 | 근거 | 확인일 | 확인자 | 상태 |
|---|---|---|---|---|---|---|

## 설계 변경

## 사외 문서와의 차이

## 런타임 값 변경 이력
"""


def _profile(root: Path) -> Path:
    if (root / ".local-draft").exists():
        raise Usage("사외 초안 PC다(.local-draft) — 사내 설정은 반입한 사내 레포에서 한다(SITE_PROFILE.md는 사내 전용)")
    return root / "SITE_PROFILE.md"


def _state(text: str) -> tuple[str, str]:
    mode = MODE_RE.search(text)
    if mode and mode.group(1) != "사내 보완":
        raise Usage(f"SITE_PROFILE.md 모드가 '{mode.group(1)}'다 — 이 도구는 사내 보완(S 단계)만 진행한다"
                    "(사내 처음부터는 11-phases.md Phase 순서)")
    cur, fin = CURRENT_RE.search(text), FINISHED_RE.search(text)
    if not cur or not fin:
        raise Usage("SITE_PROFILE.md '진행 상태'에 `- 현재 단계: S-n`·`- 완료 단계: …` 줄이 없다 — 14-site.md §14.3 형식으로 고친다")
    step = cur.group(1)
    if step not in STEPS + [DONE]:
        raise Usage(f"현재 단계 '{step}'를 모른다 (순서: {' → '.join(STEPS)})")
    return step, fin.group(1).strip()


def _ofono_state(text: str) -> tuple[str | None, str]:
    """(oFono 단계 | None = 트랙 시작 전, 완료 값). 두 줄 중 하나만 있거나 모르는 단계면 사용 오류."""
    cur, fin = OFONO_CURRENT_RE.search(text), OFONO_FINISHED_RE.search(text)
    if not cur and not fin:
        return None, ""
    if not cur or not fin:
        raise Usage("SITE_PROFILE.md '진행 상태'에 `- oFono 단계: O-n`·`- oFono 완료: …` 줄이 하나만 있다 — 14-site.md §14.3 형식으로 고친다")
    step = cur.group(1)
    if step not in OFONO_STEPS + [DONE]:
        raise Usage(f"oFono 단계 '{step}'를 모른다 (순서: {' → '.join(OFONO_STEPS)})")
    return step, fin.group(1).strip()


def _profile_text(root: Path) -> str:
    prof = _profile(root)
    if not prof.exists():
        raise Usage("SITE_PROFILE.md가 없다 — 먼저 `python3 tools/site_step.py`로 시작한다")
    return prof.read_text(encoding="utf-8")


def _current(root: Path) -> str:
    return _state(_profile_text(root))[0]


def _ofono_current(text: str) -> str:
    """시작된 oFono 트랙의 단계(완료 포함). 시작 전이면 사용 오류."""
    _state(text)                                       # 모드 확인
    cur, _ = _ofono_state(text)
    if cur is None:
        raise Usage(OFONO_NOT_STARTED)
    return cur


def _step_arg(root: Path, step: str | None) -> str:
    if step is None:
        text = _profile_text(root)
        step = _state(text)[0]
        if step == DONE:                               # Android가 끝났으면 진행 중인 oFono 단계
            o_cur, _ = _ofono_state(text)
            step = o_cur if o_cur not in (None, DONE) else step
    if step.startswith("O-"):
        if step not in OFONO_STEPS:
            raise Usage(f"oFono 단계 '{step}'를 모른다 (순서: {' → '.join(OFONO_STEPS)})")
        _ofono_current(_profile_text(root))
        return step
    if step not in STEPS:
        raise Usage(f"단계 '{step}'를 모른다 (순서: {' → '.join(STEPS)})")
    return step


# --- 단계 상태 파일(docs/site/steps/S-n.json): 방문·마지막 점검 --------------------------------------------------

def _state_path(root: Path, step: str) -> Path:
    return root / sc.STEP_STATE_DIR / f"{step}.json"


def read_step_state(root: Path, step: str) -> dict:
    p = _state_path(root, step)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except ValueError:
        return {}


def write_step_state(root: Path, step: str, results: list[dict] | None = None, visited: bool = False) -> None:
    data = read_step_state(root, step) or {"step": step}
    if visited and not data.get("visited"):
        data["visited"] = date.today().isoformat()
    if results is not None:
        data.update(checked_at=datetime.now().isoformat(timespec="seconds"), exit=sc.exit_code(results), results=results)
    p = _state_path(root, step)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# --- 출력 ------------------------------------------------------------------------------------------------------

LOOP = """===== 진행 (한 단계씩, 확인 전에는 다음 단계로 가지 않는다) =====
1. 할 일을 한다. 막히면(git 충돌·인증·MCP 부재·버전 불일치) 우회하지 않고 보고한다.
2. `python3 tools/site_step.py check{arg}` — 자동 점검(읽기 전용). 실패·건너뜀·사용자 필요는 그대로 보고한다(통과로 쓰지 않는다).
3. 값 반영: `python3 tools/site_step.py propose{arg} [--set 키=값]` → diff를 보여 주고, 사용자가 승인한 ID만 `propose{arg} --apply ID[,ID]`.
4. (S-2) `python3 tools/site_step.py evals` — 사내 대상 eval의 다음 배치 명령·추정 비용(나머지는 사외 결과, s2.offsite). 비용 승인 뒤에만 실행하고, 수동 채점은 사람이 한다.
5. 요약 → **사용자 확인** → `python3 tools/site_step.py --done {step}` (사용자가 확인한 건너뜀·사용자 필요만 `--waive 점검="사유"`)."""


def _brief(step: str) -> str:
    _, note = context_pack.pack_row(step)
    row = context_pack.step_row(step) or ""
    out = f"===== {context_pack.STEPS} §15.5 {step} (요약 — 이미 본 단계) =====\n{row}\n"
    if note:
        out += f"\n===== 비고 =====\n{note}\n"
    return out + f"\n읽을 것 전체가 다시 필요하면: `python3 tools/context_pack.py {step}`\n"


def asks(results: list[dict]) -> str:
    items = [f"{i}. [{r['id']}] {r['ask']}" for i, r in
             enumerate((r for r in results if r.get("ask") and r["status"] not in sc.OK_STATUSES), 1)]
    return "===== 사용자에게 물을 것 (한 번에) =====\n" + ("\n".join(items) if items else "(없음)")


def guide(step: str, created: bool, root: Path | None = None, allow_api: bool = False, ofono: bool = False,
          started: bool = False) -> tuple[str, int]:
    """(출력, 종료 코드 = 점검 결과의 exit_code). root가 없으면 점검 없이 pack만(종료 0). `ofono`면 oFono 트랙 단계."""
    if step == DONE:
        if ofono:
            return "oFono 트랙 O-1~O-4가 모두 완료로 기록돼 있다.", 0
        return "사내 보완 S-1~S-7이 모두 완료로 기록돼 있다. 파일럿 뒤 할 일은 15-local-draft.md §15.5 S-7 비고와 docs/tasks.md.", 0
    arg = f" {step}" if ofono else ""     # 인자 없는 check·propose는 Android 현재 단계를 본다
    head = [("SITE_PROFILE.md를 새로 만들었다(사내 보완, 트래커 jira). " if created else "")
            + ("oFono 트랙을 시작했다. " if started else "") + ("oFono 트랙 " if ofono else "") + f"지금 단계: {step}",
            f"이 단계를 마치면: `site_step.py check{arg}` 보고 → 요약 → 사용자 확인 → `python3 tools/site_step.py --done {step}` "
            "(확인 전에는 다음 단계로 가지 않는다)", ""]
    if root is None:
        return "\n".join(head) + context_pack.render(step), 0
    seen = bool(read_step_state(root, step).get("visited"))
    body = _brief(step) if seen else context_pack.render(step)
    results = sc.run_checks(step, root, allow_api)
    write_step_state(root, step, results, visited=True)
    return "\n".join([*head, body, sc.report(step, results), "", asks(results), "", LOOP.format(step=step, arg=arg)]), \
        sc.exit_code(results)


def start(root: Path, allow_api: bool = False) -> tuple[str, int]:
    prof = _profile(root)
    created = not prof.exists()
    if created:
        prof.write_text(skeleton(root), encoding="utf-8", newline="\n")
    text = prof.read_text(encoding="utf-8")
    step, _ = _state(text)
    o_cur, _ = _ofono_state(text)
    if step == DONE and o_cur not in (None, DONE):     # Android가 끝났으면 oFono 단계를 바로 보인다
        return guide(o_cur, created, root, allow_api, ofono=True)
    out, code = guide(step, created, root, allow_api)
    if o_cur is not None:                              # 시작 전이면 출력은 그대로다
        out += "\n" + ("oFono 트랙: 완료" if o_cur == DONE else f"oFono 트랙: {o_cur} 진행 중 → python3 tools/site_step.py ofono")
    return out, code


def ofono_cmd(root: Path, allow_api: bool = False) -> tuple[str, int]:
    """oFono 트랙 시작·이어 하기. 줄이 없으면 S-3 완료 기록이 있을 때만 두 줄을 넣는다(O-2가 site-defaults.yaml을 본다)."""
    prof = _profile(root)
    text = _profile_text(root)
    cur, fin = _state(text)
    o_cur, _ = _ofono_state(text)
    started = o_cur is None
    if started:
        if not S3_DONE_RE.search(fin):
            raise Usage(f"oFono 트랙은 S-3 완료 기록 뒤에 시작한다(O-2에 plugin/site-defaults.yaml 필요) — 지금 Android 단계 {cur}")
        text = _insert_progress(text, "- oFono 단계: O-1", OFONO_CURRENT_RE.pattern)
        text = _insert_progress(text, "- oFono 완료: (없음)", OFONO_FINISHED_RE.pattern)
        prof.write_text(text, encoding="utf-8", newline="\n")
        o_cur = OFONO_STEPS[0]
    return guide(o_cur, False, root, allow_api, ofono=True, started=started)


def check(root: Path, step: str | None, as_json: bool, allow_api: bool) -> tuple[str, int]:
    _profile(root)
    step = _step_arg(root, step)
    results = sc.run_checks(step, root, allow_api)
    write_step_state(root, step, results)
    code = sc.exit_code(results)
    if as_json:
        return json.dumps({"step": step, "exit": code, "results": results}, ensure_ascii=False, indent=1), code
    return sc.report(step, results) + "\n\n" + asks(results), code


# --- propose ---------------------------------------------------------------------------------------------------

def _parse_sets(sets: list[str]) -> list[dict]:
    items, gate = [], {}
    for s in sets:
        key, sep, value = s.partition("=")
        key, value = key.strip(), value.strip()
        if "\n" in s or "\r" in s:
            raise Usage(f"--set {key}: 값에 줄바꿈을 넣을 수 없다(SITE_PROFILE·steps.yaml 한 줄 값)")
        if not sep or not value:
            raise Usage(f"--set {s!r}: 키=값 형식이다")
        if key in ("gate.top1", "gate.error_rate"):
            try:
                v = float(value)
            except ValueError:
                raise Usage(f"{key}: 숫자(0~1)가 아니다: {value}") from None
            if not 0 <= v <= 1:
                raise Usage(f"{key}: 0~1 범위가 아니다: {value}")
            gate[key.split(".", 1)[1]] = v
        elif key.startswith("row.") and key.count(".") >= 2:     # 확인값 행: row.<S#>.<항목>=<값> (사용자가 준 값)
            _, num, item = key.split(".", 2)
            if not re.fullmatch(r"S\d+", num):
                raise Usage(f"{key}: row.<S번호>.<항목> 형식이다(예: row.S4.샘플 Jira 키)")
            items.append(sc.row_item(f"row.{num}.{item}", num, item, value, "사용자 제공"))
        elif key in sc.STEP_INPUTS:
            if key == "eval_budget_usd":
                try:
                    value = float(value)
                except ValueError:
                    raise Usage(f"eval_budget_usd: 숫자가 아니다: {value}") from None
            elif key == "platforms":
                value = [p.strip() for p in value.split(",") if p.strip()]
            items.append({"id": f"steps.{key}", "kind": "steps", "key": key, "value": value})
        else:
            raise Usage(f"--set 키 '{key}'를 모른다 (gate.top1, gate.error_rate, row.<S#>.<항목>, {', '.join(sc.STEP_INPUTS)})")
    if gate:
        if set(gate) != {"top1", "error_rate"}:
            raise Usage("게이트는 gate.top1과 gate.error_rate를 함께 준다")
        items.append({"id": "gate", "kind": "gate", **gate})
    return items


def _user(root: Path) -> str:
    return _git(root, "config", "user.name")


def _insert_progress(text: str, line: str, pattern: str) -> str:
    """'## 진행 상태' 절에 한 줄을 둔다(같은 패턴 줄이 있으면 바꾼다)."""
    core = pattern.removeprefix("(?m)")
    rx = re.compile(core if core.endswith("$") else core + ".*$", re.M)
    if rx.search(text):
        return rx.sub(lambda m: line, text, count=1)
    head = "## 진행 상태\n"
    if head not in text:
        return text.rstrip("\n") + f"\n\n{head}{line}\n"
    i = text.index(head) + len(head)
    j = text.find("\n## ", i)
    j = len(text) if j < 0 else j
    sec = text[i:j].rstrip("\n")
    return text[:i] + (sec + "\n" if sec else "") + line + "\n" + ("\n" if j < len(text) else "") + text[j:].lstrip("\n")


def _set_row(text: str, row: list[str]) -> str:
    line = "| " + " | ".join(c.replace("|", "/") for c in row) + " |"
    lines = text.splitlines()
    if "## 확인값" not in text:
        return text.rstrip("\n") + "\n\n## 확인값\n| # | 항목 | 확인값 | 근거 | 확인일 | 확인자 | 상태 |\n|---|---|---|---|---|---|---|\n" + line + "\n"
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## 확인값"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last = start
    for i in range(start + 1, end):
        if lines[i].startswith("|"):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if cells[:2] == row[:2]:
                lines[i] = line
                return "\n".join(lines) + "\n"
            last = i
    lines.insert(last + 1, line)
    return "\n".join(lines) + "\n"


def _evidence(root: Path, text: str | None, entries: list[str]) -> str:
    base = text.rstrip("\n") + "\n" if text is not None else "# 사내 확인 근거 (사내 전용, SITE_PROFILE.md에서 옮긴 근거·긴 설명)\n\n"
    return base + "".join(f"{e}\n" for e in entries)


def _read(root: Path, rel: str) -> str | None:
    p = root / rel
    return p.read_text(encoding="utf-8") if p.is_file() else None


def transform(root: Path, item: dict, user: str, today: str, files: dict[str, str | None]) -> None:
    """`files`(상대 경로 → 내용, None은 없음)에 항목 하나를 반영한다."""
    def get(rel):
        if rel not in files:
            files[rel] = _read(root, rel)
        return files[rel]
    kind = item["kind"]
    ev = None
    if kind == "profile-row":
        files["SITE_PROFILE.md"] = _set_row(get("SITE_PROFILE.md") or "",
                                            [item["num"], item["item"], str(item["value"]), item["basis"], today, user, "확인"])
        ev = f"- ({today}) {item['id']}: {item['num']} {item['item']} = {item['value']} (근거 {item['basis']}, 확인 {user})"
    elif kind == "gate":
        line = f"- S-5 게이트: top1 ≥ {item['top1']:.2f}, error_rate ≤ {item['error_rate']:.2f} ({today} 합의)"
        files["SITE_PROFILE.md"] = _insert_progress(get("SITE_PROFILE.md") or "", line, GATE_LINE_RE.pattern)
        ev = f"- ({today}) gate: {line[2:]} — 확인 {user}"
    elif kind == "progress-line":
        files["SITE_PROFILE.md"] = _insert_progress(get("SITE_PROFILE.md") or "", item["line"], item["pattern"])
        ev = f"- ({today}) {item['id']}: {item.get('basis', '')} — 확인 {user}"
    elif kind == "steps":
        cur = yaml.safe_load(get(sc.STEPS_FILE) or "") or {}
        cur[item["key"]] = item["value"]
        files[sc.STEPS_FILE] = ("# 사내 단계 입력 (site_step.py propose --apply로만 쓴다, 사용자 승인 값)\n"
                                + yaml.safe_dump(cur, allow_unicode=True, sort_keys=False))
        ev = f"- ({today}) {item['id']} = {item['value']} — 확인 {user}"
    elif kind == "draft":
        example = _read(root, "plugin/site-defaults.example.yaml") or ""
        files[item["path"]] = ("# site-defaults.yaml 초안 (site_step.py propose, 사내 전용). example 사본이다 — 값을 사내 확인값으로\n"
                               "# 고치고 사용자 확인 뒤 plugin/site-defaults.yaml로 옮긴다(tracker.kind: jira, S-3).\n" + example)
        ev = f"- ({today}) {item['id']}: {item['path']} 생성 — 확인 {user}"
    else:
        raise Usage(f"모르는 제안 종류: {kind}")
    if ev:
        files[sc.EVIDENCE_FILE] = _evidence(root, get(sc.EVIDENCE_FILE), [ev])


def _diff(rel: str, old: str | None, new: str) -> str:
    return "".join(difflib.unified_diff((old or "").splitlines(True), new.splitlines(True),
                                        f"a/{rel}" if old is not None else "/dev/null", f"b/{rel}"))


def propose(root: Path, step: str | None, sets: list[str], apply: str | None, allow_api: bool) -> tuple[str, int]:
    _profile(root)
    step = _step_arg(root, step)
    items = []
    for r in sc.run_checks(step, root, allow_api):
        items += r.get("propose") or []
    items += _parse_sets(sets)
    by_id = {i["id"]: i for i in items}
    user, today = _user(root), date.today().isoformat()
    if apply is None:
        out = [f"제안 {step}: {len(items)}건 (쓰지 않음 — 사용자가 고른 ID만 `propose ... --apply ID[,ID]`)"]
        for it in items:
            files: dict[str, str | None] = {}
            transform(root, it, user or "<git user.name>", today, files)
            out.append(f"\n## {it['id']}")
            out += [_diff(rel, _read(root, rel), new) for rel, new in files.items() if new != _read(root, rel)]
        return "\n".join(out), 0
    ids = [i.strip() for i in apply.split(",") if i.strip()]
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise Usage(f"제안에 없는 ID: {', '.join(unknown)} (지금 제안: {', '.join(by_id) or '없음'}; --set 값은 같이 준다)")
    if not user:
        raise Usage("git user.name이 없다 — 확인자를 남길 수 없어 쓰지 않는다(`git config user.name <이름>`)")
    files = {}
    for i in ids:
        transform(root, by_id[i], user, today, files)
    for rel, new in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new, encoding="utf-8", newline="\n")
    out = f"적용: {', '.join(ids)} → {', '.join(sorted(files))} (확인자 {user})"
    warn = context_pack.site_profile_warning(root)
    return out + (f"\n{warn}" if warn else ""), 0


# --- evals (S-2) -----------------------------------------------------------------------------------------------

def _costs(root: Path) -> tuple[dict[int, float], float]:
    """(eval별 예상 비용 근거 = 사내 실행 → 사내 기준선 → 사외 기준선 → 사외 결과 기록의 최근 run, 사내 실행 누적 비용)."""
    known, spent = {}, 0.0
    for k, v in ((sc.load_offsite(root) or {}).get("evals") or {}).items():      # 가장 약한 근거(사외 모델·환경)
        costs = [r["cost_usd"] for r in (v or {}).get("runs") or [] if isinstance(r.get("cost_usd"), (int, float))]
        if costs:
            known[int(k)] = float(costs[-1])
    for base in (root / "tests/skill_evals/token_baseline.json", root / sc.SITE_BASELINE):   # 뒤가 우선(사내)
        if base.is_file():
            for k, v in (json.loads(base.read_text(encoding="utf-8")).get("evals") or {}).items():
                if isinstance(v.get("total_cost_usd"), (int, float)):
                    known[int(k)] = float(v["total_cost_usd"])
    for it in sc.site_iterations(root):
        for ex in it.glob("eval-*/with_skill/execution.json"):
            data = json.loads(ex.read_text(encoding="utf-8"))
            cost = data.get("total_cost_usd")
            if isinstance(cost, (int, float)):
                spent += cost
                m = re.match(r"eval-(\d+)", ex.parent.parent.name)
                known[int(m.group(1))] = float(cost)
    return known, spent


def evals_cmd(root: Path, batch: int, baseline: bool) -> tuple[str, int]:
    state = sc.eval_state(root)
    inputs = sc.load_inputs(root)
    model = inputs.get("eval_model")
    mflag = f" --model {model}" if model else ""
    its = sc.site_iterations(root)
    nums = [int(m.group(1)) for d in its if (m := re.match(rf"{sc.EVAL_WORKSPACE_PREFIX}(\d+)$", d.name))]
    new_it = f"tests/skill_evals/workspace/{sc.EVAL_WORKSPACE_PREFIX}{(max(nums) + 1 if nums else 1):03d}"
    if baseline:
        done_its = sorted({s["iteration"] for i, s in state.items() if i in BASELINE_EVALS and s.get("exec") == "completed"
                           and s.get("init_model")})
        if not done_its:
            return ("기준선 run 없음: 먼저 같은 모델로 실측한다(API 비용 — 사용자 승인 뒤)\n"
                    f"  python3 tests/skill_evals/run.py --iteration {new_it} --eval {' '.join(map(str, BASELINE_EVALS))} "
                    f"--execute{mflag}"), 0
        paths = " ".join(f"tests/skill_evals/workspace/{d}" for d in done_its)
        return ("사내 토큰 기준선(T4) 쓰기 — 실행 전 사용자 확인:\n"
                f"  python3 tests/skill_evals/grade.py {paths} --eval {' '.join(map(str, BASELINE_EVALS))} "
                f"--write-baseline {sc.SITE_BASELINE}"), 0
    pend = sc.load_pending(root)
    req = sc.required_ids(root, state)
    if not req:
        return "S-2 eval: 사내 대상 없음 — tests/skill_evals/pending.json의 site가 비었다(`check S-2`의 s2.pending)", 1
    _, off_m, site_m = sc.model_differs(root, state)
    grade = sc._grade_module()
    batches = {e["id"]: e.get("batch") for e in sc.eval_entries(root)}
    first = lambda i: (not (i in pend["manual"] or grade.is_safety_eval(i, batches.get(i))), i)  # noqa: E731 — 안전·수동 먼저
    clean = {i for i in req if state[i]["status"] == "graded" and not state[i].get("failed")}
    ungraded = sorted(i for i in req if state[i]["status"] == "ungraded")
    retry = sorted((i for i in req if i not in clean and state[i]["status"] not in ("none", "ungraded")), key=first)
    rest = sorted((i for i in req if state[i]["status"] == "none"), key=first)
    queue = retry + rest
    known, spent = _costs(root)
    mean = sum(known.values()) / len(known) if known else None
    est = lambda ids: None if mean is None else sum(known.get(i, mean) for i in ids)  # noqa: E731
    graded = sum(state[i]["status"] == "graded" for i in req)
    cond = sorted(set(req) - set(pend["site"]))
    out = [f"S-2 eval: 사내 대상 {len(req)}/{len(state)}"
           + (f"(모델 다름 사외 {off_m} / 사내 {site_m}: 조건부 {sc._ids(cond)} 포함)" if cond else "")
           + f" · 채점 {graded} (실패 없음 {len(clean)}) · 남음 {len(queue)} (재시도 {len(retry)}, 미실행 {len(rest)}) · "
           f"수동 채점 {pend['manual']} · 나머지 {len(state) - len(req)}개는 사외 결과(`check S-2`의 s2.offsite)"]
    if ungraded:
        out.append(f"채점만 필요(실행 기록 있음): eval {sc._ids(ungraded)} → grade.py <그 iteration> --eval …")
    if not queue:
        out.append("남은 사내 대상 eval 없음. `site_step.py check S-2`로 안전·수동 채점·사외 결과를 확인한다.")
        return "\n".join(out), 0
    nxt = queue[:batch]
    ids = " ".join(map(str, nxt))
    cost = est(nxt)
    budget = inputs.get("eval_budget_usd")
    out.append(f"다음 배치({len(nxt)}): eval {ids}")
    out.append("추정 비용: " + (f"${cost:.2f}" if cost is not None else "알 수 없음(기준선·실측·사외 결과 없음)")
               + (f" · 남은 전체 추정 ${est(queue):.2f}" if cost is not None else "") + f" · 지금까지 사내 실행 ${spent:.2f}")
    if budget is None:
        out.append("예산 미정 — 사용자에게 묻는다: `site_step.py propose --set eval_budget_usd=<USD>` → --apply")
    else:
        left = float(budget) - spent
        out.append(f"예산 ${float(budget):.2f} · 남음 ${left:.2f}"
                   + (" — 이 배치는 예산 초과: 사용자 승인 없이는 실행하지 않는다" if cost is not None and cost > left else ""))
    out += ["", "API 비용이 든다 — 사용자가 위 비용을 승인한 뒤에만 실행한다:",
            f"  python3 tests/skill_evals/run.py --iteration {new_it} --eval {ids} --execute{mflag}",
            f"  python3 tests/skill_evals/grade.py {new_it} --eval {ids}"
            + (" --token-budget" if (root / sc.SITE_BASELINE).is_file() else ""),
            *([] if model else ["(모델 미고정 — CLI 기본 모델. 기준선과 같은 모델로 고정하려면 `propose --set eval_model=<ID>`)"]),
            *([f"(사내 모델이 사외 결과 모델 {off_m}와 다르면 조건부 eval {sc._ids(sorted(pend['site_if_model_differs']))}도 "
               "사내 대상이 된다 — 실행 뒤 init_model로 다시 판정)"] if not cond and pend["site_if_model_differs"] else []),
            "한도·인증 오류로 멈추면 자동 반복하지 않고 사용 가능해진 뒤 `site_step.py evals`로 새 경로를 받는다."]
    return "\n".join(out), 0


# --- done ------------------------------------------------------------------------------------------------------

WAIVE_PROFILE_MAX = 120      # SITE_PROFILE 한 줄의 사유 글자 수(4KB 상한, 14-site.md §14.3). 전체 사유는 evidence.md


def _parse_waivers(waives: list[str]) -> dict[str, str]:
    out = {}
    for w in waives:
        cid, sep, why = w.partition("=")
        if "\n" in w or "\r" in w:
            raise Usage(f"--waive {cid.strip()}: 사유에 줄바꿈을 넣을 수 없다(SITE_PROFILE 한 줄 기록)")
        if not sep or not why.strip():
            raise Usage(f"--waive {w!r}: 점검=\"사유\" 형식이다(사유 필수)")
        if cid.strip() in out:
            raise Usage(f"--waive {cid.strip()}: 같은 점검을 두 번 줬다 — 사유를 하나로 합쳐 한 번만 준다")
        out[cid.strip()] = why.strip()
    return out


def _profile_reason(why: str) -> str:
    """SITE_PROFILE 설계 변경 줄의 사유: 길면 앞 120자 + 전체 위치(조용히 자르지 않는다)."""
    if len(why) <= WAIVE_PROFILE_MAX:
        return why
    return why[:WAIVE_PROFILE_MAX].rstrip() + f"…(전체: {sc.EVIDENCE_FILE})"


def _append_section(text: str, head: str, line: str) -> str:
    if head not in text:
        return text.rstrip("\n") + f"\n\n{head}\n{line}\n"
    i = text.index(head) + len(head)
    j = text.find("\n## ", i)
    j = len(text) if j < 0 else j
    sec = text[i:j].rstrip("\n")
    return text[:i] + sec + "\n" + line + "\n" + ("\n" if j < len(text) else "") + text[j:].lstrip("\n")


def done(root: Path, step: str, waives: list[str] | None = None, allow_api: bool = False) -> tuple[str, int]:
    prof = _profile(root)
    if not prof.exists():
        raise Usage("SITE_PROFILE.md가 없다 — 먼저 `python3 tools/site_step.py`로 시작한다")
    text = prof.read_text(encoding="utf-8")
    ofono = step.startswith("O-")
    if ofono:
        cur = _ofono_current(text)
        fin = _ofono_state(text)[1]
        track, cur_re, fin_re, label = OFONO_STEPS, OFONO_CURRENT_RE, OFONO_FINISHED_RE, "oFono "
    else:
        cur, fin = _state(text)
        track, cur_re, fin_re, label = STEPS, CURRENT_RE, FINISHED_RE, ""
    if step != cur:
        raise Usage(f"{label}현재 단계는 {cur}다 — --done {step}은 기록하지 않는다(단계를 건너뛰지 않는다)")
    waived = _parse_waivers(waives or [])
    results = sc.run_checks(step, root, allow_api)
    write_step_state(root, step, results)
    ids = {r["id"]: r for r in results}
    unknown = [w for w in waived if w not in ids]
    if unknown:
        raise Usage(f"--waive 점검 ID를 모른다: {', '.join(unknown)} (이 단계: {', '.join(ids)})")
    rep = sc.report(step, results)
    fails = [r["id"] for r in results if r["status"] == "fail"]
    if fails:
        return (rep + f"\n\n{step} 완료를 기록하지 않았다: 실패 {', '.join(fails)} (실패는 면제할 수 없다 — 고친 뒤 다시)"), 1
    pending = [r["id"] for r in results if r["status"] in ("skip", "needs-user") and r["id"] not in waived]
    if pending:
        return (rep + "\n\n" + asks(results) + f"\n\n{step} 완료를 기록하지 않았다: 건너뜀·사용자 필요 {', '.join(pending)} — "
                "사용자가 확인했으면 `--waive 점검=\"사유\"`로 사유를 남긴다"), 1
    today = date.today().isoformat()
    used = {w: why for w, why in waived.items() if ids[w]["status"] in ("skip", "needs-user")}
    recorded = []
    for w, why in used.items():     # 사유는 줄 끝 — 사유 안의 `-`·`—`·`|`가 구분자와 섞이지 않는다
        line = f"- ({today}) {step} {w} 면제(사용자 결정): {_profile_reason(why)}"
        text = _append_section(text, "## 설계 변경", line)
        recorded.append(line)
    if used:
        ev = root / sc.EVIDENCE_FILE
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text(_evidence(root, ev.read_text(encoding="utf-8") if ev.is_file() else None,
                                [f"- ({today}) {step} {w} 면제({ids[w]['status']}, 근거 {ids[w]['evidence']}) 사용자 결정: {why}"
                                 for w, why in used.items()]), encoding="utf-8", newline="\n")
    nxt = track[track.index(step) + 1] if step != track[-1] else DONE
    item = f"{step} ({today})"
    fin = item if fin in ("", "(없음)") else f"{fin}, {item}"
    text = cur_re.sub(lambda m: f"- {'oFono 단계' if ofono else '현재 단계'}: {nxt}", text, count=1)
    text = fin_re.sub(lambda m: f"- {'oFono 완료' if ofono else '완료 단계'}: {fin}", text, count=1)
    prof.write_text(text, encoding="utf-8", newline="\n")
    extra = f" (면제 {', '.join(used)} — 사유는 SITE_PROFILE.md 설계 변경)" if used else ""
    out, _ = guide(nxt, False, root, allow_api, ofono=ofono)     # 기록은 끝났다(종료 0). 다음 단계 점검 결과는 출력으로만 본다
    shown = "".join(f"  SITE_PROFILE.md 설계 변경에 기록: {line}\n" for line in recorded)     # 쓴 줄을 그대로 보인다
    return f"{step} 완료를 기록했다{extra}.\n" + shown + out, 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="site_step.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=("check", "propose", "evals", "ofono"),
                    help="없으면 시작·이어 하기. ofono: oFono 트랙(O-1~O-4) 시작·이어 하기(S-3 완료 뒤)")
    ap.add_argument("step", nargs="?", metavar="S-n|O-n", help="check·propose 대상 단계(기본: 현재 단계)")
    ap.add_argument("--done", metavar="S-n|O-n", help="사용자 확인을 받은 현재 단계: 점검 재실행 → 통과면 완료 기록·다음 단계")
    ap.add_argument("--waive", action="append", default=[], metavar='점검="사유"',
                    help="--done에서 사용자가 확인한 건너뜀·사용자 필요 점검(사유는 SITE_PROFILE.md에 남는다)")
    ap.add_argument("--json", action="store_true", help="check: JSON 출력")
    ap.add_argument("--allow-api", action="store_true",
                    help="claude CLI를 부르는 점검을 허용한다(사용자 승인 뒤). `claude mcp list`는 설정된 MCP 서버(Jira MCP 포함)에 "
                         "연결 상태만 확인한다(데이터 읽기 없음)")
    ap.add_argument("--set", action="append", default=[], metavar="키=값", help="propose: 사용자가 준 값")
    ap.add_argument("--apply", metavar="ID[,ID]", help="propose: 사용자가 승인한 제안만 쓴다")
    ap.add_argument("--batch", type=int, default=EVAL_BATCH, help="evals: 배치 크기")
    ap.add_argument("--baseline", action="store_true", help="evals: 사내 토큰 기준선 명령")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)   # 테스트용
    args = ap.parse_args(argv)
    if args.done and args.cmd:
        ap.error("--done은 단독으로 쓴다")
    if args.waive and not args.done:
        ap.error("--waive는 --done과 함께 쓴다")
    if (args.set or args.apply) and args.cmd != "propose":
        ap.error("--set·--apply는 propose에서만 쓴다")
    if args.cmd == "ofono" and args.step:
        ap.error("ofono는 단계 인자를 받지 않는다(지금 oFono 단계부터)")
    root = Path(args.root)
    code = 0
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        if args.done:
            out, code = done(root, args.done, args.waive, args.allow_api)
        elif args.cmd == "check":
            out, code = check(root, args.step, args.json, args.allow_api)
        elif args.cmd == "propose":
            out, code = propose(root, args.step, args.set, args.apply, args.allow_api)
        elif args.cmd == "evals":
            out, code = evals_cmd(root, max(1, args.batch), args.baseline)
        elif args.cmd == "ofono":
            out, code = ofono_cmd(root, args.allow_api)
        else:
            out, code = start(root, args.allow_api)
        print(out)
    except Usage as exc:
        print(f"site_step: {exc}", file=sys.stderr)
        return 2
    warn = context_pack.site_profile_warning(root)
    if warn:
        print(warn, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
