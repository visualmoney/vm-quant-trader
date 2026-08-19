# ADR-0004: `update(dt)`를 `Broker` ABC의 추상 메서드로 승격한다

| 항목 | 내용 |
| --- | --- |
| 상태 | **제안됨 (Proposed)** — 미구현. **파괴적 변경** |
| 작성일 | 2026-08-19 |
| 맥락 | [spec/kis-broker-design.md](../spec/kis-broker-design.md) §2.2 |
| 관련 요구 | FR-1 ([spec/kis-broker.md](../spec/kis-broker.md)) |

## 맥락

`broker.py`의 `@abstractmethod`는 12개이고 그중 `update`는 없다. 그런데 호출부 두 곳이 이미 이를 사용한다.

| 호출부 | 위치 | 빈도 |
| --- | --- | --- |
| `ExecutionHandler.__call__` | `execution_handler.py:86` | 주문 제출 직후마다 |
| `BacktestTradingSession.run` | `backtest.py:408` | 이벤트 루프 매 틱 |

즉 **암묵 계약**이다. `Broker`를 상속한 새 클래스가 `update`를 빠뜨려도 인스턴스화는 성공하고, 실행 중에야 `AttributeError`로 터진다.

## 결정

`broker.py`에 `@abstractmethod def update(self, dt)`를 추가한다. 추상 메서드 12개 → **13개**.

## 검토한 대안

| 대안 | 내용 |
| --- | --- |
| 대안 1 | 현행 유지 (암묵 계약) |
| 대안 2 | 기본 구현(no-op)을 가진 비추상 메서드로 추가 |

## 근거

라이브 브로커에서 `update`는 **시가평가와 reconciliation의 유일한 진입점**이다. 누락은 예외가 아니라 **조용한 상태 발산**으로 나타난다 — 포지션 시가가 갱신되지 않은 채 사이징이 돌고, 잔고 대조가 영원히 실행되지 않는다.

대안 2는 라이브 구현체가 실수로 no-op을 상속받을 여지를 남긴다. 이 결정의 목적이 바로 그 실수를 막는 것이므로 자기모순이다.

## 결과

- **외부 사용자의 커스텀 `Broker` 구현이 깨진다.** 완화 요인 두 가지:
  - 이 저장소는 포크이며 배포 사용자층이 상류와 다르다.
  - `tests/unit/test_abstract_base_classes.py`가 ABC 목록을 명시 관리하고 `Broker`를 이미 포함한다(`:49`). 추상 메서드 수 변경이 테스트에 드러난다.
- CHANGELOG에 **파괴적 변경**으로 기록한다.
- 설계안 §2.2가 지적한 나머지 두 계약 누출(`get_account_total_equity()["master"]`, `broker.portfolios[id]` 직접 접근)은 이 ADR의 범위 밖이다 — 별도로 다룬다.
