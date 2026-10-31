# oFono 로그 해석 보조 (탐색 분석)

> placeholder다. 사내 로그로 정한다: 줄 형식 TODO(SITE:S24), 구성요소·카테고리 TODO(SITE:S25), 짝 TODO(SITE:S26). 여기 이름에 기댄 결론은
> "placeholder 규칙 기반"이라고 밝힌다.

**판별 기준은 그 이슈 DB `SNAP/parser-rules/`다**(`tags.yaml` ident → 카테고리, `extractors.yaml`, `ril.yaml`).
이 문서는 해석 보조다. 필요한 이름만 `grep -n`으로 찾는다.

## 줄 모양

- journald 한 스트림: `<시각> <호스트> <ident>[<pid>]: <메시지>`(형식 가정). `timeline.md`에는 tag = ident로 보인다.
- upstream 디버그 앞머리 `src/<파일>.c:<함수>() `가 메시지 앞에 붙을 수 있다. 구성요소가 나눠 쓰면 tag가
  `<ident>/<모듈>`이다.
- 데몬은 `ofonod`(upstream) 말고도 여럿이다. 이름은 site 설정이 정하고 여기서는 `daemon-a`·`daemon-b`로 쓴다.

## 짝·데몬 사이 요청

`proto: <이름>`이 붙은 줄은 짝 규칙이 맺은 요청·응답이다. 응답 없는 요청, 오류 응답, 데몬 사이 지연(요청 데몬 →
응답 데몬)을 가설 근거로 쓴다. 짝 설정이 없으면 이런 표시가 없다 — "짝 정보 없음"이라고 쓴다.

## upstream 개념 (예시, 카테고리 매핑은 DB `tags.yaml`)

| upstream 개념 | 보통 카테고리(일반 6종 기준) |
|---|---|
| modem 전원·온라인 | 여러 카테고리 공통(DB가 정함) |
| sim (PIN·SIM 준비) | sim |
| netreg (등록·신호) | network |
| gprs·ConnectionContext (attach·컨텍스트 활성화) | data |
| voicecall | call |
| sms | sms |
| ims | ims |

D-Bus 오류 이름 예시: `org.ofono.Error.{Failed, InProgress, NotImplemented, InvalidArguments, InvalidFormat,
NotFound, NotAttached, NotRegistered, SimNotReady, Timedout, AccessDenied, Canceled}` — 대상 버전 소스 `src/error.c`로 확인한다.

## 코드

루트 키는 `code.roots`의 것(주 루트 `ofono`, 구성요소 루트는 DB `code_root_keys`)만 쓴다. Android 이름(RIL 요청 이름·
데이터 연결 클래스·실패 원인 enum)을 oFono 가설에 가져오지 않는다 — 다른 스택이라 맞는 줄이 없다.
