"""oFono `dump_dmsg_w_re()` 조각에 갈린 IMSI·ICCID 실행 중 마스킹 (08-safety.md §8, 설계 §4.3).

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
    return f"Sep 20 15:10:{ts} dut daemon.info {ident}[{pid}]: src/dbus.c:dump_dmsg_w_re() "


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
