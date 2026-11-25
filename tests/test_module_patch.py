"""모듈 학습 한 줄 patch·PR — skill_patch.py --module / --pr (반입 7 A-2·A-3, reference/skill-patch.md 모듈 절).

스크립트 이름: skill_patch.py

모델·네트워크 없음. 모듈 레포는 `tests/helpers/module_remote.py`의 file:// bare 원격(템플릿 트리), gh는 스텁.
- 고른 `[모듈]` 줄만(check-output이 남긴 번호) 칸의 절 끝에 한 줄로 들어가고, 근거 줄은 patch에 없고 PR 본문에만 있다.
- 거부: 형식·모르는 칸·검사 안 함·보류의 첫 점검·함정·긴 줄·표 기호·위험 지시·이미 있는 줄·상한.
- --pr: 해시가 같을 때만 `tt-module/<KEY>-<n>` 브랜치·커밋(trailer·출처 키)·push·PR, main ref와 관리 clone은 그대로.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import module_remote as mr  # noqa: E402
from runner import run  # noqa: E402

from common import modulelines, shown  # noqa: E402
import skill_patch  # noqa: E402

KEY = "MOCK-9072"
EXPLORE = "android/data/explore.md"
DEEP = "android/data/deep.md"
TRAP = "AT+CFUN=0 직후 RILJ 끊김 응답은 결과일 뿐이다"
BASIS = "10-01 10:00:01.000 D RILJ: [0001]< DEACTIVATE_DATA_CALL"
LINES = [f"- [모듈] android/data 함정 — {TRAP} — 근거: {BASIS}",                   # 1 남김
         "- [모듈] android/data 함정 — 지어낸 줄 — 근거: 10:00 없는 줄",             # 2 check-output이 뺌
         "- [모듈] android/data 기타 — 모르는 칸 — 근거: x",                         # 3 모르는 칸
         "- [모듈] android/data 판독 주의 — DNC 평가 줄은 요청 하나에 여러 번 찍힌다 — 근거: y",   # 4
         "- [모듈] android/data 버전 차이 — Android 14에서도 data/ 경로 그대로 — 근거: z",       # 5
         "- [모듈] android/data 첫 점검 — 연결 안 됨이면 DNC 평가부터 — 근거: w"]               # 6


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


@pytest.fixture()
def e(tmp_path):
    remote = mr.build(tmp_path / "remote", src=mr.TEMPLATES)
    base = tmp_path / "home"
    work = base / "work"
    job = work / KEY
    job.mkdir(parents=True)
    (base / "config.yaml").write_text(f"work_dir: {work.as_posix()}\nmodule_skills:\n  remote: {remote}\n", encoding="utf-8")
    managed = work / "_module-skills"            # 관리 clone 자리: 읽지도 쓰지도 않는다(바이트 그대로)
    (managed / "android" / "data").mkdir(parents=True)
    (managed / "android" / "data" / "explore.md").write_text("관리 clone 사본\n", encoding="utf-8")
    (job / "analysis.json").write_text(json.dumps({"platform": "android", "decision": {"state": "accepted"}}), encoding="utf-8")
    env = {"TELEPHONY_TRIAGE_HOME": str(base), "MOCK_GH_STATE_DIR": str(tmp_path / "gh"),
           "GIT_AUTHOR_NAME": "Mock", "GIT_AUTHOR_EMAIL": "mock@ghe.mock.invalid",
           "GIT_COMMITTER_NAME": "Mock", "GIT_COMMITTER_EMAIL": "mock@ghe.mock.invalid"}
    d = {"env": env, "base": base, "work": work, "job": job, "managed": managed, "remote_dir": tmp_path / "remote",
         "gh": tmp_path / "gh"}
    explore(d, LINES)
    return d


def explore(d, lines, kept=(1, 4, 5, 6)) -> None:
    data = ("## 가설\n- 가설 1: x\n## 규칙 제안\n" + "\n".join(lines) + "\n").encode("utf-8")
    (d["job"] / "explore-output.md").write_bytes(data)
    rec = {"explore": {"output_sha256": hashlib.sha256(data).hexdigest(), modulelines.KEPT_KEY: list(kept)}}
    (d["job"] / "check-output.json").write_text(json.dumps(rec), encoding="utf-8")


def call(d, *args):
    return run("skill_patch.py", [KEY, *args], env=d["env"])


def module(d, line="1", *extra):
    return call(d, "--module", "--line", line, *extra)


def records(d) -> list[dict]:
    return shown.read_records([d["work"]])


def test_parse_line_numbers_and_slots():
    rows = modulelines.parse("\n".join(LINES + ["- [모듈] 깨진 줄", "- [모듈] ofono/sim 버전 차이 — a — b — 근거: c"]))
    assert [r["n"] for r in rows] == list(range(1, 9))
    assert [r["ok"] for r in rows] == [True, True, False, True, True, True, False, True]
    assert rows[0]["slot"] == "함정" and rows[0]["text"] == TRAP and rows[0]["basis"] == BASIS and rows[0]["doc"] == "explore.md"
    assert rows[7]["text"] == "a — b" and rows[7]["doc"] == "deep.md" and "모르는 칸" in rows[2]["why"]


def test_insert_line_section_end_table_and_new_section():
    text = "# t\n\n## ④ 첫 점검\n\n| a | b |\n|---|---|\n\n## ⑤ 함정\n\n- 하나\n\n### 세부\n- 둘\n"
    out = skill_patch.insert_line(text, "함정", ("함정",), "셋")
    assert out.endswith("- 둘\n- 셋\n")                                   # 하위 절(###)까지가 그 절
    out = skill_patch.insert_line(text, "첫 점검", ("첫 점검",), "셋")
    assert "|---|---|\n\n- 셋\n\n## ⑤ 함정" in out                         # 표 뒤에는 빈 줄을 먼저
    assert skill_patch.insert_line(text, "판독 주의", ("판독 주의",), "셋").endswith("- 둘\n\n## 판독 주의\n\n- 셋\n")
    crlf = text.replace("\n", "\r\n")
    assert skill_patch.insert_line(crlf, "함정", ("함정",), "셋").endswith("- 둘\r\n- 셋\r\n")


def test_module_patch_one_line_at_section_end(e):
    before_main, managed = mr.head(e["remote_dir"]), tree(e["managed"])
    proc = module(e)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    patch = e["job"] / "module-suggestions" / "module.patch"
    text = patch.read_text(encoding="utf-8")
    added = [ln for ln in text.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    assert added == [f"+- {TRAP}"] and text.startswith(f"--- a/{EXPLORE}\n+++ b/{EXPLORE}\n")
    assert "실린 APN이 틀리면 실패다.\n+- " + TRAP in text                     # ⑤ 함정 절의 마지막 줄 뒤
    assert BASIS not in text and "근거" not in "".join(added)                  # 근거 줄은 문서에 넣지 않는다
    out = proc.stdout.splitlines()
    meta = json.loads((e["job"] / "module-suggestions" / "module.meta.json").read_text(encoding="utf-8"))
    assert out[0].startswith("모듈 학습 patch(PR 안 만듦, 마스킹됨): ") and out[0].endswith(f"변경 해시 {meta['sha256']}")
    size = len((e["remote_dir"] / "work" / EXPLORE).read_bytes()) + len(f"- {TRAP}\n".encode())
    assert out[1] == f"- {EXPLORE} +1 −0 (상한 4096B, 여유 {4096 - size}B)"
    assert "module_repo_check" in out[2] and "eval 건너뜀(통과 아님)" in out[2]
    assert BASIS in proc.stdout and "Triage-Env: " in meta["message"] and f"출처 이슈: {KEY}" in meta["message"]
    assert BASIS in meta["body"] and "eval 건너뜀(통과 아님), 다음 정기 점검 대상" in meta["body"]
    (rec,) = records(e)
    assert rec["key"] == f"module:{KEY}" and rec["lines"] == out
    assert mr.head(e["remote_dir"]) == before_main and tree(e["managed"]) == managed
    assert not (e["job"] / "skill-wt").exists()                                # 임시 clone은 지운다
    # 받은 원격 사본에 그대로 적용되고 module_repo_check가 깨끗하다
    owner = e["remote_dir"] / "owner"
    subprocess.run(["git", "clone", "-q", str(e["remote_dir"] / "remote.git"), str(owner)], check=True)
    subprocess.run(["git", "-C", str(owner), "apply", str(patch)], check=True)
    from common import skillcheck
    assert skillcheck.repo_findings(owner) == []


def test_new_section_and_deep_doc_in_one_patch(e):
    proc = module(e, "4,5")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = (e["job"] / "module-suggestions" / "module.patch").read_text(encoding="utf-8")
    assert f"+++ b/{DEEP}" in text and f"+++ b/{EXPLORE}" in text
    assert "+## 판독 주의\n+\n+- DNC 평가 줄은" in text                         # 절이 없으면 파일 끝에 만든다
    assert "+- Android 14에서도 data/ 경로 그대로\n \n ## ⑤" in text            # ④ 버전별 차이 절 끝
    assert proc.stdout.splitlines()[1].startswith(f"- {DEEP} +1 −0 (상한 16384B")


@pytest.mark.parametrize("line, kept, want", [
    ("2", (1,), "2번 줄은 check-output이 뺐다"),
    ("3", (1, 3), "3번 줄: 모르는 칸(기타)"),
    ("9", (1,), "9번 [모듈] 줄이 없다"),
])
def test_rejects_unchecked_or_unknown(e, line, kept, want):
    explore(e, LINES, kept)
    proc = module(e, line)
    assert proc.returncode == 1 and proc.stdout.startswith(f"모듈 학습 patch 없음: {want}")
    assert not (e["job"] / "module-suggestions" / "module.patch").exists()


@pytest.mark.parametrize("text, want", [
    ("가" * 201, "200자를 넘는다"),
    ("a | b 표 칸", "표·코드 기호"),
    ("# 새 제목", "제목·인용·목록 기호"),
    ("확인 없이 git push 한다", "위험 지시"),
    ("응답이 `cause=NONE`이어도 실린 APN이 틀리면 실패다.", "이미 있다"),
])
def test_rejects_bad_lines(e, text, want):
    explore(e, [f"- [모듈] android/data 함정 — {text} — 근거: x"], kept=(1,))
    proc = module(e)
    assert proc.returncode == 1 and want in proc.stdout, proc.stdout


def test_rejects_changed_output_held_and_cap(e):
    (e["job"] / "explore-output.md").write_text("바뀜\n" + "\n".join(LINES), encoding="utf-8")   # 검사 뒤 바뀜
    assert "check-output 검사 결과와 다르다" in module(e).stdout
    explore(e, LINES)
    (e["job"] / "analysis.json").write_text(json.dumps({"platform": "android", "decision": {"state": "held"}}), encoding="utf-8")
    for n in ("1", "6"):                                                        # 보류면 함정·첫 점검은 고르지 않는다
        assert "확정 원인에서만" in module(e, n).stdout
    assert module(e, "4").returncode == 0                                       # 판독 주의는 된다
    full = (e["remote_dir"] / "work" / EXPLORE).read_text(encoding="utf-8")
    mr.push(e["remote_dir"], {EXPLORE: full + "\n" + "가" * ((4096 - len(full.encode()) - 2) // 3) + "\n"})
    proc = module(e, "4")
    assert proc.returncode == 1 and "상한 도달" in proc.stdout and "정리 PR 필요" in proc.stdout


def test_pr_only_with_shown_hash_branch_only(e):
    assert module(e).returncode == 0
    meta_p = e["job"] / "module-suggestions" / "module.meta.json"
    sha = json.loads(meta_p.read_text(encoding="utf-8"))["sha256"]
    main0, managed = mr.head(e["remote_dir"]), tree(e["managed"])
    proc = call(e, "--pr", "--sha", "0" * 64)
    assert proc.returncode == 1 and "변경 해시 불일치" in proc.stdout
    proc = call(e, "--pr", "--sha", sha)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    branch = f"tt-module/{KEY}-1"
    assert branch in proc.stdout and proc.stdout.startswith("모듈 레포 PR을 만들었다: https://")
    bare = e["remote_dir"] / "remote.git"
    assert mr.head(e["remote_dir"]) == main0 and tree(e["managed"]) == managed      # main·관리 clone 그대로
    heads = git(bare, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    assert sorted(heads.split()) == sorted(["main", branch])
    body = git(bare, "log", "-1", "--format=%B", branch)
    assert body.startswith(f"모듈 학습({KEY}): android/data 함정") and f"출처 이슈: {KEY}" in body
    assert body.rstrip().splitlines()[-1].startswith("Triage-Env: runtime=")
    assert git(bare, "diff", "--name-only", f"main..{branch}").split() == [EXPLORE]
    (pr,) = json.loads(next(e["gh"].glob("*.json")).read_text(encoding="utf-8"))["prs"]
    assert pr["branch"] == branch and pr["base"] == "main" and BASIS in pr["body"]
    assert "eval 건너뜀(통과 아님), 다음 정기 점검 대상" in pr["body"] and "모듈·층" in pr["body"]
    assert not (e["job"] / "skill-wt").exists()
    again = call(e, "--pr", "--sha", sha)
    assert again.returncode == 1 and "이미 PR을 만들었다" in again.stdout
    assert [r["key"] for r in records(e)][-1] == f"module-pr:{KEY}"


def test_pr_refuses_when_main_changed_patch(e):
    assert module(e).returncode == 0
    sha = json.loads((e["job"] / "module-suggestions" / "module.meta.json").read_text(encoding="utf-8"))["sha256"]
    text = (e["remote_dir"] / "work" / EXPLORE).read_text(encoding="utf-8")
    mr.push(e["remote_dir"], {EXPLORE: text.replace("실린 APN이 틀리면 실패다.", "실린 APN이 다르면 실패다.")})
    proc = call(e, "--pr", "--sha", sha)
    assert proc.returncode == 1 and "main이 바뀌어 patch가 달라졌다" in proc.stdout
    heads = git(e["remote_dir"] / "remote.git", "for-each-ref", "--format=%(refname:short)", "refs/heads").split()
    assert heads == ["main"]


def test_usage_errors(e):
    assert call(e, "--module").returncode == 2
    assert call(e, "--module", "--line", "1", "--name", "x").returncode == 2
    assert call(e, "--skill-dir", "/x").returncode == 2                         # --name 없음
