"""reference 파서 백엔드 (16-existing-assets.md §16.3).

공통 처리(포맷·시각·RIL 페어링·윈도우)는 제품 수준이다. builtin 판별은 벤더 RIL IPC 결과
둘뿐이다(H C1+D R12·S17): `VENDOR_IPC_TAGS`(`RIL`) 줄을 `common.vendor_ipc.detect`에 넘겨
`builtin.common.vendor_ipc_error`·`builtin.common.vendor_request_failed`를 낸다. 태그 규칙(tags.yaml)과
무관하게 나온다(태그 묶음이 없는 DB에서도 같다). 태그 이름·줄 모양은 첨부 로그에서 본 것이며 사내에서 조정한다
(TODO(SITE:S9)). site 백엔드는 이 클래스를 상속해 `detect()`·`builtin_events()`를 바꾸면 공통 처리를 그대로
재사용한다(벤더 이벤트도 원하면 `super().detect()`를 합친다).

구현 위치는 `platforms/android/backend.py`이고 `parser_backends/reference`는 BACKEND만 다시 내보낸다.
"""

from __future__ import annotations

import copy
from pathlib import Path
import re
from typing import Sequence

from common import events, vendor_ipc
from . import logcat, ril
from parser_backends.base import ParserBackend, Window

VERSION = "0.1.0"

# 벤더 IPC 결과 줄을 보는 태그(첨부 로그 A의 벤더 RIL 태그). TODO(SITE:S9) 사내 태그 확인
VENDOR_IPC_TAGS = frozenset({"RIL"})


class ReferenceBackend(ParserBackend):
    name = "reference"

    # 슬롯 표기·RIL 태그. `configure(profile)`이 바꾼 복사본에만 들어간다 (전역 상태 없음).
    _phone = logcat.DEFAULT_PHONE_RULES
    _ril_tags = ril.RIL_TAGS
    _ril_vendor = None

    def configure(self, profile) -> "ReferenceBackend":
        other = copy.copy(self)
        other._phone = profile.phone
        other._ril_tags = profile.ril_tags
        other._ril_vendor = profile.ril_vendor
        return other

    def version(self) -> str:
        return VERSION

    def builtin_events(self) -> list[str]:
        return list(vendor_ipc.EVENTS)

    def detect(self, record: dict) -> list[tuple[str, dict]]:
        """줄 레코드 하나에 대한 builtin 판별 `[(이벤트 이름, fields)]`.
        reference는 `VENDOR_IPC_TAGS` 줄의 벤더 IPC 결과만 본다. site 백엔드가 바꾼다."""
        if record.get("tag") not in VENDOR_IPC_TAGS:
            return []
        return vendor_ipc.detect(record.get("msg") or "")

    # -- 공통 처리 ---------------------------------------------------------

    def _line_record(self, line: logcat.LogLine) -> dict:
        rec = events.make_event(
            ts=logcat.format_ts(line.dt),
            pid=line.pid,
            tid=line.tid,
            level=line.level,
            tag=line.tag,
            msg=line.msg,
            phone_id=self._phone.phone_id(line.tag, line.msg),
            ril=ril.parse(line.tag, line.msg, tags=self._ril_tags, phone=self._phone),
            source=f"{events.BACKEND_PREFIX}{self.name}",
            # 입력 목록 순번과 물리 줄 번호(1부터). 04-parser-matching.md §5.8 (6).
            line_ref=events.line_ref(line.file_index, line.line_no),
        )
        rec.update({"_dt": line.dt, "_file": line.file_index, "_line": line.line_no, "_sub": 0})
        return rec

    def _builtin_record(self, base: dict, event: str, fields: dict, sub: int) -> dict:
        parts = event.split(".")
        rec = dict(base)
        rec.update(
            {
                "category_hint": parts[1] if len(parts) >= 3 and parts[0] == "builtin" else None,
                "ril": None,
                "event": event,
                "fields": {k: str(v) for k, v in fields.items() if v is not None},
                "_sub": sub,
            }
        )
        return rec

    def parse(
        self,
        paths: Sequence[str | Path],
        tz: str | None,
        year: int | None,
        window: Window | None,
    ) -> list[dict]:
        out: list[dict] = []
        streams: dict[tuple, list[list[dict]]] = {}
        for index, path in enumerate(paths):
            lines, _ = logcat.read_file(path, index, tz, year)
            # Only conventional rotation names in the same directory share a capture.
            path = Path(path).resolve()
            stem = re.sub(r"\.\d+$", "", path.name)
            stem = re.sub(r"[._-]\d+(?=\.log$)", "", stem)
            chunks: dict[tuple, list[dict]] = {}
            prev, epoch = None, 0
            for line in lines:
                delta = (line.dt - prev).total_seconds() if prev else 0
                if (delta < -logcat.BACKWARD_THRESHOLD_SEC or delta >= logcat.JUMP_THRESHOLD_SEC
                        or logcat.epoch_break(line)):
                    epoch += 1
                prev = line.dt
                chunks.setdefault(epoch, []).append(self._line_record(line))
            for segment, records in chunks.items():
                # 불연속이 있는 파일은 다른 파일과 잇지 않는다.
                key = (path.parent, stem, (index, segment) if epoch else None)
                streams.setdefault(key, []).append(records)
        for chunks in streams.values():
            chunks.sort(key=lambda records: records[0]["_dt"])
            segments, current = [], []
            for chunk in chunks:
                gap = (chunk[0]["_dt"] - current[-1]["_dt"]).total_seconds() if current else 0
                if current and (gap < 0 or gap >= logcat.JUMP_THRESHOLD_SEC):
                    segments.append(current)
                    current = []
                current.extend(chunk)
            if current:
                segments.append(current)
            for records in segments:
                ril.pair(records)  # Pair the entire capture before window filtering.
                out.extend(records)
        records, out = out, []
        if self._ril_vendor:  # 벤더 줄은 다른 에포크·파일일 수 있어 전체 레코드로 한 번
            ril.link_vendor(records, self._ril_vendor)
        for rec in records:
            if window and not (window[0] <= rec["_dt"] <= window[1]):
                continue
            out.append(rec)
            for sub, (event, fields) in enumerate(self.detect(rec), 1):
                out.append(self._builtin_record(rec, event, fields, sub))
        out.sort(key=lambda r: (r["_dt"], r["_file"], r["_line"], r["_sub"]))
        return [{k: v for k, v in rec.items() if not k.startswith("_")} for rec in out]


BACKEND = ReferenceBackend()
