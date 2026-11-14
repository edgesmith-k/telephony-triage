# 사내에서 모듈 템플릿 이름 채우기

반입 묶음의 모듈 템플릿은 벤더 고유 이름이 placeholder(`VIPC_EXAMPLE_*`, `Example…`, `vrild` 등)로 들어 있다.
이 폴더의 양식(레포에 들어 있다)에는 **실제 값이 없다**. 실제 값은 사내 로그·소스를 보고 사내에서 채운다.

| 파일 | 내용 |
|---|---|
| `ofono-names-form.json` | oFono placeholder 83종. `real` 칸이 빈칸 |
| `android-names-form.json` | Android placeholder 45종(벤더 RIL 아래 층). `real` 칸이 빈칸 |
| `tools/names_fill.py` | 채운 양식대로 사내 스냅샷(`docs/site/module-skills`)과 그 `modules.yaml`의 플랫폼 블록을 바꾼다 |

각 행: `placeholder`, `real`(채울 칸), `kind`(종류), `count`(쓰인 횟수), `example_lines`(레포의 합성 로그에서 이 이름이 나오는 줄 — 어느 데몬의 어떤 줄에서 찾을지 단서), `files`.

## 순서
1. 반입을 마치고 사내 레포 작업 브랜치에서 사내 스냅샷을 만든다: `docs/SITE_RESTORE.md` ⓪의 블록(지금 HEAD의 템플릿을 `docs/site/module-skills/`(SITE_PATHS)로 뜬다).
   **레포의 `templates/module-skills`는 고치지 않는다** — 사외 파일이라 고치면 다음 재반입이 멈춘다. 이름은 스냅샷에만 채운다.
2. 양식을 사내 경로로 복사한다: `cp tools/site_names/ofono-names-form.json docs/site/ofono-names-form.json`. 레포의 양식은 빈칸 그대로 둔다(같은 이유).
   사내 Claude에게 아래 문장을 준다(로그 경로만 바꾼다). 토큰을 쓰는 단계는 이것 하나다.
   > `docs/site/ofono-names-form.json`의 각 행에서 `example_lines`와 `kind`를 단서로, `<사내 마스킹 로그 경로>`에서 같은 자리에 나오는 실제 이름을 찾아 `real`에 채워 줘. 확실한 것만 채우고 모르면 비워 둬. 로그 전체를 읽지 말고 행마다 grep으로 찾아. 채운 결과를 표(placeholder · real · 근거 줄)로 보여 주고, 내가 확인하기 전에는 파일을 바꾸지 마.
3. 표를 확인한 뒤 미리 보기 → 적용:
   ```
   python3 -I -X utf8 tools/names_fill.py docs/site/module-skills docs/site/ofono-names-form.json
   python3 -I -X utf8 tools/names_fill.py docs/site/module-skills docs/site/ofono-names-form.json --write
   ```
4. 모듈 스킬 레포에 얹는다: `python3 tools/make_module_repo.py <out> --site-overlay docs/site/module-skills`(`docs/SITE_RESTORE.md` ③).
5. `python3 tools/site_step.py modules coverage --out docs/site/module-coverage.diff`(토큰 0)로 모듈에 없는 데몬·태그를 본다.
6. 모듈 eval `--dry-run`과 테스트를 돌리고, 모듈 레포 PR로 올린다.

## 알아 둘 것
- 빈 행은 placeholder로 남는다. 다 못 채워도 동작은 하고, 채운 만큼 분석 문서가 실제 로그와 맞는다.
- 이름 단위 치환이다. 규칙 식의 모양 자체가 실제 로그와 다르면(`modules.yaml`의 잡음·배경·사슬 식) 사내에서 손으로 고친다.
- Android 양식은 꼴로 찾은 목록이라 평범한 꼴의 placeholder는 빠졌을 수 있다. 사내 IMS는 별도 APK라 IMS 줄은 따로 맞춘다.
- 채운 양식·스냅샷·`docs/site/` 출력은 사내 값이다(SITE_PATHS라 재반입이 덮지 않는다). 사내 밖으로 내지 않는다.
