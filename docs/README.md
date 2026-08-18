# QSTrader 문서

문서는 독자에 따라 두 갈래로 나뉜다.

## `user/` — 전략 개발자용

QSTrader를 **사용해** 전략을 만드는 사람을 위한 문서. 엔진 내부 구현을 몰라도 읽을 수 있어야 한다.

설치, 데이터 준비, 백테스트 조립, 알파모델 작성, 결과 해석, 자주 밟는 함정.

## `dev/` — 엔진 기여자용

QSTrader 자체를 **수정하는** 사람을 위한 문서. 계약, 불변식, 테스트 정책, 기술부채.

### `dev/reports/` — 시점별 조사 보고서

`dev/` 바로 아래의 문서는 코드와 함께 갱신되는 **살아있는 문서**다.
반면 `reports/`는 특정 시점의 **스냅샷**이며 갱신하지 않는다. 낡은 조사 결과가 현재 명세처럼 읽히는 것을 막기 위해 분리한다.

파일명 규칙: `{yyyymmdd}-{nn}-{topic}.md` — 같은 날 여러 건이면 `nn`을 증가시킨다.

| 보고서 | 요약 |
| --- | --- |
| [20260818-01-codebase-comprehension-strategy.md](dev/reports/20260818-01-codebase-comprehension-strategy.md) | 아키텍처 지도, 4단계 학습 경로, **실습 과제 10종(T1~T10)**, 확장 지점 15개, 커버리지 공백 및 기술부채 지도 (기준: `b94c6c0` / v0.3.10) |
| [20260818-02-transaction-cost-consolidation.md](dev/reports/20260818-02-transaction-cost-consolidation.md) | `Transaction.cost_with_commission`를 `Portfolio`가 사용하도록 통합하는 **구현 준비서** — 동치성 분석, 변경 설계, 테스트 계획, CHANGELOG 초안 (미구현) |
| [20260818-03-performance-module-defects.md](dev/reports/20260818-03-performance-module-defects.md) | `statistics/performance.py`에서 발견한 **결함 2건** — 발생하지 않는 `ValueError`, 최대 낙폭 과소 보고(실측 최대 5.44%p). 특성 테스트로 고정, 수정 미실시 |
