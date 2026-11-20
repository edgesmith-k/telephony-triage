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
ROW = ("key", "condition", "expect", "top", "top3", "adopted", "verdict", "anchor_ok", "error")


def current() -> dict:
    root = plugin_root()     # 명시 루트(SITE_PATHS 제외 복사본) — 사내 레포에서도 같은 결과
    db = maf.build_seed_db(tmp("tt-accuracy-db-") / "db", root)
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "offline_eval.py"), str(maf.OUT / "labelset.yaml"), "--json",
                           "--db", str(db), "--plugin-root", str(root)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    return {"by_condition": out["by_condition"], "runs": [{k: r.get(k) for k in ROW} for r in out["items"]]}


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


STAGE5_CORRECT = ["C15-1", "CTLM-1", "D12R-1", "HAL-1", "MMH-1", "PAIRFAIL-1", "RECOVER-1", "TOKONLYPOS-1", "TOKPOS-1",
                  "TPEVAL-1", "TPRERR-1", "TPVRF-1"]


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
    assert sorted(r["key"] for r in adopted) == STAGE5_CORRECT
    for cond in ("no_time", "time"):
        s = now["by_condition"][cond]
        assert (s["accepted_correct"], s["accepted_wrong"], s["held"]) == (0, 0, s["evaluated"]), (cond, s)
        assert set(s["held_reasons"]) <= {"no_reference", "no_candidate", "cause_unconfirmed", "cause_unjudged"}, s
        assert s["held_reasons"].get("no_reference"), s


if __name__ == "__main__" and "--update" in sys.argv:
    try:
        BASELINE.write_text(json.dumps(current(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    finally:
        cleanup_tmp()
    print(BASELINE)
