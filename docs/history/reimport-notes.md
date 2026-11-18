# 지난 재반입 노트 (DRAFT_NOTES에서 옮김)

## import-20261115 (사내 반입 11/16)

- **재반입 노트 (import-20261115 = import-20261103(`77e2827`) 이후 전부)**
  - guard 판정이 바뀌었다(`08-safety.md §9`): base push·병합 계열(규칙 6·11)과 규칙 5(`ci_mode: actions`)는 거부→ask, Claude의 Approve·리뷰 기각·자동 병합 켜기·보호 변경·`refs/remotes` 위조는 새로 거부. 팀 배포 전 `site_step.py check S-4a` `s4a.protection_guard` 통과. §8대로 사내 대상 eval 12개 모두 다시. S1 확인 전인데 site-defaults `tracker.isolation_confirmed: true`면 `false`로.
  - 새 DB는 마스킹 끔(SITE_INSTALL §9, 스킬 eval 없음). 가리는 DB만 S13을 새 방법으로 다시, 그 전엔 사내 로그를 DB에 안 넣는다.
  - S-5 `offline_eval`은 이슈 DB에 이미 있는 키도 표본내로 뺀다. 옛 판으로 `summary`까지 한 대기 작업은 PR 본문에 메모 원문이 남는다 → `summary` 다시나 `discard`. `issue_db.path`가 이슈 DB clone이 아니면(빈 값·상대 경로·`issue-db.config.yaml` 없음) `db_pr`·`db_verify`가 git 전에 종료 2. #112·#113 변경은 표시 기록 블록(`render_markdown`·`shown.record`)에 닿지 않는다.
  - `platform.ril.vendor`를 두었으면 벤더 HAL 짝(`hal`)이 바뀔 수 있다 → `db_regress`로 확인(#109). S-0이 `site_step` 첫 단계(#102). 직접 입력한 소스 경로는 개인 `code_profiles`에 자동 저장(#106).
  - 그 밖(#80 모듈 스킬 레포·+1 병합, #85 스냅샷 overlay, #86 Android 17 태그·RIL·슬롯, #87 OpenCode, #90·#95·#98 마스킹): 파일별 영향·관리자 할 일(`site-defaults.yaml`의 `analyzers.*.inputs`·`max_tokens_hint`·`issue_db.merge` 지우기)은 `MODULE_SKILLS_RESULT.md` "반입 노트"(#80까지). #114 백엔드 0.1.5: 첫 분석은 캐시 없이 돈다, `min_version`은 그대로. #117: plan·DB 영향 없음. 사내 DB는 schema PR 전까지 항목 `ref` 든 계획을 종료 2로 거부. #118: data 규칙 `NOT_IN_SERVICE`(등록 상실 뒤)→모뎀·망. #119: Android 합성 벤더 줄 꼴만(규칙 불변).
  - #121 정밀 탐색(`--deep`): 명시 요청 때만, 효과 미확인. `deep.md`는 사내 스냅샷에 새로 만들고(없으면 `--site-overlay` 종료 1) 플러그인 배포 뒤 모듈 레포에 올린다. #122: `import_draft --label` 필수. `tracker.read_tools`에 쓰기형 도구 이름 거부(doctor `tracker` warn). 경계 검사 15~20자리·이슈 DB hook 교체는 SITE_INSTALL §8. `docs/development` 22개는 `docs/history`로 옮김(dry-run 지움 약 41). OpenCode는 첫 설치(`opencode/README.md`: `tt-oc publish`, git ≥ 2.38, 모델이 낸 명령을 붙여 넣지 않는다). #123·#125~#135: 탐색 `--with <모듈>`(보조 모듈 줄 절), report 네 칸, `import_draft --status`, Android 시드, 흐름 점검·제안 줄, 마스킹 끔. `set-flow-step`·oFono 글자 버전은 DB schema PR 뒤.
  - OpenCode: install --force 재설치(+ --explore-model), 관리 설정 task는 새 객체 또는 문자열 deny
  - 사내 읽기(1103 대비, KB): S-0 −18.2·S-1 +8.3·S-2 +6.9·S-3 +12.4·S-4 +5.2·S-4a +1.1·S-5 +0.3·S-6 0·S-7 +2.1.
