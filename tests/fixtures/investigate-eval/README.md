# 조사 모드 비교 eval 합성 case (`tools/investigate_eval.py`)

합성 case 2개(공개 근거만 — 줄 모양은 AOSP·에뮬레이터 형식을 흉내 낸 것이고 태그 `vrild`는 placeholder다). 틀 시험용이며 모델 출력을
기록한 것이 아니다. 사내는 실제 case 5~10건을 SITE_PATHS에 같은 모양으로 두고 돌린다.

- `<case>/case.json`: 정답 책임 층·원인 줄 고정 조각
- `<case>/before/`: 변경 전(조사 모드 없음 — `investigation` 없음, 결론 보류)
- `<case>/after/`: 변경 뒤(`analysis.json`에 check-output이 쓴 `investigation`)
