"""ofono_reference 파서 백엔드 — **뼈대**(17-platforms 설계 §5). 형식 가정(placeholder)이다, TODO(SITE:S24·S26).

android reference 백엔드(`platforms/android/backend.py`)와 같은 구조(파일 → 에포크 → 레코드 → 프로토콜별 짝 →
윈도우 → 정렬)를 플랫폼 중립으로 다시 썼다. android 모듈은 import하지 않는다.

- 줄 해석: `SPEC.log`(`journal.py`). 시계 이상 기준은 `common.logtime`.
- 짝 규칙: `configure(profile)`이 받은 `PairProtocol` 목록(`profile.protocols`, 비면 `SPEC.protocols` — SPEC 기본은
  내장 `gril`(`gril.py`), site 설정 `kind: regex`는 `pairing.py`, `kind: hop`은 `hop.py`). 줄마다 **처음 맞는** 프로토콜의
  주석을 이벤트 `ril` 칸에 쓰고, `name != "ril"`이면 `proto: <name>`을 단다. 짝은 프로토콜마다 **목록 순서로** 수집 구간
  전체(모든 데몬 줄)에 `pair(records)`를 부른다 — 각 `pair`는 자기 주석만 바꾼다(`PairProtocol` 계약, `reads`의 앞 프로토콜
  주석은 읽기만). 그래서 데몬 사이 짝은 한 스트림 안에서만 된다.
- 구성요소(17-platforms §9): `profile.components`의 ident → 구성요소. `msg_format`이 있으면 그 함수가 뗀 본문으로
  짝 규칙을 보고(이벤트 `msg`는 원문), `split_tag`면 이벤트 tag를 `ident/subtag`로 쓴다(이벤트 tag는 마스킹되지
  않으므로 `subtag`가 `SUBTAG_RE` 모양일 때만 — 아니면 나누지 않는다).
- 0.0.3: 줄 형식 (c) BusyBox syslogd(레벨은 severity)·내장 짝 `gril`·슬롯 규칙(`[<slot>,`·`/ril_<n>`)이 기본 출력을 바꾼다
  (gril trace 줄의 `ril`·`phone_id`, (c) 줄 해석). (a)·(b) 형식이고 gril 줄·`/ril_<n>`이 없는 로그의 출력은 0.0.2와 같다.
- builtin 판별(11/05 승인 ③, H C1 R12): `VENDOR_IPC_IDENTS`(`exynos-ril`, 첨부 로그에서 본 벤더 RIL 데몬 이름,
  TODO(SITE:S25)) 줄에 `common.vendor_ipc.detect`를 부른다 → `builtin.common.vendor_ipc_error`·
  `builtin.common.vendor_request_failed`. 그 밖 ident 줄은 판별하지 않는다. 이슈 DB tags.yaml에 `ipc: vendor`가 하나라도
  있으면 그 태그만 본다(`apply_rules`, 04-parser-matching §5.8 (2)).
- 레벨 보정(C1+D 보정에서 `journal.read_file`에서 옮김): `LEVEL_UNRELIABLE_IDENTS`(기본값 정본은 `journal.py`) 줄은
  severity와 상관없이 `"I"`. tags.yaml에 `level: unreliable`이 하나라도 있으면 그 태그만.
  사내 백엔드는 이 클래스를 상속해 `detect()`만 바꿔도 된다.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Sequence

from common import events, logtime, vendor_ipc
from parser_backends.base import ParserBackend, TagAttrSet, Window

from . import SPEC
from .journal import DEFAULT_LEVEL, LEVEL_UNRELIABLE_IDENTS

VERSION = "0.0.3"
# split_tag 하위 식별: 글자로 시작하는 식별자 모양만 tag에 붙인다(숫자로 시작하는 값·공백·`:`·`/`는 나누지 않음)
SUBTAG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
# 벤더 IPC 결과 판별을 부를 ident(첨부 oFono 로그의 벤더 RIL 데몬, TODO(SITE:S25)). split_tag면 `ident/subtag`도 받는다.
VENDOR_IPC_IDENTS = frozenset({"exynos-ril"})


class OfonoReferenceBackend(ParserBackend):
    name = "ofono_reference"
    platform = "ofono"

    # 슬롯 규칙·짝 규칙. `configure(profile)`이 바꾼 복사본에만 들어간다 (전역 상태 없음).
    _phone = SPEC.phone
    _protocols: tuple = tuple((p, frozenset(p.default_tags)) for p in SPEC.protocols)
    _components: dict = {}   # ident → (Component, 형식 함수 | None). 아래에서 SPEC 기본으로 채운다
    # 태그 속성 판단(`apply_rules`가 사본에 새로 만든다). 기본은 상수 집합.
    _level_unreliable = TagAttrSet(None, "level", "unreliable", LEVEL_UNRELIABLE_IDENTS)
    _vendor_ipc = TagAttrSet(None, "ipc", "vendor", VENDOR_IPC_IDENTS)

    @staticmethod
    def _component_map(components, spec) -> dict:
        formats = dict(spec.msg_formats)
        return {ident: (comp, formats.get(comp.msg_format) if comp.msg_format else None)
                for comp in components for ident in comp.idents}

    def configure(self, profile) -> "OfonoReferenceBackend":
        other = copy.copy(self)
        other._phone = profile.phone
        tags = dict(profile.protocol_tags)
        spec = profile.spec or SPEC
        protocols = profile.protocols or spec.protocols     # 손으로 만든 PlatformProfile(테스트)은 protocols가 비어 있다
        other._protocols = tuple((p, tags.get(p.name, frozenset(p.default_tags))) for p in protocols)
        other._components = self._component_map(profile.components, spec)
        return other

    def apply_rules(self, rules) -> "OfonoReferenceBackend":
        """tags.yaml `level: unreliable`·`ipc: vendor`(04-parser-matching §5.8 (2)). 키마다 DB가 하나도 선언하지 않으면
        기본 상수(`LEVEL_UNRELIABLE_IDENTS`·`VENDOR_IPC_IDENTS`), 하나라도 선언하면 DB만 본다."""
        other = copy.copy(self)
        other._level_unreliable = TagAttrSet(rules, "level", "unreliable", LEVEL_UNRELIABLE_IDENTS)
        other._vendor_ipc = TagAttrSet(rules, "ipc", "vendor", VENDOR_IPC_IDENTS)
        return other

    def version(self) -> str:
        return VERSION

    def builtin_events(self) -> list[str]:
        return list(vendor_ipc.EVENTS)

    def log_format(self):
        return SPEC.log

    def detect(self, record: dict) -> list[tuple[str, dict]]:
        """줄 레코드 하나에 대한 builtin 판별 `[(이벤트 이름, fields)]`. 벤더 RIL 데몬 줄(`_vendor_ipc`: 기본
        `VENDOR_IPC_IDENTS`, tags.yaml `ipc: vendor`가 있으면 그것)의 IPC 결과만 본다."""
        tag = record.get("tag") or ""
        if not self._vendor_ipc(tag, tag.split("/", 1)[0]):
            return []
        return vendor_ipc.detect(record.get("msg") or "")

    def _annotate(self, tag: str, msg: str) -> dict | None:
        for proto, tags in self._protocols:
            ann = proto.annotate(tag, msg, tags, self._phone)
            if ann:
                return ann if proto.name == "ril" else {**ann, "proto": proto.name}
        return None

    def _view(self, line) -> tuple[str, str]:
        """(이벤트 tag, 짝 규칙 입력 본문). 구성요소 형식이 없거나 맞지 않으면 원문 그대로."""
        hit = self._components.get(line.tag)
        if hit is None or hit[1] is None or not (self._protocols or hit[0].split_tag):
            return line.tag, line.msg
        view = hit[1](line.msg)
        if view is None:
            return line.tag, line.msg
        split = hit[0].split_tag and isinstance(view.subtag, str) and SUBTAG_RE.fullmatch(view.subtag)
        tag = f"{line.tag}/{view.subtag}" if split else line.tag
        return tag, view.body

    def _line_record(self, line) -> dict:
        tag, body = self._view(line)
        rec = events.make_event(
            ts=logtime.format_ts(line.dt),
            pid=line.pid,
            tid=line.tid,
            level=DEFAULT_LEVEL if self._level_unreliable(tag, line.tag) else line.level,
            tag=tag,
            msg=line.msg,
            phone_id=self._phone.phone_id(line.tag, line.msg),
            ril=self._annotate(line.tag, body),
            source=f"{events.BACKEND_PREFIX}{self.name}",
            line_ref=events.line_ref(line.file_index, line.line_no),
        )
        rec.update({"_dt": line.dt, "_file": line.file_index, "_line": line.line_no, "_sub": 0})
        return rec

    def _builtin_record(self, base: dict, event: str, fields: dict, sub: int) -> dict:
        parts = event.split(".")
        rec = dict(base)
        rec.update({
            "category_hint": parts[1] if len(parts) >= 3 and parts[0] == "builtin" else None,
            "ril": None,
            "event": event,
            "fields": {k: str(v) for k, v in fields.items() if v is not None},
            "_sub": sub,
        })
        return rec

    def parse(self, paths: Sequence[str | Path], tz: str | None, year: int | None, window: Window | None) -> list[dict]:
        log = self.log_format()
        streams: dict[tuple, list[list[dict]]] = {}
        for index, path in enumerate(paths):
            lines, _ = log.read_file(path, index, tz, year)
            # 같은 디렉토리의 관례적 회전 이름(syslog, syslog.1)만 한 수집으로 잇는다.
            path = Path(path).resolve()
            stem = re.sub(r"[._-]\d+(?=\.log$)", "", re.sub(r"\.\d+$", "", path.name))
            chunks: dict[int, list[dict]] = {}
            prev, epoch = None, 0
            for line in lines:
                delta = (line.dt - prev).total_seconds() if prev else 0
                if (delta < -logtime.BACKWARD_THRESHOLD_SEC or delta >= logtime.JUMP_THRESHOLD_SEC
                        or log.epoch_break(line)):
                    epoch += 1
                prev = line.dt
                chunks.setdefault(epoch, []).append(self._line_record(line))
            for segment, records in chunks.items():
                # 불연속이 있는 파일은 다른 파일과 잇지 않는다.
                streams.setdefault((path.parent, stem, (index, segment) if epoch else None), []).append(records)
        out: list[dict] = []
        for chunks in streams.values():
            chunks.sort(key=lambda records: records[0]["_dt"])
            segments, current = [], []
            for chunk in chunks:
                gap = (chunk[0]["_dt"] - current[-1]["_dt"]).total_seconds() if current else 0
                if current and (gap < 0 or gap >= logtime.JUMP_THRESHOLD_SEC):
                    segments.append(current)
                    current = []
                current.extend(chunk)
            if current:
                segments.append(current)
            for records in segments:
                for proto, _tags in self._protocols:   # 윈도우를 자르기 전에 수집 전체로 짝짓는다
                    proto.pair(records)
                out.extend(records)
        selected: list[dict] = []
        for rec in out:
            if window and not (window[0] <= rec["_dt"] <= window[1]):
                continue
            selected.append(rec)
            for sub, (event, fields) in enumerate(self.detect(rec), 1):
                selected.append(self._builtin_record(rec, event, fields, sub))
        selected.sort(key=lambda r: (r["_dt"], r["_file"], r["_line"], r["_sub"]))
        return [{k: v for k, v in rec.items() if not k.startswith("_")} for rec in selected]


OfonoReferenceBackend._components = OfonoReferenceBackend._component_map(SPEC.components, SPEC)

BACKEND = OfonoReferenceBackend()
