#!/usr/bin/env python3
"""분석 정확도 단계 1 기준값: 조합 로그에서 지금 코드가 무엇을 원인으로 내는지 (`tests/fixtures/accuracy/`).

- 생성기(`tests/helpers/make_accuracy_fixtures.py`) 출력 = 넣어 둔 조합 로그·라벨셋·코멘트.
- 시드 DB(시드 계획 다섯 개)로 라벨셋을 조건별로 돌린 요약 = `baseline.json`. 규칙 동작 확인용 표본 안 자료이고 정확도 수치가
  아니다. 뒤 단계 PR이 판정·순위를 바꾸면 이 파일을 같이 고쳐(`python3 tests/test_accuracy_baseline.py --update`) 숫자 변화가
  diff에 보이게 한다. 포털 열은 환경에 따라 없을 수 있어 넣지 않는다(`offline_eval.py --portal`로 따로 낸다).
- 플러그인 루트는 `runner.plugin_root()`(example 기본값 + 모의 site 백엔드)다. CLI로 같은 표를 내려면 `--plugin-root`로 같은 종류의
  루트를 준다(기본 루트는 사내에서 실제 `plugin/`이라 설정이 다를 수 있다, `tests/fixtures/README.md`).
"""

from __future__ import annotations

import functools
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

import make_accuracy_fixtures as maf  # noqa: E402
from runner import cleanup_tmp, plugin_root, tmp  # noqa: E402

BASELINE = maf.OUT / "baseline.json"
ROW = ("key", "condition", "expect", "top", "top3", "adopted", "verdict", "anchor_ok", "error", "held_why", "held_cause")


def _eval(root: Path, db: Path, *extra: str) -> dict:
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "offline_eval.py"), str(maf.OUT / "labelset.yaml"), "--json",
                           "--db", str(db), "--plugin-root", str(root), *extra],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    return {"by_condition": out["by_condition"], "runs": [{k: r.get(k) for k in ROW} for r in out["items"]]}


def current() -> dict:
    root = plugin_root()     # 명시 루트(SITE_PATHS 제외 복사본) — 사내 레포에서도 같은 결과
    db = maf.build_seed_db(tmp("tt-accuracy-db-") / "db", root)
    out = _eval(root, db)
    # 코멘트 지점 채택을 끈 problem 조건(보고용) — 기본은 사용자 결정 Y1: 허용(`eligibility.comment_adopt: true`)
    out["comment_adopt_off"] = _eval(plugin_root(eligibility={"comment_adopt": False}), db, "--condition", "problem")
    return out


@functools.cache
def _current() -> dict:
    """같은 세션의 두 시험이 offline_eval을 한 번만 돌리게(결과는 읽기만 한다)."""
    return current()


def test_generator_output_matches_committed_files():
    result = maf.run(check=True)
    assert not result["missing"] and not result["mismatched"], f"{result} — python3 tests/helpers/make_accuracy_fixtures.py"


def test_baseline_matches_current_code():
    assert BASELINE.is_file(), "baseline.json 없음 — python3 tests/test_accuracy_baseline.py --update"
    assert _current() == json.loads(BASELINE.read_text(encoding="utf-8")), \
        "지금 코드의 요약이 기준값과 다르다 — 의도한 변화면 python3 tests/test_accuracy_baseline.py --update 후 diff를 PR에 보인다"


STAGE5_CORRECT = ["C15-1", "CTLM-1", "D12R-1", "HAL-1", "MMH-1", "PAIRFAIL-1", "RECOVER-1", "TOKONLYPOS-1", "TOKPOS-1"]
R1_CORRECT = ["TPEVAL-1", "TPRERR-1", "TPVRF-1"]      # R1 양성(problem.json 없음 — look_at+problem 조건 밖)


def test_stage5_holds_without_reference_and_adopts_only_eligible():
    """단계 4·5-1 완료 기준: 기준(실패 지점)이 없는 no_time·time 조건은 채택 0(전부 보류, 사유 기록). 기준 줄이 있는 look_at은
    자격 검사를 통과한 것만 채택한다 — 틀린 채택 0, 단계 4의 맞는 채택 7건(이름 그대로) + 새 양성 token 점 2건 + R1 양성 3건
    (TPRERR·TPEVAL·TPVRF), R1 음성(CPX·CPXD)과 NEARPOS(AP 줄 인용)는 problem.json 없이 보류. 기준값(baseline.json)과 같음은 위 시험이 본다."""
    now = _current()
    runs = {c: [r for r in now["runs"] if r["condition"] == c] for c in ("no_time", "time", "look_at")}
    assert runs["no_time"] and runs["time"] and runs["look_at"]
    assert [r["key"] for c in ("no_time", "time") for r in runs[c] if r["adopted"] is not None] == []
    adopted = [r for r in runs["look_at"] if r["adopted"]]
    assert all(r["adopted"] == r["expect"] for r in adopted), adopted
    assert sorted(r["key"] for r in adopted) == sorted(STAGE5_CORRECT + R1_CORRECT)
    for cond in ("no_time", "time"):
        s = now["by_condition"][cond]
        assert (s["accepted_correct"], s["accepted_wrong"], s["held"]) == (0, 0, s["evaluated"]), (cond, s)
        assert set(s["held_reasons"]) <= {"no_reference", "no_candidate", "cause_unconfirmed", "cause_unjudged"}, s
        assert s["held_reasons"].get("no_reference"), s


def test_stage5_problem_input_answer_upper_bound():
    """단계 5-2 완료 기준(정답 입력 problem.json — 라벨에서 손으로 쓴 것, "정답 입력일 때의 상한"): look_at+problem은 틀린 채택
    0·look_at의 맞는 채택 그대로 + NEARPOS(AP 줄 인용 → 문제 파악 유형으로 근처 사건). problem(기준 줄 없음)은 코멘트 단서만이고
    `eligibility.comment_adopt` 기본(참, Y1 허용)에서 TOKPOS·TOKONLYPOS·CLUEPOS 3건만 맞게 채택(3/0/21). 끈 실행(보고용)은 그 3건이
    ineligible(comment_unconfirmed)로 보류된다."""
    now = _current()
    runs = {c: [r for r in now["runs"] if r["condition"] == c] for c in ("look_at+problem", "problem")}
    adopted = [r for r in runs["look_at+problem"] if r["adopted"]]
    assert all(r["adopted"] == r["expect"] for r in adopted), adopted
    assert sorted(r["key"] for r in adopted) == sorted(STAGE5_CORRECT + ["NEARPOS-1"])
    adopted = [r for r in runs["problem"] if r["adopted"]]
    assert sorted(r["key"] for r in adopted) == ["CLUEPOS-1", "TOKONLYPOS-1", "TOKPOS-1"]
    assert all(r["adopted"] == r["expect"] for r in adopted), adopted
    s = now["by_condition"]["problem"]
    assert (s["accepted_correct"], s["accepted_wrong"], s["held"]) == (3, 0, 21), s
    # 끈 실행: 그 3건은 붙은 사건의 원인이 정답인 채로 보류(comment_unconfirmed)
    off = now["comment_adopt_off"]
    held = [r for r in off["runs"] if r["held_why"] == "comment_unconfirmed"]
    assert sorted(r["key"] for r in held) == ["CLUEPOS-1", "TOKONLYPOS-1", "TOKPOS-1"]
    assert all(r["held_cause"] == r["expect"] for r in held) and not any(r["adopted"] for r in off["runs"]), held


def test_comment_clues_adopt_only_right_and_look_at_turns_them_off():
    """코멘트 단서 자동 추출(모델 없음, issue_file이 있는 항목): comments 조건은 틀린 채택 0, 맞는 채택 TOKPOS·CLUEPOS(token·기준 줄
    없이 코멘트만)이고 재시험 사례(RETEST·RETESTX)는 단서 없음으로 보류. look_at+comments는 자동 추출이 꺼져 항목마다 look_at과
    같다. 실패 지점은 코멘트 출처라 confirmed가 없다(found만)."""
    now = _current()
    s = now["by_condition"]["comments"]
    assert s["accepted_wrong"] == 0 and s["location_confirmed"] == 0, s
    runs = [r for r in now["runs"] if r["condition"] == "comments"]
    assert sorted(r["key"] for r in runs if r["adopted"]) == ["CLUEPOS-1", "TOKPOS-1"]
    assert all(r["adopted"] == r["expect"] for r in runs if r["adopted"])
    assert {r["key"]: r["held_why"] for r in runs if r["key"].startswith("RETEST")} == {"RETEST-1": None, "RETESTX-1": None}
    look = {r["key"]: r for r in now["runs"] if r["condition"] == "look_at"}
    both = [r for r in now["runs"] if r["condition"] == "look_at+comments"]
    assert both and all({k: r[k] for k in ROW if k != "condition"} == {k: look[r["key"]][k] for k in ROW if k != "condition"}
                        for r in both)


if __name__ == "__main__" and "--update" in sys.argv:
    try:
        BASELINE.write_text(json.dumps(current(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    finally:
        cleanup_tmp()
    print(BASELINE)
