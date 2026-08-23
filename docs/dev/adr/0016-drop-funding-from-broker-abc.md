# ADR-0016: 자금 이체 4종을 `Broker` ABC에서 제외한다

| 항목 | 내용 |
| --- | --- |
| 상태 | **채택됨** (2026-08-23) |
| 성격 | **파괴적 변경** — 추상 메서드 13개 → 9개 |
| 관련 | [ADR-0004](0004-promote-update-to-abc.md), [ADR-0015](0015-venue-neutral-live-package.md), [보고서 20260823-01 §5.1 소견 B-1](../reports/20260823-01-codebase-comprehension-strategy.md) |

## 맥락

`Broker` ABC의 추상 메서드 13개 중 4개가 자금 이체였다.

```text
subscribe_funds_to_account(amount)
withdraw_funds_from_account(amount)
subscribe_funds_to_portfolio(portfolio_id, amount)
withdraw_funds_from_portfolio(portfolio_id, amount)
```

`SimulatedBroker`에서는 실동작한다 — 백테스트는 어딘가에서 초기 자금이 나와야 하고, 마스터 현금 계정과 서브포트폴리오 사이의 내부 이체가 그 수단이다(`backtest.py:238`).

**라이브에서는 넷 다 거절만 했다.** 증권사는 자금 이체 API를 제공하지 않으므로 — KIS도, DB증권도 — 로컬 잔고만 바꾸면 계좌와 즉시 어긋난다. 그래서 `LiveBroker`는 네 개를 구현하되 전부 `_reject_funding()`으로 같은 `NotImplementedError`를 던졌다. **ABC가 강제해서 존재하는, 거절만 하는 메서드 4개**였다.

문제는 두 가지다.

1. **인터페이스가 추상이 아니라 시뮬레이터를 서술한다.** `Broker`를 인자로 받는 코드는 계약상 이 넷을 호출해도 된다고 믿을 근거가 있는데, 라이브 구현에서는 언제나 예외다. 즉 계약이 거짓말을 한다.
2. **비용이 브로커 수에 비례한다.** ADR-0015로 `LiveBroker`가 모든 증권사의 공통 상위가 되면서 복제 압력 자체는 사라졌지만, 다른 성격의 브로커(예: 선물 계좌, 해외 계좌)를 별도로 만들면 같은 거절 스텁 4개가 다시 필요해진다.

인터페이스 분리 원칙(ISP) 위반의 교과서적 형태다.

## 결정

**네 개를 `Broker` ABC에서 제거한다.** 추상 메서드는 13개에서 **9개**가 된다.

| 구현체 | 이후 |
| --- | --- |
| `SimulatedBroker` | **그대로 유지.** 추상이 아닌 평범한 메서드가 된다. 백테스트가 자금을 넣는 유일한 경로이므로 동작·시그니처·테스트 모두 불변 |
| `LiveBroker` | **네 개와 `_reject_funding`을 삭제한다.** ABC가 강제하지 않는 이상 존재 이유가 없다 |

`Broker` 클래스 docstring의 *"through which all subscriptions and withdrawals will occur"* 문장도 함께 정정한다. 계약에서 빠진 것을 docstring이 계속 약속하면 제거의 의미가 없다.

### 왜 `LiveBroker`의 스텁까지 지우는가

친절한 예외 메시지를 남기는 선택지가 있었다. 지우기로 한 이유는 **`AttributeError`가 더 정직하기 때문**이다. `NotImplementedError`는 "이 메서드는 있는데 아직 안 만들었다"를 뜻하지만, 라이브 계좌에 입금 API는 앞으로도 없다. 메서드가 없는 것이 사실이다.

메시지가 담고 있던 운영 지식 — *"증권사에서 직접 입금하라, 엔진은 잔고를 읽는다"* — 은 운용 문서(`docs/user/kis-live-operations.md`)와 `LiveBroker.seed_from_venue()`의 docstring에 이미 있으며, 잃지 않는다.

## 대안과 기각 사유

| 대안 | 기각 사유 |
| --- | --- |
| **현행 유지** | 계약이 라이브 구현에 대해 거짓이다. 이 ADR의 전제 |
| **`FundableBroker` 하위 인터페이스 신설** ([보고서 R5](../reports/20260823-01-codebase-comprehension-strategy.md)의 원안) | **다형적 호출자가 없다.** `backtest.py:238`과 `test_pcm_e2e.py:55` 둘 다 구상 `SimulatedBroker`를 상대로 부른다. 아무도 통과하지 않을 계약을 새로 만드는 것은 방금 지운 문제의 반복이다. 두 번째 자금 이체 가능 브로커가 실제로 생기면 그때 만든다 |
| **`Broker`에는 남기되 `@abstractmethod`만 뗀다** (기본 구현이 raise) | 이름이 인터페이스에 남으므로 호출해도 된다는 오해가 그대로다. 게다가 기본 구현이 raise인 메서드는 추상 메서드의 열등한 형태다 |
| **`LiveBroker`의 거절 스텁은 남긴다** | 위 참조. `AttributeError`가 사실에 더 가깝고, 운영 지식은 다른 곳에 있다 |

## 결과

**좋은 점**

- 인터페이스가 **모든 구현체가 실제로 할 수 있는 것**만 선언한다. 9개 전부 시뮬레이터와 라이브 양쪽에서 의미가 있다.
- 새 브로커의 구현 부담이 4개 줄고, 그 4개는 전부 "거절만 하는" 것이었다.
- `LiveBroker`에서 30줄이 사라진다.

**나쁜 점 / 비용**

- **파괴적 변경이다.** `Broker`를 직접 상속한 사용자 정의 브로커가 이 넷을 구현했다면 그대로 두어도 무해하지만(더 이상 요구되지 않을 뿐), `Broker` 타입 인자에 대고 이 넷을 호출하던 코드는 깨진다. 저장소 안에는 그런 호출부가 없다.
- 라이브 브로커에 입금을 시도하면 `NotImplementedError` 대신 `AttributeError`가 난다. 메시지가 덜 친절하다는 것이 의식적으로 치른 값이다.

**남는 것**

이 ADR은 [보고서 20260823-01 §5.1](../reports/20260823-01-codebase-comprehension-strategy.md)의 소견 **B-1만** 해소한다. 같은 절의 B-2(`update(dt, force=)` 시그니처 드리프트)와 B-3(`LiveTradingSession`이 의존하는 브로커 멤버 7개 중 계약이 보장하는 것은 1개, `reconcile()`의 비공개 4종 호출)은 그대로다. 보고서의 R4·R5에 해당하며 각각 별도 결정이 필요하다.

**검증**

- `tests/unit/test_abstract_base_classes.py`가 넷이 `Broker.__abstractmethods__`에 없고 `SimulatedBroker`에는 있음을 고정한다.
- `tests/unit/broker/test_live_broker.py`가 라이브 브로커에 그 넷이 **존재하지 않음**을 고정한다. 시뮬레이터에서 복사해 오다 되살아나기 쉬운 종류의 변경이라 명시적으로 막는다.
- 백테스트 e2e 5건이 무변경 통과 — 자금 주입 경로가 그대로임의 근거.
- 716 케이스 통과, `ruff check` 통과.
