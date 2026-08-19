# ADR-0005: 매도 전용 증권거래세는 `quantity` 부호로 판정한다

| 항목 | 내용 |
| --- | --- |
| 상태 | **제안됨 (Proposed)** — 미구현 |
| 작성일 | 2026-08-19 |
| 맥락 | [spec/kis-broker-design.md](../spec/kis-broker-design.md) §2.6 |
| 관련 요구 | FR-13, C-9, NFR-4 ([spec/kis-broker.md](../spec/kis-broker.md)) |

## 맥락

한국 증권거래세는 **매도 대금에만** 부과된다(C-9). 그러나 현행 `PercentFeeModel._calc_tax`는 `abs(consideration)`에 세율을 곱하므로 **매수에도 세금이 붙는다**(`percent_fee_model.py:47-68`).

## 결정

`KoreaStockFeeModel._calc_tax`가 **`quantity < 0`일 때만** 세금을 부과한다. `FeeModel` ABC는 손대지 않는다.

## 검토한 대안

| 대안 | 내용 |
| --- | --- |
| 대안 1 | `FeeModel`에 `side` 인자를 추가한다 |
| 대안 2 | `Equity.tax_exempt`를 이용한다 |

## 근거

`calc_total_cost(asset, quantity, consideration, broker=None)`는 **이미 `quantity`를 받는다**(`fee_model.py:63`). 부호로 방향을 판정할 수 있으므로 인터페이스를 넓힐 이유가 없다.

- **대안 1**은 기존 `FeeModel` 3종과 호출부 3곳(`simulated_broker.py:580`, `long_short.py:146`, `dollar_weighted.py:156`)을 모두 바꾼다. 이득 없는 파급이다.
- **대안 2**는 `tax_exempt`가 **종목 속성**이지 거래 방향이 아니어서 의미가 맞지 않는다. 게다가 현재 어떤 `FeeModel`도 이 플래그를 읽지 않는다(사용처 0건).

## 결과

- 사이저의 비용 추정도 같은 모델을 쓰므로(`long_short.py:146`) **매도 시 추정 비용이 매수보다 커진다.** 이는 실제와 부합하는 개선이다.
- **다만 사이저가 부호를 잃는다.** `_estimate_trade_costs`는 `trade_dollars`를 `abs()`에서 유도한 뒤 `trade_quantity`를 항상 양수로 만든다(`long_short.py:145`). 매도 방향 정보가 여기서 소실되므로, 사이저가 부호를 보존하도록 국소 수정이 필요하다.
- **이것이 이 설계 전체에서 유일한 엔진 코어 침습**이다. 백테스트 결과를 바꿀 수 있으므로 NFR-4(백테스트 무회귀)와 충돌 여부를 Phase 1에서 확인해야 한다 (설계안 §11 Q5).
