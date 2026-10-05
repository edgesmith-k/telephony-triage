#!/usr/bin/env python3
"""합성 logcat 생성기 (15-local-draft.md §15.2).

시나리오 YAML을 threadtime 형식 logcat으로 바꾼다. 같은 시나리오는 항상 같은
출력을 낸다(난수 없음). 사외 초안의 모든 fixture는 이것으로 만든다.

확정된 것과 placeholder
- **데이터 스택 태그는 확정 형식**이다: `DNC-<n>`, `DN-…`, `DPM-<n>`,
  `DRM-<n>`, `DSM-<n>`, `DCM-<n>`, `DSRM-<n>` (Android 13+, `14-site.md §14.1`).
- 그 밖의 태그, 로그 문구, RIL 출력 형식, 슬롯 표기(`[PHONE<n>]`),
  bugreport 섹션 헤더는 **placeholder**다. 사내에서 S7·S9·S20·S21로 확인한다
  (`14-site.md §14.2`).

시나리오 형식은 `tests/mocks/scenarios/README.md`에 있다.

CLI:
    python3 tests/mocks/logcat_gen.py <scenario.yaml> --out <dir>
        [--split-buffers] [--bugreport txt|zip] [--name <기본 파일명>]
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import yaml

LEVELS = {"V", "D", "I", "W", "E", "F"}
BUFFERS = ("main", "radio", "system", "crash", "events")

# bugreport 섹션 헤더 — TODO(SITE:S21) 사내 실제 문자열 확인
BUGREPORT_SECTIONS = {
    "system": "------ SYSTEM LOG (logcat -b system -v threadtime -d) ------",
    "radio": "------ RADIO LOG (logcat -b radio -v threadtime -d) ------",
    "main": "------ MAIN LOG (logcat -b main -v threadtime -d) ------",
    "events": "------ EVENT LOG (logcat -b events -v threadtime -d) ------",
    "crash": "------ CRASH LOG (logcat -b crash -v threadtime -d) ------",
}

# 태그 → 기본 버퍼. RIL과 데이터 스택은 radio, 나머지는 system.
RADIO_TAG_PREFIXES = (
    "RIL",
    "DNC-",
    "DN-",
    "DPM-",
    "DRM-",
    "DSM-",
    "DCM-",
    "DSRM-",
    "SST",
    "ServiceStateTracker",
    "UiccController",
    "SubscriptionManagerService",
    "SMSVC",
)

# TODO(SITE:S9) RILJ 요청/응답 출력 형식. 사내 실제 로그로 확인한다.
RIL_REQUEST_FMT = "[{serial:04d}]> {name}{args}"
RIL_RESPONSE_FMT = "[{serial:04d}]< {name} {result}"
RIL_UNSOL_FMT = "[UNSL]< {name}{args}"

# TODO(SITE:S20) 슬롯 표기. 메시지 접두어는 사내 실제 형식으로 바꾼다.
PHONE_PREFIX_FMT = "[PHONE{phone}] "


class ScenarioError(Exception):
    pass


def _parse_start(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _default_buffer(tag: str) -> str:
    for prefix in RADIO_TAG_PREFIXES:
        if tag.startswith(prefix):
            return "radio"
    return "system"


def _fmt_line(ts: datetime, pid: int, tid: int, level: str, tag: str, msg: str) -> str:
    """threadtime 형식. 연도는 없다 (parse_logcat의 `--year`가 채운다)."""
    stamp = ts.strftime("%m-%d %H:%M:%S.") + f"{ts.microsecond // 1000:03d}"
    return f"{stamp} {pid:5d} {tid:5d} {level} {tag}: {msg}"


def _render(template: str, phone: int | None, serial: int | None) -> str:
    out = template
    if "{phone}" in out:
        out = out.replace("{phone}", "" if phone is None else str(phone))
    if serial is not None and "{serial}" in out:
        out = out.replace("{serial}", f"{serial:04d}")
    return out


class Generator:
    def __init__(self, scenario: dict):
        self.scenario = scenario
        self.start = _parse_start(scenario.get("start", "2026-09-20T14:30:00+09:00"))
        self.default_phone = scenario.get("default_phone", 0)
        self.default_pid = int(scenario.get("pid", 1234))
        self.default_tid = int(scenario.get("tid", self.default_pid + 10))
        self.phone_prefix = bool(scenario.get("phone_prefix", True))
        self.clock_offset = timedelta(0)
        self.cursor = 0.0  # start로부터의 초
        # (버퍼, 줄)을 **낸 순서 그대로** 쌓는다. 합친 파일은 이 순서를 쓰고
        # (시계 이상이 있어도 수집 순서가 보존돼야 한다), 버퍼별 파일은 이
        # 순서에서 해당 버퍼만 걸러 쓴다.
        self.records: list[tuple[str, str]] = []

    # -- 시각 --------------------------------------------------------------

    def _advance(self, entry: dict) -> datetime:
        if "at" in entry:
            self.cursor = float(entry["at"])
        elif "after" in entry:
            self.cursor += float(entry["after"])
        jump = entry.get("clock_jump_sec")
        if jump is not None:
            # 시계 이상: 이 항목부터 로그 시각이 튄다 (뒤로 가거나 앞으로 뜀).
            self.clock_offset += timedelta(seconds=float(jump))
        return self.start + timedelta(seconds=self.cursor) + self.clock_offset

    # -- 항목 ---------------------------------------------------------------

    def _emit(self, ts: datetime, entry: dict, tag: str, msg: str) -> None:
        level = str(entry.get("level", "D")).upper()
        if level not in LEVELS:
            raise ScenarioError(f"알 수 없는 로그 레벨: {level}")
        pid = int(entry.get("pid", self.default_pid))
        tid = int(entry.get("tid", entry.get("pid", self.default_tid)))
        buffer_name = entry.get("buffer") or _default_buffer(tag)
        if buffer_name not in BUFFERS:
            raise ScenarioError(f"알 수 없는 버퍼: {buffer_name}")
        self.records.append((buffer_name, _fmt_line(ts, pid, tid, level, tag, msg)))

    def _entry_phone(self, entry: dict) -> int | None:
        if "phone" in entry:
            value = entry["phone"]
            return None if value is None else int(value)
        return self.default_phone

    def _message(self, entry: dict, body: str, phone: int | None) -> str:
        msg = _render(body, phone, entry.get("serial"))
        if self.phone_prefix and phone is not None and entry.get("phone_prefix", True):
            msg = PHONE_PREFIX_FMT.format(phone=phone) + msg
        return msg

    def _one(self, entry: dict) -> None:
        ts = self._advance(entry)
        phone = self._entry_phone(entry)

        if "ril_request" in entry:
            name = entry["ril_request"]
            serial = int(entry.get("serial", 1))
            args = entry.get("args", "")
            args = f" {args}" if args else ""
            body = RIL_REQUEST_FMT.format(serial=serial, name=name, args=args)
            self._emit(ts, entry, entry.get("tag", "RILJ"), self._message(entry, body, phone))
            return

        if "ril_response" in entry:
            name = entry["ril_response"]
            serial = int(entry.get("serial", 1))
            result = entry.get("result", "error=NONE")
            body = RIL_RESPONSE_FMT.format(serial=serial, name=name, result=result)
            self._emit(ts, entry, entry.get("tag", "RILJ"), self._message(entry, body, phone))
            return

        if "ril_unsol" in entry:
            name = entry["ril_unsol"]
            args = entry.get("args", "")
            args = f" {args}" if args else ""
            body = RIL_UNSOL_FMT.format(name=name, args=args)
            self._emit(ts, entry, entry.get("tag", "RILJ"), self._message(entry, body, phone))
            return

        if "tag" not in entry or "msg" not in entry:
            raise ScenarioError(f"tag/msg 또는 ril_* 가 필요합니다: {entry}")
        tag = _render(str(entry["tag"]), phone, entry.get("serial"))
        self._emit(ts, entry, tag, self._message(entry, str(entry["msg"]), phone))

    def run(self) -> dict[str, list[str]]:
        for entry in self.scenario.get("entries", []):
            if not isinstance(entry, dict):
                raise ScenarioError(f"항목은 매핑이어야 합니다: {entry!r}")
            repeat = int(entry.get("repeat", 1))
            every = entry.get("every")
            for index in range(repeat):
                step = dict(entry)
                step.pop("repeat", None)
                step.pop("every", None)
                if index > 0:
                    step.pop("at", None)
                    step["after"] = float(every if every is not None else 1.0)
                if "msg" in step:
                    step["msg"] = str(step["msg"]).replace("{i}", str(index + 1))
                self._one(step)
        buffers: dict[str, list[str]] = {}
        for buffer_name, line in self.records:
            buffers.setdefault(buffer_name, []).append(line)
        return buffers

    def merged(self) -> list[str]:
        """버퍼를 합친 한 파일. 낸 순서를 그대로 쓴다."""
        return [line for _, line in self.records]


# -- bugreport 래핑 --------------------------------------------------------


def build_bugreport(buffers: dict[str, list[str]], scenario: dict) -> str:
    build = scenario.get("build", {}) or {}
    fingerprint = build.get(
        "fingerprint", "mock/mocka56/a56:16/MOCKBUILD/MOCKA56_U1_20260915:user/release-keys"
    )
    build_id = build.get("build", "MOCKA56_U1_20260915")
    dumpstate_at = scenario.get("dumpstate_at", "2026-09-20 14:40:00")
    out = [
        "========================================================",
        f"== dumpstate: {dumpstate_at}",
        "========================================================",
        "",
        f"Build: {build_id}",
        f"Build fingerprint: '{fingerprint}'",
        "Bootloader: mock-bootloader",
        "Radio: mock-radio",
        "Network: MockTel",
        "Kernel: Linux version 0.0.0-mock",
        "",
    ]
    for name in ("system", "radio", "main", "events", "crash"):
        if name not in buffers:
            continue
        out.append(BUGREPORT_SECTIONS[name])
        out.extend(buffers[name])
        out.append("")
    # 가짜 dumpsys 섹션. 파서는 이 섹션을 읽지 않아야 한다
    # (contracts.md §3.2 extract-bugreport: "dumpsys 등 다른 섹션은 읽지 않는다").
    out.append("------ DUMPSYS (dumpsys -t 10) ------")
    out.append("DUMP OF SERVICE telephony.registry:")
    out.append("  (모의 dumpsys 내용 — 파서가 읽으면 안 된다)")
    out.append("")
    return "\n".join(out) + "\n"


# -- 출력 -------------------------------------------------------------------


def write_outputs(
    scenario: dict,
    buffers: dict[str, list[str]],
    merged: list[str],
    out_dir: Path,
    name: str,
    split_buffers: bool,
    bugreport: str | None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if bugreport:
        text = build_bugreport(buffers, scenario)
        if bugreport == "txt":
            path = out_dir / f"{name}.bugreport.txt"
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(path)
        elif bugreport == "zip":
            path = out_dir / f"{name}.bugreport.zip"
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"bugreport-{name}.txt", text)
            path.write_bytes(buf.getvalue())
            written.append(path)
        else:
            raise ScenarioError(f"알 수 없는 --bugreport 값: {bugreport}")
        return written

    if split_buffers:
        for buffer_name, lines in buffers.items():
            path = out_dir / f"{name}.{buffer_name}.log"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            written.append(path)
    else:
        path = out_dir / f"{name}.log"
        path.write_text("\n".join(merged) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    return written


def write_expect(scenario: dict, out_dir: Path, name: str) -> Path | None:
    """`.expect.yaml`을 쓴다. 합성 fixture이므로 `origin: synthetic`을 항상 넣는다
    (`contracts.md §fixture` 기대값, `15-local-draft.md §15.2`)."""
    expect = scenario.get("expect")
    if expect is None:
        return None
    data = dict(expect)
    data["origin"] = "synthetic"
    path = out_dir / f"{name}.expect.yaml"
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def generate(
    scenario_path: Path,
    out_dir: Path,
    name: str | None = None,
    split_buffers: bool = False,
    bugreport: str | None = None,
) -> dict:
    with Path(scenario_path).open(encoding="utf-8") as fh:
        scenario = yaml.safe_load(fh)
    if not isinstance(scenario, dict):
        raise ScenarioError(f"{scenario_path}: 시나리오는 매핑이어야 합니다.")
    generator = Generator(scenario)
    buffers = generator.run()
    base = name or scenario.get("name") or Path(scenario_path).stem
    written = write_outputs(
        scenario, buffers, generator.merged(), out_dir, base, split_buffers, bugreport
    )
    expect = write_expect(scenario, out_dir, base)
    return {
        "scenario": str(scenario_path),
        "name": base,
        "files": [str(p) for p in written],
        "expect": str(expect) if expect else None,
        "buffers": {k: len(v) for k, v in buffers.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="logcat_gen.py", description=__doc__)
    parser.add_argument("scenario", help="시나리오 YAML")
    parser.add_argument("--out", required=True, help="출력 디렉토리")
    parser.add_argument("--name", default=None, help="기본 파일명 (기본: 시나리오 name)")
    parser.add_argument(
        "--split-buffers",
        action="store_true",
        help="버퍼별로 파일을 나눈다 (<name>.radio.log 등)",
    )
    parser.add_argument(
        "--bugreport",
        choices=["txt", "zip"],
        default=None,
        help="합성 bugreport로 감싼다 (헤더 + logcat 섹션 + 가짜 dumpsys)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    info = generate(
        Path(args.scenario),
        Path(args.out),
        args.name,
        args.split_buffers,
        args.bugreport,
    )
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        for path in info["files"]:
            print(path)
        if info["expect"]:
            print(info["expect"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
