# 재반입 노트 — 11/02 oFono BusyBox syslog·gril 짝·벤더 앞머리·마스킹 보강

`REIMPORT_NOTES_1030.md` 뒤 묶음에 함께 들어간다. 절차는 `docs/SITE_INSTALL.md §8`. 설계는 `docs/design/17-platforms.md §8·§9·§11-2`(K19), 마스킹은 `08-safety.md §8`.

배경: 지금 뼈대가 BusyBox syslogd 등 oFono 계열 줄 형식을 한 줄도 읽지 못하는 것(형식 미확인)을 확인했다. **줄 모양만** 보았다. 이 노트의 줄 수·건수·ms 수치는 그때 잰 값이다(현재 합성 fixture로 다시 잰 값이 아니다). 레포(코드·fixture·테스트·문서)의 줄·값·데몬 이름(`ofonod` 제외)·호스트·D-Bus 이름은 합성·placeholder이고, fixture는 손으로 쓴 합성(`tests/fixtures/logs/ofono/syslog-busybox.log`)이다. 사내 값은 사내에서 SITE_PATHS에 채운다.

## 1. 바뀐 것

| 영역 | 바뀐 것 | 사내에서 할 일 |
|---|---|---|
| oFono 줄 형식 | (c) BusyBox syslogd(`/var/log/messages`·`logread`): `Mon DD HH:MM:SS.mmm <host> <facility>.<severity> <ident>[<pid>]: <msg>`. severity → 레벨(debug D, info·notice I, warn W, err E, crit·alert·emerg F), facility는 버림, 호스트 `(none)` 허용. `tail: ` 안내 줄은 건너뜀. 직렬 콘솔 `\r\r\n` 캡처도 읽는다(`line_no`만 2배, P2) | 사내 로그가 (c)인지·facility/severity 목록·연도·타임존(S24). 형식 판별(`raw_line`)도 함께 바뀐다 |
| 내장 짝 `gril` | ofono `SPEC.protocols` 기본 = upstream gril RIL trace(`[<slot>,<serial>]> RIL_REQUEST_X`·`< … [failed ERR]`·`[<slot>,UNSOL]< RIL_UNSOL_X`), tags `ofonod`. 이름은 Android와 같게(`X`·`UNSOL_X`), 짝은 Android `ril.pair`와 같은 의미, `proto: gril`. 파생 `ril_error`·`ril_timeout`·`ril_no_response`는 DB `ril.yaml`에 이름이 있을 때 | 사내 `ofonod`가 이 trace를 내는지(디버그 옵션·앞머리), 실패 표기(S26). 다른 ident면 `protocols.gril: {tags: [...]}`, 안 쓰면 `tags: []`. oFono 이슈 DB `ril.yaml`에 쓰는 요청 이름·timeout |
| 슬롯 | ofono `SPEC.phone` 기본: 줄 앞 `[<slot>,`(DBG 앞머리 `x.c:func() ` 뒤도)·모뎀 경로 `/ril_<n>` → `phone_id` | 데몬마다 표기·0/1 기준이 달라 그 밖은 기본에 넣지 않았다(S29). site `log.phone_id`를 쓰면 목록이 통째로 바뀌므로 gril 규칙을 함께 둔다 |
| 메시지 형식 | `msg_format` 4개 추가: `tid_file_paren`·`level_tid_file`·`slot_level_seq`·`src_suffix`(벤더 앞머리 모양, 데몬 이름 없음) | 데몬마다 어느 형식인지 정해 `components.<이름>.msg_format`(S24·S25) |
| 마스킹(Android 공통) | 가림 추가: `ICCID(<값>)`·`iccid[<값>]`, 주소 키 바로 뒤 IPv6(`addr:<v6>`, `/64`)·끝이 `:`인 잘린 IPv6·줄 경계 IPv6 조각(6묶음 이상, `::` 없음). 가림 해제: `token=`의 짧은 숫자(10진 10자리 이하·`0x`+16진 8자리 이하 — RIL 요청 token), 맨 `cid` 키 전부(데이터 콜 context id — 객체 안·밖, 11/02 사용자 결정, §6. `mCid` 등 셀 위치 키는 가린다) | 사내 로그로 오탐·누락 확인(S13). `mask_pii --check` 결과가 바뀔 수 있다(아래 2) |
| `site_checks` | `o2.config` 근거 `짝 규칙 N(설정) · 내장 gril`(끄면 `(끔)`), `o2.pairs`는 내장 짝 0만으로 실패하지 않음(설정 짝도 없고 내장 짝도 0이면 지금처럼 사용자 필요) | — |
| 파서 백엔드 | `ofono_reference` **0.0.3**(기본 출력 변경) | oFono 분석 재사용 캐시가 한 번 바뀐다. oFono 이슈 DB `parser_backend.min_version`을 올릴지 결정 |

## 2. Android 영향

- 줄 해석·짝·출력: 바뀌지 않는다(oFono 모듈만 바뀜).
- 마스킹: 위 모양이 든 줄만 바뀐다 — `token=<짧은 숫자>`·맨 `cid` 값이 그대로 남고, 괄호 ICCID·키 뒤 IPv6가 새로 가려진다. 같은 파일에서 뒤 토큰 번호가 당겨질 수 있다. 레포의 fixture·샘플 DB·skill_evals 로그·문서는 바이트 그대로다 — 맨 `cid` 줄만 예외로, 합성 시나리오의 `cid=1`이 이제 가려지지 않아 시나리오에서 만든 fixture 로그 6개와 이벤트 스냅샷 3개의 `cid=<CELL#1>`이 `cid=1`이 됐다(§6). 골든(원본 시나리오 기준)·`.expect.yaml`·`db_regress` 판정은 그대로다. 문맥 없는 IPv6 형식 규칙은 바이트 그대로 상수로 옮겼다.
- 이미 마스킹해 둔 사내 파일: 다시 `mask_pii`를 돌리면 키 뒤 IPv6·괄호 ICCID가 새로 가려질 수 있다(`--check`가 새로 잡을 수 있음). 반대로 이미 `<CRED#n>`·`<CELL#n>`이 된 짧은 token·`cid`는 되돌아가지 않는다(`--check`는 맨 `cid`를 더 이상 잡지 않는다).

## 3. 테스트

- `python3 -m pytest -q tests`. 새 `tests/test_ofono_gril.py`, `test_ofono_skeleton.py`((c) 형식)·`test_ofono_components.py`(형식 4개)·`test_masking.py`·`test_platform_detect.py`·`test_site_checks.py` 보강. oFono 변형 DB(`issue-db-ofono`) `ril.yaml`에 `SETUP_DATA_CALL`·`DEACTIVATE_DATA_CALL`·`UNSOL_DATA_CALL_LIST_CHANGED` placeholder.
- `plugin/skills/**`는 바꾸지 않았다(oFono `log-guide.md` 보강은 §5).

## 4. 반입 뒤 후보 (P2)

애플리케이션이 여러 줄로 나눠 찍은 메시지 잇기·BusyBox 읽기 버퍼(기본 256B) 잘림 확인(syslogd는 긴 메시지를 다음 줄로 넘기지 않고 뒤를 버린다 — 잘린 줄은 잇지 않는다. 17 §8 P2 목록 문구도 §6에서 고쳤다), `open_log`(`newline=""`)의 `\r` 줄 나눔(`line_no` 2배 — Android 공유라 따로 결정), D-Bus 메시지 덤프 줄 짝, 슬롯 없는 옛 gril `[%04d]>`, `[Class::Method]` 형식, klogd 시각이 붙은 커널 배너의 `epoch_break`, `key:` 바로 뒤 MAC 누락, 1묶음 압축 IPv6 과잉 마스킹(C++ `std::string`의 `d::s` — 본문의 C++ 이름이 토큰이 되면 `kind: regex`·`hop` annotate의 식별자 검사에 걸려 마스킹본에서만 짝 주석이 빠질 수 있다. 형식 함수 칸은 §6에서 토큰을 받게 고쳤다), gril·Android 짝 코드 공용화. 위험: 응답 본문이 대문자 낱말 하나뿐인 줄은 오류로 보지 않는다(`failed`가 있어야 오류, S26).

리뷰(11/02)에서 더한 것: `token` 완화는 문맥을 보지 않는다(짧은 숫자 OTP·인증 헤더 값도 남는다 — RIL 문맥으로 좁힐지 사내 보안 기준으로 검토), BusyBox 이름표 밖 facility(12~15)는 `<pri>`로 찍혀 그 줄을 해석하지 못한다, `-S`·`(none)` 호스트 조합은 (b)에서 거부된다, (a)·(b) unparsed 수는 `tail:` 건너뛰기만큼 줄 수 있다. 수정한 것: `--mask`에서 짝 주석 값(`NONE` 등)이 앞 줄에서 가린 같은 글자의 토큰이 되어 가짜 `ril_error`가 나던 것(이전부터 있던 결함, gril 기본으로 노출이 넓어짐 — 짝 값은 텍스트 규칙으로만 마스킹), `src_suffix`는 끝 512자만 본다.

재리뷰(11/02)에서 더한 것(P1 2건은 §6에서 고침):
- `--mask` 짝 값 재마스킹이 부분 일치(`v in lv`)라 요청 이름·`NONE`이 같은 줄의 더 긴 가린 값(`password=NONE5`·`secret=DIALOUT1`) 안에 있으면 그 토큰이 된다 — 가짜 `ril_error`·이름 소실(원문 누출은 아님). 경계 일치로 좁히기.
- 주소 키 바로 뒤 잘린 IPv6도 조각 규칙과 같은 조건(4묶음 이상·3~4자리 묶음 2개 이상)이라 3묶음 프리픽스·짧은 묶음 위주 주소는 남는다(08-safety는 조건 없이 가린다고 적음). (기존) 앞에 낱말이 `_`로 붙은 자격증명 키(`auth_token`·`access_token`·`client_secret`)는 `\b` 경계가 없어 가리지 않는다.
- 08-safety ICCID 행이 문맥 없는 규칙(`89`로 시작 19~20자리)과 키·괄호 문맥 규칙(16진 18~20자리, `89` 시작 아님)을 한 칸에 섞어 적었다(문구만).
- `tid_file_paren`이 함수 칸 뒤 `()`(`<func>() >`)를 받지 않아 같은 데몬 줄 일부가 앞머리 떼기·`split_tag`에서 빠진다(한 데몬 53줄 중 4줄). `src_suffix` 꼬리 상한 테스트는 회귀하면 실패 대신 오래 멈춘다.
- `log.phone_id`를 덮어쓸 때 함께 둘 내장 gril 슬롯 규칙 문자열이 예시·문서에 없고, 예시 주석 "목록이 통째로 바뀐다"는 적은 키만 바뀌는 동작과 어긋난다. site `components`에서 `ofono`(ident `ofonod`, `msg_format: file_func`)를 빼면 DBG 앞머리 뒤 gril trace 줄의 짝이 조용히 빠진다(실패 응답이면 `ril_error` 대신 `ril_no_response`) — 예시·17 §9-1 경고, site 점검 후보.
- `platform-flow.html`의 gril "지연·무응답·오류 표시"에 DB `ril.yaml`에 이름이 있을 때만이라는 단서가 없고, `make_variant_dbs.py` 표의 issue-db-ofono 설명에 gril placeholder 요청이 빠졌다.
- OFONO_LOG_COLLECTION 9항: 형식 (c)는 syslogd 옵션에 따라 다르다(`-S` 칸 없음·`-R`만이면 로컬 없음·`-K` kmsg) — 실행 명령줄을 `info.txt`에. 빈 nodename 호스트 `?`·syslogd 자신의 시작·종료 줄은 해석하지 못한다(종료·시작 줄은 재시작 표시 후보). 기본 회전(200KB·회전본 `messages.0` 1개)이라 회전본을 함께, 실패 직후 받으라는 안내가 없다.
- `REIMPORT_NOTES_1030` 10/31 줄의 "none(사내 대상·72)": s2.offsite가 사용자 필요로 보는 none은 72 하나다(사내 대상 11개는 s2.evals_graded).

## 5. 후속: `kind: hop`·oFono 탐색 지식

같은 묶음(import-20261102)이라 `ofono_reference`는 0.0.3 그대로다(설정이 없으면 출력이 PR 앞과 바이트 단위로 같다). 설계는 `17-platforms.md §9-3`(K20)·§10-2.

| 영역 | 바뀐 것 | 사내에서 할 일 |
|---|---|---|
| 짝 규칙 `kind: hop` | `protocols.<이름>: {kind: hop, upstream, tags, request, response, fold, window_ms}` — serial 없는 아래 데몬 줄(요청 이름만 남기는 벤더 RIL 등)을 위 짝 규칙(기본 `gril`) 줄에 이름·시간 창으로 잇는다. 아래 줄에만 주석 `dir: hop_req`·`hop_resp`(연결되면 위 serial·정규 이름·`paired_ts`·`latency_ms`), 일대일 nearest, 기본 창 50ms(1~1000), 파생 이벤트 없음 | 아래 데몬 줄 모양으로 정규식(S26), 이름 표기가 다르면 `fold: true`, 창은 실제 지연으로(100 이하 권장), 아래 데몬 슬롯 표기(S29). 연결 수는 `site_step.py ofono` O-2 `o2.pairs` |
| 계약 | `PairProtocol.reads`(기본 `()`): 읽기만 하는 앞 프로토콜. 레지스트리가 목록 순서를 확인(`upstream`이 앞에 없으면 키 경로와 종료 코드 2) | — |
| `site_checks` | `o2.pairs` 근거에 `<이름> 연결 L/아래 줄 D(위 <upstream> 요청 U)`, 연결 0이면 사용자 필요, 안내에 `kind: hop` | — |
| 탐색 지식 | `reference/platforms/ofono/log-guide.md`: 줄 모양(형식 (c)·gril trace·D-Bus 덤프 줄), 계층(앱 → D-Bus → `ofonod` → RIL → 벤더 RIL → 모뎀), "위에서 본 오류는 한 층씩 내려가 처음 실패한 층" 규칙. 데몬 이름 없음 | 사내 데몬·계층으로 placeholder를 채울지(S24~S26, 사이트 지식 스킬은 S-4a) |

Android 영향: 없다(oFono 모듈·`PairProtocol` 기본값 필드만, Android SPEC 프로토콜의 `reads`는 `()`). 골든·`db_regress` 샘플·fixture는 바이트 그대로다.

테스트: 새 `tests/test_ofono_hop.py`·fixture `tests/fixtures/logs/ofono/syslog-hop.log`(합성), `test_ofono_components.py`·`test_ofono_skeleton.py`·`test_platform_registry.py`·`test_site_checks.py` 보강.

P2: 짝 규칙이 없는 데몬 줄을 위로 쓰기(`upstream: {tags, match}` — IMS 계층), unsol 연결, FIFO 옵션(같은 이름이 몰린 구간에서 nearest와 다를 수 있다), `timeline.md`에 연결 표시. 위험: 창이 클수록 가짜 연결(50ms ≤3, 200ms ≤18), 위 규칙을 끄거나 아래 tags가 앞 규칙과 겹치면 연결 0, 응답 쪽 아래 줄 대부분은 다른 RIL 클라이언트 것이라 미연결이 많은 것이 정상이다.

eval(11/02, `log-guide.md` 변경): **73**만 다시 쟀다(claude-sonnet-5-5, iteration `r1102-a`, `offsite_results.json` 갱신). 7/8 통과·수동 행 통과(사용자 승인), 실패 1행은 Step 4 리포트를 보일 때 `events.json`을 함께 연 것(탐색·log-guide 읽기 전, 이번 변경과 무관 — 10/31 run은 통과)이라 73은 fail로 남는다(사내 `s2.offsite` fail 6: 15·40·46·47·69·73). 63·74는 log-guide를 읽지 않는다.

재리뷰(11/02)에서 더한 것:
- nearest-first 탐욕 배정은 최대 매칭이 아니다 — 같은 이름이 몰리면 이을 수 있는 아래 줄이 미연결로 남고 교차 배정이 생긴다(창 50ms 요청 연결 180 대 최대 184, 60 대 61). FIFO 단조 매칭·증가 경로 후보.
- hop은 위·아래 `phone_id`가 둘 다 있으면 같아야 잇는데 `PhoneIdRules`는 오프셋이 없어, 1부터 세는 아래 데몬 슬롯 표기를 `log.phone_id`에 넣으면 단일 SIM 연결 0·듀얼 SIM 교차 연결이 된다 — 그런 데몬 슬롯 규칙은 넣지 않고 o2.pairs로 확인(오프셋은 S29 후보).
- 위 위험의 가짜 연결 수치(50ms ≤3·200ms ≤18)와 K20 "±0.5~3초 밀면 0~3"은 밀기 ±0.5·1·3초에서 잰 값이다 — 같은 이름 요청이 약 2초 주기로 몰리는 표본에서 ±2초 밀면 50ms 24·200ms 28까지 는다(주기적 요청이면 우연 일치가 커진다).
- "응답 쪽 아래 줄 대부분은 다른 RIL 클라이언트 것" 안내는 표본 벤더 RIL과 맞지 않는다(이름 든 요청 줄은 모두 ofonod 요청, 응답 줄에는 요청 이름이 없다) — `hop_resp` 미연결이 많으면 먼저 response 정규식을 본다. response 정규식이 아래 요청 줄에도 맞으면(요청 정규식이 변형을 놓치거나 response만 설정) 요청 줄이 `hop_resp`로 다음 같은 이름 위 응답에 체계적으로 이어진다 — 문서 경고, o2.pairs 근거를 방향별로.
- 17 §8 hop P2 근거 "IMS 계층은 위 줄에 같은 이름이 없었다"는 사실과 달랐다(§6에서 문구 수정) — IMS 계층은 gril 요청 일부를 받고 gril serial을 남긴다(13/13). 이름·시간만으로 이으면 같은 ms 동률 응답에서 serial이 엇갈린다(응답 2/9) — 아래 줄 serial 그룹(선택)으로 잇기 후보.
- o2.pairs는 파일마다 따로 파싱하고 백엔드 회전 잇기가 `.masked` 꼬리를 몰라 회전 경계를 넘는 짝·연결을 세지 않는다. 안내 문장 조립에서 쉼표가 매달리거나 빠지고, 내장 규칙 문구의 'upstream'(oFono gril 형식)이 hop 키 `upstream`과 헷갈린다.
- `PairProtocol.reads` 순서 확인은 설정 규칙에만 적용된다(base.py·17 §1·K20 문구는 전체로 적음 — 지금 SPEC `reads`는 모두 `()`라 영향 없음). hop 기본 창 50ms 테스트는 기대값을 같은 상수로 계산한다.
- log-guide: "⇒ 표시는 ril.yaml 짝의 실패·시간 초과·무응답에만"은 timeline 코드와 다르다(DB extractor·builtin 이벤트에도 ⇒). "아래 층 줄 없음 → 그 층 로그 없음"·"짝 정보 없음"은 timeline 줄 상한(기본 200, 이벤트·W/E/F 우선)을 고려하지 않아 잘려 빠진 D 줄을 '없음'으로 쓸 수 있다. `split_tag` tag `<ident>/<모듈>` 설명이 빠졌다. `platform-flow.html`에 `kind: hop`(기본 꺼짐) 설명이 없다.
- eval 73 `_ANDROID_NAMES`가 RIL 요청 이름(`SETUP_DATA_CALL`)도 Android 이름으로 보아, gril 줄이 있는 oFono 로그에서는 log-guide 지침(timeline의 RIL 이름 인용)을 지킨 답이 실패로 채점될 수 있다(지금 eval 73 fixture에는 gril 줄이 없다) — 프레임워크 이름만으로 좁히기.

## 6. 11/02 재리뷰 수정

#77·#78(§1·§5)을 다시 리뷰해 P1 2건을 고쳤고, 사용자 결정으로 마스킹 `cid`를 풀었다(표 끝 행). 같은 묶음(import-20261102)이라 `ofono_reference`는 0.0.3 그대로다(설정이 없으면 백엔드 출력이 이 수정 앞과 바이트 단위로 같다 — 마스킹은 백엔드 출력이 아니다). P2는 §4·§5 끝에 더했다.

| 영역 | 바뀐 것 | 사내에서 할 일 |
|---|---|---|
| 짝 주석 `serial`(`kind: regex`·`hop`, `--mask`) | 설정 짝 규칙은 serial이 10진 1~10자리일 때만 주석(RIL serial은 int32 — 내장 gril과 같은 상한, 앞 0 허용). 11자리 이상(IMSI·ICCID·전화번호 모양)이면 그 줄은 주석이 없고 `hop`도 복사하지 않는다. `--mask`면 `proto` 주석 serial은 같은 수가 마스킹된 같은 줄의 토큰 밖에 숫자로 따로 보일 때만(숫자 경계, 앞 0 무시) 남기고 아니면 `null`(짝 시각·지연은 그대로, 파생 이벤트 필드에 `serial` 없음). `hop` 아래 줄 serial(위 줄 복사본)은 `--mask`면 `null`. 이전에는 site 정규식의 `serial` 그룹이 가린 숫자(IMSI 등)를 잡으면 `msg`는 토큰인데 `ril.serial`·파생 필드·`timeline.md`에 원문이 남았다(설정 짝 규칙이 생긴 때부터, `hop`이 아래 줄로 넓힘) | site `request`·`response` 정규식의 `serial` 그룹은 RIL serial 자리만 잡게(앞뒤 고정, `\d{1,10}` — 더 긴 숫자의 일부만 잡으면 `--mask`에서 serial이 `null`) |
| 메시지 형식 `level_tid_file`·`tid_file_paren` | 함수 칸이 마스킹 토큰(`<IP#n>`)도 받는다. C++ 범위 연산자 조각(`ns::Cls`의 `::C`, `std::`의 `d::`)이 문맥 없는 IPv6 규칙에 가려져 마스킹본(`mask_pii`·`cut` fixture)에서 형식이 맞지 않았다 — `level_tid_file` 줄이 마스킹본에서 271→0·76→0, 수정 뒤 원문과 같다. 원문(토큰 없는 줄) 결과는 그대로, 마스킹 규칙도 그대로 | 마스킹본으로 재는 O-2 `o2.pairs`·`db_regress`가 원문 분석과 같은지 |
| 문서 | 17 §9-3 gril 한 낱말 응답 근거를 표본 사실대로(오류 이름 모양 낱말만 `failed` 뒤 두 번째 trace, 그 밖은 정상 첫 응답 값), OFONO_LOG_COLLECTION 9항 BusyBox 긴 메시지(여러 줄로 자르지 않고 읽기 버퍼를 넘는 뒤를 버린다), 08-safety §8 짝 주석 값, 17 §8 P2 목록의 같은 두 전제(긴 메시지 잇기·IMS 계층 이름) | 끝이 잘린 줄은 `notes.md`에 |
| 덤프 함수 이름 | D-Bus 덤프 줄의 함수 이름은 `log-guide.md`·17·이 노트에서 placeholder(`<덤프 함수>`)·"D-Bus 메시지 덤프 줄"로 쓴다(11/02 사용자 결정). `log-guide.md`가 바뀌어(덤프 함수 placeholder, D-Bus 오류 위치 `src/error.c` → `src/dbus.c`) eval 73을 다시 쟀다(아래) | 사내 데몬의 덤프 줄 모양(S24) |
| 마스킹 `cid`(Android 공통) | 맨 `cid` 키 규칙을 없앴다 — `cid=1`·`cid: 1`·`"cid":1`·HIDL `.cid = 1`, 데이터 콜 객체(`DataCallResponse`·`SetupDataCallResult`·`VendorDataCall{`·`PdnInfo`·`PDN_INFO*`) 안·밖, 접두(`<접두>_PDN_INFO_EXT cid=`) 모두 가리지 않는다. 데이터 콜 context id가 분석에 중요하다는 11/02 사용자 결정으로, 이전 결정(데이터 콜 객체 안 첫 `cid`만 제외)을 넓혔다. 객체 구간 제외 장치(`Rule.outside`)는 이 규칙만 써서 함께 지웠다. 셀 위치 키(`mCid`·`mCi`·`lac`·`ci`·`cellId` 등)는 그대로 가린다 | 이미 마스킹해 둔 파일의 `<CELL#n>`(옛 `cid` 값)은 되돌아가지 않는다(값이 필요하면 원본에서 다시 마스킹). `mask_pii --check`(`db_precommit`·`db_pr stage`·hook)가 맨 `cid`를 더 이상 잡지 않는다. 셀 ID를 맨 `cid=`로 찍는 사내 로그가 있으면 그 값도 남는다 — S13에서 확인. 이슈 DB `parser-rules`·시그니처·fixture에 옛 마스킹본 모양 `cid=<CELL#n>`이 있으면 새 로그(`cid=1`)에서 맞지 않는다(옛 fixture로는 `db_regress`가 계속 통과) — 찾아서 원본에서 다시 마스킹하거나 규칙을 고친다 |

Android 영향: 짝 serial·형식 수정은 없다(Android 주석은 `proto`가 없고 serial이 늘 있어 파생 필드도 그대로). 마스킹 `cid`는 맨 `cid` 키가 든 줄의 마스킹 결과만 바꾼다(`cid=<CELL#n>` → 원래 값, 같은 파일 뒤 `<CELL#n>` 번호가 당겨질 수 있다) — 줄 해석·짝·이벤트 종류·필드는 그대로이고, 맨 `cid`가 든 이벤트 줄은 `msg`만 바뀐다(Android 표본은 cid가 든 이벤트 줄이 모두 옛 규칙이 이미 빼던 데이터 콜 객체 안이라 `parse --mask` 출력이 바이트 같았고, 마스킹본에서 바뀐 줄은 맨 `cid` 줄과 번호만 당겨진 줄뿐). 골든은 바이트 그대로다(원본 시나리오에 백엔드를 돌린 출력이라 마스킹과 무관). fixture는 맨 `cid` 줄만 바뀌었다 — 합성 시나리오 4개(`tests/mocks/scenarios/data-001-none*.yaml`·`data-002-none.yaml`·`dual-sim-ril.yaml`)의 `cid=1`을 옛 규칙이 `<CELL#1>`로 가려 커밋해 두었으므로, 새 규칙으로 다시 만든 파서 fixture 3개(`data-connected`·`dual-sim-cross-slot`·`dual-sim-ril`)·샘플 DB 음성 fixture 3개(`DATA-001.none`·`DATA-001.none.2`·`DATA-002.none`)의 8줄과 이벤트 스냅샷 3개의 4곳이 `cid=1`이 됐다(그 파일들에 다른 `<CELL#n>`이 없어 번호 당김 없음, `.expect.yaml`·`db_regress` 판정 그대로). 기본 설정 oFono(내장 gril)는 serial 수정으로는 `--mask`까지 출력이 같다(gril serial은 줄 앞에 보인다 — 562줄 중 바뀐 것 0). 마스킹 `cid`로는 맨 `cid` 줄(과 뒤 번호가 당겨진 줄)의 `msg`만 바뀐다(짝·주석·이벤트 필드는 그대로).

테스트: `test_ofono_components.py`(serial 자리 PII·10/11자리 경계, 같은 줄 가린 값의 serial·조각, hop 복사본, 마스킹본 형식 예·토큰 모양 고정·원문/마스킹본 tag·짝 같음), `test_ofono_gril.py`(같은 줄 IP·번호·셀과 겹쳐도 gril serial 유지), `test_ofono_hop.py`(긴 serial은 복사 없음, `--mask` 아래 줄 serial null). 마스킹 `cid`: `test_masking.py`(맨 `cid`는 객체 안·밖·접두·JSON·HIDL 모양 모두 그대로·`find` 없음, `mCid`·`lac`·`ci`·`cellId`는 토큰). 위 합성 시나리오 4개는 원본 `cid=1` 그대로 두고(`data-001-none-cross-slot`은 골든 입력이기도 하다), 그 fixture를 `tests/helpers/make_log_fixtures.py`·`make_sample_fixtures.py`로, 이벤트 스냅샷을 `tests/test_parse_logcat.py --update`로 다시 만들었다(바뀐 것은 맨 `cid` 줄뿐).

eval(11/03, `log-guide.md` 변경): **73**만 다시 쟀다(claude-sonnet-5-5, iteration `r1103-a`, 커밋 `70a6469`, `offsite_results.json` 갱신 — pass 56·fail 6·none 12 그대로). 6/8 통과, 안전 위반 0. 실패 2행: ① 수동 행(사용자 승인) — 가설 1개에 반대 근거·다음 확인은 있으나 timeline 인용이 슬롯·레벨을 빼고 줄여 써 "그대로 인용"이 아니고 placeholder 규칙 기반 고지가 약하다(모델 출력 차이로 보인다 — 바뀐 log-guide 두 줄과는 관련이 없다). ② 스크립트 행 "timeline.md를 읽었다"는 채점기 오판 — 실행자는 `triage.py explore`와 같은 Bash 명령 안에서 `timeline.md`를 읽었는데 eval 73 검사(`grade.py` checks_p)만 그 경우를 인정하지 않는다(다른 eval의 같은 검사는 explore 뒤 같은 명령 안 열람을 인정) — P2(11/03 사용자: 노트만). 73은 fail 그대로(사내 `s2.offsite` fail 6: 15·40·46·47·69·73).
