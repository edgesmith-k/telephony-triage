# 모의 소스 트리 (15-local-draft.md §15.2)

`code_roots.py`(경로 검증, 트리 버전 추정, `find-symbol`)를 시험하기 위한
**심볼만 있는 스텁**이다. 실제 AOSP·벤더 소스가 아니다.

- 루트 키: `aosp` → `android16/`·`android17/`,
  `vendor_ril` → 그 아래 `vendor/mockril/`
  (`02-config.md §4` `code_profiles.roots`,
  `issue-db.config.yaml`의 `code_root_keys`)
- 트리 버전 식별 파일: `build/make/core/version_defaults.mk` — TODO(SITE:S11)
  (사내 트리에서 버전을 알 수 있는 파일은 다를 수 있다)
- **16과 17에서 경로가 다른 파일**: `DataFailCause.java`
  - 16: `frameworks/base/telephony/java/android/telephony/DataFailCause.java`
  - 17: `frameworks/opt/telephony/src/java/com/android/internal/telephony/data/fail/DataFailCause.java`
  - `find-symbol`이 버전마다 다른 경로를 찾아내는지 시험한다
    (`07-workflow.md §Step 2-1`, `§Step 5`).
- 벤더 RIL 태그·구조는 placeholder다 — TODO(SITE:S10)
