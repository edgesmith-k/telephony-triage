---
name: probe
description: 빈 플러그인 실험용 스킬. 커맨드와 스킬의 관계, ${CLAUDE_PLUGIN_ROOT} 치환을 확인할 때 쓴다.
---

# probe 스킬

이 스킬이 불렸다는 것은 **플러그인의 스킬이 로드된다**는 뜻이다.

확인 항목:

- 이 스킬 본문에서 `${CLAUDE_PLUGIN_ROOT}`가 치환되는가?
  아래 경로를 Bash로 `ls` 해 보면 안다.

  ```sh
  ls "${CLAUDE_PLUGIN_ROOT}/scripts/probe.py"
  ```

- 커맨드(`/probe:ping`)와 이 스킬이 같이 쓰이는가, 따로 부르는가?

결과는 `tests/mocks/plugin-probe/README.md`의 '사외 결과' 표에 적는다(사내는 `SITE_PROFILE.md`).
