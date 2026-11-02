# oFono 로그 해석 보조 (탐색 분석)

> placeholder다(줄 형식 TODO(SITE:S24), 구성요소·카테고리 S25, 짝 S26). 여기 이름에 기댄 결론은 "placeholder 규칙 기반"이라고 밝힌다.

**판별 기준은 그 이슈 DB `SNAP/parser-rules/`다**(`tags.yaml` ident → 카테고리, `extractors.yaml`, `ril.yaml`).
이 문서는 해석 보조다. 이름은 `grep -n`으로 필요한 것만 찾는다.

## 줄 모양 (`timeline.md`: 시각 슬롯 레벨 tag 메시지)

- tag = 데몬 ident. `ofonod`(upstream) 말고도 데몬이 여럿이다(이름은 site 설정, 여기서는 `daemon-a`).
- `ofonod` RIL trace: `[<slot>,<serial>]> <이름>` 요청, `[<slot>,<serial>]< <이름>` 응답(`failed <ERROR>`면 실패),
  `[<slot>,UNSOL]< <이름>` 비요청. 같은 serial이 한 요청·응답이고 slot이 타임라인 `p<n>`이다. `RIL_REQUEST_`를 뗀
  이름이 DB `ril.yaml` 이름이다.
- `dump_dmsg method call|signal - i:<인터페이스> m:<메서드> p:<경로>` = `ofonod`가 주고받은 D-Bus. `p:/ril_<n>` = 슬롯 n.
- 앞머리 `src/<파일>.c:<함수>() `는 upstream 디버그 출력이다(소스 위치 단서).

## 계층과 판단 규칙

앱·관리 데몬 → D-Bus `org.ofono.*` → `ofonod`(rilmodem/gril) → RIL 소켓 → 벤더 RIL 데몬 → 모뎀. 곁가지: RIL에 직접
붙는 다른 클라이언트, IMS 모듈 → IMS 데몬. 아래 층 오류는 위로 번져 층마다 다른 이름으로 다시 보인다.

**위에서 본 오류는 시각·이름으로 한 층씩 내려가 처음 실패한 층을 찾는다.** 그 층이 원인 후보이고 위 층들은 증상이다.
근거는 수 ms 안의 아래 층 줄, `failed`, ⇒ `ril_error`·`ril_timeout`·`ril_no_response` 표시다. 아래 층 줄이 없으면
"그 층 로그 없음"이라고 쓰고 원인을 지어내지 않는다 — 로그 수준·수집 범위 탓일 수 있다.

짝 결과는 ⇒ 표시로만 보인다(`ril.yaml`에 이름이 있을 때). 데몬 사이 연결(`kind: hop`)은 표시가 없으니 같은 이름의
위·아래 줄을 시각 차로 맞춘다. 짝 설정이 없으면 "짝 정보 없음"이라고 쓴다.

## upstream 개념 → 카테고리 (예시, 최종은 DB `tags.yaml`)

modem 전원·온라인: 공통 · sim: sim · netreg: network · gprs·ConnectionContext: data · voicecall: call · sms: sms · ims: ims.
D-Bus 오류 `org.ofono.Error.<이름>`(Failed·InProgress·NotAttached·SimNotReady·Timedout 등)은 대상 버전 `src/error.c`로 확인한다.

## 코드·이름

루트 키는 `code.roots`의 것(주 루트 `ofono`, 구성요소 루트는 DB `code_root_keys`)만 쓴다. RIL 요청 이름은 타임라인·DB
`ril.yaml`에 나온 것만 쓰고, Android 프레임워크 이름(클래스·실패 원인 enum)은 쓰지 않는다 — 다른 스택이라 맞는 줄이
없고 가설을 틀린 쪽으로 끈다.
