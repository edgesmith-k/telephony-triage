# Android 시작 유형 묶음 (이슈 DB 시드)

빈 이슈 DB로 파일럿을 시작하지 않도록, **AOSP 프레임워크 로그만으로 판별되는** 유형·원인 초안을 카테고리별 `source: import` 계획으로 둔 것이다.
운영 이슈 DB 뼈대에는 들어 있지 않다 — 사내 S-4에서 카테고리마다 실제 로그를 붙여 PR로 등록한다(`docs/design/15-local-draft.md` S-4, `16-existing-assets.md §16.4`).

- `<카테고리>/plan.json`: 새 유형(증상)·원인·시그니처·필요한 파서 태그 규칙. 유형 목록은 이 파일의 `new-type`·`new-cause`.
- `<카테고리>/fixtures/*.log`: **합성 로그**다(AOSP 소스의 로그 문구와 에뮬레이터 캡처 모양으로 쓴 최소 줄). 계획의 `add-fixture`마다 `expect: {"origin": "synthetic"}`으로 표시돼 있다.
- 근거는 공개 자료뿐이다(AOSP 소스, 에뮬레이터, 합성). 벤더 RIL·모뎀 줄은 없다 — CP·망 쪽 원인은 `cp_evidence`에 "벤더 로그로 확정"과 다음에 받을 로그만 적혀 있다.
- 버전: 근거가 Android 17 소스·에뮬레이터 캡처뿐이라 모든 원인과 `code_refs` 항목이 `platform_versions: ["17"]`이다. 다른 버전 로그로도 확인되면 그 버전을 더한다(버전 표시는 후보를 걸러내지 않고 리포트에 "버전 불일치"만 붙인다). 새 Android 버전이 나왔을 때 할 일은 `docs/design/99-deferred.md` K절.
- 해결책은 모두 미검증(`unverified`), Jira 기록은 없다. 시간 기준(몇 초 넘으면 지연 등)은 정하지 않았다 — `TODO(SITE)`.

## 사내 등록 순서 (카테고리 하나씩)

1. 카테고리 폴더를 작업 폴더로 복사한다(`<work_dir>/import-<카테고리>-1/`). 이 레포의 원본은 고치지 않는다(사외 파일 — 고치면 다음 반입이 멈춘다).
2. 유형마다 같은 증상의 **사내 실제 로그**를 마스킹해 `fixtures/`의 합성 로그를 같은 이름으로 바꾸고, 그 `add-fixture`의 `"origin": "synthetic"`을 지운다(`expect`가 비면 `expect` 키째).
   실제 로그가 없는 유형·원인은 계획에서 뺀다(그 `new-type`/`new-cause`와 딸린 `add-fixture`). 음성 fixture도 실제 정상 로그로 바꾼다.
3. 시그니처를 실제 문구에 맞춘다. 프레임워크 줄은 대개 그대로 맞지만 빌드마다 문구가 다를 수 있다. 계획의 `add-parser-rule`이 넣는 태그가 운영 DB에 이미 있으면 그 op를 빼고, 뼈대의 `placeholder` 태그 규칙은 `update-parser-rule`로 바꾼다.
4. `base_sha`를 `db_pr snapshot`이 낸 sha로 채우고 초안 검증을 돌린다: `db_verify.py rules --plan <plan.json> --draft <폴더>` — R1~R5. 다른 유형 fixture에서 걸리면 시그니처를 좁힐지 `also_allowed`로 허용할지는 사용자가 고른다.
5. `db_pr stage … --branch import/<카테고리>-<n>` → 확인 화면 → 승인 뒤 push → 카테고리 오너 리뷰. 한 PR은 새 유형 10개 이하.
6. 합성 fixture가 남으면 S-6 점검(`origin: synthetic` 0건)이 잡고, S-4 시드 수(`s4.seed`)에도 세지 않는다.

계획이 이 레포의 뼈대에 그대로 적용되고 서로 걸리지 않는지는 `tests/test_android_seeds.py`가 본다(합성 로그 기준 — 실제 로그로 바꾼 뒤의 판정은 4번).
