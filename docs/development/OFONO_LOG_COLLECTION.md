# oFono 로그 수집 체크리스트 (사용자용)

> `docs/design/17-platforms.md` §8 미룬 것(oFono 실제 파서 규칙·이슈 DB, `14-site.md` S24~S29)을 위한 수집 안내다. 설계서 원문 그대로이며 사내 구성요소 이름은 쓰지 않는다.

> 목적: oFono용 파서 규칙·이슈 DB를 만들기 위한 **형식 확인과 시드 사례** 수집이다. 수집·분석은 **사내에서만** 한다. 이 레포(사외)에는 실제 로그·구성요소 이름·호스트명을 넣지 않는다.

## 1) 시나리오(각 정상 2건 + 실패 2건. 서로 다른 날이나 다른 단말을 1건씩 섞는다)

| 영역 | 정상 | 실패(가능한 만큼) |
|---|---|---|
| 데이터 연결 | 부팅 후 자동 연결, 수동 끊기·다시 연결 | 컨텍스트 활성화 실패(APN 오류 등), 연결 후 끊김, 비행기 모드 해제 후 미연결 |
| 통화 | 발신·수신·정상 종료 | 발신 실패, 통화 중 끊김, 수신 안 됨 |
| SIM | 인식, PIN 입력 후 사용 | 미인식, PIN·PUK 잠금, 핫스왑 후 미인식 |
| 망 등록 | 등록, 로밍 등록 | 등록 거부, 서비스 없음, 등록 지연 |
| SMS | 송신·수신 | 송신 실패, 수신 누락 |
| IMS(해당 시) | 등록, VoLTE 통화 | 등록 실패, 재등록 반복 |
| eSIM/LPA(해당 시) | 프로필 다운로드·활성화 | 다운로드·전환 실패 |

## 2) 받을 로그(한 사례 = 폴더 하나)

1. **journald 전체(현재 부팅)**: `journalctl -b -o short-iso-precise --no-pager > journal.log`. 시각에 마이크로초와 타임존 오프셋이 들어간다.
2. **구성요소(데몬)별 로그를 각각**: `journalctl -b -o short-iso-precise -u <유닛> > journal-<유닛>.log`. oFono(`ofono`), 데이터 연결을 맡는 관리자(ConnMan 또는 NetworkManager), ModemManager가 함께 있으면 그것까지, 그리고 telephony에 관여하는 사내 구성요소 전부를 하나씩 받는다. 어떤 유닛이 있었는지 `notes.md`에 적는다.
3. **형식 확인용 JSON 1건**(시나리오 하나만): `journalctl -b -o json -u ofono > journal-ofono.json`. 우선순위·PID·식별자 필드 구조를 보기 위한 것이다. `_HOSTNAME`·`_MACHINE_ID`·`_BOOT_ID`는 반드시 지운다.
4. **oFono 디버그**: 실패 사례 중 최소 1건은 `ofonod`를 디버그로 켜고 받는다(일반적으로 `-d` 옵션, 예: systemd drop-in에서 `ofonod -n -d`). 켜는 방법은 사내 빌드 기준으로 확인한다.
5. **모뎀 통신 트레이스**(AT·QMI·RIL 계층 중 해당하는 것): 디버그 환경변수나 옵션은 포크마다 다르다. 켤 수 있으면 실패 사례 1건 이상에서 켠다.
6. **D-Bus**: `dbus-monitor --system "sender='org.ofono'" "destination='org.ofono'" > dbus.log`(가능하면 사례 시작 전에 켜 둔다). 속성 값에 APN 계정이 나올 수 있다(마스킹 대상).
7. **커널**: `journalctl -k -b -o short-iso-precise > kernel.log`(모뎀 USB 열거, wwan 인터페이스 등).
8. **상태·버전**(`info.txt`): oFono 버전, OS·빌드, 모뎀 펌웨어, `uname -r`, 단말 모델, `timedatectl` 출력, 실패 시점의 네트워크 상태 요약(인터페이스·라우트 유무만).
9. journald가 없는 단말: `/var/log/messages` 또는 `/var/log/syslog`. 이 경우 연도·타임존을 `info.txt`에 꼭 적는다.

## 3) 시각 동기·타임존

- 수집 전에 단말 NTP 동기를 켜고 확인한다(`timedatectl`의 `System clock synchronized: yes`).
- 실패를 본 **시각(±1분)**과 재현 절차를 `notes.md`에 적는다. 시험 장비 시계를 쓰면 단말 시계와의 차이도 적는다.
- `short-iso-precise`(오프셋 포함)를 우선한다. 연도·타임존이 없는 형식이면 둘을 기록한다.

## 4) 개수·이름

- 시나리오마다 정상 2·실패 2. 디버그 켠 사례 최소 1. 우선순위는 데이터 > 망 등록 > SIM > 통화 > SMS > IMS > eSIM.
- 폴더 이름: `<영역>-<정상|실패>-<n>/`. 안에는 `journal.log`, `journal-<유닛>.log`, `dbus.log`, `kernel.log`, `info.txt`, `notes.md`(시각·절차·기대/실제 결과·Jira 키(있으면)).

## 5) 마스킹(공유 전에 반드시)

1. 파일마다 `python3 "<플러그인>/scripts/mask_pii.py" <파일> --out <파일>.masked`(같은 값은 같은 번호로 바뀐다).
2. 검사: `python3 "<플러그인>/scripts/mask_pii.py" <*.masked> --check`. 종료 코드 1이면 나온 종류를 다시 처리한다.
3. **도구가 놓칠 수 있는 oFono 형식은 눈으로 확인한다**:
   - D-Bus 속성 값: `string "Username"` / `string "Password"` 다음 줄 `variant string "..."`
   - AT 인증 명령(`AT+CGAUTH` 등)의 계정·비밀번호
   - `+CCID:`/`+ICCID:` 응답(키 이름 없는 ICCID)과 `AT+CIMI` 응답(IMSI)
   - `+CREG`/`+CEREG`/`+C5GREG` 응답의 LAC·TAC·셀 ID(16진)
   - 통화·SMS 상대 번호와 **SMS PDU 16진 문자열**(번호·본문이 인코딩돼 있다. 통째로 지우거나 `<PDU>`로 바꾼다)
   - IMEI(`AT+CGSN`), 단말 일련번호(USB 열거 `SerialNumber:`)
   - 호스트명(journald 각 줄의 두 번째 칸), `_MACHINE_ID`, 위치 정보
   - APN 이름 중 사내 전용 이름
4. 마스킹 원본(`.masked` 아닌 파일)은 공유 폴더에 두지 않는다.
5. **호스트 칸은 지우지 말고 placeholder(예: `dut`)로 바꾼다** — 줄 형식(스탬프·호스트·식별자 칸 순서)을 그대로 둬야 형식을 정할 수 있다. 수집 때 `--no-hostname`을 썼거나 `short-full`·공백 구분 ISO(`2026-09-20 14:32:09`)처럼 형식이 다르면 그 사실을 `info.txt`에 적는다.

## 6) 반출 주의

- 실제 로그와 마스킹한 로그 모두 **사외(이 레포·사외 PC·외부 서비스)로 가져가지 않는다.** 파서 규칙·이슈 DB 시드는 사내 모드(S 단계)에서 만든다.
- 형식 설명이 꼭 사외에 필요하면 사내 반출 절차 승인을 먼저 받는다. 승인 후에도 줄 **구조만** 남긴 "형식 샘플"만 가져간다. 구성요소 이름·호스트명·서버명·경로·로그 문구는 `daemon-a`, `<MSG>` 같은 placeholder로 바꾼다.
- 사내 구성요소 이름은 사외 문서·코드·fixture에 쓰지 않는다.
