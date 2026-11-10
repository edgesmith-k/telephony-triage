# oFono 합성 로그 (형식 가정·placeholder)

**합성·형식 가정·placeholder**다. 실제 oFono 로그가 아니고, 실제 로그 문구·사내 구성요소 이름도 없다.
실제 형식은 사내 로그를 받은 뒤 정한다 (TODO(SITE:S24), `plugin/scripts/platforms/ofono/journal.py`).

| 파일 | 가정 형식 | 용도 |
|---|---|---|
| `journal-iso.log` | (a) `journalctl -o short-iso-precise` (연도·타임존 있음) | 형식 (a) 해석, `issue-db-ofono` 변형의 `DATA-001-01` 양성 fixture와 같은 내용, triage 전환 시험 |
| `syslog-bsd.log` | (b) RFC3164 syslog / `journalctl -o short` (연도·타임존 없음 → `--year`/`--tz`) | 형식 (b) 해석 |
| `journal-multi.log` | (a), 여러 데몬이 섞인 한 스트림 | 구성요소(데몬)·데몬 사이 짝(`kind: regex`, `ipc call/reply <serial>` 줄 모양도 가정)·`msg_format`(`ofonod` DBG 앞머리)·`split_tag` 시험 (`tests/test_ofono_components.py`) |
| `syslog-busybox.log` | (c) BusyBox syslogd(`<facility>.<severity>` 칸, 밀리초, 연도·타임존 없음 → `--year`/`--tz`) | 형식 (c) 해석·레벨, 내장 짝 `gril`(요청·응답·실패·unsol·접두사 없는 이름·짝 없는 요청 → `ril_error`·`ril_timeout`·`ril_no_response`), 슬롯(`[0,`·`/ril_0`), `tail:` 줄 건너뜀, 가리지 않는 값(맨 `cid=` — `PdnCtx{cid=…}`, 짧은 `token=`) (`tests/test_ofono_gril.py`) |
| `syslog-hop.log` | (c), `ofonod` gril trace + 아래 데몬(`daemon-a`)의 serial 없는 요청·응답 줄(`ipc req <NAME>`·`ipc rsp <Name>`, 줄 모양 가정) | `kind: hop` 연결: 요청 1ms·응답 앞 1ms(fold)·교차(nearest)·창 밖·위 없음·tags 밖·이름 모양 아님 (`tests/test_ofono_hop.py`) |
| `e078-sim-data.log` | (c), 첫 줄 `-- [합성]` 메모 | eval 78(모듈 후보 둘): `ofonod` W/E 줄이 `src/gprs.c:`(data)·`drivers/rilmodem/sim.c:`(sim)을 인용, `simd`·`datad` 줄은 맥락(`issue-db-ofono` 태그 밖이라 이벤트가 아니다) |

- `ofonod`는 공개 upstream 데몬 이름이다. 그 밖 구성요소 자리는 placeholder `daemon-a`(data)·`daemon-b`(call)이다.
- 호스트 칸은 `dut`(placeholder)다. 파서는 호스트를 이벤트에 넣지 않는다.
- 손으로 쓴 파일이다(생성기 없음). 마스킹을 다시 돌려도 바뀌지 않는다(`tests/test_ofono_skeleton.py`·`tests/test_ofono_components.py`가 확인).
- (c)·gril 줄은 **모양만** 확인한 것이다. 줄·값·이름은 손으로 쓴 합성이다(사내 확인 TODO(SITE:S24·S26)).
