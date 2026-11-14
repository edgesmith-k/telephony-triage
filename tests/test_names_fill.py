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


def _texts(root, platform):
    out = {}
    for p in names_fill.targets(root, platform):
        try:
            t = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if p.name == "modules.yaml":
            a, b = names_fill.block(t, platform)
            t = t[a:b]
        out[p.relative_to(root).as_posix()] = t
    return out


@pytest.mark.parametrize("platform", ["ofono", "android"])
def test_form_matches_templates_and_is_blank(platform):
    form = _form(platform)
    texts = _texts(REPO, platform)
    assert form["platform"] == platform
    for row in form["rows"]:
        assert row["real"] == ""                                   # 레포의 양식에는 실제 값을 두지 않는다
        files = sorted(n for n, t in texts.items() if row["placeholder"] in t)
        assert files == sorted(row["files"]), row["placeholder"]   # 템플릿이 바뀌면 양식도 다시 만든다
        assert sum(texts[n].count(row["placeholder"]) for n in files) == row["count"], row["placeholder"]


@pytest.mark.parametrize(("platform", "other"), [("ofono", "android"), ("android", "ofono")])
def test_fill_replaces_only_that_platform(tmp_path, platform, other):
    shutil.copytree(BASE, tmp_path / "templates" / "module-skills")
    form = _form(platform)
    for i, row in enumerate(form["rows"]):
        row["real"] = f"ZZ{i:03d}Q"
    filled = tmp_path / "f.json"
    filled.write_text(json.dumps(form), encoding="utf-8")
    cmd = [sys.executable, "-X", "utf8", str(REPO / "tools" / "names_fill.py"), str(tmp_path), str(filled)]
    before = _texts(tmp_path, platform)
    assert subprocess.run(cmd, capture_output=True, check=True).returncode == 0
    assert _texts(tmp_path, platform) == before                    # 미리 보기는 쓰지 않는다
    subprocess.run([*cmd, "--write"], capture_output=True, check=True)
    after = _texts(tmp_path, platform)
    assert not [r["placeholder"] for r in form["rows"] if any(r["placeholder"] in t for t in after.values())]
    assert _texts(tmp_path, other) == _texts(REPO, other)          # 다른 플랫폼 블록·폴더는 그대로
