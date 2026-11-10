"""tools/site_step.py restore [check]·site_checks.RESTORE_CHECKS (docs/SITE_RESTORE.md ④).

네트워크·API 없음. 스냅샷은 `tests/mocks/module-skills` 사본(합성), 이슈 DB는 변형 DB tmp git 레포(test_site_modules.make_site).
`make_module_repo.py --site-overlay`는 `Ctx.py` 바꿔치기로 흉내 낸다(인자 모양만 확인 — 실제 덮어쓰기는 make_module_repo 시험).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests" / "helpers"))
import module_remote as mr  # noqa: E402
import site_checks as sc  # noqa: E402
import site_step as ss  # noqa: E402
from tests.test_site_checks import by_id  # noqa: E402
from tests.test_site_modules import _env, make_site  # noqa: E402,F401 — autouse 환경 고정

IDS = ["restore.snapshot", "restore.source", "restore.overlay", "restore.tags", "restore.vendor_ipc", "restore.deny",
       "restore.label"]
LABEL = "import-20990101"
IPC = {"context": "SiteCtx_", "complete": "OnDone"}
SECRET = "demo-x-secret"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def overlay(monkeypatch):
    """make_module_repo 호출을 기록하고, 스냅샷(SOURCE 제외)을 <out>에 복사한 것으로 흉내 낸다. `fail`이면 종료 1."""
    calls, state = [], {"fail": False}
    real = sc.Ctx.py

    def fake(self, script, *args, timeout=None):
        if script != "tools/make_module_repo.py":
            return real(self, script, *args, timeout=timeout)
        calls.append(list(args))
        if state["fail"]:
            return 1, "ofono/_common/components.md placeholder-left\n", "스냅샷이 불완전\n"
        out, snap = Path(args[0]), Path(args[2])
        shutil.copytree(snap, out, ignore=shutil.ignore_patterns("SOURCE"))
        files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
        return 0, json.dumps({"out": str(out), "commit": "0" * 40, "files": len(files), "overlay": files,
                              "source": None}) + "\n", ""
    monkeypatch.setattr(sc.Ctx, "py", fake)
    return calls, state


def restored(tmp_path, monkeypatch, *, ipc=True, deny=True, label=LABEL) -> Path:
    """S-6을 끝낸 사내 레포 모습 + 스냅샷·SOURCE·vendor_ipc·거부 목록·반입 기준선이 모두 있는 상태."""
    root, remote = make_site(tmp_path)
    d = {"module_skills": {"remote": remote}}
    if ipc:
        d["platform"] = {"enabled": ["android", "ofono"], "vendor_ipc": dict(IPC), "others": {"ofono": {"vendor_ipc": dict(IPC)}}}
    (root / "plugin" / "site-defaults.yaml").write_text(yaml.safe_dump(d), encoding="utf-8")
    snap = root / sc.SNAPSHOT_DIR
    shutil.copytree(mr.MOCK, snap)
    (snap / "SOURCE").write_text(f"label={LABEL} sha={'a1b2c3d' * 5}0 date=2099-01-01\n", encoding="utf-8")
    (root / "SITE_PATHS").write_text("SITE_PROFILE.md\n.draft-manifest.json\ndocs/site/\nplugin/site-defaults.yaml\n",
                                     encoding="utf-8")
    (root / "README.md").write_text("공통 파일\n", encoding="utf-8")
    (root / ".draft-manifest.json").write_text(json.dumps({"schema": 1, "label": label, "files": {}}), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "site")
    if deny:
        f = tmp_path / "deny.txt"                    # 레포 밖
        f.write_text(SECRET + "\n", encoding="utf-8")
        monkeypatch.setenv("TT_DENY_FILE", str(f))
    else:
        monkeypatch.delenv("TT_DENY_FILE", raising=False)
    _tolerate_vendor_ipc(monkeypatch)
    return root


def _tolerate_vendor_ipc(monkeypatch) -> None:
    """`platforms.load`는 그대로 부른다. 이 플러그인이 아직 `vendor_ipc` 키를 모르면(설정 키가 들어오기 전 트리) 그 키만 빼고
    다시 읽는다 — 키를 아는 트리에서는 실제 검증 그대로다."""
    platforms = sc._plugin()[0]
    real = platforms.load

    def load(defaults, name=None, **kw):
        try:
            return real(defaults, name, **kw)
        except platforms.PlatformConfigError:
            d = json.loads(json.dumps(defaults))
            node = d.get("platform") or {}
            node.pop("vendor_ipc", None)
            for other in (node.get("others") or {}).values():
                other.pop("vendor_ipc", None)
            return real(d, name, **kw)
    monkeypatch.setattr(platforms, "load", load)


def run(root: Path) -> dict:
    return by_id(sc.run_checks(sc.RESTORE, root))


def test_restore_ids_and_listing(tmp_path, capsys):
    assert [sc.check_id(f) for f in sc.RESTORE_CHECKS] == IDS
    root = tmp_path / "site"
    root.mkdir()
    assert ss.main(["restore", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "docs/SITE_RESTORE.md" in out and all(m in out for m in "⓪①②③④⑤⑥⑦")
    assert not (root / "SITE_PROFILE.md").exists() and not (root / sc.STEP_STATE_DIR).exists()
    assert ss.main(["restore", "list", "--root", str(root)]) == 2
    for argv in (["restore", "--json"], ["restore", "check", "--allow-api"]):
        with pytest.raises(SystemExit) as exc:
            ss.main([*argv, "--root", str(root)])
        assert exc.value.code == 2, argv
    (root / ".local-draft").write_text("", encoding="utf-8")
    assert ss.main(["restore", "--root", str(root)]) == 2                      # 사외 초안 PC


def test_restore_check_pass(tmp_path, monkeypatch, overlay, capsys):
    root = restored(tmp_path, monkeypatch)
    prof = (root / "SITE_PROFILE.md").read_text(encoding="utf-8")
    code = ss.main(["restore", "check", "--root", str(root)])
    text = capsys.readouterr().out
    assert code == 0, text
    rows = run(root)
    assert list(rows) == IDS and {r["status"] for r in rows.values()} == {"pass"}, rows
    assert "_common 플랫폼 android, ofono" in rows["restore.snapshot"]["evidence"]
    assert "덮어쓴 파일" in rows["restore.overlay"]["evidence"] and "카테고리 일치" in rows["restore.tags"]["evidence"]
    assert "platform.others.ofono.vendor_ipc" in rows["restore.vendor_ipc"]["evidence"]
    assert "SiteCtx_" not in json.dumps(rows, ensure_ascii=False)             # 값은 보이지 않는다
    # make_module_repo 인자: <임시 out>(레포 밖) --site-overlay <스냅샷> --json
    calls, _ = overlay
    out, flag, snap, js = calls[0]
    assert flag == "--site-overlay" and js == "--json" and Path(snap) == root / sc.SNAPSHOT_DIR
    assert root not in Path(out).parents and not Path(out).exists()            # 임시 디렉토리는 지운다
    assert "자동 점검 restore" in text and "경고" not in text
    # 진행 상태 없음: SITE_PROFILE·docs/site/steps를 쓰지 않는다
    assert (root / "SITE_PROFILE.md").read_text(encoding="utf-8") == prof and not (root / sc.STEP_STATE_DIR).exists()
    assert ss.main(["restore", "check", "--json", "--root", str(root)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["step"] == "restore" and data["exit"] == 0 and len(data["results"]) == len(IDS)


def test_restore_vendor_ipc_bad_value_fails(tmp_path, monkeypatch, overlay):
    """값이 틀려 플랫폼 설정을 못 읽으면(`platforms.load` 오류 = config.py check 종료 2) 실패, 값은 보이지 않는다."""
    root = restored(tmp_path, monkeypatch)
    platforms = sc._plugin()[0]

    def bad(*a, **kw):
        raise platforms.PlatformConfigError("platform.vendor_ipc.context: 식별자 모양이 아닙니다: 1x")
    monkeypatch.setattr(platforms, "load", bad)
    r = run(root)["restore.vendor_ipc"]
    assert r["status"] == "fail" and "android" in r["evidence"] and "1x" not in r["evidence"] and "complete" in r["ask"]


def test_restore_vendor_ipc_needs_both_keys_and_site_values(tmp_path, monkeypatch, overlay):
    """placeholder 값 그대로·키 하나만은 통과가 아니다(값은 보이지 않는다)."""
    root = restored(tmp_path, monkeypatch)
    path = root / "plugin" / "site-defaults.yaml"
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    d["platform"]["others"]["ofono"]["vendor_ipc"] = {"context": "IpcCtx_", "complete": "OnDone"}
    path.write_text(yaml.safe_dump(d), encoding="utf-8")
    r = run(root)["restore.vendor_ipc"]
    assert r["status"] == "needs-user" and "ofono(platform.others.ofono.vendor_ipc, placeholder 값)" in r["evidence"]
    assert "IpcCtx_" not in json.dumps(r, ensure_ascii=False)
    d["platform"]["vendor_ipc"] = {"context": "SiteCtx_"}
    path.write_text(yaml.safe_dump(d), encoding="utf-8")
    assert run(root)["restore.vendor_ipc"]["status"] != "pass"


def test_restore_tags_skipped_db_is_not_pass(tmp_path, monkeypatch, overlay):
    """한 플랫폼의 이슈 DB를 건너뛰면 restore.tags는 skip(본 플랫폼 결과는 근거에) — ms1.tags와 달리 통과로 세지 않는다."""
    root = restored(tmp_path, monkeypatch)
    steps = root / sc.STEPS_FILE
    steps.write_text("".join(ln for ln in steps.read_text(encoding="utf-8").splitlines(True)
                             if not ln.startswith("ofono_db:")), encoding="utf-8")
    r = run(root)["restore.tags"]
    assert r["status"] == "skip" and "건너뜀 ofono" in r["evidence"] and "ofono_db" in r["ask"]


def test_restore_check_needs_user(tmp_path, monkeypatch, overlay, capsys):
    root = restored(tmp_path, monkeypatch, ipc=False, deny=False)
    rows = run(root)
    assert rows["restore.vendor_ipc"]["status"] == "needs-user" and "android(platform.vendor_ipc)" in rows["restore.vendor_ipc"]["evidence"]
    assert "②" in rows["restore.vendor_ipc"]["ask"]
    assert rows["restore.deny"]["status"] == "needs-user" and "TT_DENY_FILE" in rows["restore.deny"]["ask"]
    assert ss.main(["restore", "check", "--root", str(root)]) == 1
    text = capsys.readouterr().out
    assert "사용자에게 물을 것" in text and "[restore.deny]" in text and "--waive" not in text


def test_restore_check_label_warn_does_not_fail(tmp_path, monkeypatch, overlay, capsys):
    root = restored(tmp_path, monkeypatch, label="import-20990202")
    rows = run(root)
    r = rows["restore.label"]
    assert r["status"] == "warn" and "import-20990202" in r["evidence"] and LABEL in r["evidence"] and "⑦" in r["ask"]
    assert all(v["status"] == "pass" for k, v in rows.items() if k != "restore.label")
    assert ss.main(["restore", "check", "--root", str(root)]) == 0
    text = capsys.readouterr().out
    assert "| restore.label | 경고 |" in text and "경고 1" in text and "[restore.label]" in text
    # 기준선이 없으면 import-* 태그에서 라벨을 읽는다
    (root / ".draft-manifest.json").unlink()
    _git(root, "commit", "-q", "-am", "x")
    _git(root, "tag", LABEL)
    assert run(root)["restore.label"]["status"] == "pass"


def test_restore_check_fail_paths(tmp_path, monkeypatch, overlay):
    root = restored(tmp_path, monkeypatch)
    snap = root / sc.SNAPSHOT_DIR
    # SOURCE 형식 틀림 → source fail, label skip
    (snap / "SOURCE").write_text(f"label={LABEL}\nsha=abc\n", encoding="utf-8")
    rows = run(root)
    assert rows["restore.source"]["status"] == "fail" and rows["restore.label"]["status"] == "skip"
    # evals가 남은 스냅샷, _common 하나뿐 → snapshot fail
    (snap / "ofono" / "data" / "evals").mkdir()
    shutil.rmtree(snap / "android" / "_common")
    ev = run(root)["restore.snapshot"]["evidence"]
    assert "evals 포함" in ev and "ofono/data/evals" in ev and "_common 있는 플랫폼 1개" in ev
    # overlay 종료 1 → fail(경로·검사 id), tags skip
    _, state = overlay
    state["fail"] = True
    rows = run(root)
    assert rows["restore.overlay"]["status"] == "fail" and "placeholder-left" in rows["restore.overlay"]["evidence"]
    assert rows["restore.tags"]["status"] == "skip"
    # 스냅샷이 없으면 snapshot·source fail, overlay·tags skip
    shutil.rmtree(snap)
    rows = run(root)
    assert [rows[i]["status"] for i in IDS[:4]] == ["fail", "fail", "skip", "skip"]
    assert ss.main(["restore", "check", "--root", str(root)]) == 1


def test_restore_tags_and_deny_fail(tmp_path, monkeypatch, overlay):
    root = restored(tmp_path, monkeypatch)
    doc = yaml.safe_load((mr.MOCK / "modules.yaml").read_text(encoding="utf-8"))
    doc["platforms"]["ofono"]["modules"]["data"]["daemons"].append("ghostd")
    (root / sc.SNAPSHOT_DIR / "modules.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    (root / "docs" / "notes.md").parent.mkdir(exist_ok=True)
    (root / "docs" / "notes.md").write_text(f"공통 문서에 {SECRET} 이름\n", encoding="utf-8")   # SITE_PATHS 밖
    (root / sc.SNAPSHOT_DIR / "README.md").write_text(f"{SECRET}\n", encoding="utf-8")       # SITE_PATHS 안은 세지 않는다
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "x")
    rows = run(root)
    assert rows["restore.tags"]["status"] == "fail" and "tags.yaml에 없음 ofono:ghostd" in rows["restore.tags"]["evidence"]
    r = rows["restore.deny"]
    assert r["status"] == "fail" and "docs/notes.md 1건" in r["evidence"] and "1건/1파일" in r["evidence"]
    assert SECRET not in json.dumps(rows, ensure_ascii=False)                  # 항목 글자는 내지 않는다
    monkeypatch.setenv("TT_DENY_FILE", str(tmp_path / "missing.txt"))
    r = run(root)["restore.deny"]
    assert r["status"] == "fail" and "없음·권한" in r["evidence"]


def test_restore_deny_packed_file_is_not_pass(tmp_path, monkeypatch, overlay):
    """내용을 다 보지 못한 파일(압축)이 SITE_PATHS 밖에 있으면 0건이어도 통과가 아니다."""
    root = restored(tmp_path, monkeypatch)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "a.zip").write_bytes(b"PK\x03\x04 plain")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "zip")
    r = run(root)["restore.deny"]
    assert r["status"] == "fail" and "0건/0파일" in r["evidence"] and "압축 파일 1" in r["evidence"]
