"""ofono_reference 파서 백엔드 — **뼈대**(17-platforms 설계 §5). 형식 가정(placeholder)이다, TODO(SITE:S24·S26).

android reference 백엔드(`platforms/android/backend.py`)와 같은 구조(파일 → 에포크 → 레코드 → 프로토콜별 짝 →
윈도우 → 정렬)를 플랫폼 중립으로 다시 썼다. android 모듈은 import하지 않는다.

- 줄 해석: `SPEC.log`(`journal.py`). 시계 이상 기준은 `common.logtime`.
- 짝 규칙: `configure(profile)`이 받은 `PairProtocol` 목록(SPEC 기본은 없음). 줄마다 **처음 맞는** 프로토콜의
  주석을 이벤트 `ril` 칸에 쓰고, `name != "ril"`이면 `proto: <name>`을 단다. 짝은 프로토콜마다
  `pair(records)`를 부른다 — 각 `pair`는 자기 주석만 다룬다(`PairProtocol` 계약).
- builtin 판별 없음(`detect()` → []). 사내 백엔드는 이 클래스를 상속해 `detect()`만 바꿔도 된다.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Sequence

from common import events, logtime
from parser_backends.base import ParserBackend, Window

from . import SPEC

VERSION = "0.0.1"


class OfonoReferenceBackend(ParserBackend):
    name = "ofono_reference"
    platform = "ofono"

    # 슬롯 규칙·짝 규칙. `configure(profile)`이 바꾼 복사본에만 들어간다 (전역 상태 없음).
    _phone = SPEC.phone
    _protocols: tuple = tuple((p, frozenset(p.default_tags)) for p in SPEC.protocols)

    def configure(self, profile) -> "OfonoReferenceBackend":
        other = copy.copy(self)
        other._phone = profile.phone
        tags = dict(profile.protocol_tags)
        spec = profile.spec or SPEC
        other._protocols = tuple((p, tags.get(p.name, frozenset(p.default_tags))) for p in spec.protocols)
        return other

    def version(self) -> str:
        return VERSION

    def builtin_events(self) -> list[str]:
        return []

    def log_format(self):
        return SPEC.log

    def detect(self, record: dict) -> list[tuple[str, dict]]:
        """줄 레코드 하나에 대한 builtin 판별 `[(이벤트 이름, fields)]`. 뼈대에는 없다."""
        return []

    def _annotate(self, tag: str, msg: str) -> dict | None:
        for proto, tags in self._protocols:
            ann = proto.annotate(tag, msg, tags, self._phone)
            if ann:
                return ann if proto.name == "ril" else {**ann, "proto": proto.name}
        return None

    def _line_record(self, line) -> dict:
        rec = events.make_event(
            ts=logtime.format_ts(line.dt),
            pid=line.pid,
            tid=line.tid,
            level=line.level,
            tag=line.tag,
            msg=line.msg,
            phone_id=self._phone.phone_id(line.tag, line.msg),
            ril=self._annotate(line.tag, line.msg),
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


BACKEND = OfonoReferenceBackend()
