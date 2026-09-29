---
id: {{TYPE_ID}}
category: {{CATEGORY}}
secondary_categories: []
title: {{증상, ~하지 않음/~됨}}
summary: {{증상 한 문장}}
status: active
symptom_signatures:
  - id: {{kebab-case}}
    must_match: ['{{정규식}}']          # 또는 must_event
    must_not_match: []
    window_sec: 60
causes:
  - id: {{TYPE_ID}}-01
    status: active
    title: {{원인 명사구}}
    description: {{원인 한 문장}}
    signatures:
      - id: {{kebab-case}}
        must_match: ['{{정규식}}']      # 또는 must_event
        window_sec: 60
    recovery_signatures: []           # framework-bug/vendor-ril/modem/carrier-config면 권장
    scenario_signatures: []           # 위 유형은 fixed 전환 전 recovery/scenario 중 하나 필수
    # signatures_pending: true      # record에서 사용자가 명시할 때만. signatures를 비울 수 있음 (contracts.md §상태 값)
    resolution: {{행동 지시, ~한다}}
    resolution_type: {{user-setting|carrier-config|framework-bug|vendor-ril|modem|network|hw}}
    resolution_verification: {status: unverified}
    fix: {status: {{open|fix-submitted|wont-fix|not-a-bug}}, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null                 # 모뎀 쪽 원인이면 CP 근거 요약 (선택, 마스킹 대상)
    android_versions: []              # 빈 목록 = 전 버전
    code_refs: []
tags: []
---

## 증상
{{사용자 관점 증상, 재현 조건}}

## 증상 판별 방법
{{증상 시그니처 설명 + 마스킹된 로그 예시}}

## 원인별 상세
### {{TYPE_ID}}-01 {{원인 title}}
- **로그 예시**:
  ```
  {{마스킹된 로그 5~15줄}}
  ```
- **확인 방법**: {{어떤 로그/설정/코드를 보면 이 원인으로 확정되는지}}
- **재현 시나리오**: {{동작 순서와 조건}}
- **해결책**: {{resolution 상세}}
- **코드 위치**: {{code_refs 설명}}
- **비고**: {{버전/캐리어 특이사항}}
