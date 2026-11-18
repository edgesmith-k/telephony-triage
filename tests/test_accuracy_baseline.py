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


def test_generator_output_matches_committed_files():
    result = maf.run(check=True)
    assert not result["missing"] and not result["mismatched"], f"{result} — python3 tests/helpers/make_accuracy_fixtures.py"


def test_baseline_matches_current_code():
    assert BASELINE.is_file(), "baseline.json 없음 — python3 tests/test_accuracy_baseline.py --update"
    assert current() == json.loads(BASELINE.read_text(encoding="utf-8")), \
        "지금 코드의 요약이 기준값과 다르다 — 의도한 변화면 python3 tests/test_accuracy_baseline.py --update 후 diff를 PR에 보인다"


if __name__ == "__main__" and "--update" in sys.argv:
    try:
        BASELINE.write_text(json.dumps(current(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    finally:
        cleanup_tmp()
    print(BASELINE)
