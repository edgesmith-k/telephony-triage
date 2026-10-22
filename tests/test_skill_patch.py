"""분석 스킬 `[스킬]` 규칙 제안의 담당자용 patch — skill_patch.py (reference/skill-patch.md, contracts.md §3.2).

스크립트 이름: skill_patch.py show_guard.py

- 사본(`JOB/skill-suggestions/<이름>/<rel>`) → 같은 프로세스 unified diff(새 파일 `/dev/null`, CRLF·끝 줄바꿈 없음 보존)
  → 마스킹(mask_pii와 같은 함수) → 스킬 디렉토리 임시 사본에서 `git apply --check` → `<이름>.patch`·고정 안내 줄·파일별 줄 수.
- 경로 탈출(`..`·심볼릭 링크)·마스킹이 문맥 줄을 바꿈·변경 없음은 patch 없이 메모(종료 1), 이전 patch도 지운다.
- 스킬 디렉토리는 그대로, 낸 줄은 표시 기록(`kind: patch`)으로 남는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import run  # noqa: E402
import shown_records  # noqa: E402

from common import shown  # noqa: E402
import skill_patch  # noqa: E402

KEY = "MOCK-9071"
NAME = "mock-data-analyzer"
REL = "references/DATA-001.md"
GUIDE_TAIL = " — 분석 스킬 담당자에게 전달, 담당자가 검토 후 스킬 소스에서 git apply"
ORIG = "# DATA-001 점검\n\n1. 데이터 설정을 본다.\n2. APN을 본다.\n3. 로밍 설정을 본다.\n"
ADDED = "4. 설정 화면 경로(설정 > 네트워크 > 모바일 데이터)를 본다.\n"


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture()
def env(tmp_path):
    """사용자 홈(work_dir만 있는 config)·작업 폴더·모의 분석 스킬 디렉토리."""
    base = tmp_path / "home"
    hook_env = shown_records.home(base)
    job = base / "work" / KEY
    job.mkdir(parents=True)
    sk = tmp_path / "skills" / NAME
    (sk / "references").mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: mock-data-analyzer\n---\n", encoding="utf-8")
    (sk / REL).write_text(ORIG, encoding="utf-8", newline="\n")
    return {"env": hook_env, "base": base, "job": job, "sk": sk, "copies": job / "skill-suggestions" / NAME,
            "patch": job / "skill-suggestions" / f"{NAME}.patch"}


def put(e, rel: str, data) -> Path:
    p = e["copies"] / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def call(e, *extra, name=NAME, sk=None):
    return run("skill_patch.py", [KEY, "--skill-dir", str(sk or e["sk"]), "--name", name, *extra], env=e["env"])


def git_apply(cwd: Path, patch: Path, *flags):
    return subprocess.run(["git", "apply", *flags, str(patch)], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, "GIT_CEILING_DIRECTORIES": str(cwd.parent)})


def records(e) -> list[dict]:
    return shown.read_records([e["base"] / "work"])


def test_success_patch_guidance_counts_and_record(env, tmp_path):
    put(env, REL, ORIG + ADDED)
    before = tree(env["sk"])
    proc = call(env)
    assert proc.returncode == 0, proc.stderr
    path = env["patch"].absolute()
    want = [f"스킬 제안 patch(적용 안 함, 마스킹됨): {path}{GUIDE_TAIL}", f"- {REL} +1 −0"]
    assert proc.stdout.splitlines() == want
    text = env["patch"].read_text(encoding="utf-8")
    assert text.startswith(f"--- a/{REL}\n+++ b/{REL}\n@@ ") and "+" + ADDED in text
    assert tree(env["sk"]) == before                       # 스킬 디렉토리는 그대로
    # 담당자 쪽: 원본 사본에 그대로 적용되고 결과가 사본과 같다
    other = tmp_path / "owner"
    other.mkdir()
    (other / "references").mkdir()
    (other / REL).write_text(ORIG, encoding="utf-8", newline="\n")
    assert git_apply(other, env["patch"]).returncode == 0
    assert (other / REL).read_text(encoding="utf-8") == ORIG + ADDED
    (rec,) = records(env)
    assert rec["script"] == "skill_patch" and rec["kind"] == "patch" and rec["job"] == KEY
    assert rec["key"] == f"patch:{KEY}/{NAME}" and rec["lines"] == want and rec["path"] == str(path)
    js = json.loads(call(env, "--json").stdout)
    assert js["status"] == "ok" and js["patch"] == str(path) and js["lines"] == want
    assert js["files"] == [{"path": REL, "added": 1, "removed": 0}]


def test_new_file_and_no_trailing_newline(env, tmp_path):
    put(env, REL, ORIG.replace("2. APN을 본다.\n", ""))               # 한 줄 지움
    put(env, "references/NEW.md", "새 점검\n끝 줄바꿈 없음")
    proc = call(env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[1:] == [f"- {REL} +0 −1", "- references/NEW.md +2 −0"]
    text = env["patch"].read_text(encoding="utf-8")
    assert "--- /dev/null\n+++ b/references/NEW.md\n@@ -0,0 +1,2 @@\n+새 점검\n+끝 줄바꿈 없음\n\\ No newline at end of file\n" in text
    owner = tmp_path / "owner"
    owner.mkdir()
    (owner / "references").mkdir()
    (owner / REL).write_text(ORIG, encoding="utf-8", newline="\n")
    assert git_apply(owner, env["patch"]).returncode == 0
    assert (owner / "references" / "NEW.md").read_bytes() == "새 점검\n끝 줄바꿈 없음".encode("utf-8")


def test_crlf_original_is_preserved(env, tmp_path):
    crlf = ORIG.replace("\n", "\r\n").encode("utf-8")
    (env["sk"] / REL).write_bytes(crlf)
    put(env, REL, crlf + ADDED.replace("\n", "\r\n").encode("utf-8"))
    proc = call(env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[1] == f"- {REL} +1 −0"          # 줄 끝만 다른 줄은 바뀐 줄로 세지 않는다
    data = env["patch"].read_bytes()
    assert b" 3. \xeb\xa1\x9c\xeb\xb0\x8d \xec\x84\xa4\xec\xa0\x95\xec\x9d\x84 \xeb\xb3\xb8\xeb\x8b\xa4.\r\n" in data
    owner = tmp_path / "owner"
    (owner / "references").mkdir(parents=True)
    (owner / REL).write_bytes(crlf)
    assert git_apply(owner, env["patch"]).returncode == 0
    assert (owner / REL).read_bytes() == crlf + ADDED.replace("\n", "\r\n").encode("utf-8")


@pytest.mark.parametrize("case", ["sk-symlink", "symlink-dir", "symlink-copy"])
def test_path_escape_is_rejected(env, tmp_path, case):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.md").write_text("밖\n", encoding="utf-8")
    if case == "sk-symlink":      # SK 안의 링크가 밖을 가리킨다(resolve 탈출)
        os.symlink(outside, env["sk"] / "esc")
        put(env, "esc/x.md", "밖\n바꿈\n")
    elif case == "symlink-dir":
        env["copies"].mkdir(parents=True)
        os.symlink(outside, env["copies"] / "linked")
    else:
        env["copies"].mkdir(parents=True)
        os.symlink(outside / "x.md", env["copies"] / "x.md")
    env["patch"].parent.mkdir(parents=True, exist_ok=True)
    env["patch"].write_text("이전 patch\n", encoding="utf-8")       # 이전 실행의 patch는 지운다
    before = tree(outside)
    proc = call(env)
    assert proc.returncode == 1, proc.stderr
    (line,) = proc.stdout.splitlines()
    assert line.startswith("스킬 제안 patch 없음(담당자 메모로 전달): ")
    assert ("스킬 디렉토리 밖" in line) if case == "sk-symlink" else ("심볼릭 링크" in line or "일반 파일" in line)
    assert not env["patch"].exists() and tree(outside) == before
    (rec,) = records(env)
    assert rec["kind"] == "patch" and rec["lines"] == [line] and "path" not in rec


def test_collect_missing_or_empty_copies(tmp_path):
    with pytest.raises(skill_patch.Memo, match="사본 폴더가 없다"):
        skill_patch.collect(tmp_path / "none", tmp_path)
    copies = tmp_path / "c"
    copies.mkdir()
    with pytest.raises(skill_patch.Memo, match="사본이 없다"):
        skill_patch.collect(copies, tmp_path)


def test_masking_that_changes_context_fails_without_patch(env):
    imei_line = "기준 단말 imei=490154203237518 에서 재현\n"
    (env["sk"] / REL).write_text(ORIG + imei_line, encoding="utf-8", newline="\n")
    before = tree(env["sk"])
    put(env, REL, ORIG + imei_line + ADDED)
    proc = call(env)
    assert proc.returncode == 1
    (line,) = proc.stdout.splitlines()
    assert line.startswith("스킬 제안 patch 없음(담당자 메모로 전달): 마스킹이 문맥·삭제 줄을 바꿔 원본에 적용되지 않는다")
    assert "490154203237518" not in line and "<IMEI#1>" in line
    assert not env["patch"].exists() and tree(env["sk"]) == before
    assert "490154203237518" not in json.dumps(records(env), ensure_ascii=False)


def test_masking_added_lines_only_is_fine(env):
    put(env, REL, ORIG + "5. 재현 단말 imei=490154203237518 기록\n")
    proc = call(env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = env["patch"].read_text(encoding="utf-8")
    assert "490154203237518" not in text and "+5. 재현 단말 imei=<IMEI#1> 기록\n" in text


def test_unchanged_unknown_dir_and_bad_input(env, tmp_path):
    put(env, REL, ORIG)
    proc = call(env)
    assert proc.returncode == 1 and "바뀐 파일 없음" in proc.stdout
    proc = call(env, sk=tmp_path / "missing")
    assert proc.returncode == 1 and "스킬 디렉토리가 없다" in proc.stdout
    put(env, "references/bin.dat", b"\xff\xfe\x00")
    proc = call(env)
    assert proc.returncode == 1 and "UTF-8 텍스트가 아니다" in proc.stdout
    proc = call(env, name="..")
    assert proc.returncode == 2 and "점뿐" in proc.stderr
    proc = run("skill_patch.py", ["NOPE-1", "--skill-dir", str(env["sk"]), "--name", NAME], env=env["env"])
    assert proc.returncode == 2 and "작업 디렉토리가 없다" in proc.stderr


def test_name_is_sanitized(env):
    copies = env["job"] / "skill-suggestions" / "mock-analyzers-mock-data-analyzer"
    (copies / "references").mkdir(parents=True)
    (copies / REL).write_text(ORIG + ADDED, encoding="utf-8", newline="\n")
    proc = call(env, name="mock-analyzers:mock-data-analyzer")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (env["job"] / "skill-suggestions" / "mock-analyzers-mock-data-analyzer.patch").is_file()


def test_apply_check_failure_is_a_memo(env, monkeypatch):
    """마스킹 비교를 지나도 원본에 맞지 않는 patch(문맥 불일치)는 `git apply --check`가 잡는다. 스킬 디렉토리 대신 임시 사본만 본다."""
    sk = env["sk"]
    bad = f"--- a/{REL}\n+++ b/{REL}\n@@ -1,2 +1,3 @@\n 없는 줄\n 또 없는 줄\n+추가\n"
    why = skill_patch.apply_check(sk, bad)
    assert why and why.startswith("git apply --check 실패")
    good = f"--- a/{REL}\n+++ b/{REL}\n@@ -5,0 +6 @@\n+{ADDED}"
    assert skill_patch.apply_check(sk, good) is None
    assert (sk / REL).read_text(encoding="utf-8") == ORIG     # 확인은 사본에서만


def test_outer_git_repo_is_not_used(env):
    """스킬 디렉토리가 git 저장소 안이어도(사본은 `.git` 제외·GIT_CEILING_DIRECTORIES) 저장소 상태를 바꾸지 않는다."""
    sk = env["sk"]
    subprocess.run(["git", "init", "-q", str(sk)], check=True)
    subprocess.run(["git", "-C", str(sk), "add", "-A"], check=True)
    def status():
        return subprocess.run(["git", "-C", str(sk), "status", "--porcelain"], capture_output=True, text=True).stdout
    head, st = (sk / ".git" / "index").read_bytes(), status()
    put(env, REL, ORIG + ADDED)
    assert call(env).returncode == 0
    assert (sk / ".git" / "index").read_bytes() == head and status() == st


def test_copy_error_is_a_memo(env, monkeypatch):
    """임시 사본 복사·읽기 실패(OSError·shutil.Error)는 내부 오류가 아니라 메모(종료 1, 기록)다."""
    import shutil
    import types

    put(env, REL, ORIG + ADDED)

    def boom(*a, **k):
        raise shutil.Error([("a", "b", "denied")])
    monkeypatch.setattr(skill_patch.shutil, "copytree", boom)
    monkeypatch.setattr(skill_patch, "job_dir", lambda args, defaults: (env["job"], []))
    args = types.SimpleNamespace(key=KEY, skill_dir=str(env["sk"]), name=NAME, platform=None)
    doc, code = skill_patch.run(args, {})
    assert code == 1 and doc["status"] == "memo" and "복사하지 못했다(Error)" in doc["lines"][0]
    assert not env["patch"].exists() and records(env)[-1]["lines"] == doc["lines"]
