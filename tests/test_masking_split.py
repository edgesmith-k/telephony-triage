"""oFono 덤프 함수(`<함수>()`, 시험은 지어낸 `example_dump()`) 조각에 갈린 IMSI·ICCID 실행 중 마스킹 (08-safety.md §8, 설계 §4.3).

합성 oFono syslog 줄만 쓴다(가짜 값, 실제 값 아님). `mask_lines`·`mask_records`·`residual`·`redact`를 같이 본다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import dumpjoin, masking  # noqa: E402
import mask_pii  # noqa: E402
import parse_logcat  # noqa: E402
import platforms  # noqa: E402

IMSI, IMSI_A, IMSI_B = "450081234567890", "45008123", "4567890"
ICCID, ICCID_A, ICCID_B = "89820012345678901234", "898200123456", "78901234"


def _dump(ts: str = "05.100", pid: int = 812, ident: str = "ofonod") -> str:
    return f"Sep 20 15:10:{ts} dut daemon.info {ident}[{pid}]: src/dbus.c:example_dump() "


OTHER = "Sep 20 15:10:05.200 dut daemon.info connmand[9]: src/main.c:tick() state=ready"
OTHER2 = "Sep 20 15:10:05.250 dut daemon.info ofonod[813]: src/sim.c:other() poll"


def _split(a: str, b: str, key: str = "imsi=", ts_b: str = "05.350", **kw) -> list[str]:
    head_b = kw.pop("head_b", None) or _dump(ts_b)
    return [_dump("05.100") + f"method return dict{{{key}{a}", head_b + f"{b}, more}}"]


def _records(lines: list[str]) -> list[dict]:
    """줄 → 파서 레코드 모양(tag·pid·ts·msg)."""
    out = []
    for line in lines:
        head, _, msg = line.partition("]: ")
        ident, _, pid = head.rsplit(" ", 1)[1].partition("[")
        out.append({"tag": ident, "pid": int(pid), "ts": f"2026-09-20T15:10:{line[13:19]}+09:00", "msg": msg})
    return out


def _mask(lines: list[str]):
    masker = masking.new_masker(log_lines=True)
    return masking.mask_lines(masker, lines), masker


def _mask_recs(lines: list[str]):
    masker = masking.new_masker(log_lines=True)
    return [r["msg"] for r in masking.mask_records(masker, _records(lines))], masker


def _plain(lines: list[str]) -> list[str]:
    masker = masking.new_masker(log_lines=True)
    return [masker(line) for line in lines]


def _both(lines: list[str]):
    """(경로 결과, 줄 단위 결과) 쌍: 줄 목록과 레코드 msg."""
    masker = masking.new_masker(log_lines=True)
    plain_recs = [masker(r["msg"]) for r in _records(lines)]
    return ((_mask(lines)[0], _plain(lines)), (_mask_recs(lines)[0], plain_recs))


def test_imsi_split_8_7_all_paths():
    lines = _split(IMSI_A, IMSI_B)
    for out, masker in (_mask(lines), _mask_recs(lines)):
        assert out[0].endswith("imsi=<IMSI#1>") and "<IMSI#1>, more}" in out[1], out
        assert masker.counts.get("IMSI") == 1
        assert not any(d in "".join(out) for d in (IMSI_A, IMSI_B))
    text = "\n".join(lines)
    assert masking.residual(text).get("IMSI") == 1
    assert masking.residual("\n".join(_mask(lines)[0])) == {}
    red, counts = masking.redact(text)
    assert counts.get("IMSI") == 1 and red.count("<REDACTED:IMSI>") == 2 and IMSI_B not in red


def test_iccid_split_12_8():
    lines = _split(ICCID_A, ICCID_B, key="iccid=")
    assert _plain(lines)[0].endswith(ICCID_A)                 # 줄 단위로는 둘 다 남는다
    for out, masker in (_mask(lines), _mask_recs(lines)):
        assert out[0].endswith("iccid=<ICCID#1>") and out[1].split("() ")[1].startswith("<ICCID#1>")
        assert masker.counts.get("ICCID") == 1
    assert masking.residual("\n".join(lines)).get("ICCID") == 1
    assert masking.residual("\n".join(_mask(lines)[0])) == {}
    assert masking.redact("\n".join(lines))[0].count("<REDACTED:ICCID>") == 2


def test_interleaved_lines_kept():
    a, b = _split(IMSI_A, IMSI_B)
    lines = [a, OTHER, OTHER2, b]
    for out, _m in (_mask(lines), _mask_recs(lines)):
        assert out[0].endswith("<IMSI#1>") and "<IMSI#1>, more}" in out[3]
    out, _m = _mask(lines)
    assert out[1:3] == _plain(lines)[1:3]
    red = masking.redact("\n".join(lines))[0].split("\n")
    assert red[1:3] == lines[1:3]


def test_time_gap_rules():
    near = _split(IMSI_A, IMSI_B, head_b=_dump("06.200"))
    near[0] = near[0].replace("05.100", "05.999")
    for out, _m in (_mask(near), _mask_recs(near)):
        assert "<IMSI#1>, more}" in out[1]                    # .999 → 다음 초 .200 (Δ<1초)
    far = _split(IMSI_A, IMSI_B, head_b=_dump("06.100"))     # Δ = 1.0초 → 안 이음
    for out, plain in _both(far):
        assert out == plain and IMSI_B in out[1]


def test_pid_or_ident_differs_not_joined():
    for head in (_dump("05.350", pid=813), _dump("05.350", ident="ofonoX")):
        lines = _split(IMSI_A, IMSI_B, head_b=head)
        for out, plain in _both(lines):
            assert out == plain and IMSI_B in out[1]
        assert masking.residual("\n".join(lines)) == masking.residual(lines[0])


def test_dump_func_from_site_defaults():
    """덤프 함수 이름은 site-defaults `dump_func`(기본 placeholder) — 정한 이름의 줄만 잇고, 다른 함수 줄은 잇지 않는다."""
    site = [ln.replace("example_dump()", "site_dump_x()") for ln in _split(IMSI_A, IMSI_B)]
    want = [ln.replace("example_dump()", "site_dump_x()") for ln in _mask(_split(IMSI_A, IMSI_B))[0]]
    try:
        dumpjoin.configure("site_dump_x")
        assert _mask(site)[0] == want
        for out, plain in _both(_split(IMSI_A, IMSI_B)):                      # placeholder 이름은 이제 덤프가 아니다
            assert out == plain and IMSI_B in out[1]
    finally:
        dumpjoin.configure(dumpjoin.DEFAULT_FUNC)
    mixed = _split(IMSI_A, IMSI_B, head_b=_dump("05.350").replace("example_dump()", "other_fn()"))
    for out, plain in _both(mixed):
        assert out == plain and IMSI_B in out[1]
    assert dumpjoin.groups_from_lines(["no call here", "x[1]: plain text"]) == []
    # 다른 프로세스가 읽는 site-defaults 값: oFono 블록 위치는 기본 플랫폼에 따라, 이상한 값은 기본값(검증은 platforms)
    assert dumpjoin.func_from({"platform": {"others": {"ofono": {"dump_func": "site_dump_x"}}}}) == "site_dump_x"
    assert dumpjoin.func_from({"platform": {"name": "ofono", "dump_func": "site_dump_x"}}) == "site_dump_x"
    assert dumpjoin.func_from({"platform": {"dump_func": "site_dump_x"}}) == dumpjoin.DEFAULT_FUNC == platforms.DUMP_FUNC_DEFAULT
    assert dumpjoin.func_from({"platform": {"others": {"ofono": {"dump_func": "x() y"}}}}) == dumpjoin.DEFAULT_FUNC
    assert dumpjoin.func_from(None) == dumpjoin.DEFAULT_FUNC


def test_other_function_lines_do_not_weaken_masking():
    """다른 함수 줄은 덤프 조각이 아니다: 시각 없는 덤프 조각 사이에 끼어도 묶음을 닫지 않고, 같은 함수의 보통 줄을
    이어 다른 규칙(MAC)을 막지 않는다(리뷰 재현 입력 두 개)."""
    untimed = ["ofonod[100]: src/dbus.c:example_dump() info imsi=45000123",
               "ofonod[100]: src/network.c:other_fn() status ok",
               "ofonod[100]: src/dbus.c:example_dump() 4567890 end"]
    out = _mask(untimed)[0]
    assert out[2].endswith("<IMSI#1> end") and "4567890" not in masking.redact("\n".join(untimed))[0]
    timed = ["Sep 20 14:32:11.100 host ofonod[100]: src/sim.c:read_cb() iccid=8982012345678901",
             "Sep 20 14:32:11.200 host ofonod[100]: src/sim.c:read_cb() 23:45:67:89:ab:cd"]
    assert _mask(timed)[0][1].endswith("read_cb() <MAC#1>")
    assert masking.residual("\n".join(timed)).get("MAC") == 1


def test_same_imsi_whole_elsewhere_same_number():
    lines = _split(IMSI_A, IMSI_B) + [OTHER.replace("state=ready", f"imsi={IMSI}")]
    for out, masker in (_mask(lines), _mask_recs(lines)):
        assert out[2].endswith("imsi=<IMSI#1>") and masker.counts["IMSI"] == 2


def test_no_cross_match_is_byte_identical():
    lines = [_dump("05.100") + f"imsi={IMSI} iccid={ICCID}", OTHER, _dump("05.300") + "tail ip=10.1.2.3"]
    for out, plain in _both(lines):
        assert out == plain
    assert masking.redact("\n".join(lines))[0].split("\n") == [masking.redact(x)[0] for x in lines]


def test_unkeyed_digits_across_chunks_not_masked():
    """키 없는 18자리 넘는 숫자열(뒤집힌 ICCID `98…` 꼴 포함)이 조각 경계를 넘어도 이은 글에서 가리지 않는다(285행 제외)."""
    for a, b in (("9828002143", "6587092143"), ("8982001234", "5678901234"), (IMSI_A, IMSI_B)):
        lines = [_dump("05.100") + f"bytes {a}", _dump("05.300") + f"{b} end"]
        for out, plain in _both(lines):
            assert out == plain
        per_line: dict = {}
        for x in lines:
            for k, v in masking.residual(x).items():
                per_line[k] = per_line.get(k, 0) + v
        assert masking.residual("\n".join(lines)) == dict(sorted(per_line.items()))
        assert masking.redact("\n".join(lines))[0].split("\n") == [masking.redact(x)[0] for x in lines]
    assert masking.forced_lines(masking.new_masker(log_lines=True), lines) == {}


def test_nai_imsi_split():
    lines = [_dump("05.100") + "user 0" + IMSI_A, _dump("05.300") + IMSI_B + "@nai.epc.example"]
    out, masker = _mask(lines)
    assert IMSI_B not in out[1] and out[1].split("() ")[1].startswith("<IMSI#1>") and masker.counts["IMSI"] == 1


def test_dumpjoin_records_matches_lines():
    lines = [*_split(IMSI_A, IMSI_B)[:1], OTHER, _split(IMSI_A, IMSI_B)[1]]
    recs = _records(lines)
    g_lines, g_recs = dumpjoin.groups_from_lines(lines), dumpjoin.groups_from_records(recs)
    assert [[i for i, _c in g] for g in g_lines] == [[i for i, _c in g] for g in g_recs] == [[0, 2]]


def test_run_cut_piece_two_only(tmp_path):
    log = tmp_path / "ofono.log"
    a, b = _split(IMSI_A, IMSI_B)
    log.write_text("\n".join([a, OTHER, b]) + "\n", encoding="utf-8")
    out = tmp_path / "cut.log"
    args = parse_logcat.build_parser().parse_args(
        ["cut", str(log), "--around", "2026-09-20T15:10:05.350+09:00", "--seconds", "0.05", "--context", "0",
         "--out", str(out), "--tz", "Asia/Seoul", "--year", "2026"])
    info = parse_logcat.run_cut(args, platforms.load({}, "ofono", require_enabled=False))
    text = out.read_text(encoding="utf-8")
    assert info["lines"] == 1 and "<IMSI#1>, more}" in text and IMSI_B not in text and info["replacements"] == {"IMSI": 1}


def test_fields_from_pieces_use_same_token(tmp_path):
    lines = _split(IMSI_A, IMSI_B)
    recs = _records(lines)
    recs[1]["fields"] = {"tail": IMSI_B, "head": IMSI_A}
    masker = masking.new_masker(log_lines=True)
    forced = masking.forced_records(masker, recs)
    got = [parse_logcat._mask_record(r, masker, forced.get(i)) for i, r in enumerate(recs)]
    assert got[1]["fields"] == {"tail": "<IMSI#1>", "head": "<IMSI#1>"} and masker.counts["IMSI"] == 1
    # mask_pii 이벤트 모드도 같다
    src, dst = tmp_path / "events.json", tmp_path / "out.json"
    src.write_text(json.dumps({"events": recs}), encoding="utf-8")
    mask_pii.run_events(argparse.Namespace(events=str(src), out=str(dst)), None)
    events = json.loads(dst.read_text(encoding="utf-8"))["events"]
    assert events[1]["fields"]["tail"] == "<IMSI#1>" and "<IMSI#1>, more}" in events[1]["msg"]
    # mask_pii 파일 모드
    raw = tmp_path / "raw.log"
    raw.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mask_pii.run_replace(argparse.Namespace(files=[str(raw)], in_place=True, out=None), None)
    masked = raw.read_text(encoding="utf-8")
    assert IMSI_A not in masked and IMSI_B not in masked and masked.count("<IMSI#1>") == 2


def test_short_piece_not_in_value_table():
    """짧은 조각("0"·"450")은 값 표에 넣지 않는다 — 같은 글자의 이벤트 필드가 토큰이 되면 안 된다."""
    for a, b in ((IMSI_A + IMSI_B[:-1], IMSI_B[-1]), (IMSI_A[:3], IMSI_A[3:] + IMSI_B)):
        lines = _split(a, b)
        out, masker = _mask(lines)
        assert out[0].endswith("imsi=<IMSI#1>") and "<IMSI#1>, more}" in out[1], out
        short = a if len(a) < len(b) else b
        assert masker.mask_value(short) == short


def test_untimed_record_does_not_close_timed_group():
    """시각 없는 dump 레코드가 끼어도 시각 있는 레코드 묶음은 닫히지 않는다."""
    lines = _split(IMSI_A, IMSI_B)
    recs = _records(lines)
    mid = dict(recs[0], ts=None, pid="77")
    assert [[i for i, _c in g] for g in dumpjoin.groups_from_records([recs[0], mid, recs[1]])] == [[0, 2]]


def _check(path: Path) -> dict:
    return mask_pii.run_check(argparse.Namespace(files=[str(path)], changed=False, staged=False), None)


def test_check_flags_split_iccid_line_numbers(tmp_path):
    """`--check`도 갈린 조각을 묶는다: 조각마다 원 줄 번호로 낸다(사이에 다른 줄), 종료 1."""
    a, b = _split(ICCID_A, ICCID_B, key="iccid=")
    log = tmp_path / "split.log"
    log.write_text("\n".join([a, OTHER, b]) + "\n", encoding="utf-8")
    res = _check(log)
    assert [(d["line"], d["kind"]) for d in res["detections"]] == [(1, "ICCID"), (3, "ICCID")]
    assert res["detections"][1]["col"] == b.index(ICCID_B) + 1
    sys.path.insert(0, str(REPO / "tests" / "helpers"))
    import runner

    proc = runner.run("mask_pii.py", ["--check", str(log)])
    assert proc.returncode == 1, proc.stderr
    assert [(d["line"], d["kind"]) for d in json.loads(proc.stdout)["detections"]] == [(1, "ICCID"), (3, "ICCID")]
    a, b = _split(IMSI_A, IMSI_B)
    log.write_text("\n".join([a, OTHER, b]) + "\n", encoding="utf-8")
    assert [(d["line"], d["kind"]) for d in _check(log)["detections"]] == [(1, "IMSI"), (3, "IMSI")]


def test_check_clean_after_replace(tmp_path):
    raw = tmp_path / "raw.log"
    raw.write_text("\n".join([*_split(ICCID_A, ICCID_B, key="iccid="), OTHER, *_split(IMSI_A, IMSI_B)]) + "\n",
                   encoding="utf-8")
    mask_pii.run_replace(argparse.Namespace(files=[str(raw)], in_place=True, out=None), None)
    assert _check(raw) == {"checked": 1, "detections": []}


BETWEEN = ["--between", "2026-09-20T15:10:05.300+09:00", "2026-09-20T15:10:05.400+09:00"]


def _parse(log: Path, *extra: str) -> list[dict]:
    sys.path.insert(0, str(REPO / "tests" / "helpers"))
    from runner import variant_db

    rules = variant_db("issue-db-ofono") / "parser-rules"
    args = parse_logcat.build_parser().parse_args(
        ["parse", str(log), "--rules", str(rules), "--tz", "Asia/Seoul", "--year", "2026", *extra])
    profile = platforms.load({}, "ofono", require_enabled=False)
    return parse_logcat.run_parse(args, REPO / "plugin", {}, profile)["events"]


def _split_log(tmp_path: Path, a: str, b: str, key: str = "imsi=") -> Path:
    log = tmp_path / "ofono.log"
    first, second = _split(a, b, key=key)
    log.write_text("\n".join([first, OTHER, second]) + "\n", encoding="utf-8")
    return log


def test_parse_window_piece_two_only(tmp_path):
    """`parse --mask`의 시간 창이 첫 조각을 빼도 둘째 조각은 전체 값 토큰으로 가린다(`--full`의 같은 레코드 msg와 같음)."""
    for a, b, key, tok in ((IMSI_A, IMSI_B, "imsi=", "<IMSI#1>"), (ICCID_A, ICCID_B, "iccid=", "<ICCID#1>")):
        log = _split_log(tmp_path, a, b, key)
        win = [e for e in _parse(log, "--mask", *BETWEEN) if e["event"] is None]
        assert len(win) == 1 and b not in win[0]["msg"] and win[0]["msg"].endswith(f"{tok}, more}}")
        full = [e for e in _parse(log, "--mask", "--full") if e["event"] is None and e["ts"] == win[0]["ts"]]
        assert [e["msg"] for e in full] == [win[0]["msg"]]


def test_parse_main_uses_site_dump_func(tmp_path):
    """`parse_logcat.py parse --mask`는 자기 site-defaults의 `dump_func`로 조각을 잇는다(플러그인 루트별)."""
    import subprocess
    sys.path.insert(0, str(REPO / "tests" / "helpers"))
    import make_plugin_root
    from runner import variant_db

    log = tmp_path / "site.log"
    first, second = (ln.replace("example_dump()", "site_dump_x()") for ln in _split(IMSI_A, IMSI_B))
    log.write_text("\n".join([first, OTHER, second]) + "\n", encoding="utf-8")
    rules = variant_db("issue-db-ofono") / "parser-rules"

    def msgs(root):
        proc = subprocess.run([sys.executable, str(root / "scripts" / "parse_logcat.py"), "parse", str(log), "--rules",
                               str(rules), "--tz", "Asia/Seoul", "--year", "2026", "--mask", "--full", "--plugin-root",
                               str(root)], capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, proc.stderr
        return " ".join(e["msg"] or "" for e in json.loads(proc.stdout)["events"])

    plain = make_plugin_root.make()
    assert IMSI_B in msgs(plain)                                         # placeholder 이름이면 잇지 않는다
    site = make_plugin_root.make()
    path = site / "site-defaults.yaml"
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.setdefault("platform", {}).setdefault("others", {}).setdefault("ofono", {})["dump_func"] = "site_dump_x"
    if data["platform"].get("name") == "ofono":
        data["platform"]["dump_func"] = data["platform"]["others"].pop("ofono")["dump_func"]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    out = msgs(site)
    assert IMSI_B not in out and "<IMSI#1>, more}" in out


def test_parse_window_no_context_leak(tmp_path):
    events = _parse(_split_log(tmp_path, IMSI_A, IMSI_B), "--mask", *BETWEEN)
    lo, hi = (parse_logcat.logtime.parse_ts(t) for t in BETWEEN[1:])
    assert events and all(lo <= parse_logcat.logtime.parse_ts(e["ts"]) <= hi for e in events)
    assert not any("method return" in str(e.get("msg")) for e in events)


def test_parse_window_same_as_backend_window(tmp_path):
    """덤프 표식(`dumpjoin.mark()`)이 있는 로그: 창 뒤 자르기(마스킹) 레코드 집합이 백엔드 창 자르기(비마스킹)와 같다 — 경계 포함."""
    log = tmp_path / "ofono.log"
    first, second = _split(IMSI_A, IMSI_B)
    lines = [first, OTHER, _dump("05.300") + "start", second, _dump("05.400") + "edge", _dump("05.401") + "after"]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert dumpjoin.mark() in log.read_text(encoding="utf-8")

    def key(events):
        return sorted((e["ts"], e["tag"], e.get("event")) for e in events)

    masked, plain = _parse(log, "--mask", *BETWEEN), _parse(log, *BETWEEN)
    assert key(masked) == key(plain) and len([e for e in plain if e["event"] is None]) == 3
