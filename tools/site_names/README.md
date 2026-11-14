# 사내에서 모듈 템플릿 이름 채우기

반입 묶음의 모듈 템플릿은 벤더 고유 이름이 placeholder(`VIPC_EXAMPLE_*`, `Example…`, `vrild` 등)로 들어 있다.
이 폴더의 양식(레포에 들어 있다)에는 **실제 값이 없다**. 실제 값은 사내 로그·소스를 보고 사내에서 채운다.

| 파일 | 내용 |
|---|---|
| `ofono-names-form.json` | oFono placeholder 83종. `real` 칸이 빈칸 |
| `android-names-form.json` | Android placeholder 45종(벤더 RIL 아래 층). `real` 칸이 빈칸 |
| `tools/names_fill.py` | 채운 양식대로 템플릿과 `modules.yaml`의 그 플랫폼 블록을 바꾼다 |

각 행: `placeholder`, `real`(채울 칸), `kind`(종류), `count`(쓰인 횟수), `example_lines`(레포의 합성 로그에서 이 이름이 나오는 줄 — 어느 데몬의 어떤 줄에서 찾을지 단서), `files`.

## 순서
1. 반입을 마치고 사내 레포 작업 브랜치를 만든다. 양식은 **사내 레포 안에서** 채운다(채운 양식을 커밋할지는 사내 규정대로 — 사외로 나가는 곳에는 두지 않는다).
2. 사내 Claude에게 아래 문장을 준다(로그 경로만 바꾼다). 토큰을 쓰는 단계는 이것 하나다.
   > `ofono-names-form.json`의 각 행에서 `example_lines`와 `kind`를 단서로, `<사내 마스킹 로그 경로>`에서 같은 자리에 나오는 실제 이름을 찾아 `real`에 채워 줘. 확실한 것만 채우고 모르면 비워 둬. 로그 전체를 읽지 말고 행마다 grep으로 찾아. 채운 결과를 표(placeholder · real · 근거 줄)로 보여 주고, 내가 확인하기 전에는 파일을 바꾸지 마.
3. 표를 확인한 뒤 미리 보기 → 적용:
   ```
   python3 -I -X utf8 tools/names_fill.py <레포 루트> tools/site_names/ofono-names-form.json
   python3 -I -X utf8 tools/names_fill.py <레포 루트> tools/site_names/ofono-names-form.json --write
   ```
4. `python3 tools/site_step.py modules coverage --out docs/site/module-coverage.diff`(토큰 0)로 모듈에 없는 데몬·태그를 본다.
5. 모듈 eval `--dry-run`과 테스트를 돌리고, 모듈 레포 PR로 올린다.

## 알아 둘 것
- 빈 행은 placeholder로 남는다. 다 못 채워도 동작은 하고, 채운 만큼 분석 문서가 실제 로그와 맞는다.
- 이름 단위 치환이다. 규칙 식의 모양 자체가 실제 로그와 다르면(`modules.yaml`의 잡음·배경·사슬 식) 사내에서 손으로 고친다.
- Android 양식은 꼴로 찾은 목록이라 평범한 꼴의 placeholder는 빠졌을 수 있다. 사내 IMS는 별도 APK라 IMS 줄은 따로 맞춘다.
- 채운 양식과 `docs/site/` 출력은 사내 값이다. 사내 밖으로 내지 않는다.
