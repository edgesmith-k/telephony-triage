---
name: mock-data-analyzer
description: 모의 data 심층 분석 스킬. 사내 기존 data 분석 스킬(16-existing-assets.md §16.5)을 대신한다. 사외 테스트에서 analyze Step 5 뒤의 호출 경로만 확인한다.
---

# 모의 data 심층 분석 스킬

사내에 이미 있는 **data 카테고리 분석 스킬**을 연결하는 자리를 사외에서
흉내 낸 것이다 (`16-existing-assets.md §16.5`). 실제 분석은 하지 않는다.

## 언제 불리나

`analyze` Step 5(코드 분석) 뒤, Step 6 리포트 전. 설정은
`site-defaults.yaml` 또는 사용자 config의 `analyzers.data`다.

```yaml
analyzers:
  data:
    skill: mock-data-analyzer
    when: ask                  # 기본값. 1위가 data일 때 호출 여부를 묻는다
    inputs: [events_json, log_paths, top_candidates, jira_summary]
    max_tokens_hint: medium
```

- `--analyzer`는 묻지 않고 호출, `--no-analyzer`는 호출하지 않는다.
- 스킬이 없거나 실패해도 analyze는 계속한다 ("심층 분석 생략: <사유>").

## 입력

| 이름 | 내용 |
|---|---|
| `events_json` | 파서 이벤트 JSON **경로** (마스킹된 상태) |
| `log_paths` | 로그 파일 경로 목록 |
| `top_candidates` | 상위 후보 `[{type, cause, score, confidence}]` |
| `jira_summary` | 마스킹된 Jira 요약 한두 줄 |

원문 로그를 통째로 넘기지 않는다.

## 출력

리포트의 **"심층 분석 (mock-data-analyzer)"** 절에 붙는 텍스트.
분류 후보·점수·확정에는 영향을 주지 않는다. 다른 원인을 제시하면
"분석 스킬 의견: <내용>"으로 보여주고, 사용자가 Step 7에서 그 원인을
고를 수 있게 한다(고르면 `decision: chose-other`).

- 출력은 리포트에 넣기 전에 `mask_pii`를 한 번 더 거친다.
- PR 본문에는 요약 한두 줄만 넣는다(원문 인용 금지).
- 이슈 DB에 없는 원인을 제시해도 그것만으로 원인을 만들지 않는다.
  사용자가 고르면 `new-cause` 흐름(시그니처 초안·검증 포함)으로 간다.

## 사외 테스트에서 쓰는 법

LLM 없이 호출 경로만 확인하려면 같은 디렉토리의 `run.py`를 쓴다.
같은 입력이면 항상 같은 출력을 낸다.

```sh
python3 tests/mocks/skills/data-analyzer/run.py --input <입력.json>
```

## 사내 연결 (S-4a)

`analyzers.data.skill`을 사내 실제 스킬 이름으로 바꾸고, 실제 이슈 1건으로
dry-run 한다 — TODO(SITE:S1) 스킬 이름과 호출 방식 확인.
