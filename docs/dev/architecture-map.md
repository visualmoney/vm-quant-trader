# VMTrader 아키텍처 지도

기여자가 가장 먼저 읽는 문서. 이 저장소가 실제로 어떻게 생겼는지의 요약집이다.

| 항목 | 내용 |
| --- | --- |
| 성격 | **살아있는 문서** — 코드와 같은 커밋에서 갱신한다 |
| 담지 않는 것 | 커버리지·케이스 수·실행 시간 같은 **실측값**. 그 숫자는 [`reports/`](reports/)의 것이고, 산문에 넣으면 낡는다 |
| 틀렸을 때 | 해당 절을 **지우고 고쳐 쓴다**. 이력은 git이 갖는다 (§7) |

세 문서의 역할은 이렇게 갈린다. [`architecture-principles.md`](architecture-principles.md)는 **잣대**다 — 이 저장소가 아니라 일반 원리를 서술하며, 이 저장소가 그것을 얼마나 따르는지는 §6이 정본이다. [`testing.md`](testing.md)는 **집행**이다 — 테스트를 어떻게 쓰는가, 계층·주입 규약·커버리지 정책. 이 문서는 **현황**이다 — 무엇이 어디에 있고 어느 계약이 무엇으로 고정되는가.

---

## 1. 30초 요약

두 평면이 하나의 `QuantTradingSystem`을 공유한다. 그것이 이 저장소 구조의 전부다.

```
                    ┌───────────────────────────────────────┐
                    │  QuantTradingSystem   system/qts.py   │
   두 평면의 합류점 → │  PCM → Alpha/Risk/Optimiser/Sizer     │
                    │  → ExecutionHandler → broker          │
                    │  Portfolio / Position / Transaction   │
                    └──────────▲───────────────▲────────────┘
                               │               │
             qts(dt, stats)    │               │    qts(now)
                               │               │
  ┌────────────────────────────┴──┐        ┌───┴────────────────────────────┐
  │ 백테스트 평면                  │        │ 라이브 평면 — cron 단발        │
  │ trading/backtest.py           │        │ trading/live.py                │
  │                               │        │                                │
  │ SimulationEngine  시간을 만든다│        │ cron        시간을 준다        │
  │ SimulatedBroker   체결을 흉내  │        │ LiveBroker  체결을 수집        │
  │ SimulatedExchange NYSE 고정   │        │ KrxExchange 휴장일 파일        │
  │ BacktestDataHandler→DataSource│        │ LiveDataHandler → BrokerClient │
  │ Tearsheet / JSONStatistics    │        │ OrderLedger(SQLite) / Guard    │
  │                               │        │ reconcile / TaskQueueWorker    │
  └───────────────────────────────┘        └───────────────┬────────────────┘
                                                           │
                                          프로세스 경계 ────┤ BrokerClient Protocol
                                          SDK는 여기 밖     │ scripts/kis_gateway.py
                                                           ▼
                                                      증권사 API
```

**무엇을 고치려면 어디를 보는가**

| 고치려는 것 | 먼저 볼 곳 | 함께 볼 것 |
| --- | --- | --- |
| 전략이 내는 가중치 | `alpha_model/` · `risk_model/` | §4 |
| 가중치가 정수 수량이 되는 규칙 | `portcon/pcm.py` · `portcon/order_sizer/` | §5 |
| 비용·세금 | `broker/fee_model/` | [ADR-0005](adr/0005-sell-side-transaction-tax.md) · [ADR-0017](adr/0017-paper-is-a-mode-not-a-broker.md) |
| 백테스트 한 스텝의 순서 | `trading/backtest.py` `run()` | §2.1 |
| 라이브 한 사이클의 순서 | `trading/live.py` `run_rebalance()` | §2.2 · [ADR-0009](adr/0009-cron-oneshot-live-session.md) |
| 실주문·체결 수집 | `broker/live_broker.py` | [ADR-0006](adr/0006-decouple-submit-from-fill.md) · [ADR-0008](adr/0008-task-queue-fill-pump.md) |
| 두 번째 증권사 붙이기 | `broker/live/client.py` + `scripts/kis_gateway.py` | [ADR-0015](adr/0015-venue-neutral-live-package.md) · §4 |
| 개장·휴장 판정 | `exchange/` | [ADR-0014](adr/0014-holiday-calendar-from-real-account.md) |
| 가격이 어디서 오는가 | `data/` | §5 · [보고서 20260818-05](reports/20260818-05-data-source-contract.md) |
| 무엇이 거래를 막는가 | `broker/live/guards.py` · `broker/live/reconcile.py` | §5 |

---

## 2. 두 평면의 실행 순서

### 2.1 백테스트 — `BacktestTradingSession.run()` (`trading/backtest.py:393`)

시간을 **만드는** 쪽이다. `SimulationEngine`이 하루에 두 이벤트(`market_open` 14:30 UTC, `market_close` 21:00 UTC)를 낸다.

1. `for event in self.sim_engine:` — 이벤트를 하나 꺼낸다 (`:409`)
2. `broker.update(dt)` — 시가평가하고, 개장 중이면 대기 주문을 체결한다 (`:416`)
3. `market_close`면 `signals.update(dt)` — 롤링 버퍼를 하루치 전진시킨다 (`:420`)
4. 리밸런스 시각이고 burn-in을 통과했으면 **`qts(dt, stats)`** (`:432` / `:440`)
5. `market_close`면 `_update_equity_curve(dt)` — 자본곡선 1포인트 (`:448` / `:450`)

리밸런스 판정은 `frozenset` 완전 일치다(`:144`, `_is_rebalance_event`). **완전 일치**라는 점이 함정을 하나 만든다 — [보고서 20260823-01 §9-6](reports/20260823-01-codebase-comprehension-strategy.md).

주문은 4단계 안에서 끝난다. `ExecutionHandler`가 주문마다 `submit_order()` 직후 `broker.update(dt)`를 부르기 때문이다(`execution/execution_handler.py:85-86`). 지연도, 다음 봉 시가 체결도 없다.

### 2.2 라이브 — `LiveTradingSession.run_rebalance()` (`trading/live.py:128`)

시간을 **받는** 쪽이다. cron이 프로세스를 띄우는 것이 곧 이벤트이며, 기동 1회 = 사이클 1회다([ADR-0009](adr/0009-cron-oneshot-live-session.md)).

1. `reconcile(self.broker)` — 이전 프로세스가 남긴 미결 주문을 정산하고 포지션을 대조한다. `halt_trading`이면 여기서 끝 (`:146`)
2. `broker.guard.check_can_trade()` — 킬스위치 (`:154`)
3. `_is_rebalance_day(now)` — 거래일이고 일정에 있는가 (`:160`)
4. `broker.exchange.is_open_at_datetime(now)` — 개장 중인가 (`:165`)
5. `broker.update(now, force=True)` — 스로틀을 우회해 늦은 체결을 흡수하고 시가평가 (`:170`)
6. `_warm_up_signals(now)` — 매 기동마다 버퍼를 채운다. **이력이 0인 자산이 하나라도 있으면 그날은 거래하지 않는다** (`:172-188`, [ADR-0012](adr/0012-signal-history-from-venue.md))
7. **`qts(now)`** — 접수만 하고 즉시 반환 (`:190`, [ADR-0006](adr/0006-decouple-submit-from-fill.md))
8. `broker.settle(deadline)` — 시간예산 안에서 체결을 수집 (`:195`)

`_deadline()`은 시간예산과 폐장−버퍼 중 **이른 쪽**이 이긴다(`:75-99`).

`run_end_of_day()`(`:222`)는 **별도 기동**이다. `reconcile(halt_on_mismatch=False)` → `update(force=True)` → `record_equity()`. 리밸런스가 죽은 날에도 자본곡선은 기록된다.

### 2.3 갈리는 지점과 합쳐지는 지점

| | 갈린다 | 합쳐진다 |
| --- | --- | --- |
| **시간축** | `SimulationEngine`이 만든다 / cron이 준다 | — |
| **브로커** | `SimulatedBroker` / `LiveBroker` — 다른 클래스다 | `Broker` ABC 9개(§4) |
| **거래소** | `SimulatedExchange`(NYSE 하드코딩) / `KrxExchange`(휴장일 파일) | `Exchange` ABC |
| **데이터** | `BacktestDataHandler`+`DataSource` / `LiveDataHandler`+`BrokerClient` | **공유 ABC 없음 — 덕타이핑** ⚠️ |
| **수수료** | 실제로 차감된다 / 사이저의 **추정에만** 쓰이고 실제 비용은 `OrderReport.fees` | `FeeModel` 객체는 같다, **의미가 다르다** ⚠️ |
| **전략 파이프라인** | — | **`qts(dt)` 한 줄. 여기가 합류점이다** |
| **회계** | — | `Portfolio` / `Position` / `Transaction` 동일 |

합류점이 한 줄이라는 것이 이 설계의 성취다. 표의 ⚠️ 둘은 부채이며 §6과 [보고서 20260823-01 §9-1](reports/20260823-01-codebase-comprehension-strategy.md)이 추적한다.

---

## 3. 모듈 지도

| 패키지 | 책임 | 평면 |
| --- | --- | --- |
| `trading/backtest.py` | 백테스트 조립 + 메인 루프 | BT |
| `trading/live.py` | 라이브 1사이클 (cron 단발) | LV |
| `system/` | 전략 파이프라인 조립 + 리밸런스 일정 | 공유 |
| `portcon/` | 가중치 → 정수 수량 | 공유 |
| `execution/` | 주문 목록 → 브로커 제출 | 공유 |
| `alpha_model/` `risk_model/` | 신호 → 가중치 | 공유 |
| `signals/` | 롤링 지표 + 워밍업 | 공유 + LV |
| `asset/` | 자산·유니버스 | 공유 |
| `messaging/` | 이벤트 어휘 9종(주문 6 + 생명주기 3) + 단일 소비자 `Mailbox` — **리프**, 엔진 내부 무의존. **아직 생산자·소비자 0** | 공유 |
| `broker/broker.py` | `Broker` ABC — 추상 9개 | 공유 |
| `broker/portfolio/` | 현금·포지션·손익 회계 | 공유 |
| `broker/fee_model/` | 비용 모델 5종 (`KoreaStock` 포함) | 공유 |
| `broker/simulated_broker.py` | 체결 시뮬레이션 | BT |
| `broker/live_broker.py` | 실주문·비동기 체결 수집·시가평가 | LV |
| **`broker/live/`** | **벤더 중립** 라이브 인프라 — Protocol·워커·가드·원장·대조·예외 | LV |
| **`broker/kis/`** | **KIS 고유** — 응답 필드 파싱 1모듈 | LV |
| `data/` | 가격 조회 파사드 + 소스 3종 + 라이브 핸들러 | 분리 |
| `exchange/` | 개장·거래일 판정 | 분리 |
| `simulation/` | 시간축 이벤트 생성 | BT |
| `statistics/` | 티어시트 / JSON 성과 | BT |
| `utils/` `settings.py` `env_file.py` | 콘솔·전역 설정·`.env` 적재 | 공유 |

**벤더 경계**([ADR-0015](adr/0015-venue-neutral-live-package.md)). `broker/live/`는 어떤 증권사도 언급하지 않는다. `broker/kis/`에는 응답 파서 하나만 있다. 엔진 코어는 `broker/kis/`를 import하지 않으며, SDK는 패키지 밖 `scripts/kis_gateway.py`에서만 import된다. 이 세 가지 전부 테스트가 AST로 고정한다(§5).

패키지 밖 조립부는 `scripts/`(게이트웨이·휴장일 조회·승격 판정·스모크)와 `examples/`다.

---

## 4. 확장점

새로 붙이려면 구현하는 것들. 목록 자체를 `tests/unit/test_abstract_base_classes.py`가 고정한다 — ABC를 늘리거나 추상 메서드를 빼면 그 파일이 같은 커밋에서 바뀌어야 한다.

| 인터페이스 | 무엇을 구현하는가 | 동봉 구현체 |
| --- | --- | --- |
| `AlphaModel` | `__call__(dt) -> dict{str: float}` | `FixedSignals`, `SingleSignal` |
| `RiskModel` | `__call__(dt, weights) -> dict` | 없음 |
| `PortfolioOptimiser` | `__call__(dt, initial_weights)` | `FixedWeight`, `EqualWeight` |
| `OrderSizer` | `__call__(dt, weights) -> dict{str: dict}` | `DollarWeightedCashBuffered`, `LongShortLeveraged` |
| `Universe` | `get_assets(dt) -> list[str]` | `Static`, `Dynamic` |
| `Signal` | `__call__(asset, lookback)` | `SMA`, `Momentum`, `Volatility` |
| `FeeModel` | `calc_total_cost(asset, qty, consideration, broker)` | `Zero`, `Percent`, `Fixed`, `KoreaStock` |
| `ExecutionAlgorithm` | `__call__(dt, initial_orders)` | `MarketOrder` |
| `Rebalance` | `_generate_rebalances() -> list[pd.Timestamp]` | `BuyAndHold`, `Daily`, `Weekly`, `EndOfMonth` |
| `SimulationEngine` | `__iter__ -> SimulationEvent` | `DailyBusinessDay` |
| `Exchange` | `is_open_at_datetime(dt)` | `Simulated`(NYSE), `Krx`(KST + 휴장일) |
| `Broker` | **추상 9개** — 조회 6 · `create_portfolio` · `submit_order` · `update` | `SimulatedBroker`, `LiveBroker` |
| `DataSource` | `get_bid` / `get_ask` / `get_assets_historical_closes` | `CSVDailyBar`, `InMemoryDailyBar` |
| `Statistics` | `update` / `get_results` / `plot_results` / `save` | `Tearsheet`, `JSONStatistics` |
| `TradingSession` | `run()` | `Backtest`, `Live` |
| `Asset` | (추상 메서드 없음) | `Cash`, `Equity` |
| **`BrokerClient`** (Protocol) | **6개** — `place_market_order` · `get_order_report` · `get_balance` · `get_price` · `get_daily_closes` · `get_trading_day`, 그리고 속성 **`venue` · `mode`** | 패키지 안에는 **없음** — 게이트웨이가 구현한다 |

**두 번째 증권사의 실제 확장점은 `BrokerClient` 하나다.** 게이트웨이 파일 하나를 쓰면 되고 엔진은 건드리지 않는다([ADR-0015](adr/0015-venue-neutral-live-package.md), [보고서 20260823-01 §5.3](reports/20260823-01-codebase-comprehension-strategy.md)).

**단, `Broker` 9개만으로는 라이브 평면이 돌지 않는다.** `LiveTradingSession`과 `reconcile()`이 의존하는 것 중 ABC가 보장하는 것은 일부이며, 나머지는 문서화되지 않은 암묵 계약이다 — 비공개 메서드 4개를 포함한다. `LiveBroker` 상속으로 우회되고 있어 두 번째 증권사가 막히지는 않는다. [보고서 20260823-01 §5.2 소견 B-3, 권고 R4](reports/20260823-01-codebase-comprehension-strategy.md).

---

## 5. 계약 ↔ 테스트 링크 표

**어느 계약이 어느 테스트로 고정되는가의 색인이다.** 테스트를 어떻게 쓰는가(계층·주입 규약·커버리지 정책)는 [`testing.md`](testing.md)가 정본이며 여기서 되풀이하지 않는다.

| 불변식 / 계약 | 어디에 구현되어 있는가 | 무엇이 고정하는가 | 근거 |
| --- | --- | --- | --- |
| 엔진 시계는 뒤로 가지 않는다 | `broker/live_broker.py:170-186` (`_now()` 클램프) | `tests/unit/broker/test_live_broker.py::test_a_clock_that_steps_backwards_is_clamped` · `::test_fills_confirmed_out_of_order_do_not_raise` | [ADR-0007](adr/0007-engine-clock-timestamps.md) · D1 |
| 회계 타임스탬프의 단조성 — 과거 시각 기표는 raise | `broker/portfolio/portfolio.py:208-214` | 위 두 건 + `tests/unit/broker/portfolio/test_portfolio.py` | [ADR-0007](adr/0007-engine-clock-timestamps.md) |
| 접수와 체결의 분리 — `submit_order`는 기다리지 않는다 | `broker/live_broker.py:415-493` | `test_live_broker.py::test_submit_order_returns_before_the_fill_arrives` · `tests/integration/trading/test_live_session_e2e.py::test_every_order_reaches_the_venue_before_any_fill_is_collected` | [ADR-0006](adr/0006-decouple-submit-from-fill.md) |
| 회계의 단일 작성자 — 워커는 버퍼에만 적재, 기표는 메인 스레드 | `broker/live_broker.py:496-547` (`_poll_once`) · `:549-571` (`_drain_fill_buffer`) · `:645-655` (드레인 배리어) | `tests/unit/broker/live/test_worker.py::test_join_tasks_is_a_drain_barrier` | [ADR-0008](adr/0008-task-queue-fill-pump.md) · D2 |
| 정산 워커는 데몬이 아니다 | `broker/live/worker.py:140-143` (`daemon=False`) | `test_worker.py::test_a_raising_on_terminate_does_not_strand_the_thread` · `tests/unit/test_kis_gateway.py::test_the_sdk_gets_a_timeout_it_does_not_set_itself` — **플래그 자체를 단언하는 테스트는 없다**(§6 비고) | [ADR-0008](adr/0008-task-queue-fill-pump.md) · [보고서 20260822-01 §3](reports/20260822-01-worker-lifecycle-and-shutdown.md) · **D2 불변식 3 불채택** |
| 체결은 누적 총량으로 보고되고 증분으로 기표된다 | `broker/live/client.py:10-14` (계약) · `broker/live_broker.py:521` (증분) · `broker/live/ledger.py:311` (멱등키 `order_no:cumulative_filled`) | `test_live_broker.py::test_incremental_fills_are_booked_once_each` · `::test_partial_fill_books_only_what_filled` · `test_live_session_e2e.py::test_a_restart_does_not_book_the_same_fill_twice` | D4 불변식 5 |
| 원장은 배포 신원을 기억하고 다른 배포를 거부한다 | `broker/live/ledger.py:139-184` (`stamp_identity`) · `:105-110` (`meta` 테이블) | `tests/unit/broker/live/test_ledger_identity.py` 전체 | [ADR-0017](adr/0017-paper-is-a-mode-not-a-broker.md) |
| 주문은 재시도되지 않는다 — 발주 엔드포인트가 멱등이 아니다 | `broker/live_broker.py:474-482` | `test_live_broker.py::test_orders_are_never_retried` · `::test_a_venue_rejection_does_not_stop_the_session` | D13 · D4 불변식 4 |
| 대조의 비대칭 — 과대보유는 멈추고 미추적은 보고만 | `broker/live/reconcile.py:49` (`halt_trading` 산식) · `:120-127` | `tests/unit/broker/live/test_reconcile.py::test_local_overstatement_halts_trading` · `::test_untracked_holdings_are_reported_without_halting` | [ADR-0001](adr/0001-portfolio-source-of-truth.md) · D13 |
| 킬스위치는 파일이고 매번 다시 읽는다 | `broker/live/guards.py:61-72` · `:74-86` | `tests/unit/broker/live/test_guards.py::test_kill_switch_is_read_each_time_not_cached` · `::test_kill_switch_file_halts_trading` | D14 불변식 4 |
| 신호 이력이 0인 자산이 있으면 그날은 거래하지 않는다 | `trading/live.py:172-188` · `signals/warmup.py:104-120` | `tests/unit/trading/test_live_session.py::test_a_starved_signal_stops_the_rebalance` · `::test_signals_are_warmed_on_every_launch` | [ADR-0012](adr/0012-signal-history-from-venue.md) · 원칙 1 |
| 정산 마감은 시간예산과 폐장−버퍼 중 **이른 쪽** | `trading/live.py:75-99` | `test_live_session.py::test_the_deadline_is_the_earlier_of_budget_and_close` | [ADR-0006](adr/0006-decouple-submit-from-fill.md) · D14 |
| 매도 전용 증권거래세 — `quantity` 부호로 판정, ETF는 면제 | `broker/fee_model/korea_fee_model.py:96-100` | `tests/unit/broker/fee_model/test_korea_fee_model.py::test_tax_is_asymmetric_between_sides` · `::test_sign_of_consideration_does_not_decide_the_side` · `::test_a_tax_exempt_asset_pays_commission_but_no_tax` · `tests/unit/portcon/order_sizer/test_trade_cost_sign.py::test_korean_tax_is_reserved_on_sells_only` | [ADR-0005](adr/0005-sell-side-transaction-tax.md) · [ADR-0017](adr/0017-paper-is-a-mode-not-a-broker.md) |
| 첫 봉 이전 조회는 마지막 가격이 아니라 NaN — 룩어헤드 방지 | `data/daily_bar.py:127-133` · `:154-160` | `tests/unit/data/test_daily_bar_memory.py::test_price_before_the_first_bar_is_nan` · `tests/integration/data/test_in_memory_data_source.py::test_a_backtest_starting_before_the_data_fails_loudly` | [보고서 20260818-05](reports/20260818-05-data-source-contract.md) · D8 불변식 2 |
| 일봉은 자정이 아니라 세션 시각으로 정렬된다 | `data/daily_bar.py:78-79` (Open→14:30 UTC, Close→21:00 UTC) | `test_daily_bar_memory.py::test_unadjusted_bars_become_open_and_close_timestamps` | D8 불변식 2 |
| 벤더 SDK는 패키지 안에서 import되지 않는다 | `broker/live/client.py:94-120` (Protocol) · `broker/live/` 전체 | `tests/unit/test_vendor_import_boundary.py::test_the_package_never_imports_a_broker_sdk` · `::test_only_vendor_code_imports_vendor_code` · `::test_the_neutral_live_package_names_no_vendor` | [ADR-0015](adr/0015-venue-neutral-live-package.md) · 스펙 NFR-3 |
| 라이브 가격 실패는 0도 NaN도 아닌 예외 / 마크 부재는 직전 평가 유지 | `data/live_data_handler.py:38-67` (`PriceUnavailable`) · `broker/live_broker.py:772-796` (`_mark_to_market`) | `test_live_broker.py::test_marking_keeps_the_last_valuation_when_a_mark_is_missing` | D7 불변식 1 · D13 불변식 2 |
| 라이브 매도는 보유량으로, 매수는 현금으로 클램프된다 | `broker/live_broker.py:367-413` (`_clamp_quantity`) | `test_live_broker.py::test_short_sales_are_refused` · `::test_sales_are_clamped_to_the_holding` · `::test_buys_are_clamped_to_available_cash` · `::test_fractional_quantities_are_floored` | [보고서 20260823-01 §9-5](reports/20260823-01-codebase-comprehension-strategy.md) |
| `Broker` ABC의 추상은 9개이고 자금이체를 요구하지 않는다 | `broker/broker.py:38-186` | `tests/unit/test_abstract_base_classes.py::test_broker_requires_update` · `::test_broker_does_not_require_a_funding_api` | [ADR-0004](adr/0004-promote-update-to-abc.md) · [ADR-0016](adr/0016-drop-funding-from-broker-abc.md) |
| 모든 ABC가 진짜 ABC다 — `@abstractmethod`가 실제로 강제된다 | `abc.ABC` 상속 15종 | `test_abstract_base_classes.py::test_is_a_real_abc` · `::test_cannot_instantiate_abstract_base_class` | §4 |
| 백테스트 전 거래 이력이 픽스처와 **완전 일치**한다 | `trading/backtest.py:393-460` 루프 전체 | `tests/integration/trading/test_backtest_e2e.py` 5건이 `.dat`를 `assert_frame_equal` 대조 | 원칙 2 (회귀 단계) |
| 매도가 매수보다 먼저 체결된다 (현금 확보) | `broker/simulated_broker.py:680` (`sorted(orders, key=direction)`) | 전용 단위 테스트 **없음** — 위 `.dat` 완전 일치가 간접 고정 | D1 |

마지막 행이 이 표의 쓸모를 보여준다. 계약은 있는데 그것을 **이름 붙여 고정하는 테스트가 없고**, 픽스처가 우연히 지키고 있다. 그런 칸을 눈에 띄게 하는 것이 이 표의 목적이다.

---

## 6. `architecture-principles.md` 적용 검토

[`architecture-principles.md`](architecture-principles.md)는 일반 참조 모델이다. 아래는 그 잣대를 이 저장소에 대어 본 결과이며, **적용 상태의 정본은 이 표다.**

상태는 네 값 중 하나다. `준수` / `부분` / `미준수(부채)` / `불채택`. `불채택`은 결함이 아니라 **전제가 다르거나 범위 밖이라는 판단**이며, 반드시 이유와 근거 문서를 단다.

| 축 | 적용 상태 | 근거 | 비고 |
| --- | --- | --- | --- |
| **원칙 1** 데이터 정직성 | **부분** | 결측 전파: `daily_bar.py:127-133`·`:154-160`, `data_source.py`, `live_data_handler.py:62-66`. 테스트 §5 | 다만 `daily_bar.py:85`의 `ffill`과 `:130`·`:157`의 `get_indexer(method='pad')`가 결측 세션을 직전값으로 채우고 **그 값으로 체결한다** — 금지 목록의 "직전값 캐리포워드(장중 실행 판단용)"에 해당. `test_in_memory_data_source.py::test_a_gap_in_the_bars_is_valued_at_the_last_known_price`의 docstring이 이 정책을 통과하는 유일한 테스트임을 스스로 밝힌다 |
| **원칙 2** 시뮬·실환경 동형성 | **부분** | 1단계(회귀): 강함 — `.dat` 완전 일치 e2e 5건. 2단계(경계 감사): 부분 — `test_krx_exchange.py`가 세션 경계·휴장일을 덮으나 **백테스트 평면에는 휴장일 캘린더 자체가 없다** | **3단계(실거래 재현)가 없다.** 원장에 실체결가가 쌓이고 있으나 재생 대조 절차가 없다. `scripts/promotion_check.py`의 자동 항목은 배포 위생을 보지 손익 일치를 보지 않는다. 아래 "값진 3가지" ② |
| **D1** 경로 의존 루프 | **준수** | 백테스트 전 구간 단일 스레드. 순서 고정(`backtest.py:409-450`), 체결은 `execution_handler.py:85-86`이 같은 스텝에 묶는다. 결정론은 `.dat` 완전 일치가 고정 | 스텝 순서가 참조 모델과 **다르다** — 이 저장소는 `체결 → 신호 → 전략 → 기록`이고 시계 전진은 이터레이터가 한다. 다르되 고정되어 있고 회귀가 지킨다. 프로세스 단위 병렬은 `settings.PRINT_EVENTS`가 모듈 전역+`global`(`settings.py:14-19`)이라 걸림돌이 있다 |
| **D2** 단일 소비자 파이프라인 | **부분** | 단일 FIFO 워커(`broker/live/worker.py`), 락은 핸드오프 버퍼 하나(`live_broker.py:543`) | **상태를 독점하는 스레드가 소비자가 아니라 메인 스레드다.** 워커는 조회하고 버퍼에 append만 하며, `Portfolio` 기표는 드레인 배리어 뒤 메인 스레드가 한다([ADR-0008](adr/0008-task-queue-fill-pump.md)). 액터 모델의 목적은 달성되고 배치가 뒤집혀 있다 |
| **D2 불변식 3** (전 스레드 데몬) | **불채택** | `broker/live/worker.py:141` `daemon=False`. [ADR-0008](adr/0008-task-queue-fill-pump.md)이 "daemon=False, 상주 금지"를 명시 | **전제가 다르다 — cron 단발 대 상주 데몬.** 근거 3층([보고서 20260822-01 §3](reports/20260822-01-worker-lifecycle-and-shutdown.md)): ① [ADR-0009](adr/0009-cron-oneshot-live-session.md)로 워커 수명 < 프로세스 수명이라 "워커가 종료를 막는다"가 성립하지 않는다 ② 체결 유실 0의 종료 시퀀스가 요구사항이다 ③ join이 곧 회계 단일 작성자 배리어다. 전제가 바뀌면(상주 전환) 재검토 대상. **부채: 이 플래그를 직접 단언하는 테스트가 없다** — `daemon=True`로 뒤집어도 스위트가 통과한다 |
| **D2-a** 백프레셔 | **불채택 — 범위 밖** | 큐는 무제한이나 생산자가 메인 스레드 하나이고 게시량이 미결 주문 수로 유계다(`live_broker.py:634-640`) | push 기반 수신(WebSocket)이 없다. 실시간 시세를 도입하면 이 축이 되살아난다 |
| **D3** 실행 모드 전환 (동기/비동기 dispatcher) | **불채택** | 백테스트에는 큐가 아예 없다 — `SimulatedBroker.update`가 호출 스레드에서 즉시 체결(`:672-682`) | dispatcher 주입 대신 **브로커 구현을 갈아끼우는** 방식을 택했다([ADR-0006](adr/0006-decouple-submit-from-fill.md)). 결정론은 얻지만 **D3 불변식 1(두 모드가 동일 핸들러 코드)은 미충족** — 체결 경로가 두 클래스로 갈린다. 원칙 2의 잔여 위험이며 [보고서 20260823-01](reports/20260823-01-codebase-comprehension-strategy.md) R5와 같은 뿌리 |
| **D4** 주문 상태 기계 | **부분** | 원장 상태 3종 + 진행 상태(`broker/live/ledger.py:25-29`). 불변식 5(부분 체결 누적)는 강함 — §5 | 부모-자식 관계·조건부 주문 그룹은 **범위 밖**(시장가 단일 주문뿐, `execution/execution_algo/market_order.py`). 불변식 1(열거형 필터)은 필터 API 자체가 없어 해당 없음. 불변식 4는 아래 D13 참조 |
| **D5** 체결 가능성 — 캘린더가 아니라 데이터 | **부분** | **라이브는 준수.** 캘린더는 깨어나는 시점·발주 게이트로만 쓰인다(`live.py:160`·`:165`, `live_broker.py:440`) — 체결 여부는 venue의 `OrderReport`가 정한다. **[ADR-0014](adr/0014-holiday-calendar-from-real-account.md)는 D5와 충돌하지 않는다**: D5 본문이 "전략이 선언한 시장/스케줄은 깨어나는 시점을 정하는 편의 장치로만" 쓰는 것을 명시적으로 허용한다. `holiday_file_covers`(`krx_exchange.py:35-68`)가 다 떨어진 캘린더를 걸러 이 용법을 안전하게 만든다 | **백테스트는 부분.** `simulated_broker.py:672`가 캘린더로 체결을 게이트한다. 실질적으로는 무해하다 — 이벤트가 14:30/21:00 두 개뿐이라 게이트가 항상 참이고, 실제 판정은 가격 존재 여부가 한다. 다만 R1·R3(세션 공백은 체결 없음)은 `pad`가 깨뜨린다 — 원칙 1 행과 같은 결함 |
| **D6** 체결가와 호가의 분리 | **불채택 — 범위 밖** | 일봉 해상도이고 Bid = Ask다(`daily_bar.py:145-146`). 라이브도 Bid = Ask이며 이는 명시적 판단이다 — 시장가는 어차피 스프레드를 넘는다 | 옵션 등 비유동 상품은 범위 밖(`backtest.py:210` "Only equities are supported"). **폴백 금지만은 지켜진다** — `get_mark`이 가격 없으면 raise하고 폴백하지 않는다(`live_data_handler.py:62`) |
| **D7** 평가 폴백 사다리와 "나쁜 0" | **부분** | 라이브는 사다리 ③을 정확히 구현한다 — 마크 부재 시 직전 평가 유지(`live_broker.py:772-796`), 사이징 경로는 0/NaN 대신 raise(`live_data_handler.py:62-66`). §5에 테스트 | 백테스트는 실패가 `np.nan`으로 수렴하고 광범위 `except Exception`이 원인을 지운다(`backtest_data_handler.py:26`·`:40`·`:62`·`:80`). **"나쁜 0"은 없다** — 0이 아니라 NaN이고, NaN은 사이저 가드가 잡는다 |
| **D8** 공급자 추상화와 표현 계층 분리 | **부분** | `DataSource` ABC(`data/data_source.py`)에 계약이 역추출되어 있다. 불변식 2(세션 정렬·룩어헤드 방지)는 **강함** — §5 두 행. 불변식 3(조정 상태 노출)은 `adjust_prices` / `adjusted=`로 부분 충족 | **미해소: 라이브 데이터 계층에 ABC가 없다.** `LiveDataHandler`는 어떤 ABC도 구현하지 않고 `BacktestDataHandler`와 상속 관계도 없다 — 덕타이핑이다([보고서 20260823-01](reports/20260823-01-codebase-comprehension-strategy.md) §9-1, 권고 R7) |
| **D9** 계층 캐시와 버전 무효화 | **불채택 — 범위 밖** | 원격 객체 저장소도 버전 키도 없다. 캐시는 둘뿐 — 프로세스 내 `lru_cache`(`daily_bar.py:108`·`:135`)와 휴장일 JSON([ADR-0014](adr/0014-holiday-calendar-from-real-account.md)) | D9의 정신은 **다른 형태로** 지켜진다: 무효화 대신 **범위 검사**(`holiday_file_covers`)가 낡은 캐시가 조용히 틀리는 것을 막는다. 별건으로 `lru_cache`는 히트율이 낮게 실측되어 유지 비용만 남았다([보고서 20260818-06](reports/20260818-06-safety-net-and-profiling.md)) — 정리 대상 |
| **D10** 설정 우선순위 (환경이 코드를 이기는가) | **불채택** | 환경이 코드를 덮어쓰지 않는다. 공급자 선택은 조립부 인자로 준다(`data_handler=`·`optimiser=`·`execution_algo=`). 환경변수는 `VMTRADER_CSV_DATA_DIR` 정도(`backtest.py:196`·`:208`) | D10 자체가 조건부 결정이고 불변식 1이 그것을 "놀라운 동작"이라 부른다. 이 저장소는 반대 방향을 명시적으로 택했다 — `env_file.py:158-163`이 **이미 설정된 값을 덮어쓰지 않는다.** 규모에 맞는 선택 |
| **D11** 기업행위 멱등성 | **불채택 — 범위 밖** | 이 저장소는 기업행위를 **적용하지 않는다.** 벤더가 조정한 `Adj Close`를 읽어 시가를 비율로 스케일할 뿐이고(`daily_bar.py`의 `adjust_prices` 분기), 배당을 현금 사건으로 지급하는 경로가 없다 | 그래서 불변식 4(가격 조정과 현금 지급을 동시에 하지 않는다)는 **자동으로 지켜진다** — 한쪽만 한다. 변환도 `__init__`에서 1회 수행되어 프레임에 캐시되므로 재적용 위험이 없다. 배당을 현금 사건으로 도입하면 이 축 전체가 되살아난다 |
| **D12** 외부 현금흐름의 분리 | **부분** | 백테스트: `SimulatedBroker`의 자금이체 4종이 `PortfolioEvent`로 감사 기록을 남긴다(`portfolio.py:147`·`:192`). 라이브: **의도적으로 없다** — [ADR-0016](adr/0016-drop-funding-from-broker-abc.md)이 ABC에서 제거했고 잔고는 `seed_from_venue()`가 읽는다 | **미해소.** 성과 계산이 외부 현금흐름을 분리하지 않는다. 라이브 계좌에 입금하면 `record_equity()`의 곡선이 튀고 `promotion_check.py`의 판정 입력이 오염되는데 그것을 검출하는 기준이 자동 항목에 없다. 사유 문자열도 없다(불변식 3 미충족). 아래 "값진 3가지" ③ |
| **D13** 비대칭 복원력 (읽기 관대·쓰기 엄격) | **부분** | 읽기 관대: `reconcile()`이 미추적 보유를 보고만 하고 멈추지 않으며 과대보유만 halt한다(`reconcile.py:49`·`:120-127`). 비대칭이 의도임을 `test_reconcile.py`가 고정. 불변식 2(잔고 실패에 0 금지) 준수 | **불변식 3이 부분.** venue의 주문 거절이 예외로 전파되지 않고 원장 `REJECTED` + 로그로 끝난다(`live_broker.py:474-482`). 은폐는 아니다 — 원장에 남고 로그에 뜬다 — 그러나 `submit_order`가 아무것도 반환하지 않아 **호출자는 실패를 알 방법이 없다.** 킬스위치만 예외로 올린다. 미지값 `UNKNOWN` 보존은 파서에 없다 |
| **D14** 스케줄링과 생명주기 | **부분** | 두 평면 모두 순서가 고정되어 있다(§2). 불변식 2: `settle`이 `sleep=` 주입을 받는다(`live_broker.py:580`). 불변식 4: 킬스위치가 단일 게이트다 — 사이클 진입(`live.py:154`)·주문마다(`guards.py:88`)·정산 라운드마다(`live_broker.py:630`) | **불변식 1(훅 순서가 두 모드에서 동일)은 미충족.** 백테스트는 개장/폐장 2이벤트, 라이브는 cron 2기동이며 대응 관계가 §2에만 있고 코드가 강제하지 않는다. `SIGINT`/`SIGTERM` 핸들러도 없다([보고서 20260822-01 §7](reports/20260822-01-worker-lifecycle-and-shutdown.md)). 불변식 5(24시간 시장)는 범위 밖 |
| **D15** 관측성과 성능 예산 | **부분** | 불변식 3(경량 직렬화) 준수 — 원장은 행 단위 INSERT. 불변식 5(하트비트) **준수** — `settle()`이 남은 예산의 1/4마다 드레인을 짚고 로그를 남긴다(`live_broker.py:645-664`), `test_live_broker.py::test_a_slow_drain_is_reported_but_still_waited_out`·`::test_each_settle_round_leaves_a_drain_sample`이 고정 | **불변식 1이 역방향이다** — `settings.PRINT_EVENTS`의 기본값이 `True`(`settings.py:14`)라 스텝별 상태 출력이 **기본 활성**이고 끄는 쪽이 opt-out이다. 참조 모델이 지목한 안티패턴("스텝마다 상태 로그")이 기본값. **불변식 4(산출물에 버전 정보) 미준수** — 패키지에 `__version__`가 없고 원장·자본곡선 어디에도 코드 버전이 없다. 불변식 6(후처리 실패 분리)도 미충족 |
| **Part VI** 결정 간 의존 관계 | **부분** | 변경 영향표의 대부분은 §5의 테스트가 실제로 잡는다 | D1↔D2 결합(스텝 순서 변경 시 결정론)은 `.dat` 완전 일치가 잡으나, [보고서 20260818-06](reports/20260818-06-safety-net-and-profiling.md)이 **e2e가 전면적 룩어헤드를 통과시킨다**고 실측했다. 회귀 대조의 한계는 [`testing.md`](testing.md) §6이 정본 |
| **Part VII** 안티패턴 카탈로그 | — | 13개 중 이 저장소에서 확인된 것: "결측 시 직전값 반환"(원칙 1 행), "스텝마다 상태 로그"(D15 행), "백테스트 전용 사건 경로"(D3 행 — 경로가 아니라 클래스가 갈린다) | "캘린더로 체결 가능 판정"은 **라이브에는 해당하지 않는다** — D5 행 참조. 나머지는 범위 밖이거나 확인되지 않았다 |
| **Part VIII** 도입 체크리스트 | — | 명확히 **예**: 스텝 순서 문서화·회귀(§2·§5), 공유 상태 단일 스레드(D2), 룩어헤드 방지(§5), 읽기/쓰기 복원력 구분(D13) | 명확히 **아니오**: 백그라운드 스레드 전 데몬(**의도적 불채택**), 진단 기본 비활성(D15), 산출물 버전 정보(D15), 실거래 재현 계획(원칙 2), 상태 전이표 테스트(D4) |

### 지금 가장 값진 3가지

이 매핑이 아니었으면 드러나지 않았을, **실제로 조치할 가치가 있는 것** 셋이다. 보고서 20260823-01이 이미 추적 중인 R4·R6·R7·R8은 여기 넣지 않는다 — 그쪽 정본을 따르면 된다.

**① 산출물에 코드 버전이 없다 (D15 불변식 4).** [ADR-0017](adr/0017-paper-is-a-mode-not-a-broker.md)은 원장이 **누가** 만들었는지(venue·mode·account)를 기억하게 했다. 그런데 **무엇이** 만들었는지 — 어느 코드가 그 주문을 냈는지 — 는 여전히 비어 있다. [ADR-0013](adr/0013-real-money-promotion-criteria.md)의 승격 판정이 읽는 원장은 되돌릴 수 없는 결정의 유일한 증거인데, 그 증거가 어느 버전의 사이저·비용모델·클램프 규칙에서 나왔는지 알 수 없다. 승격 뒤 손익이 어긋나면 어느 커밋을 되짚어야 하는지 답할 방법이 없다. 원장 `meta`에 버전 한 행을 더하는 것으로 끝난다 — 셋 중 가장 싸고 가장 값지다.

**② 정확도 검증이 회귀 대조에서 멈춰 있다 (원칙 2).** 참조 모델은 회귀 검증을 "어제의 자신과 비교하는 것"이라 부르며 3단계(실거래 재현) 없이는 정확도를 주장하지 않는 편이 정직하다고 한다. 이 저장소는 1단계가 매우 강하고(`.dat` 완전 일치) 3단계가 없다. 그런데 **재료는 이미 다 있다** — 모의투자 원장에 실체결가·수수료·시각이 쌓이고 있고, [ADR-0017](adr/0017-paper-is-a-mode-not-a-broker.md)이 그 원장의 신원까지 보증한다. 빠진 것은 "그 구간을 백테스트로 재생해 실현 손익이 허용오차 안에 드는가"를 묻는 절차 하나다. 이것이 [ADR-0013](adr/0013-real-money-promotion-criteria.md)의 자동 항목에 없다는 사실이, 지금 승격 기준이 **배포 위생은 보지만 정확도는 보지 않는다**는 뜻이다.

**③ 외부 현금흐름이 성과에서 분리되지 않는다 (D12).** 라이브 계좌에 입금하면 `record_equity()`가 그린 곡선이 튀고, 그 곡선을 읽는 승격 판정과 향후 성과 비교가 조용히 오염된다. 백테스트에는 자금이체가 사건으로 남지만(`broker/portfolio/portfolio.py:147`·`:192`), 라이브에는 그 개념 자체가 없다 — [ADR-0016](adr/0016-drop-funding-from-broker-abc.md)이 계약에서 지운 것은 옳았으나, 지운 자리에 "잔고가 거래 없이 변했다"를 검출하는 것을 두지 않았다. 대조가 포지션만 보고 현금은 보지 않기 때문에(`reconcile.py:77-100`) 이 변화는 어디에서도 잡히지 않는다. 운용을 시작하면 반드시 밟는다.

---

## 7. 이 문서의 갱신 규칙

`reports/`는 스냅샷이라 본문을 갱신하지 않고 상태 열로 추적한다. **이 문서는 반대다 — 틀린 절은 지우고 고쳐 쓴다.** 이력은 git이 갖는다. 낡은 서술을 남겨 두면 진입점 문서가 진입점을 잘못 알려주는 셈이 된다.

| 무엇이 바뀌면 | 어느 절을 고치는가 |
| --- | --- |
| `backtest.py` `run()` 또는 `live.py` `run_rebalance()`/`run_end_of_day()`의 단계 | §2 (그리고 순서가 바뀌었다면 §1 그림) |
| 패키지 추가·삭제·이동 | §3 (벤더 경계가 움직였다면 §1 그림도) |
| ABC 또는 `BrokerClient` Protocol의 메서드 | §4 — `tests/unit/test_abstract_base_classes.py`도 같은 커밋에서 바뀐다 |
| 불변식을 고정하는 테스트의 추가·삭제·개명 | §5. **파일:줄을 인용했으면 그 줄이 움직였을 때도 고친다** |
| 새 ADR 채택 또는 기존 ADR 폐기 | §2·§5의 근거 링크, 그리고 §6에서 해당 축의 상태 |
| 부채 해소 또는 신규 부채 확인 | §6의 상태 값. `미준수(부채)` → `준수`로 바꿀 때는 무엇이 그것을 고정하는지 §5에 행을 함께 넣는다 |
| `architecture-principles.md`의 축 추가·수정 | §6에 행을 추가한다. **`불채택`으로 두려면 이유와 근거 문서가 반드시 붙는다** |

두 가지는 이 문서에 들어오지 않는다. **실측값**(커버리지·케이스 수·실행 시간·모듈 줄 수)은 [`reports/`](reports/)와 CI의 것이고, **테스트 작성 규약과 커버리지 정책**은 [`testing.md`](testing.md)의 것이다. §5 표는 색인이지 정책이 아니다.
