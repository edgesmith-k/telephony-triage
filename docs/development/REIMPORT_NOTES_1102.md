# 재반입 노트 — 11/02 oFono BusyBox syslog·gril 짝·벤더 앞머리·마스킹 보강

`REIMPORT_NOTES_1030.md` 뒤 묶음에 함께 들어간다. 절차는 `docs/SITE_INSTALL.md §8`. 설계는 `docs/design/17-platforms.md §8·§9·§11-2`(K19), 마스킹은 `08-safety.md §8`.

배경: 사용자가 사외에서 공개 oFono 계열 장비 로그 2개(사용자 확인: 사내 로그 아님)를 주어 지금 뼈대가 그 형식을 한 줄도 읽지 못하는 것(형식 미확인)을 확인했다. 표본에서는 **모양만** 보았고, 표본의 줄·값·데몬 이름(`ofonod` 제외)·호스트·D-Bus 이름은 레포(코드·fixture·테스트·문서)에 넣지 않았다. fixture는 손으로 쓴 합성(`tests/fixtures/logs/ofono/syslog-busybox.log`)이다.

## 1. 바뀐 것

| 영역 | 바뀐 것 | 사내에서 할 일 |
|---|---|---|
| oFono 줄 형식 | (c) BusyBox syslogd(`/var/log/messages`·`logread`): `Mon DD HH:MM:SS.mmm <host> <facility>.<severity> <ident>[<pid>]: <msg>`. severity → 레벨(debug D, info·notice I, warn W, err E, crit·alert·emerg F), facility는 버림, 호스트 `(none)` 허용. `tail: ` 안내 줄은 건너뜀. 직렬 콘솔 `\r\r\n` 캡처도 읽는다(`line_no`만 2배, P2) | 사내 로그가 (c)인지·facility/severity 목록·연도·타임존(S24). 형식 판별(`raw_line`)도 함께 바뀐다 |
| 내장 짝 `gril` | ofono `SPEC.protocols` 기본 = upstream gril RIL trace(`[<slot>,<serial>]> RIL_REQUEST_X`·`< … [failed ERR]`·`[<slot>,UNSOL]< RIL_UNSOL_X`), tags `ofonod`. 이름은 Android와 같게(`X`·`UNSOL_X`), 짝은 Android `ril.pair`와 같은 의미, `proto: gril`. 파생 `ril_error`·`ril_timeout`·`ril_no_response`는 DB `ril.yaml`에 이름이 있을 때 | 사내 `ofonod`가 이 trace를 내는지(디버그 옵션·앞머리), 실패 표기(S26). 다른 ident면 `protocols.gril: {tags: [...]}`, 안 쓰면 `tags: []`. oFono 이슈 DB `ril.yaml`에 쓰는 요청 이름·timeout |
| 슬롯 | ofono `SPEC.phone` 기본: 줄 앞 `[<slot>,`(DBG 앞머리 `x.c:func() ` 뒤도)·모뎀 경로 `/ril_<n>` → `phone_id` | 데몬마다 표기·0/1 기준이 달라 그 밖은 기본에 넣지 않았다(S29). site `log.phone_id`를 쓰면 목록이 통째로 바뀌므로 gril 규칙을 함께 둔다 |
| 메시지 형식 | `msg_format` 4개 추가: `tid_file_paren`·`level_tid_file`·`slot_level_seq`·`src_suffix`(벤더 앞머리 모양, 데몬 이름 없음) | 데몬마다 어느 형식인지 정해 `components.<이름>.msg_format`(S24·S25) |
| 마스킹(Android 공통) | 가림 추가: `ICCID(<값>)`·`iccid[<값>]`, 주소 키 바로 뒤 IPv6(`addr:<v6>`, `/64`)·끝이 `:`인 잘린 IPv6·줄 경계 IPv6 조각(6묶음 이상, `::` 없음). 가림 해제: `token=`의 짧은 숫자(10진 10자리 이하·`0x`+16진 8자리 이하 — RIL 요청 token), 벤더 데이터 콜 객체 `PdpContext{…}`·`PdnInfo:`·`PDN_INFO*`의 `cid`(11/02 사용자 승인) | 사내 로그로 오탐·누락 확인(S13). `mask_pii --check` 결과가 바뀔 수 있다(아래 2) |
| `site_checks` | `o2.config` 근거 `짝 규칙 N(설정) · 내장 gril`(끄면 `(끔)`), `o2.pairs`는 내장 짝 0만으로 실패하지 않음(설정 짝도 없고 내장 짝도 0이면 지금처럼 사용자 필요) | — |
| 파서 백엔드 | `ofono_reference` **0.0.3**(기본 출력 변경) | oFono 분석 재사용 캐시가 한 번 바뀐다. oFono 이슈 DB `parser_backend.min_version`을 올릴지 결정 |

## 2. Android 영향

- 줄 해석·짝·출력: 바뀌지 않는다(oFono 모듈만 바뀜).
- 마스킹: 위 모양이 든 줄만 바뀐다 — `token=<짧은 숫자>`가 그대로 남고, 객체 안 `cid`가 남고, 괄호 ICCID·키 뒤 IPv6가 새로 가려진다. 같은 파일에서 뒤 토큰 번호가 당겨질 수 있다. 레포의 fixture·샘플 DB·skill_evals 로그·문서는 바이트 그대로다(골든·`db_regress` 샘플 불변). 문맥 없는 IPv6 형식 규칙은 바이트 그대로 상수로 옮겼다.
- 이미 마스킹해 둔 사내 파일: 다시 `mask_pii`를 돌리면 키 뒤 IPv6·괄호 ICCID가 새로 가려질 수 있다(`--check`가 새로 잡을 수 있음). 반대로 이미 `<CRED#n>`·`<CELL#n>`이 된 짧은 token·객체 cid는 되돌아가지 않는다.

## 3. 테스트

- `python3 -m pytest -q tests`. 새 `tests/test_ofono_gril.py`, `test_ofono_skeleton.py`((c) 형식)·`test_ofono_components.py`(형식 4개)·`test_masking.py`·`test_platform_detect.py`·`test_site_checks.py` 보강. oFono 변형 DB(`issue-db-ofono`) `ril.yaml`에 `SETUP_DATA_CALL`·`DEACTIVATE_DATA_CALL`·`UNSOL_DATA_CALL_LIST_CHANGED` placeholder.
- `plugin/skills/**`는 바꾸지 않았다(oFono `log-guide.md` 보강은 §5).

## 4. 반입 뒤 후보 (P2)

syslog 줄 여러 개로 잘린 긴 메시지 잇기, `open_log`(`newline=""`)의 `\r` 줄 나눔(`line_no` 2배 — Android 공유라 따로 결정), D-Bus `dump_dmsg` 짝, 슬롯 없는 옛 gril `[%04d]>`, `[Class::Method]` 형식, klogd 시각이 붙은 커널 배너의 `epoch_break`, `key:` 바로 뒤 MAC 누락, 1묶음 압축 IPv6 과잉 마스킹(C++ `std::string`의 `d::s`), gril·Android 짝 코드 공용화. 위험: 응답 본문이 대문자 낱말 하나뿐인 줄은 오류로 보지 않는다(`failed`가 있어야 오류, S26).

리뷰(11/02)에서 더한 것: `token` 완화는 문맥을 보지 않는다(짧은 숫자 OTP·인증 헤더 값도 남는다 — RIL 문맥으로 좁힐지 사내 보안 기준으로 검토), BusyBox 이름표 밖 facility(12~15)는 `<pri>`로 찍혀 그 줄을 해석하지 못한다, `-S`·`(none)` 호스트 조합은 (b)에서 거부된다, (a)·(b) unparsed 수는 `tail:` 건너뛰기만큼 줄 수 있다. 수정한 것: `--mask`에서 짝 주석 값(`NONE` 등)이 앞 줄에서 가린 같은 글자의 토큰이 되어 가짜 `ril_error`가 나던 것(이전부터 있던 결함, gril 기본으로 노출이 넓어짐 — 짝 값은 텍스트 규칙으로만 마스킹), `PDN_INFO` 예외를 `PDN_INFO_EXT`까지로, `src_suffix`는 끝 512자만 본다.

## 5. 후속: `kind: hop`·oFono 탐색 지식

같은 묶음(import-20261102)이라 `ofono_reference`는 0.0.3 그대로다(설정이 없으면 출력이 PR 앞과 바이트 단위로 같다). 설계는 `17-platforms.md §9-3`(K20)·§10-2.

| 영역 | 바뀐 것 | 사내에서 할 일 |
|---|---|---|
| 짝 규칙 `kind: hop` | `protocols.<이름>: {kind: hop, upstream, tags, request, response, fold, window_ms}` — serial 없는 아래 데몬 줄(요청 이름만 남기는 벤더 RIL 등)을 위 짝 규칙(기본 `gril`) 줄에 이름·시간 창으로 잇는다. 아래 줄에만 주석 `dir: hop_req`·`hop_resp`(연결되면 위 serial·정규 이름·`paired_ts`·`latency_ms`), 일대일 nearest, 기본 창 50ms(1~1000), 파생 이벤트 없음 | 아래 데몬 줄 모양으로 정규식(S26), 이름 표기가 다르면 `fold: true`, 창은 실제 지연으로(100 이하 권장), 아래 데몬 슬롯 표기(S29). 연결 수는 `site_step.py ofono` O-2 `o2.pairs` |
| 계약 | `PairProtocol.reads`(기본 `()`): 읽기만 하는 앞 프로토콜. 레지스트리가 목록 순서를 확인(`upstream`이 앞에 없으면 키 경로와 종료 코드 2) | — |
| `site_checks` | `o2.pairs` 근거에 `<이름> 연결 L/아래 줄 D(위 <upstream> 요청 U)`, 연결 0이면 사용자 필요, 안내에 `kind: hop` | — |
| 탐색 지식 | `reference/platforms/ofono/log-guide.md`: 줄 모양(형식 (c)·gril trace·`dump_dmsg`), 계층(앱 → D-Bus → `ofonod` → RIL → 벤더 RIL → 모뎀), "위에서 본 오류는 한 층씩 내려가 처음 실패한 층" 규칙. 데몬 이름 없음 | 사내 데몬·계층으로 placeholder를 채울지(S24~S26, 사이트 지식 스킬은 S-4a) |

Android 영향: 없다(oFono 모듈·`PairProtocol` 기본값 필드만, Android SPEC 프로토콜의 `reads`는 `()`). 골든·`db_regress` 샘플·fixture는 바이트 그대로다.

테스트: 새 `tests/test_ofono_hop.py`·fixture `tests/fixtures/logs/ofono/syslog-hop.log`(합성), `test_ofono_components.py`·`test_ofono_skeleton.py`·`test_platform_registry.py`·`test_site_checks.py` 보강.

P2: 짝 규칙이 없는 데몬 줄을 위로 쓰기(`upstream: {tags, match}` — 공개 표본 IMS 계층), unsol 연결, FIFO 옵션(같은 이름이 몰린 구간에서 nearest와 다를 수 있다), `timeline.md`에 연결 표시. 위험: 창이 클수록 가짜 연결(공개 표본 50ms ≤3, 200ms ≤18), 위 규칙을 끄거나 아래 tags가 앞 규칙과 겹치면 연결 0, 응답 쪽 아래 줄 대부분은 다른 RIL 클라이언트 것이라 미연결이 많은 것이 정상이다.
