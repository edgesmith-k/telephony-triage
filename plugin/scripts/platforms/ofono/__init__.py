"""oFono 플랫폼 — **뼈대**(17-platforms 설계 §5). 형식 가정(placeholder)이다.

실제 로그 형식·태그·짝 규칙은 사용자가 사내 로그를 구한 뒤 정한다. 지금은 레지스트리·플랫폼 선택·이슈 DB 분리·
파서 전환이 실제로 되는지를 합성 로그로 보이는 최소 계약이다.

- 로그 줄 해석·원문 줄 판별·재부팅 표시: `journal.py`(journald/syslog/BusyBox syslogd 가정 형식, TODO(SITE:S24)).
- 짝 규칙(`protocols`): 코드 기본은 upstream gril RIL trace 짝 `gril`(`gril.py`, tags `ofonod` — site-defaults
  `protocols.gril: {tags: [...]}`로 바꾸고 `[]`면 끈다, TODO(SITE:S26)). site는 `protocols.<이름>: {kind: regex, ...}`
  (serial 짝, `pairing.py`)·`{kind: hop, upstream, ...}`(serial 없는 아래 데몬 줄을 위 짝 규칙 줄에 이름·시간 창으로 잇기,
  `hop.py`)로 짝 규칙을 더 만든다(기본 없음 — `gril` 뒤에 적은 순서로 붙는다). 슬롯 표기: gril 줄 앞 `[<slot>,`·모뎀 경로
  `/ril_<n>`(`gril.py`, TODO(SITE:S29) — 데몬마다 다른 표기는 사내 확인 뒤 site `log.phone_id`로). 묶음 입력(capture): 없음.
- 구성요소(데몬, 17-platforms §9): 코드 기본은 공개 upstream `ofonod` 하나(DBG 앞머리 가정 `file_func`).
  사내 데몬 목록·ident·소스 루트 키는 site-defaults `components.<이름>`, TODO(SITE:S24·S25·S27). 메시지 하위 형식
  함수는 `msgformat.py`.
- 소스 트리: TODO(SITE:S27). 파서 백엔드: `ofono_reference`(`backend.py`, `parser_backends/ofono_reference`).

표준 라이브러리와 이 패키지의 하위 모듈, `platforms.base`만 import한다(guard가 레지스트리로 불러온다.
`backend.py`는 불러오지 않는다 — 백엔드는 `parser_backends.<SPEC.default_backend>`가 고른다).
"""

import re

from platforms.base import Component, LogFormat, PairProtocol, PhoneIdRules, PlatformSpec, SourceTree, TemplateMeta

from . import gril, hop, journal, msgformat, pairing, template

SPEC = PlatformSpec(
    name="ofono",
    label="oFono",
    log=LogFormat(
        read_file=journal.read_file,
        raw_line=journal.raw_line,
        find_raw=journal.find_raw,
        epoch_break=journal.epoch_break,
    ),
    phone=PhoneIdRules((), (gril.SLOT_PREFIX_RE,), (gril.MODEM_PATH_RE,)),                   # TODO(SITE:S29)
    protocols=(PairProtocol(gril.NAME, frozenset(gril.TAGS), gril.annotate, gril.pair),),   # TODO(SITE:S26)
    source_tree=SourceTree(("src",), (("configure.ac", re.compile(r"AC_INIT\(\[?ofono\]?,\s*\[?(\d+)")),)),
    primary_root="ofono",
    default_root_keys=("ofono",),
    capture=None,
    default_backend="ofono_reference",
    block_keys=("source_tree", "log", "protocols", "components"),
    components=(Component("ofono", ("ofonod",), root_key="ofono", msg_format="file_func"),),   # TODO(SITE:S24·S25)
    msg_formats=msgformat.FORMATS,
    protocol_kinds=((pairing.KIND, pairing.build), (hop.KIND, hop.build)),
    # 모듈 스킬 템플릿·모듈 eval 자료(17-platforms §10-3). layers는 module_eval 출력 형식의 한 줄 — 바이트가 시험으로 고정돼 있다
    template=TemplateMeta(
        names=re.compile(r"ofonod|org\.ofono\.|\bgril\b"),                     # Android 문서에 없어야 하는 oFono 이름(S11)
        layers=("<관리 데몬 | D-Bus | ofonod | 벤더 RIL(<데몬>) | 모뎀·망 | 곁가지(<데몬>) | 그 층 로그 없음(<층>) "
                "| 원인 아님(정상 동작)>"),
        builtin_docs={"pre": (("platforms/ofono/log-guide.md", "builtin/platforms/ofono/log-guide.md"),),
                      "post": (("platforms/ofono/log-guide.md", "builtin/platforms/ofono/log-guide.md"),)},
        equals_live=(("platforms/ofono/log-guide.md", "platforms/ofono/log-guide.md"),),
        deep_baseline_note="deep without arm은 지금 oFono에 분석 스킬이 없어 log-guide.md만 준 구성 기준선이다",
        doc_checks=(template.daemon_table_check, template.dbus_check),
    ),
)
