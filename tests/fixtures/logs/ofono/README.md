# oFono 합성 로그 (형식 가정·placeholder)

**합성·형식 가정·placeholder**다. 실제 oFono 로그가 아니고, 실제 로그 문구·사내 구성요소 이름도 없다.
실제 형식은 사내 로그를 받은 뒤 정한다 (TODO(SITE:S24), `plugin/scripts/platforms/ofono/journal.py`).

| 파일 | 가정 형식 | 용도 |
|---|---|---|
| `journal-iso.log` | (a) `journalctl -o short-iso-precise` (연도·타임존 있음) | 형식 (a) 해석, `issue-db-ofono` 변형의 `DATA-001-01` 양성 fixture와 같은 내용, triage 전환 시험 |
| `syslog-bsd.log` | (b) RFC3164 syslog / `journalctl -o short` (연도·타임존 없음 → `--year`/`--tz`) | 형식 (b) 해석 |

- `ofonod`는 공개 upstream 데몬 이름이다. 그 밖 구성요소 자리는 placeholder `daemon-a`(data)·`daemon-b`(call)이다.
- 호스트 칸은 `dut`(placeholder)다. 파서는 호스트를 이벤트에 넣지 않는다.
- 손으로 쓴 파일이다(생성기 없음). 마스킹을 다시 돌려도 바뀌지 않는다(`tests/test_ofono_skeleton.py`가 확인).
