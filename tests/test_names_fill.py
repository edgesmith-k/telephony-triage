"""tools/names_fill.py와 빈 양식(tools/site_names/): 양식이 템플릿과 맞는지, 채우면 그 플랫폼만 바뀌는지."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "templates" / "module-skills"
sys.path.insert(0, str(REPO / "tools"))
import names_fill  # noqa: E402


def _form(platform):
    return json.loads((REPO / "tools" / "site_names" / f"{platform}-names-form.json").read_text(encoding="utf-8"))


def _texts(base, platform):
    out = {}
    for p in names_fill.targets(base, platform):
        try:
            t = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if p.name == "modules.yaml":
            a, b = names_fill.block(t, platform)
            t = t[a:b]
        out[p.relative_to(base).as_posix()] = t
    return out


@pytest.mark.parametrize("platform", ["ofono", "android"])
def test_form_matches_templates_and_is_blank(platform):
    form = _form(platform)
    texts = {f"templates/module-skills/{k}": v for k, v in _texts(BASE, platform).items()}   # 양식의 files는 레포 기준 경로
    assert form["platform"] == platform
    for row in form["rows"]:
        assert row["real"] == ""                                   # 레포의 양식에는 실제 값을 두지 않는다
        files = sorted(n for n, t in texts.items() if row["placeholder"] in t)
        assert files == sorted(row["files"]), row["placeholder"]   # 템플릿이 바뀌면 양식도 다시 만든다
        assert sum(texts[n].count(row["placeholder"]) for n in files) == row["count"], row["placeholder"]


@pytest.mark.parametrize(("platform", "other"), [("ofono", "android"), ("android", "ofono")])
def test_fill_replaces_only_that_platform_in_the_snapshot(tmp_path, platform, other):
    snap = tmp_path / "docs" / "site" / "module-skills"            # 사내 스냅샷(SITE_PATHS)
    shutil.copytree(BASE, snap)
    shutil.copytree(BASE, tmp_path / "templates" / "module-skills")
    form = _form(platform)
    for i, row in enumerate(form["rows"]):
        row["real"] = f"ZZ{i:03d}Q"
    filled = tmp_path / "f.json"
    filled.write_text(json.dumps(form), encoding="utf-8")
    tool = [sys.executable, "-X", "utf8", str(REPO / "tools" / "names_fill.py")]
    refused = subprocess.run([*tool, str(tmp_path / "templates" / "module-skills"), str(filled), "--write"], capture_output=True)
    assert refused.returncode != 0                                   # 레포 템플릿(사외 파일)은 받지 않는다
    assert _texts(tmp_path / "templates" / "module-skills", platform) == _texts(BASE, platform)
    cmd = [*tool, str(snap), str(filled)]
    subprocess.run(cmd, capture_output=True, check=True)
    assert _texts(snap, platform) == _texts(BASE, platform)          # 미리 보기는 쓰지 않는다
    subprocess.run([*cmd, "--write"], capture_output=True, check=True)
    after = _texts(snap, platform)
    assert not [r["placeholder"] for r in form["rows"] if any(r["placeholder"] in t for t in after.values())]
    assert _texts(snap, other) == _texts(BASE, other)                # 다른 플랫폼 블록·폴더는 그대로
