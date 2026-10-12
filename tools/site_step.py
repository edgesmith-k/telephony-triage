#!/usr/bin/env python3
"""사내 보완(S 단계) 진행기: "사내 설정 시작"이면 이것 하나로 지금 할 단계와 읽을 것을 낸다 (15-local-draft.md §15.5).

    python3 tools/site_step.py              # 시작·이어 하기: SITE_PROFILE.md가 없으면 만들고(S-1), 현재 단계 pack 출력
    python3 tools/site_step.py --done S-n   # 사용자 확인을 받은 뒤: S-n 완료 기록 → 다음 단계 pack 출력

- 순서는 S-1 → S-2 → S-3 → S-4a → S-4 → S-5 → S-6 → S-7(`STEPS`). S-0(선택)은 반입 전 일이라 넣지 않는다.
- `SITE_PROFILE.md`의 "진행 상태" `현재 단계`·`완료 단계` 줄만 읽고 고친다(나머지 절은 그대로). 형식은 14-site.md §14.3.
- 새로 만들 때 트래커는 jira다(사내 결정: S30·S31 GitHub 트래커 항목은 해당 없음, S-3에서 `tracker.kind: jira`).
- 단계 완료 판정(완료 기준 점검·사용자 확인)은 Claude와 사용자가 한다. 이 도구는 기록과 다음 단계 안내만 한다.
- 사외 초안 PC(`.local-draft`)에서는 SITE_PROFILE.md를 만들지 않는다(종료 2, 반입 전 경계 검사가 막는 파일이다).

종료 코드: 0 정상, 2 사용 오류(사외 PC, 모드·단계 불일치, 진행 상태 줄 없음).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_pack  # noqa: E402

STEPS = ["S-1", "S-2", "S-3", "S-4a", "S-4", "S-5", "S-6", "S-7"]
DONE = "완료"
CURRENT_RE = re.compile(r"(?m)^- 현재 단계: *(\S+).*$")
FINISHED_RE = re.compile(r"(?m)^- 완료 단계: *(.*)$")
MODE_RE = re.compile(r"(?m)^- 모드: *(.+?)\s*$")


class Usage(Exception):
    pass


def _base(root: Path) -> str:
    try:
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = ""
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
- 진행: `python3 tools/site_step.py`(지금 단계) → 완료 기준·사용자 확인 → `python3 tools/site_step.py --done <단계>`

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


def guide(step: str, created: bool) -> str:
    if step == DONE:
        return "사내 보완 S-1~S-7이 모두 완료로 기록돼 있다. 파일럿 뒤 할 일은 15-local-draft.md §15.5 S-7 비고와 docs/tasks.md."
    head = [("SITE_PROFILE.md를 새로 만들었다(사내 보완, 트래커 jira). " if created else "") + f"지금 단계: {step}",
            "이 단계를 마치면: 완료 기준 점검 → 결과 요약 → 사용자 확인 → "
            f"`python3 tools/site_step.py --done {step}` (확인 전에는 다음 단계로 가지 않는다)", ""]
    return "\n".join(head) + context_pack.render(step)


def start(root: Path) -> str:
    prof = _profile(root)
    created = not prof.exists()
    if created:
        prof.write_text(skeleton(root), encoding="utf-8", newline="\n")
    step, _ = _state(prof.read_text(encoding="utf-8"))
    return guide(step, created)


def done(root: Path, step: str) -> str:
    prof = _profile(root)
    if not prof.exists():
        raise Usage("SITE_PROFILE.md가 없다 — 먼저 `python3 tools/site_step.py`로 시작한다")
    text = prof.read_text(encoding="utf-8")
    cur, fin = _state(text)
    if step != cur:
        raise Usage(f"현재 단계는 {cur}다 — --done {step}은 기록하지 않는다(단계를 건너뛰지 않는다)")
    nxt = STEPS[STEPS.index(step) + 1] if step != STEPS[-1] else DONE
    item = f"{step} ({date.today().isoformat()})"
    fin = item if fin in ("", "(없음)") else f"{fin}, {item}"
    text = CURRENT_RE.sub(lambda m: f"- 현재 단계: {nxt}", text, count=1)
    text = FINISHED_RE.sub(lambda m: f"- 완료 단계: {fin}", text, count=1)
    prof.write_text(text, encoding="utf-8", newline="\n")
    return f"{step} 완료를 기록했다.\n" + guide(nxt, False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="site_step.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--done", metavar="S-n", help="사용자 확인을 받은 현재 단계를 완료로 기록하고 다음 단계를 낸다")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)   # 테스트용
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        root = Path(args.root)
        print(done(root, args.done) if args.done else start(root))
    except Usage as exc:
        print(f"site_step: {exc}", file=sys.stderr)
        return 2
    warn = context_pack.site_profile_warning(root)
    if warn:
        print(warn, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
