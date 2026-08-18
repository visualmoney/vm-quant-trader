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

보고서 본문은 갱신하지 않으므로, 이후 조치는 아래 표의 **상태** 열에서 추적한다. 보고서가 지적한 결함이 이미 수정되었는지를 본문을 열어 보지 않고 알 수 있어야 하기 때문이다. 각 보고서 머리말에도 같은 내용의 후속 안내가 한 줄 붙는다.

| 보고서 | 상태 | 요약 |
| --- | --- | --- |
| [20260818-01-codebase-comprehension-strategy.md](dev/reports/20260818-01-codebase-comprehension-strategy.md) | 유효 · 일부 해소 | 아키텍처 지도, 4단계 학습 경로, **실습 과제 10종(T1~T10)**, 확장 지점 15개, 커버리지 공백 및 기술부채 지도 (기준: `b94c6c0` / v0.3.10). §8-1은 v0.3.12에서, §8-7의 일부는 v0.3.13에서 해소. T5~T8 수행 완료 |
| [20260818-02-transaction-cost-consolidation.md](dev/reports/20260818-02-transaction-cost-consolidation.md) | **v0.3.13 구현 완료** | `Transaction.cost_with_commission`를 `Portfolio`가 사용하도록 통합하는 구현 준비서 — 동치성 분석, 변경 설계, 테스트 계획 |
| [20260818-03-performance-module-defects.md](dev/reports/20260818-03-performance-module-defects.md) | **v0.3.13 수정 완료** | `statistics/performance.py`의 **결함 2건** — 발생하지 않는 `ValueError`, 최대 낙폭 과소 보고(실측 최대 5.44%p) |
| [20260818-04-execution-and-cost-layer-limits.md](dev/reports/20260818-04-execution-and-cost-layer-limits.md) | **부분 수정** | T7 실험 — 사이저의 **수수료 과대 추정**(성과 손실의 22.2%)과 실행 알고리즘 주입 지점 부재는 v0.3.13에서 수정. **시간 분할 실행 불가(L1)는 구조적 한계로 남음** |
| [20260818-05-data-source-contract.md](dev/reports/20260818-05-data-source-contract.md) | **v0.3.13 수정 완료** | T8 실험 — `DataSource` ABC 신설과 인메모리 구현체 추가, 역추출한 계약, `adjusted` 인자 불일치 해소, **시작일 이전 조회가 미래 가격을 반환하던 룩어헤드 결함** |
