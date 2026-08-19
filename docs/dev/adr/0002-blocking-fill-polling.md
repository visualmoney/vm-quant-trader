# ADR-0002: 체결 폴링은 `submit_order()` 안에서 블로킹한다

| 항목 | 내용 |
| --- | --- |
| 상태 | **제안됨 (Proposed)** — 미구현 |
| 작성일 | 2026-08-19 |
| 맥락 | [spec/kis-broker-design.md](../spec/kis-broker-design.md) §2.1, §6 |
| 관련 요구 | FR-3·FR-16, NFR-7, C-7 ([spec/kis-broker.md](../spec/kis-broker.md)) |

## 맥락

`SimulatedBroker`는 `submit_order()`에서 주문을 큐에 넣고, `update(dt)`가 큐를 비우며 즉시 체결시킨다(`simulated_broker.py:672-682`). 실계좌는 접수와 체결이 분리되므로 어딘가에서 폴링해야 한다. 어디서 하느냐가 이 결정이다.

`ExecutionHandler`는 **주문마다** `submit_order` 직후 `update(dt)`를 호출한다.

```
execution_handler.py:83-86    for order in final_orders:
                                  self.broker.submit_order(self.broker_portfolio_id, order)
                                  self.broker.update(dt)
```

## 결정

**`KisBroker.submit_order()`가 접수 후 종결까지 동기 폴링한다.** `update(dt)`는 시가평가와 reconciliation만 담당한다.

## 검토한 대안

| 대안 | 내용 |
| --- | --- |
| 대안 1 | `submit_order`는 접수만 하고 큐에 넣는다. `update(dt)`가 폴링해 체결분을 반영한다 (`SimulatedBroker`와 동형) |
| 대안 2 | 비동기 이벤트 펌프 (웹소켓 체결 통보) |

## 근거

- **대안 1은 호출 형태가 어차피 같다.** `ExecutionHandler`가 제출 직후 `update`를 부르므로 "제출→즉시 update"라는 순서는 동일하고, 다만 `update`가 다른 주문의 폴링까지 떠안아 책임이 섞인다.
- **결정안은 주문 1건의 생애가 한 함수 안에서 끝난다.** 원장의 write-ahead 전이(INTENT→SUBMITTED→FILLED/PARTIAL/STALE)를 한곳에 둘 수 있다 (FR-16).
- **대안 2는 C-7로 배제**된다 — 웹소켓 스트리밍은 비범위다.
- 리밸런싱 주기가 일~주 단위이므로 **주문당 수십 초 블로킹은 비용이 아니다.** lab의 `KisExecution`이 동일한 판단을 내렸고 그 docstring이 근거를 남겼다 — *"일~월 리밸런싱 빈도에서 몇 초 폴링 대기는 문제가 아니다."*

## 결과

- `submit_order`가 **느리고 블로킹**한다. `Broker` ABC docstring이 기술한 *"It contains a queue of open orders"*(`broker.py:20-21`) 모델에서 벗어난다.
- 종목 20개면 최악 20 × (`poll_interval` × `max_polls`)이 걸린다. **NFR-7(10분 이내) 상한 검증이 필수**다.
- `execution_handler.py:86`의 `update(dt)` 호출이 폴링 직후 시가평가·잔고조회를 유발해 **불필요한 API 호출**이 된다. 라이브 경로에서는 `update`가 최소 호출 간격(throttle)을 갖도록 한다 — 구체적 방식은 설계안 §10의 Q4로 남는다.
