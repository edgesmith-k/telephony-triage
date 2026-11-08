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
    python3 tools/site_step.py modules                  # 모듈 스킬 트랙(MS-1~MS-2) 시작·이어 하기, S-3 완료 뒤
    python3 tools/site_step.py modules check [--json] [--allow-api]   # 지금 MS 단계 점검(= check MS-n)
    python3 tools/site_step.py modules coverage [--json] [--out F] [--min-lines N]   # 사내 로그 → 모듈별 줄 수·빈 이름·modules.yaml diff
    python3 tools/site_step.py audit [--since D|레포=sha] [--last] [--repo R] [--cap-tokens N] [--inhouse-model RX] [--jobs DIR] [--json]
    python3 tools/site_step.py audit --record [--defer ID[,ID]]     # 정기 점검: 토큰 0 검사 → Claude가 볼 것(상한 안) → 기준점 기록
    python3 tools/site_step.py audit --notify [--create] [--json]   # 걸린 항목(P0·P1·실패 검사)을 이슈 DB 레포 Issue로(기본 보기만)
    python3 tools/site_step.py runtime-check claude-gateway         # Claude Code + 사내 모델 프로필 표(모델 호출 없음)
    python3 tools/site_step.py runtime-check opencode [--project D] # OpenCode 1.19.5·설정·관리 설정 점검 + 사내 확인 0(OpenAI 호환) curl
    python3 tools/site_step.py runtime-check opencode --project D --jira KEY [--missing-key KEY]
                                                        # OpenCode Jira 읽기 사내 확인(모델 토큰 0, tools/oc_jira_check.py)

- 순서는 S-1 → S-2 → S-3 → S-4a → S-4 → S-5 → S-6 → S-7(`STEPS`). S-0(선택)은 반입 전 일이라 넣지 않는다.
- oFono 트랙은 Android 단계와 따로 O-1 → O-2 → O-3 → O-4(`OFONO_STEPS`)다. "oFono 설정 시작"이면 `ofono`: S-3 완료 기록 뒤에만
  "진행 상태"에 `- oFono 단계: O-1`·`- oFono 완료: (없음)`을 넣는다(한 번). `check`·`propose`·`--done`은 단계 인자로 O-n을 받는다.
  인자 없는 실행은 Android 단계에 안내 한 줄(`oFono 트랙: O-n 진행 중 → …`)을 붙이고, Android가 모두 완료면 oFono 단계를 바로 보인다.
- 모듈 스킬 트랙(MODULE_SKILLS_PLAN_IMPL §6)은 MS-1 → MS-2(`MODULE_STEPS`, 점검은 `site_checks.MODULE_CHECKS`)다. `modules`는 S-3 완료 기록
  뒤에만 "진행 상태"에 `- 모듈 단계: MS-1`·`- 모듈 완료: (없음)`을 넣는다(한 번). `check`·`--done`은 MS-n도 받는다. 안내는 §15.5에 MS 행이
  있으면 그것, 없으면 `MODULE_GUIDE`. `modules coverage`는 `tools/module_coverage.py`(토큰 0, 사내 전용 출력), `audit`은
  `tools/site_audit.py`(토큰 0 검사 뒤 Claude가 볼 것과 추정 토큰만 보인다 — Claude를 부르지 않는다, `docs/site/audit/`만 쓴다.
  이슈 DB마다 시그니처 소실 행 `audit.<레포>.drift`: 자주 맞던 원인 시그니처가 새 빌드 기록에서 0회면 사용자 필요·항목 `drift:<레포>:<K>`).
- 점검(`site_checks.py`)은 판정만 하고 단계를 넘기지 않는다. `--done`은 실패가 있으면 거부하고, 건너뜀·사용자 필요는
  `--waive`(사유는 SITE_PROFILE.md "설계 변경"·docs/site/evidence.md에 남는다 — 사유는 줄 끝, SITE_PROFILE에는 120자까지 +
  `…(전체: docs/site/evidence.md)`, 기록한 줄은 `--done` 출력에 보인다) 없이는 거부한다. 사용자 확인 없이 `--done`하지 않는다.
- `SITE_PROFILE.md`의 "진행 상태" `현재 단계`·`완료 단계`(oFono는 `oFono 단계`·`oFono 완료`) 줄과, 승인된 `propose --apply` 항목만
  고친다. 형식은 14-site.md §14.3.
- S-2 eval은 `tests/skill_evals/pending.json`의 사내 대상(`site`, 사내 모델이 사외 결과 모델과 다르면 `site_if_model_differs`도)만
  돌린다. 나머지는 사외 결과 기록(`offsite_results.json`, 점검 `s2.offsite`)으로 갈음한다.
- 새로 만들 때 트래커는 jira다(사내 결정: S30·S31 GitHub 트래커 항목은 해당 없음, S-3에서 `tracker.kind: jira`).
- 사외 초안 PC(`.local-draft`)에서는 SITE_PROFILE.md를 만들지 않는다(종료 2, 반입 전 경계 검사가 막는 파일이다).
- `runtime-check`(계획 I O10, docs/development/RUNTIMES.md)는 단계와 무관하게 환경마다 한 번 돌리는 점검이다(SITE_PROFILE을 읽거나
  쓰지 않는다). 판정은 기존 코드: claude-gateway는 `claude_child.gateway_profile_check`(missing·differs → 1), opencode는
  `opencode/bin/tt-oc`(버전 = PINNED, 없으면 설치 안내·설치한 opencode.json 필수 설정·opencode가 있으면 사전 점검 전체)와
  `gen_opencode.managed_problems`(/etc/opencode, 없으면 warn). 사내 확인 0(게이트웨이 curl — claude-gateway는 Anthropic `/v1/messages`,
  opencode는 OpenAI 호환 `/models`·`/chat/completions`)은 명령만 보인다(실행하지 않는다).

종료 코드: 0 정상(점검은 통과·정보만), 1 점검 실패·건너뜀·사용자 필요(`--done` 거부 포함, runtime-check의 missing·differs·fail 행),
2 사용 오류(사외 PC, 모드·단계 불일치, 진행 상태 줄 없음,
S-3 완료 전 `ofono`·`modules`, 시작 전 O-n·MS-n, runtime-check 대상이 claude-gateway·opencode가 아님, `modules` 뒤 인자가
check·coverage가 아님, `audit`의 잘못된 --since·기록 없는 --last·계획 없는(낡은) --record).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True    # 사내 레포에 __pycache__를 남기지 않는다(아래 import 전)

import argparse  # noqa: E402
import difflib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
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
MODULE_STEPS = ["MS-1", "MS-2"]
MODULE_CURRENT_RE = re.compile(r"(?m)^- 모듈 단계: *(\S+).*$")
MODULE_FINISHED_RE = re.compile(r"(?m)^- 모듈 완료: *(.*)$")
MODULE_NOT_STARTED = "모듈 스킬 트랙이 시작되지 않았다 — S-3 완료 뒤 `python3 tools/site_step.py modules`"
MODULE_SUBS = ("check", "coverage")
# §15.5에 MS 행이 없을 때의 안내(MODULE_SKILLS_PLAN_IMPL §6). 15-local-draft.md에 행이 생기면 그것을 쓴다
MODULE_GUIDE = {
    "MS-1": """MS-1 모듈 스킬 레포 연결 (MODULE_SKILLS_PLAN_IMPL §6·docs/SITE_INSTALL.md §10)
1. **주소를 넣기 전에** 설치 분석 스킬이 연결된 카테고리(예: analyzers.data.skill)에 `prefer: skill`을 적을지 정한다(ms1.prefer).
2. `tools/make_module_repo.py`로 GHE module-skills 레포를 만들고 브랜치 보호(IMPL §4.5)를 켠다(관리자).
3. site-defaults `module_skills.remote`·`base_branch`·`boundary.patterns`(S33·S34), git ≥ 2.25.
4. `site_step.py modules check` — remote 도달·push 권한·트리 = modules.yaml·데몬 ⊆ tags.yaml·prefer·보호/CI(정보).
5. 세션 안 중첩 `claude -p`는 ms1.nested_claude가 보인 명령을 사용자가 한 번 돌린다(토큰, 승인 뒤).
6. `site_step.py modules coverage` — 사내 로그로 빈 이름을 찾아 modules.yaml diff(모듈 레포 PR)·tags.yaml(계획 op PR, 사용자 확인).""",
    "MS-2": """MS-2 사내 스킬 합치기(선택)·정기 점검 (MODULE_SKILLS_PLAN_IMPL §6, 결정 기록 11/05 ③)
1. (선택) 사내 Android 분석 스킬을 `android/<m>/`에 합친다(텍스트 절차만). 합치기 전에는 `prefer: skill`로 그대로 쓴다.
2. (선택) `module_eval.py`를 S-5 라벨셋(마스킹, tests/site/module-evals/)에 소수로 — 비용 승인 뒤.
3. 정기 점검(매주, 상한 300,000 토큰): `site_step.py audit` → 사내 Claude 리뷰(review.md) → `audit --record`.""",
}
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


def _module_state(text: str) -> tuple[str | None, str]:
    """(모듈 단계 | None = 트랙 시작 전, 완료 값). 두 줄 중 하나만 있거나 모르는 단계면 사용 오류."""
    cur, fin = MODULE_CURRENT_RE.search(text), MODULE_FINISHED_RE.search(text)
    if not cur and not fin:
        return None, ""
    if not cur or not fin:
        raise Usage("SITE_PROFILE.md '진행 상태'에 `- 모듈 단계: MS-n`·`- 모듈 완료: …` 줄이 하나만 있다 — 14-site.md §14.3 형식으로 고친다")
    step = cur.group(1)
    if step not in MODULE_STEPS + [DONE]:
        raise Usage(f"모듈 단계 '{step}'를 모른다 (순서: {' → '.join(MODULE_STEPS)})")
    return step, fin.group(1).strip()


def _module_current(text: str) -> str:
    _state(text)
    cur, _ = _module_state(text)
    if cur is None:
        raise Usage(MODULE_NOT_STARTED)
    return cur


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
        if step == DONE:                               # Android가 끝났으면 진행 중인 oFono 단계(없으면 모듈 단계)
            o_cur, _ = _ofono_state(text)
            m_cur, _ = _module_state(text)
            step = o_cur if o_cur not in (None, DONE) else (m_cur if m_cur not in (None, DONE) else step)
    if step.startswith("MS-"):
        if step not in MODULE_STEPS:
            raise Usage(f"모듈 단계 '{step}'를 모른다 (순서: {' → '.join(MODULE_STEPS)})")
        _module_current(_profile_text(root))
        return step
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


MODULE_LOOP = """===== 진행 (한 단계씩, 확인 전에는 다음 단계로 가지 않는다) =====
1. 할 일을 한다. 막히면(충돌·인증·권한·버전 불일치) 우회하지 않고 보고한다.
2. `python3 tools/site_step.py modules check` — 자동 점검(읽기 전용, 모듈 레포는 임시 clone). 실패·건너뜀·사용자 필요는 그대로 보고한다.
3. `python3 tools/site_step.py modules coverage` / `audit` — 토큰 0. 토큰을 쓰는 명령은 보이기만 한다(사용자 승인 뒤 실행).
4. 요약 → **사용자 확인** → `python3 tools/site_step.py --done {step}` (사용자가 확인한 건너뜀·사용자 필요만 `--waive 점검="사유"`)."""


def _module_body(step: str) -> str:
    row = context_pack.step_row(step)
    if row:
        return f"===== {context_pack.STEPS} §15.5 {step} =====\n{row}\n"
    return f"===== {step} (내장 안내 — §15.5에 MS 행 없음) =====\n{MODULE_GUIDE[step]}\n"


def guide(step: str, created: bool, root: Path | None = None, allow_api: bool = False, ofono: bool = False,
          started: bool = False, module: bool = False) -> tuple[str, int]:
    """(출력, 종료 코드 = 점검 결과의 exit_code). root가 없으면 점검 없이 pack만(종료 0). `ofono`면 oFono 트랙 단계,
    `module`이면 모듈 스킬 트랙 단계."""
    if module:
        return _module_guide(step, root, allow_api, started)
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


def _module_guide(step: str, root: Path | None, allow_api: bool, started: bool) -> tuple[str, int]:
    if step == DONE:
        return "모듈 스킬 트랙 MS-1~MS-2가 모두 완료로 기록돼 있다. 정기 점검은 계속: `python3 tools/site_step.py audit`(매주).", 0
    head = [("모듈 스킬 트랙을 시작했다. " if started else "") + f"모듈 스킬 트랙 지금 단계: {step}",
            f"이 단계를 마치면: `site_step.py modules check` 보고 → 요약 → 사용자 확인 → `python3 tools/site_step.py --done {step}` "
            "(확인 전에는 다음 단계로 가지 않는다)", ""]
    if root is None:
        return "\n".join(head) + _module_body(step), 0
    results = sc.run_checks(step, root, allow_api)
    write_step_state(root, step, results, visited=True)
    return "\n".join([*head, _module_body(step), sc.report(step, results), "", asks(results), "",
                      MODULE_LOOP.format(step=step)]), sc.exit_code(results)


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
    m_cur, _ = _module_state(text)
    if step == DONE and o_cur in (None, DONE) and m_cur not in (None, DONE):
        return guide(m_cur, created, root, allow_api, module=True)
    out, code = guide(step, created, root, allow_api)
    if o_cur is not None:                              # 시작 전이면 출력은 그대로다
        out += "\n" + ("oFono 트랙: 완료" if o_cur == DONE else f"oFono 트랙: {o_cur} 진행 중 → python3 tools/site_step.py ofono")
    if m_cur is not None:
        out += "\n" + ("모듈 스킬 트랙: 완료" if m_cur == DONE else
                       f"모듈 스킬 트랙: {m_cur} 진행 중 → python3 tools/site_step.py modules")
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


def modules_cmd(root: Path, sub: str | None, allow_api: bool = False, as_json: bool = False, out: str | None = None,
                min_lines: int | None = None) -> tuple[str, int]:
    """모듈 스킬 트랙 시작·이어 하기(`sub` 없음), 지금 MS 단계 점검(`check`), 사내 로그 coverage(`coverage`)."""
    if sub is not None and sub not in MODULE_SUBS:
        raise Usage(f"modules 뒤에는 {' | '.join(MODULE_SUBS)}만 온다: {sub}")
    prof = _profile(root)
    text = _profile_text(root)
    cur, fin = _state(text)
    m_cur, _ = _module_state(text)
    if sub == "coverage":
        return coverage_cmd(root, as_json, out, min_lines)
    if sub == "check":
        if m_cur is None:
            raise Usage(MODULE_NOT_STARTED)
        if m_cur == DONE:
            return "모듈 스킬 트랙 MS-1~MS-2가 모두 완료로 기록돼 있다(점검은 `check MS-n`).", 0
        return check(root, m_cur, as_json, allow_api)
    started = m_cur is None
    if started:
        if not S3_DONE_RE.search(fin):
            raise Usage(f"모듈 스킬 트랙은 S-3 완료 기록 뒤에 시작한다(site-defaults.yaml 필요) — 지금 Android 단계 {cur}")
        text = _insert_progress(text, "- 모듈 단계: MS-1", MODULE_CURRENT_RE.pattern)
        text = _insert_progress(text, "- 모듈 완료: (없음)", MODULE_FINISHED_RE.pattern)
        prof.write_text(text, encoding="utf-8", newline="\n")
        m_cur = MODULE_STEPS[0]
    return guide(m_cur, False, root, allow_api, module=True, started=started)


def coverage_cmd(root: Path, as_json: bool, out: str | None, min_lines: int | None) -> tuple[str, int]:
    """`modules coverage`: 사내 입력(steps.yaml 로그 폴더·이슈 DB clone, 모듈 레포 임시 clone)으로 module_coverage. 사내 전용 출력."""
    import module_coverage as mc

    n = mc.MIN_LINES if min_lines is None else max(1, min_lines)
    ctx = sc.Ctx(root)
    try:
        if not sc.module_settings(ctx)["ms"]:
            return "modules coverage: module_skills.remote 없음 — `modules check`의 ms1.config", 1
        try:
            result = mc.run_site(ctx, min_lines=n)
        except sc.ModuleCloneError as exc:
            return f"modules coverage: 모듈 레포 임시 clone 실패 — {exc}", 1
    finally:
        ctx.cleanup()
    code = mc.exit_code(result, n) if result["platforms"] else 1
    written = ""
    if out and result["suggestion"]["diff"]:
        dst = Path(out) if Path(out).is_absolute() else root / out
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(result["suggestion"]["diff"], encoding="utf-8", newline="\n")
        written = f"\nmodules.yaml 제안 diff를 썼다: {dst}"
    if as_json:
        return json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True), code
    return mc.render(result) + written, code


def audit_cmd(root: Path, args) -> tuple[str, int]:
    import site_audit

    _profile_text(root)                                # 사외 PC·SITE_PROFILE 없음은 사용 오류
    try:
        if args.record:
            return site_audit.record(root, args.defer), 0
        if args.notify:
            p = site_audit.load_plan(root)
            ctx = sc.Ctx(root)
            try:
                res = site_audit.notify(ctx, p, create=args.create)
            finally:
                ctx.cleanup()
            if args.json:
                return json.dumps(res, ensure_ascii=False, indent=1), res["exit"]
            return site_audit.render_notify(res), res["exit"]
        ctx = sc.Ctx(root)
        try:
            p = site_audit.plan(ctx, since=args.since, last=args.last, repos=args.repo, cap=args.cap_tokens,
                                inhouse=args.inhouse_model, jobs=args.jobs)
        finally:
            ctx.cleanup()
    except site_audit.AuditUsage as exc:
        raise Usage(str(exc)) from None
    files = site_audit.write_plan(root, p)
    if args.json:
        return json.dumps(p, ensure_ascii=False, indent=1), p["exit"]
    return site_audit.render(p) + f"\n(썼다: {', '.join(files)})", p["exit"]


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
    rx = re.compile(core if core.endswith("$") else core + ".*$", re.MULTILINE)
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
    module = step.startswith("MS-")
    if module:
        cur = _module_current(text)
        fin = _module_state(text)[1]
        track, cur_re, fin_re, label = MODULE_STEPS, MODULE_CURRENT_RE, MODULE_FINISHED_RE, "모듈 "
    elif ofono:
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
    cur_word, fin_word = ("모듈 단계", "모듈 완료") if module else (("oFono 단계", "oFono 완료") if ofono else ("현재 단계", "완료 단계"))
    text = cur_re.sub(lambda m: f"- {cur_word}: {nxt}", text, count=1)
    text = fin_re.sub(lambda m: f"- {fin_word}: {fin}", text, count=1)
    prof.write_text(text, encoding="utf-8", newline="\n")
    extra = f" (면제 {', '.join(used)} — 사유는 SITE_PROFILE.md 설계 변경)" if used else ""
    out, _ = guide(nxt, False, root, allow_api, ofono=ofono, module=module)     # 기록은 끝났다(종료 0). 다음 단계 점검 결과는 출력으로만 본다
    shown = "".join(f"  SITE_PROFILE.md 설계 변경에 기록: {line}\n" for line in recorded)     # 쓴 줄을 그대로 보인다
    return f"{step} 완료를 기록했다{extra}.\n" + shown + out, 0


# -- 런타임 점검 (계획 I O10, docs/development/RUNTIMES.md) ----------------------------------------------------------
# 모델·네트워크를 부르지 않는다(사내 토큰 최소). 판정은 기존 코드에 맡긴다: claude-gateway는 `common.claude_child`
# `gateway_profile_check`, opencode는 `opencode/bin/tt-oc`의 `version_row`·`config_problems`·`preflight`와
# `tools/gen_opencode.py` `managed_problems`.

RUNTIMES = ("claude-gateway", "opencode")
RUNTIME_FAIL = ("missing", "differs", "fail")
CHECK0_BODY = ('{"model":"\'"$MODEL"\'","max_tokens":128,"stream":true,'
               '"tools":[{"name":"get_time","description":"현재 시각","input_schema":{"type":"object","properties":{}}}],'
               '"tool_choice":{"type":"tool","name":"get_time"},"messages":[{"role":"user","content":"지금 몇 시?"}]}')


def check0_text() -> str:
    """사내 확인 0(게이트웨이 `/v1/messages` 스트리밍 tool_use) — 사용자가 직접 실행할 curl 명령(여기서는 실행하지 않는다)."""
    return "\n".join([
        "사내 확인 0 — 게이트웨이 /v1/messages 스트리밍 tool_use (이 도구는 실행하지 않는다, 사용자가 터미널에서 한 번):",
        "```sh",
        "GW=<게이트웨이 주소(/v1 앞까지)>; KEY=<게이트웨이 키>; MODEL=<사내 모델 ID>",
        'curl -sS -N "$GW/v1/messages" -H "content-type: application/json" -H "anthropic-version: 2023-06-01" \\',
        '  -H "x-api-key: $KEY" -H "authorization: Bearer $KEY" \\',
        f"  -d '{CHECK0_BODY}'",
        "```",
        '통과: `event: content_block_start`에 `"type":"tool_use"`, 이어서 `input_json_delta`, 끝에 `message_stop`. '
        "결과(통과/실패와 첫 오류 줄 — 키는 빼고)를 보고한다.",
    ])


OC_CHECK0_BODY = ('{"model":"\'"$MODEL"\'","max_tokens":64,"stream":true,'
                  '"tools":[{"type":"function","function":{"name":"get_time","description":"현재 시각",'
                  '"parameters":{"type":"object","properties":{}}}}],'
                  '"tool_choice":{"type":"function","function":{"name":"get_time"}},'
                  '"messages":[{"role":"user","content":"지금 몇 시?"}]}')
_SHELL_BAD = "'\"$`\\ \n"


def _oc_gateway(proj: Path | None) -> tuple[str, str]:
    """설치한 opencode.json의 provider baseURL·모델 ID(비밀 아님). 없거나 읽지 못하면 자리표시."""
    base, model = "<게이트웨이 URL(/v1까지, install --gateway-url)>", "<사내 모델 ID>"
    if proj is None:
        return base, model
    try:
        cfg = json.loads((proj / "opencode.json").read_text(encoding="utf-8"))
        prov_id, _, mid = str(cfg.get("model") or "").partition("/")
        url = (((cfg.get("provider") or {}).get(prov_id) or {}).get("options") or {}).get("baseURL")
    except (OSError, ValueError, AttributeError):
        return base, model
    if isinstance(url, str) and url.startswith(("http://", "https://")) and not any(c in url for c in _SHELL_BAD):
        base = url.rstrip("/")
    if mid and "@@" not in mid and not any(c in mid for c in _SHELL_BAD):
        model = mid
    return base, model


def oc_check0_text(proj: Path | None) -> str:
    """OpenCode용 사내 확인 0 — OpenAI 호환(`@ai-sdk/openai-compatible`) 모양 curl 명령(실행하지 않는다).
    키는 `$TT_GATEWAY_API_KEY` 이름만 쓴다."""
    base, model = _oc_gateway(proj)
    return "\n".join([
        "사내 확인 0(OpenCode) — 게이트웨이 OpenAI 호환 엔드포인트 (이 도구는 실행하지 않는다, 사용자가 터미널에서 한 번):",
        "```sh",
        f"BASE='{base}'; MODEL='{model}'   # 키: export TT_GATEWAY_API_KEY=… (출력·파일에 적지 않는다)",
        "# (a) 토큰 0: 모델 목록에 $MODEL이 있는지",
        'curl -sS "$BASE/models" -H "authorization: Bearer $TT_GATEWAY_API_KEY"',
        "# (b) 선택(토큰 소량): 스트리밍 tool_calls",
        'curl -sS -N "$BASE/chat/completions" -H "content-type: application/json" \\',
        '  -H "authorization: Bearer $TT_GATEWAY_API_KEY" \\',
        f"  -d '{OC_CHECK0_BODY}'",
        "```",
        '통과: (a) `"data"`에 `"id":"<MODEL>"`, (b) `data:` 줄 `delta`에 `"tool_calls"`(이름 `get_time`), 끝에 `data: [DONE]`. '
        "결과(통과/실패와 첫 오류 줄 — 키는 빼고)를 보고한다. Anthropic 모양(/v1/messages)은 Claude Code용이다.",
    ])


def _runtime_table(title: str, rows: list[dict]) -> str:
    cell = lambda t: str(t).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines = [title, "", "| 항목 | 상태 | 내용 |", "|---|---|---|"]
    lines += [f"| {r.get('key') or r.get('check')} | {r['status']} | {cell(r['detail'])} |" for r in rows]
    return "\n".join(lines)


def _runtime_result(rows: list[dict], fix: str) -> tuple[str, int]:
    bad = [str(r.get("key") or r.get("check")) for r in rows if r["status"] in RUNTIME_FAIL]
    if bad:
        return f"결과: 실패 {len(bad)}행({', '.join(bad)}) — {fix}", 1
    return "결과: 통과(warn·info 행은 막지 않는다)", 0


def _scripts_on_path() -> None:
    p = str(ROOT / "plugin" / "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)


GATEWAY_SCOPE = ("재는 것: 환경 변수·자격 이름, claude CLI 버전, 설치본 hooks.json, S1 기록(tracker.isolation_confirmed). "
                 "안 재는 것: 게이트웨이 프로토콜·모델 응답·hook 실제 동작·must_show — 사내 확인 0·2·3·5가 확정한다")


def gateway_site_rows(env: dict) -> list[dict]:
    """토큰 0 추가 행(종합 리뷰 F: 이전에는 환경 변수 비교만이라 '종료 0 = 환경이 된다'로 읽혔다). 모두 ok·warn·info — 종료 코드에는
    영향이 없다(전제 확정은 사내 확인). `claude --version`은 모델·네트워크를 부르지 않는다."""
    _scripts_on_path()
    from common import site_defaults, userconfig

    rows: list[dict] = []
    exe = shutil.which("claude", path=env.get("PATH"))
    if not exe:
        rows.append({"key": "claude_cli", "status": "warn", "detail": "PATH에 claude 없음 — Claude Code를 쓰는 터미널에서 다시 실행"})
    else:
        try:
            proc = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=20, env=env)
            text = (proc.stdout or proc.stderr or "").strip().splitlines()
            ver = text[0][:80] if text else ""
            rows.append({"key": "claude_cli", "status": "ok" if proc.returncode == 0 and ver else "warn",
                         "detail": ver or f"--version 종료 {proc.returncode}"})
        except (OSError, subprocess.TimeoutExpired) as exc:
            rows.append({"key": "claude_cli", "status": "warn", "detail": f"--version 실행 실패({type(exc).__name__})"})
    user = userconfig.load_user() or {}
    scripts_path = userconfig.get(user, "plugin.scripts_path")
    hooks = Path(str(scripts_path)).expanduser().parent / "hooks" / "hooks.json" if scripts_path else None
    if hooks is None or not hooks.is_file():
        rows.append({"key": "plugin_hooks", "status": "warn",
                     "detail": "설치본 hooks.json 없음(setup 전이거나 plugin.scripts_path 불일치) — /telephony-triage:setup 뒤 다시"})
    else:
        try:
            data = json.loads(hooks.read_text(encoding="utf-8"))
            groups = data.get("hooks", data) if isinstance(data, dict) else {}
            n = sum(len(v) for v in groups.values() if isinstance(v, list))
            rows.append({"key": "plugin_hooks", "status": "ok" if n else "warn",
                         "detail": f"{hooks} — 이벤트 {', '.join(groups)} (matcher {n}개). 실제 로드 여부는 사내 확인 5"})
        except (OSError, ValueError, AttributeError) as exc:
            rows.append({"key": "plugin_hooks", "status": "warn", "detail": f"hooks.json 읽기 실패({type(exc).__name__})"})
    try:
        defaults = site_defaults.load(ROOT / "plugin")
        confirmed = userconfig.get(defaults, "tracker.isolation_confirmed")
        rows.append({"key": "isolation_confirmed", "status": "ok" if confirmed is True else "info",
                     "detail": "S1 기록됨 — Jira 읽기 결과 격리 확인" if confirmed is True
                     else "미기록 — S1 확인 전에는 guard가 Jira 읽기마다 묻는다(site-defaults tracker.isolation_confirmed)"})
    except site_defaults.SiteDefaultsMissing:
        rows.append({"key": "isolation_confirmed", "status": "info", "detail": "plugin/site-defaults.yaml 없음(S-3 전)"})
    return rows


def runtime_claude_gateway(env: dict) -> tuple[str, int]:
    """Claude Code + 사내 모델(게이트웨이) 프로필: `claude_child.gateway_profile_check` 표 + 토큰 0 추가 행(`gateway_site_rows`),
    missing·differs가 있으면 1."""
    _scripts_on_path()
    from common import claude_child

    rows = claude_child.gateway_profile_check(env) + gateway_site_rows(env)
    result, code = _runtime_result(rows, "사용자 settings.json env(또는 환경 변수)를 고친 뒤 다시 실행한다")
    title = ("런타임 점검 claude-gateway — 모델 호출 없음(프로세스 환경 + 사용자 settings.json env, 비밀 값은 적지 않는다). "
             + GATEWAY_SCOPE)
    return "\n\n".join([_runtime_table(title, rows), result, check0_text()]), code


def _load_tt_oc():
    from importlib.machinery import SourceFileLoader
    import importlib.util

    loader = SourceFileLoader("tt_oc", str(ROOT / "opencode" / "bin" / "tt-oc"))
    spec = importlib.util.spec_from_loader("tt_oc", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _managed_row(managed_dir: Path) -> dict:
    import gen_opencode

    found = [managed_dir / n for n in gen_opencode.MANAGED_NAMES if (managed_dir / n).is_file()]
    if not found:
        return {"check": "managed-config", "status": "warn",
                "detail": f"{managed_dir}/opencode.json 없음 — 관리자 배포 권장(opencode/managed.json.sample, 다중 방어)"}
    _scripts_on_path()
    from common import oc_adapter

    try:
        cfg = json.loads(oc_adapter._strip_jsonc(found[0].read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        return {"check": "managed-config", "status": "fail", "detail": f"{found[0]} 읽기 실패: {type(exc).__name__}"}
    wrong = gen_opencode.managed_problems(cfg)
    if wrong:
        return {"check": "managed-config", "status": "fail",
                "detail": f"{found[0]}: " + ", ".join(wrong[:6]) + (f" 외 {len(wrong) - 6}" if len(wrong) > 6 else "")
                          + " — opencode/managed.json.sample과 맞춘다(관리자)"}
    return {"check": "managed-config", "status": "ok", "detail": f"{found[0]}: managed.json.sample의 막는 항목 모두 있음"}


def runtime_opencode(project: str | None, opencode: str, managed_dir: Path, env: dict) -> tuple[str, int]:
    """OpenCode v1: 버전(= tt-oc PINNED, 없으면 설치 안내), 설치한 opencode.json의 v1 필수 설정(snapshot:false 등), opencode가
    있으면 `tt-oc` 사전 점검 전체(합쳐진 실제 설정·지문·지시 파일·config.py doctor), 관리 설정(/etc/opencode). 사내 확인 0은
    명령만 보인다."""
    tt = _load_tt_oc()
    oc = shutil.which(opencode, path=env.get("PATH"))
    rows: list[dict] = []
    if not oc:
        rows.append({"check": "opencode-version", "status": "fail",
                     "detail": f"opencode 없음 — OpenCode {tt.PINNED}를 설치한다(예: npm install -g opencode-ai@{tt.PINNED}, "
                               "사내 설치 경로는 관리자). 다른 버전은 쓰지 않는다"})
    raw = project or env.get("TT_OC_PROJECT")
    proj = meta = None
    if raw:
        try:
            proj, meta = tt.load_project(raw)
        except tt.Refused as exc:
            rows.append({"check": "project", "status": "fail", "detail": str(exc)})
    else:
        rows.append({"check": "project", "status": "fail",
                     "detail": "OpenCode 프로젝트 폴더 없음 — tools/gen_opencode.py install --dest <git 밖 폴더> … 뒤 "
                               "--project <폴더>(또는 TT_OC_PROJECT)로 다시 실행"})
    if proj is not None:
        try:
            wrong = tt.config_problems(json.loads((proj / "opencode.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, AttributeError) as exc:
            wrong = [f"읽기 실패({type(exc).__name__})"]
        rows.append({"check": "installed-config", "status": "fail" if wrong else "ok",
                     "detail": ("설정 불일치: " + ", ".join(wrong) + " — gen_opencode.py install --force") if wrong
                     else f"{proj / 'opencode.json'}: snapshot:false·share:disabled·autoupdate:false·허용 목록·task deny"})
        if oc:
            rows += tt.preflight(oc, proj, meta, tt.child_env(meta))
    elif oc:
        rows.append(tt.version_row(oc, env)[0])
    rows.append(_managed_row(managed_dir))
    result, code = _runtime_result(rows, "행의 안내대로 고친 뒤 다시 실행한다(버전 불일치·설정 우회는 하지 않고 보고)")
    title = f"런타임 점검 opencode — 모델 호출 없음(고정 {tt.PINNED})"
    return "\n\n".join([_runtime_table(title, rows), result, oc_check0_text(proj)]), code


def runtime_opencode_jira(project: str | None, opencode: str, key: str, missing: str | None, env: dict) -> tuple[str, int]:
    """OpenCode Jira 읽기 사내 확인(`tools/oc_jira_check.py`): 가짜 모델 서버로 실제 opencode·실제 Jira MCP를 거쳐 있는 티켓·없는
    티켓을 읽고 모델이 받은 글을 본다. 통과 기록을 쓰고 관문을 여는 명령을 보인다(열지는 않는다)."""
    _scripts_on_path()
    import oc_jira_check

    return oc_jira_check.check(_load_tt_oc(), project, opencode, key, missing, env)


def runtime_check(target: str | None, project: str | None, managed_dir: Path, jira: str | None = None,
                  missing_key: str | None = None) -> tuple[str, int]:
    if target not in RUNTIMES:
        raise Usage(f"runtime-check 대상은 {' | '.join(RUNTIMES)}: {target or '(없음)'}")
    if (jira or missing_key) and target != "opencode":
        raise Usage("--jira·--missing-key는 runtime-check opencode에서만 쓴다")
    if missing_key and not jira:
        raise Usage("--missing-key는 --jira와 함께 쓴다")
    env = dict(os.environ)
    if target == "claude-gateway":
        return runtime_claude_gateway(env)
    if jira:
        return runtime_opencode_jira(project, env.get("TT_OPENCODE") or "opencode", jira, missing_key, env)
    return runtime_opencode(project, env.get("TT_OPENCODE") or "opencode", managed_dir, env)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="site_step.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=("check", "propose", "evals", "ofono", "modules", "audit", "runtime-check"),
                    help="없으면 시작·이어 하기. ofono: oFono 트랙(O-1~O-4) 시작·이어 하기(S-3 완료 뒤). modules: 모듈 스킬 트랙"
                         "(MS-1~MS-2, S-3 완료 뒤). audit: 정기 점검(토큰 0 검사·시그니처 소실 + Claude가 볼 것, Claude는 부르지 않는다). "
                         "runtime-check: claude-gateway|opencode 런타임 점검(모델·네트워크 호출 없음)")
    ap.add_argument("step", nargs="?", metavar="S-n|O-n|MS-n",
                    help="check·propose 대상 단계(기본: 현재 단계). runtime-check면 claude-gateway|opencode, "
                         "modules면 check|coverage")
    ap.add_argument("--project", help="runtime-check opencode: gen_opencode.py install --dest 폴더(기본: TT_OC_PROJECT)")
    ap.add_argument("--jira", metavar="KEY", help="runtime-check opencode: Jira 읽기 사내 확인 — 있는 티켓 키(모델 토큰 0)")
    ap.add_argument("--missing-key", metavar="KEY", help="runtime-check opencode --jira: 오류 경로용 없는 티켓 키")
    ap.add_argument("--done", metavar="S-n|O-n|MS-n", help="사용자 확인을 받은 현재 단계: 점검 재실행 → 통과면 완료 기록·다음 단계")
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
    ap.add_argument("--out", help="modules coverage: modules.yaml 제안 diff를 쓸 파일(상대 경로는 레포 기준)")
    ap.add_argument("--min-lines", type=int, default=None, help="modules coverage: 제안·알림 줄 수 기준(기본 20)")
    ap.add_argument("--since", action="append", default=[], metavar="YYYY-MM-DD|레포=sha", help="audit: 창 시작")
    ap.add_argument("--last", action="store_true", help="audit: 기록된 지난 점검부터(기본과 같다, 기록이 없으면 사용 오류)")
    ap.add_argument("--repo", action="append", default=[], metavar="ops_db|ofono_db|modules", help="audit: 볼 레포만")
    ap.add_argument("--cap-tokens", type=int, default=None, help="audit: 점검 한 번의 Claude 토큰 상한(기본 300000)")
    ap.add_argument("--inhouse-model", action="append", default=[], metavar="정규식", help="audit: 사내 모델 ID 정규식")
    ap.add_argument("--jobs", help="audit: 근거 원문 검사 기록을 찾을 work_dir(기본: 사용자 config work_dir)")
    ap.add_argument("--record", action="store_true", help="audit: 마지막 계획의 끝 커밋을 기준점으로 기록")
    ap.add_argument("--defer", action="append", default=[], metavar="ID[,ID]", help="audit --record: 다음 점검으로 미룰 항목")
    ap.add_argument("--notify", action="store_true", help="audit: 마지막 계획의 P0·P1 항목·실패 검사 행을 이슈 DB 레포 Issue로(기본 보기만)")
    ap.add_argument("--create", action="store_true", help="audit --notify: 실제로 만든다(사용자 확인 뒤). 열린 같은 표식 Issue는 건너뜀")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)   # 테스트용
    ap.add_argument("--managed-dir", default=None, help=argparse.SUPPRESS)  # 테스트용(기본 gen_opencode.MANAGED_DIR)
    args = ap.parse_args(argv)
    if args.done and args.cmd:
        ap.error("--done은 단독으로 쓴다")
    if args.waive and not args.done:
        ap.error("--waive는 --done과 함께 쓴다")
    if (args.set or args.apply) and args.cmd != "propose":
        ap.error("--set·--apply는 propose에서만 쓴다")
    if args.cmd == "ofono" and args.step:
        ap.error("ofono는 단계 인자를 받지 않는다(지금 oFono 단계부터)")
    if (args.project or args.managed_dir) and args.cmd != "runtime-check":
        ap.error("--project는 runtime-check에서만 쓴다")
    window_opts = args.since or args.last or args.repo or args.cap_tokens is not None or args.inhouse_model or args.jobs
    if (window_opts or args.record or args.defer or args.notify or args.create) and args.cmd != "audit":
        ap.error("--since·--last·--repo·--cap-tokens·--inhouse-model·--jobs·--record·--defer·--notify·--create는 audit에서만 쓴다")
    if args.cmd == "audit":
        if args.step:
            ap.error("audit는 단계 인자를 받지 않는다")
        if args.defer and not args.record:
            ap.error("--defer는 --record와 함께 쓴다")
        if args.record and (window_opts or args.notify):
            ap.error("--record는 --defer만 함께 쓴다")
        if args.create and not args.notify:
            ap.error("--create는 --notify와 함께 쓴다")
        if args.notify and (window_opts or args.defer):
            ap.error("--notify는 --create·--json만 함께 쓴다")
        if args.cap_tokens is not None and args.cap_tokens <= 0:
            ap.error("--cap-tokens는 0보다 크다")
    if (args.out or args.min_lines is not None) and not (args.cmd == "modules" and args.step == "coverage"):
        ap.error("--out·--min-lines는 modules coverage에서만 쓴다")
    if (args.jira or args.missing_key) and args.cmd != "runtime-check":
        ap.error("--jira·--missing-key는 runtime-check opencode에서만 쓴다")
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
        elif args.cmd == "modules":
            out, code = modules_cmd(root, args.step, args.allow_api, args.json, args.out, args.min_lines)
        elif args.cmd == "audit":
            import site_audit
            if args.cap_tokens is None:
                args.cap_tokens = site_audit.AUDIT_CAP_TOKENS
            out, code = audit_cmd(root, args)
        elif args.cmd == "runtime-check":
            import gen_opencode
            out, code = runtime_check(args.step, args.project,
                                      Path(args.managed_dir) if args.managed_dir else gen_opencode.MANAGED_DIR,
                                      args.jira, args.missing_key)
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
