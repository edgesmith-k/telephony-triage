# oFono 로그 해석 보조 (탐색 분석)

> placeholder다(줄 형식 TODO(SITE:S24), 구성요소·카테고리 S25, 짝 S26). 여기 이름에 기댄 결론은 "placeholder 규칙 기반"이라고 밝힌다.

**판별 기준은 그 이슈 DB `SNAP/parser-rules/`다**(`tags.yaml` ident → 카테고리, `extractors.yaml`, `ril.yaml`).
이 문서는 해석 보조다. 이름은 `grep -n`으로 필요한 것만 찾는다.

## 줄 모양 (`timeline.md`: 시각 슬롯 레벨 tag 메시지)

- tag = 데몬 ident. `ofonod`(upstream) 말고도 데몬이 여럿이다(이름은 site 설정, 여기서는 `daemon-a`).
- `ofonod` RIL trace: `[<slot>,<serial>]> <이름>` 요청, `[<slot>,<serial>]< <이름>` 응답(`failed <ERROR>`면 실패),
  `[<slot>,UNSOL]< <이름>` 비요청. 같은 serial이 한 요청·응답이고 slot이 타임라인 `p<n>`이다. `RIL_REQUEST_`를 뗀
  이름이 DB `ril.yaml` 이름이다.
- `<덤프 함수> method call|signal - i:<인터페이스> m:<메서드> p:<경로>` = `ofonod`가 주고받은 D-Bus. `p:/ril_<n>` = 슬롯 n.
- 앞머리 `src/<파일>.c:<함수>() `는 upstream 디버그 출력이다(소스 위치 단서).

⇒ 표시는 `ril.yaml`에 이름이 있는 짝의 실패·시간 초과·무응답에만 붙는다(성공한 짝은 표시가 없다). 데몬 사이 연결
(`kind: hop`)도 표시가 없으니 위·아래 줄을 시각 차로 맞춘다. RIL trace 줄이 없는 로그면 "짝 정보 없음"이라고 쓴다.

## 코드·이름

루트 키는 `code.roots`의 것(주 루트 `ofono`, 구성요소 루트는 DB `code_root_keys`)만 쓴다. RIL 요청 이름은
`timeline.md` 줄에 나온 것만 인용한다 — `ril.yaml`은 카테고리·timeout 확인용이고, 거기에만 있는 이름으로 "없는 줄"을
말하지 않는다. Android 프레임워크 이름(클래스·실패 원인 enum)도 쓰지 않는다 — 다른 스택이라 가설을 틀린 쪽으로 끈다.
