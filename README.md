# telephony-triage

Android Telephony 이슈 분석 도구(Claude Code 플러그인). Jira 이슈와 logcat을 받아 원인·해결책을 분석하고,
결과를 카테고리 > 이슈 유형(증상) > 원인으로 사내 GitHub 이슈 DB 레포(`telephony-issue-db`)에 누적한다.
분류 확정·push 같은 쓰기 단계는 항상 사용자 확인을 거치고, main에는 직접 push하지 않는다(브랜치 + PR).

## 시작

- 사용자: 플러그인을 설치한 뒤 `/telephony-triage:setup`으로 설정하고 `/telephony-triage:analyze`로 분석한다.
  자세한 사용법과 범위는 [GUIDE.md](GUIDE.md).
- 개발자: Claude Code 세션을 이 레포 루트에서 열면 [CLAUDE.md](CLAUDE.md)가 로드된다.
  모드(사외 초안 / 사내 보완 / 사내 처음부터)와 작업 방식은 거기에 있다.
- 사내 반입·보완 담당자: [GUIDE.md](GUIDE.md) §4.
- 설계 문서 지도: [docs/design/README.md](docs/design/README.md).

## 테스트

```
python3 -m venv .venv && . .venv/bin/activate
pip install '.[test]'
python3 -m pytest -q tests
```

Windows는 `PYTHONUTF8=1`.
