"""`tools/make_excerpt.py`(마스킹 발췌 자르기, H C1+D R7·R34): tmp의 합성 원본 로그·거부 목록 디렉토리로만 돈다.

원본 글자는 출력·파일에 나오지 않아야 하고, 근거가 구간 밖이면 쓰지 않는다. `pytest tests/test_make_excerpt.py`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "make_excerpt.py"
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
from common import skillcheck

IMSI = "45005" + "1234567890"                  # 합성 15자리(경계 검사의 긴 숫자 패턴을 피해 나눠 쓴다)
APN = "corp-apn.example.net"
HOST = "rig7lab"
SECRETS = (IMSI, APN, HOST, "fake_ipc9")
RAW = [
    f"Nov  1 10:00:00 {HOST} ofonod[812]: start",
    f"Nov  1 10:00:01 {HOST} ofonod[812]: src/gprs.c:activate() apn={APN}",
    f"Nov  1 10:00:02 {HOST} exynos-ril[901]: [RilContext_0] OnRequestComplete Request ID=27, result=2",
    f"Nov  1 10:00:03 {HOST} ofonod[812]: imsi={IMSI}",
    f"Nov  1 10:00:04 {HOST} ofonod[812]: noise",
    f"Nov  1 10:00:05 {HOST} ofonod[812]: noise",
    f"Nov  1 10:00:06 {HOST} exynos-ril[901]: open /dev/fake_ipc9 failed",
    f"Nov  1 10:00:07 {HOST} ofonod[812]: Activating context failed",
    f"Nov  1 10:00:08 {HOST} ofonod[812]: end",
    # oFono SimManager GetProperties 덤프 3줄(합성, C1+D 보정 §1.2): 사업자 이름·MCC/MNC, 키·값이 조각에 갈린다
    f"Nov  1 10:00:09 {HOST} ofonod[812]: src/dbus.c:dump_dmsg_w_re() method return - i:org.ofono.SimManager "
    'm:GetProperties p:/ril_0 a:array[dict{"ServiceProviderName", variant("MOCKTEL")}, '
    'dict{"MobileCountryCode", variant("450")}, dict{"MobileNet',
    f"Nov  1 10:00:09 {HOST} ofonod[812]: src/dbus.c:dump_dmsg_w_re() "
    'workCode", variant("05")}, dict{"Name", variant("MOCK',
    f"Nov  1 10:00:09 {HOST} ofonod[812]: src/dbus.c:dump_dmsg_w_re() " '-SPLIT")}]',
]
DUMP_SECRETS = ("MOCKTEL", 'variant("450")', 'variant("05")', "MOCK-SPLIT", '"MOCK', "-SPLIT")


def _case(tmp: Path, lines="2-4,7-8", evidence=("result=2", "Activating context failed")) -> Path:
    case = tmp / "sim-x"
    case.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "name": "sim-x", "kind": "deep", "synthetic": False,
            "origin": {"kind": "masked-excerpt", "log": "O2", "episode": "E4b", "lines": lines,
                       "masker": "<채움>", "residual": "<채움>"},
            "expect": {"evidence": list(evidence)}}
    (case / "case.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return case


def _raw(tmp: Path) -> tuple[Path, Path]:
    raw_dir = tmp / "raw"
    raw_dir.mkdir(exist_ok=True)
    raw = raw_dir / "o2.txt"
    raw.write_text("\r\n".join(RAW) + "\r\n", encoding="utf-8")
    return raw, raw_dir


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", check=False)


def test_write_masks_tokenises_and_never_prints_raw(tmp_path):
    raw, raw_dir = _raw(tmp_path)
    case = _case(tmp_path)
    proc = _run("--case", case, "--raw", raw, "--against", raw_dir, "--write")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = (case / "files" / "source.log").read_text(encoding="utf-8")
    lines = text.split("\n")
    assert lines[0] == "-- [마스킹 발췌] O2 E4b 줄 2-4,7-8" and lines[4] == "-- [생략]" and len(lines) == 8 and lines[-1] == ""
    assert "<IMSI#1>" in text and "<APN#1>" in text and "<DEV#1>" in text and " host1 ofonod" in text
    for s in SECRETS:
        assert s not in text and s not in proc.stdout and s not in proc.stderr, s
    masker = [ln.split(": ", 1)[1] for ln in proc.stdout.splitlines() if ln.startswith("masker: ")]
    assert len(masker) == 1 and skillcheck.MASKER_RE.fullmatch(masker[0])
    # 채운 origin은 load_case 규칙(skillcheck.origin_problems)을 통과한다
    data = yaml.safe_load((case / "case.yaml").read_text(encoding="utf-8"))
    data["origin"].update(masker=masker[0], residual="2026-11-06")
    assert skillcheck.origin_problems(data, text) == []
    assert _run("--case", case, "--raw", raw, "--against", raw_dir, "--check").returncode == 0


def test_check_detects_drift(tmp_path):
    raw, raw_dir = _raw(tmp_path)
    case = _case(tmp_path)
    assert _run("--case", case, "--raw", raw, "--against", raw_dir, "--write").returncode == 0
    log = case / "files" / "source.log"
    log.write_text(log.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    proc = _run("--case", case, "--raw", raw, "--against", raw_dir, "--check")
    assert proc.returncode == 1 and "drift" in proc.stdout


def test_evidence_outside_segments_refuses(tmp_path):
    raw, raw_dir = _raw(tmp_path)
    case = _case(tmp_path, lines="3-4,7-7")              # 한 줄 어긋남: 8줄의 근거가 빠진다
    proc = _run("--case", case, "--raw", raw, "--against", raw_dir, "--write")
    assert proc.returncode == 1 and "evidence 2: 구간 안에 없음" in proc.stdout
    assert not (case / "files" / "source.log").exists()


def test_without_against_only_masker(tmp_path):
    """--against 없이는 로그 마스커만 쓴다: IMSI·호스트 칸은 가리지만 APN 값·장치 노드는 원본 거부 목록이 있어야 가린다
    (그래서 사외 절차는 늘 `--against <첨부 디렉토리>`다)."""
    raw, _ = _raw(tmp_path)
    case = _case(tmp_path)
    proc = _run("--case", case, "--raw", raw, "--write")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = (case / "files" / "source.log").read_text(encoding="utf-8")
    assert IMSI not in text and HOST not in text and APN in text and "/dev/fake_ipc9" in text
    assert not any(s in proc.stdout for s in SECRETS)


def test_dump_carrier_plmn_and_split_chunks(tmp_path):
    """GetProperties 덤프: 사업자 이름(ServiceProviderName·Name)은 거부 목록, MCC·MNC는 모양 규칙으로 `<PLMN#n>`.
    `dump_dmsg_w_re()` 조각에 갈린 키(MobileNet|workCode)·값(MOCK|-SPLIT)도 잡고, 갈린 값은 두 조각 모두 같은 토큰."""
    raw, raw_dir = _raw(tmp_path)
    case = _case(tmp_path, lines="2-4,7-12")
    proc = _run("--case", case, "--raw", raw, "--against", raw_dir, "--write")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = (case / "files" / "source.log").read_text(encoding="utf-8").split("\n")
    l10, l11, l12 = lines[-4:-1]
    assert 'variant("<CARRIER#1>")' in l10 and 'variant("<PLMN#1>")' in l10
    assert 'variant("<PLMN#2>")' in l11 and l11.endswith('variant("<CARRIER#2>')
    assert l12.endswith('dump_dmsg_w_re() <CARRIER#2>")}]')
    for s in (*SECRETS, *DUMP_SECRETS):
        assert all(s not in ln for ln in lines) and s not in proc.stdout and s not in proc.stderr, s
    assert _run("--case", case, "--raw", raw, "--against", raw_dir, "--check").returncode == 0
    # --against 없이도 모양 규칙(MCC·MNC)은 가린다. 사업자 이름은 거부 목록이 있어야 가린다.
    proc = _run("--case", case, "--raw", raw, "--write")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = (case / "files" / "source.log").read_text(encoding="utf-8")
    assert 'variant("<PLMN#1>")' in text and 'variant("<PLMN#2>")' in text and "MOCKTEL" in text


def test_usage_errors(tmp_path):
    raw, _ = _raw(tmp_path)
    case = _case(tmp_path, lines="8-14")                 # 원본 12줄을 넘는다
    assert _run("--case", case, "--raw", raw, "--write").returncode == 2
    case = _case(tmp_path, lines="7-8,2-4")              # 오름차순 아님
    assert _run("--case", case, "--raw", raw, "--write").returncode == 2
    data = yaml.safe_load((case / "case.yaml").read_text(encoding="utf-8"))
    data["synthetic"] = True
    (case / "case.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert _run("--case", case, "--raw", raw, "--write").returncode == 2
    assert _run("--case", tmp_path / "none", "--raw", raw, "--write").returncode == 2
    assert _run("--case", case, "--raw", raw, "--against", raw, "--write").returncode == 2   # --against는 디렉토리
