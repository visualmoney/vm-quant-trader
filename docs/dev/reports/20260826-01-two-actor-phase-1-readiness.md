# 2액터 모델 Phase 1 진입 준비 검토 보고서

| 항목 | 내용 |
| --- | --- |
| 문서 ID | `20260826-01-two-actor-phase-1-readiness` |
| 작성일 | 2026-08-26 |
| 관점 | Software Architect (독립 검토) |
| 상태 | **검토 완료 · 코드 변경 없음** |
| 검토 대상 | [`threading-and-event-architecture.md`](../threading-and-event-architecture.md) v3(결정 13개), `vmtrader/messaging/`, `alpha_model/base_strategy_executor.py`, `system/qts.py`, `portcon/pcm.py`, `broker/live_broker.py`, `broker/live/{worker,reconcile}.py`, `trading/{backtest,live}.py` |
| 기준 | `16b9d0f` · 796 passed / 2 skipped |
| 관련 결정 | 이 문서의 결정 2·3·4·6·8·8-a·9·10·11·12, [ADR-0006](../adr/0006-decouple-submit-from-fill.md)·[0008](../adr/0008-task-queue-fill-pump.md)·[0009](../adr/0009-cron-oneshot-live-session.md) |
| 관련 이슈 | [#58](https://github.com/visualmoney/vm-quant-trader/pull/58), [#60](https://github.com/visualmoney/vm-quant-trader/issues/60) |

> **이 보고서는 스냅샷이다.** 아래 소견 중 어느 것이 조치되었는지는 본문이 아니라
> `docs/README.md`의 보고서 표에서 추적한다.

---

## 1. 요약

**Phase 0은 Actor 2를 만들었다. Actor 1은 만들지 않았다.** 브로커 쪽에는 메일박스도,
`post_command`도, `_dispatch`도, 소비 루프도 없다. 그런데 설계 문서는 "액터 구조가 동기
모드에서 완성됐고, 스레드를 켜는 일만 Phase 1에 남았다"고 닫았다 — 남은 절반이 **돈을
소유한 절반**이다.

| # | 물음 | 답 |
| --- | --- | --- |
| Q1 | §3 위반이 더 있는가 | **있다.** 세 번째가 철회된 결정 5와 **같은 경로**로 되살아났다 — 이번에는 이름이 아니라 **주입된 콜러블**을 타고(B1) |
| Q2 | Phase 1이 설계대로 도는가 | **돌지 않는다.** 플래그를 뒤집으면 cron 평면에서 리밸런스가 **조용히 일어나지 않는다**(B3) |
| Q3 | 두 평면이 같은 메인 스레드 구조를 쓰는가 | **아니다.** cron 단발은 배리어의 연쇄이고 상주는 루프다. 결정 12의 `while True` 스케치는 상주에만 참이다(B4) |
| Q4 | 결정 8의 "버려도 다음 폴이 복구한다"가 맞는가 | **6종 중 1종에만 맞다.** 그리고 결정 12의 배선이 결정 8과 8-a를 **서로 모순되게** 만든다(M1) |
| Q5 | `Thread` 상속의 잔여 위험이 있는가 | **3건 더 있고 그중 1건은 현재 살아 있는 버그다**(M5) |

소견 15건 — **진입 차단 4건**, 주요 6건, 경미 5건.

---

## 2. 검증 방법

독립 검토 에이전트의 소견을 그대로 옮기지 않았다. **차단·주요 소견의 사실 주장은 전부 이
저장소에서 직접 재현하거나 코드로 확인했다.** 아래 표가 그 결과다.

| 주장 | 확인 방법 | 결과 |
| --- | --- | --- |
| 실행기의 outbox가 Actor 1의 쓰기 경로에 묶여 있다 | `grep post_command` | `live.py:99`, `backtest.py:418` — 확인 |
| 스레드 모드에서 `settle()`이 리밸런스보다 먼저 돈다 | `live.py:230-235` 순서 | 확인 |
| `on_start`/`on_stop`을 부르는 곳이 없다 | `vmtrader/`·`tests/` 전수 grep | **0건** — 확인 |
| 기동 전 `stop()`이 raise한다 | 실행 | `RuntimeError: cannot join thread before it is started` |
| 종료 드레인 중 `post_event`가 가드 1을 타지 않는다 | 실행 | `MailboxClosed` (문서는 `RuntimeError`를 약속) |
| 동기 모드 `run()` 직접 호출에 가드가 없다 | 코드 | 확인 — `take()`에서 영구 블록 |
| 게이트웨이가 락을 쥔 채 sleep한다 | `kis_gateway.py:488-495` | 확인 — `_CALL_LOCK` 안에서 sleep 2회 |
| 문서의 `file:line` 인용이 낡았다 | 6건 대조 | 전부 15~50줄 어긋남 |
| 토픽 10종 중 생산자가 없는 것이 8종 | 전수 grep | 확인 |
| 라이브 조립이 `data_handler` 1개를 공유한다 | `test_live_session_e2e.py:124-151` | 확인 — 4곳이 같은 인스턴스 |

M1의 유실 시나리오와 B4의 구조 논증은 **관측이 아니라 분석**이다. 그 점을 해당 절에 표시했다.

---

## 3. 진입 차단 (4건)

### B1 — 세 번째 §3 위반: 실행기의 outbox가 곧 Actor 1의 쓰기 경로다

**철회된 결정 5가 의존성 주입을 타고 그대로 돌아왔다.**

결정 5는 "`qts(dt)`의 호출 사슬을 끝까지 따라가면 Actor 1의 상태를 읽고 **쓴다**"는 이유로
철회됐다. 결정 9가 `qts`를 쪼개 Actor 2가 `decide_weights`만 돌게 했다. 그런데 두 조립부가
Actor 2에게 **나머지 절반의 바인드 메서드를 그대로 넘긴다.**

```python
live.py:99       post_command=self.qts.size_and_submit
backtest.py:418  post_command=lambda command: self.qts.size_and_submit(command, stats=stats)
```

그리고 `base_strategy_executor.py`의 `_dispatch`가 그것을 **실행기 스레드 위에서** 호출한다.

```
_dispatch → size_and_submit → build_orders      → get_portfolio_as_dict   (Actor 1 읽기)
                            → execution_handler → submit_order            (open_orders·원장 쓰기)
                                                → broker.update(dt)       → transact_asset (회계 기표)
                                                                          → 메인 스레드 SQLite 연결
```

철회된 결정 5의 표와 **한 줄씩 그대로 같다.** 다른 점은 위반이 이름이 아니라 주입된 콜러블을
타고 간다는 것뿐이고, 그래서 AST 경계 테스트가 보지 못했다.

**왜 차단인가.** 결정 3(`daemon=True`)의 안전성은 결정 6("executor는 `Portfolio`를 만지지
않는다")에 의존한다고 문서가 명시한다 — "결정 6이 깨지면 이 결정도 함께 재검토한다".
현재 배선은 **코드 수준에서 결정 6을 깨뜨린다.** 결정 3·6·9가 모두 조립부가 지키지 않는
전제 위에 서 있다.

**부수 소견 — 경계 테스트가 거짓 안심을 준다.** `test_base_strategy_executor.py`의 import
경계 테스트는 docstring에 "this proves the code has no way to reach it at all"이라고 적었지만,
증명하는 것은 **import**가 닿지 않는다는 것뿐이다. 주입된 콜러블 두 개가 닿는다.

**조치.** 없는 객체에 이름을 준다 — Actor 2의 outbox는 스레드 모드에서 `broker_mailbox.post`여야
하고 `qts.size_and_submit`이어서는 안 된다. `LiveBroker`(또는 얇은 `BrokerActor`)가 실행기와
대칭으로 `post_command`/`_dispatch`를 갖는다. 그리고 인스턴스 수준 단언을 추가한다 —
`synchronous is False`일 때 `_post_command`·`_decide`가 `vmtrader.broker`·`vmtrader.execution`
소속 객체의 바인드 메서드여서는 안 된다.

### B2 — 결정 4의 모드는 두 사실이 아니라 **세 사실**이고, 위험한 칸에 가드가 없다

결정 4는 (`synchronous`, `start()`) 2×2 표를 두고 가드 2개로 나쁜 칸 둘을 막았다. 그런데
실효 모드는 이제 **셋**이다 — 플래그, `start()`, 그리고 **`post_command`가 어디를 가리키는가**.
세 번째에는 가드도 테스트도 없다.

| `synchronous` | `start()` | `post_command` | 결과 |
| --- | --- | --- | --- |
| True | 안 함 | 직접 호출 | ✅ Phase 0 |
| False | 함 | 브로커 메일박스 | ✅ 의도한 Phase 1 |
| False | 함 | **직접 호출** | 🔴 B1 — 데몬 스레드에서 회계 기표 |
| True | 안 함 | 브로커 메일박스 | ⚠️ 명령이 쌓이고 소비자 없음 — 리밸런스 통째 유실 |

문서 스스로 "가드는 구현 편의가 아니라 이 결정의 성립 조건이다"라고 적었는데, **돈을 잃을 수
있는 칸이 가드 없는 칸이다.**

**조치.** 짝을 규율이 아니라 구조로 만든다. `post_command`를 자유 콜러블로 받지 말고 브로커
액터를 받아 **같은 `synchronous` 플래그에서 outbox를 유도**하거나, 불일치 조합의 생성을
거부한다(D3 불변식 2 — 한 사실은 한 곳에서).

### B3 — Phase 1의 cron 단발이 동작하지 않는다: 리밸런스가 생기기 전에 `settle()`이 돈다

```python
live.py:230   self._executor().post_event(RebalanceDue(dt=now))
live.py:231   outcome['traded'] = True
live.py:235   outcome['fills_booked'] = self.broker.settle(deadline)
```

`synchronous=False`면 `post_event`는 이벤트를 큐에 넣고 **즉시 반환한다.** `settle()`은
`while self.open_orders:`로 시작하는데 `open_orders`는 **비어 있다** — 아직 아무것도 사이징·제출되지
않았다. 루프 본문이 한 번도 돌지 않고 `settle`이 `0`을 반환하고, `run_rebalance`가 반환하고,
프로세스가 나가면서 `daemon=True`인 실행기가 `decide_weights` 도중에 잘린다.

**리밸런스가 조용히 일어나지 않고, outcome은 `traded: True, fills_booked: 0`으로 성공처럼
보고한다.** 다음 기동의 `reconcile()`도 복구하지 못한다 — reconcile은 *주문*을 정산하는데
주문이 만들어진 적이 없다.

**더 깊은 지점 — 결정 12의 논증이 Actor 2에도 그대로 적용되는데 문서가 놓쳤다.**
결정 12는 "cron 단발에서 '사이클이 끝났나'가 액터 경계를 넘는 질문이 된다"는 이유로 Actor 1에
전용 스레드를 주지 않았다. **Actor 2에 스레드를 주면 같은 질문이 반대 방향으로 생긴다** —
메인 스레드는 정산하기 전에 Actor 2가 결정을 끝냈는지 알아야 한다. 결정 12는 문제의 절반을
풀고 다 풀었다고 선언했다.

**조치.** 질의가 아니라 **이미 있는 배리어**로 답한다. cron에서
`post_event(RebalanceDue)` → `executor.stop(timeout)`(close + join = 드레인 배리어, 마지막
`TargetWeights`가 게시됐음이 보장됨) → 메인 스레드가 Actor 1 메일박스를 비움 → **그다음**
`settle(deadline)`. join은 답장이 아니므로 §5 금지 규칙 1에 걸리지 않는다.

### B4 — 상주와 cron 단발은 **서로 다른 메인 스레드 구조**를 요구한다 (분석)

결정 12의 `[Phase 1] 메인: while True: dispatch(mailbox.take())` 스케치는 **상주 평면에만
참이다.**

**cron 단발**은 종료 상태가 정의된 **배리어의 연쇄**다 — reconcile → 워밍 → 리밸런스 게시 →
Actor 2 배리어 → Actor 1 드레인 → 마감까지 정산 → 종료. `while True`가 없다. `settle()`의
동기 `int` 반환값은 이 모양에서만 살아남는다.

**상주**는 `while not stopping: dispatch(mailbox.take(timeout))`이고, 그 모양에서는:

- **`settle()`이 지금 형태로 존재할 수 없다.** `settle()` 안에 있는 동안 메인 스레드는 최대
  `time_budget`(기본 60분) 동안 **메일박스를 소비하지 않는다.** `TargetWeights`와 푸시된 WS
  이벤트가 그 뒤에 쌓이고, **200 상한 유실이 하필 정산 중에 도달 가능해진다.** 결정 11의 순서
  증명("Actor 1 큐의 순서: PollDue → … → TargetWeights, FIFO가 보장")은 **항상 take하는
  루프**를 전제하는데, 그렇지 않다.
- **`settle()`은 책임을 여섯 개 지고 있다** — 시간 예산, 킬스위치 게이트, 라운드 구성, 드레인
  배리어와 하트비트, 워커 수명, STALE 종결, 그리고 반환값. §7은 이것을 한 줄("`PollDue` 배선")로
  적고 있다.
- **§7의 두 항목이 서로 모순된다.** 결정 12는 메인 스레드 선택의 근거로 `settle()`의 동기
  반환값을 들고, §7의 `PollDue` 항목은 그 반환값을 없앤다. 상주 평면에서 둘 다 참일 수 없다.
- 스케치의 `take()`에 timeout이 없어, 그 루프는 **킬스위치를 영영 확인하지 않는다.** 지금은
  정산 라운드마다 확인한다(D14 불변식 4 회귀). `Mailbox.take`는 이미 timeout을 받는다.

**조치.** 두 모양을 §4·§7에 **두 개의 메인 스레드 구조**로 명시하되 `_dispatch`는 공유한다 —
결정 4가 실행기에 대해 한 것과 같은 방식이다. 그리고 **Phase 1에서 `settle()`을 `PollDue`로
전환하지 않는다.** Phase 1a = 스레드 켜기 + cron 모양 유지, Phase 1b = 상주 전환(별도 ADR).

---

## 4. 주요 (6건)

### M1 — 결정 8의 자가복구 논거는 Actor 1 메일박스에 들어올 6종 중 **1종**만 덮는다

| 메시지 | 생산자 | 자가복구 | 근거 |
| --- | --- | --- | --- |
| `PollDue` | 스케줄러 | **예** | 다음 폴이 미결 전체를 다시 조회 |
| WS `OrderFilled` | 웹소켓 | **조건부 예** | 폴링이 함께 도는 동안만 |
| **fill-pump 조회 결과** | 워커 | **아니오** | 아래 |
| **`TargetWeights`** | Actor 2 | **아니오** | 아무도 다시 보내지 않음(C-1이 이미 지적) |
| **`EndOfDay`** | 스케줄러 | **아니오** | 하루 한 번 — 자산 곡선의 그날 점이 영영 안 써짐 |
| **WS `OrderAccepted`** | 웹소켓 | **아니오** | `open_orders`에 없으면 아무것도 그 주문을 폴링하지 않음 |

**fill 결과의 경우 — 결정 8의 논거가 뒤집힌다 (분석).** `_poll_once`는 **생산자 쪽에서**
기표 워터마크를 전진시킨다.

```python
booked = ledger.record_fill(...)                    # 원장 기록 (워커 스레드)
if booked:
    self._fill_buffer.append(fill)                  # 오늘은 무손실 핸드오프
state['booked_quantity'] = report.filled_quantity   # 워터마크 전진
state['booked_fees'] = report.fees
```

결정 12는 이 append를 **Actor 1의 메일박스 게시로 바꾸라**고 한다. 그 순간 유계·유실 게시가
되면, 버려진 fill에 대해 원장에는 행이 있고 `booked_quantity`는 이미 전진했으므로 다음 폴이
`increment = filled - booked = 0`을 계산한다 — **그 체결은 다시 방출되지도, `Portfolio`에
닿지도 않는다.** 세션 내내 현금과 포지션이 틀리고 그 위에서 사이징이 돌며 `record_equity()`가
틀린 점을 쓴다. 다음 기동의 `seed_from_venue`가 덮어써서 프로세스를 건너서는 낫지만 **세션
안에서는 낫지 않고**, `reconcile`은 이 잔차를 `untracked`로 분류해 **중단 없이 보고만** 한다.

이 논거는 문서에 **이미 결정 8-a로 적혀 있다** — "메일박스의 유실이 안전한 이유가 여기서는
성립하지 않는다 — 버려지는 것이 바로 그 '다음 폴'의 일부이기 때문이다." 결정 12의 배선이
fill 핸드오프를 메일박스 **안으로** 옮기므로, **결정 8과 8-a가 결정 12 아래에서 서로
모순된다.**

**상한 자체에 대한 부수 소견 둘.**

- `Mailbox.post`는 **최신 것을 버린다.** 벤더 리포트가 누계인 상황에서 이는 최악의 선택이다 —
  최신 리포트가 이전 것을 모두 대체하므로, 꼬리 유실은 **낡은 데이터를 남기고 신선한 것을
  버린다.** 누계 데이터에 맞는 구조는 FIFO + 꼬리 유실이 아니라 **주문번호별 최신값 슬롯**이며,
  그편이 결정 8이 의존하는 성질에 대해 무손실이고 미결 주문 수로 자연히 유계다.
- Actor 2의 **무제한** 메일박스도 유효기간이 같다. 근거가 "생산자가 미결 주문 수로 유계다"인데
  WS `OrderFilled` 생산자가 그것도 깬다. §7은 Actor 1 쪽 절반만 적고 있다.

### M2 — 결정 3의 표가 fill-pump에 대해 사실과 다르고, §1-3의 락 인벤토리가 틀렸다

- 결정 3 표의 `fill-pump | 소유 없음 (조회만)`과 §1-2의 "버퍼에 append만 한다"는 **둘 다
  거짓이다.** `_poll_once`는 워커에서 돌면서 **Actor 1의 상태를 쓴다** —
  `state['booked_quantity']`·`['booked_fees']`가 `self.open_orders`의 항목을 변경하고,
  `ledger.record_fill`이 두 번째 연결로 원장에 쓴다. 오늘 직렬화되는 것은 오직 드레인
  배리어 덕이고, 그 배리어는 B4가 해체하는 바로 그 `settle()` 모양의 산물이다.
- §1-3 "락 인벤토리 — 1개"는 틀렸다. **최소 셋이다** — `_buffer_lock`, `Mailbox._lock`(문서가
  인정), 그리고 **인정되지 않은 모듈 수준 `_CALL_LOCK`**(`scripts/kis_gateway.py:69`)이 벤더의
  계좌당 호출 한도를 모든 스레드·모든 게이트웨이 인스턴스에 걸쳐 지킨다.
- 그 세 번째 락은 부기가 아니다. `_throttle()`이 **락을 쥔 채로 sleep한다**(`:488-495`).
  Phase 1에서 Actor 2의 `decide_weights` → 알파 모델 → `get_price`가 Actor 1의
  `place_market_order`와 **같은 락을 놓고 경합한다.** 즉 **느린 전략이 주문 제출을 멈출 수
  있다** — §3이 분리의 존재 이유로 내건 바로 그 성질("전략 코드가 5초 걸려도 브로커 이벤트
  수신은 멈추지 않는다")이 깨진다.

### M3 — §3 소유권표가 공유 가변 인프라를 전부 빠뜨렸다 (체계적 공백)

§3의 표는 넷을 적었지만, 이음매는 최소 넷을 **더** 가로지르고 그것들에 주인이 없다.

| 공유 객체 | Actor 1이 만짐 | Actor 2가 만짐 |
| --- | --- | --- |
| `data_handler`(`_marks`, `clear_cache()`) | `submit_order`, `_clamp_quantity`, `_mark_to_market` | 알파·리스크·옵티마이저 |
| 벤더 `client` / 호출 예산 | `place_market_order`, `get_order_report`, `get_price` | `get_price`(데이터 핸들러 경유) |
| `universe` | `_obtain_full_asset_list` | `_create_zero_target_weights_vector` |
| `SignalsCollection` | 메인 스레드가 워밍 | 알파 모델이 Actor 2 스레드에서 읽음 |

라이브 조립이 **인스턴스 하나를 공유**하는 것을 확인했다 — `test_live_session_e2e.py:124-151`이
같은 `data_handler`를 브로커·사이저·옵티마이저·PCM에 넘긴다. `clear_cache()`는 `_marks = {}`로
평범한 dict를 날리는데, 이를 Actor 1 스레드가 부르는 동안 Actor 2가 `decide_weights` 중일 수
있다.

**기존 경계 테스트가 이것을 잡지 못하는 이유.** `test_deciding_weights_never_reaches_the_broker`는
`alpha_model`을 `lambda dt: {...}`로 갈아끼운다. **PCM 배관**이 브로커 속성에 닿지 않음을
증명할 뿐, 실제 알파 모델이 무엇을 만지는지는 말하지 않는다. 실제 알파 모델은
`data_handler`와 `signals`를 들고 있다.

**왜 놓쳤나.** 결정 10이 "주 경로에는 계좌 상태가 아예 필요 없다"로 결론 내고 멈췄다.
*계좌* 상태에 대해서는 참이고, 그래서 문서가 더 보지 않았다. **이음매는 공유 상태로부터
자유로운 것이 아니라 공유 *계좌* 상태로부터 자유롭다.**

### M4 — 오류 전파가 정의돼 있지 않고, 두 모드가 이미 서로 다르게 동작한다

- **두 모드는 실패에서 동형이 아니다.** 스레드 모드의 `run()`은 잡아서 로그하고 `on_error`를
  부르고 계속한다. 동기 모드의 `post_event`는 `_dispatch`를 **try/except 없이** 부르므로 예외가
  호출자에게 나간다. 따라서 `live.py:101`의 `on_error=self._log_error`는 **오늘 죽은 코드다.**
  동형성 테스트는 행복 경로만 비교한다. D3 불변식 1은 두 모드가 같은 핸들러 코드를 탄다고
  말하고 실제로 그렇다 — 그리고 그것이 raise할 때 갈라진다.
- **`decide`가 raise하면.** 오늘(동기): `live.py:230`에서 전파, `run_rebalance`가 raise, outcome
  없음, `settle` 미실행. Phase 1(스레드): 삼켜지고 로그되고 `outcome['traded'] = True`는 그대로,
  `settle`이 0을 기표, 종료코드 0. **같은 실패에 정반대의 운영 신호.**
- **치명/복구 가능의 어휘가 없다.** `submit_order`는 `KillSwitchEngaged`를 **다시 던져서**
  리밸런스 밖으로 에스컬레이션한다. Phase 1에서 `size_and_submit`은 Actor 1의 루프 안에서
  돌고, §6.7 ②는 그 루프가 예외를 삼켜야 한다고 말한다. **킬스위치의 에스컬레이션이 삼켜진다.**
- **C-5의 안전 주장이 과하다.** "잘린 자리에서 보내려던 명령은 유실되지만 … 다음 기동의
  `reconcile()`이 정산한다" — reconcile은 주문을 정산한다. `TargetWeights` 유실은 주문이 애초에
  만들어지지 않았다는 뜻이고, reconcile이 찾을 것이 없다. **그날이 조용히 건너뛰어지는데
  문서는 덮인다고 믿고 있다.**

### M5 — 결정 2의 `Thread` 이름공간 위험이 3건 더 있고, 그중 1건은 살아 있는 버그다

전부 실행으로 재현했다.

1. **기동 전 `stop()`이 `RuntimeError: cannot join thread before it is started`로 죽는다.**
   `stop()`이 메일박스를 닫고 무조건 `self.join(timeout)`을 부른다. `start()` 전에 실패한
   세션이 `finally`에서 `stop()`을 부르면 **원래 예외가 Thread의 수명 오류에 가려진다.**
   테스트 없음.
2. **가드 1이 종료 창을 실제로 덮지 않는다.** 결정 4는 "정지(`stop()`) 후의 게시도 같은 가드에
   걸린다"고 적었지만 그렇지 않다 — `stop()`이 메일박스를 **먼저** 닫고 `is_alive()`는 드레인이
   끝날 때까지 `True`라, 드레인 중 게시는 `else` 가지를 타고 `MailboxClosed`를 낸다.
   **한 조건에 예외 타입이 둘**이고, C-5의 2→3단계가 정확히 그 창이다.
3. **그림자 테스트가 버전에 취약하다.** 테스트가 **한 번도 기동하지 않은** 동기 인스턴스를
   검사한다. 3.13에서는 모든 Thread 속성이 `__init__`에서 대입돼 우연히 완전하지만,
   `pyproject.toml`이 지원하는 3.10~3.12에서는 `_ident`·`_native_id`·`_tstate_lock`·`_is_stopped`가
   `start()` 시점에 대입되므로 그 이름들과의 충돌을 놓친다.
4. `run()`은 Thread의 공개 API다. 동기 실행기에서 `run()`을 직접 부르면 `take()`에서 영구
   블록된다. **가드 2는 `start()`만 덮는다.**

### M6 — 결정 1의 계약이 강제되지 않고, 훅 3개 중 2개가 배선되지 않았다

- 두 조립부가 `strategy=...alpha_model`을 넘긴다 — `AlphaModel`이지 **`BaseStrategy`가
  아니다.** 기존 전략 전부(`FixedSignalsAlphaModel`, `TopNMomentumAlphaModel`, 예제들)에
  `on_fill`이 없다. Phase 1에서 `OrderFilled`가 흐르기 시작하는 순간 `_dispatch`가 체결마다
  `AttributeError`를 내고 루프가 삼키며 **모든 체결 통지가 조용히 사라진다.**
- **`on_start`·`on_stop`을 부르는 곳이 없다**(전수 grep 0건). §5 스케치에는 루프 뒤의
  `self._strategy.on_stop()`이 있는데 구현이 뺐다. 훅 표면 3개 중 **1/3만 도달 가능하다.**
  신호 워밍업이 놓일 자리도 여기다(M3).
- **토픽 10종 중 8종에 생산자가 없다** — 주문 이벤트 6종 전부와 `PollDue`·`EndOfDay`.
  결정 7의 어휘 관리 원칙(C-2: "어휘를 미리 늘리면 발행자 없는 토픽이 남는다")이
  `AmendOrder`/`CancelOrder`를 보류한 근거인데, **정작 실린 6종에는 그 규칙이 적용되지 않았다.**

---

## 5. 경미 (5건)

- **`RebalanceDue`의 docstring이 철회된 결정 5를 서술한다** — "The handler for this event is
  where `qts(dt)` is called"(`messaging/lifecycle.py`). 코드 주석이 인용하는 문서와 모순된다.
- **문서의 `file:line` 인용이 전부 낡았다.** 6건을 대조해 전부 15~50줄 어긋남을 확인했다 —
  `_buffer_lock` 문서 147/실제 161, `Mailbox._lock` 53/80, `live.py` 리밸런스 190/230,
  `run_end_of_day` 222/262, `backtest.py` 폴링 416/431, `transact_asset` 577/612.
  **하필 Phase 1이 전환해야 할 호출 지점들이다.** `architecture-map.md` §7이 이것을 고치는
  것을 규칙으로 정하고 있다.
- **`stats`가 클로저로 이음매를 넘는다.** `backtest.py:418`이 `post_command` 안에서 그 실행의
  `stats` dict를 포획한다. 동기 동안은 무해하나, 백테스트가 스레드를 켜면 실행기 스레드에서
  append하고 메인 루프가 읽는다. 백테스트의 `synchronous=True`를 하드코딩된 리터럴이 아니라
  **단언된 불변식**으로 두기를 권한다.
- **`architecture-map.md` §6의 D2-a 행이 "불채택 — 범위 밖"**, D2가 "부분"으로 남아 있다.
  Phase 1이 착지하는 순간 둘 다 바뀐다.
- Actor 2의 무제한 메일박스 근거도 WS 생산자로 실효된다(M1 부수 소견) — §7은 Actor 1 쪽만 적음.

---

## 6. Phase 1 계획 — 의존 순서

**Phase 1을 쪼갠다. 1a = 스레드 켜기 + cron 모양 유지, 1b = 상주.** 문서는 이 둘을 하나로
다루는데 하나가 아니며, 1b는 어차피 별도 ADR이 필요하다.

| # | 단계 | 위험 | 무엇이 옳음을 증명하는가 |
| --- | --- | --- | --- |
| 0 | **v3 문서 정정** — 결정 3의 fill-pump 행과 §1-3 락 인벤토리(M2), §3 소유권표에 공유 인프라 행 추가(M3), 결정 8의 자가복구 주장을 6행 표로 교체(M1), 오류 의미론 결정 신설(M4), §7을 1a/1b로 분할(B4) | 없음 | 문서가 코드와 모순되는 주장을 더는 하지 않음 |
| 1 | **Actor 1을 객체로 만든다** — 브로커 쪽 `post_command`·`_mailbox`·`_dispatch`, 여전히 동기 구동 | 낮음 | `.dat` 완전 일치 e2e 통과 유지 |
| 2 | **outbox 재배선 + 세 번째 가드**(B1·B2) | 낮음 · **가치 높음** | 스레드 모드에서 `_post_command`가 브로커 객체의 바인드 메서드가 아님을 인스턴스 단언 |
| 3 | **fill 핸드오프를 유실 불가로**(M1) — 워터마크 전진을 워커에서 메인으로 이동, 명령·생명주기 무유실 레인 | **중간 — 회계 증분** | N건을 버려도 다음 폴 뒤 포트폴리오가 벤더 누계로 수렴 |
| 4 | **결정 1 계약 강제 + `on_start`/`on_stop` 배선**(M6), 신호 워밍업을 Actor 2로(M3) | 낮음 | 비`BaseStrategy`가 생성에서 거부됨 |
| 5 | **Actor 2에 자기 데이터 핸들러/가격 스냅샷**(M3), 벤더 클라이언트를 Actor 2에서 제거(M2) | 중간 | `clear_cache()` 중 결정이 바뀌지 않음 |
| 6 | **cron 단발 재구성**(B3) — 게시 → `executor.stop` → Actor 1 드레인 → `settle` | **높음 — 라이브 제어 흐름** | `test_live_session_e2e`를 플래그로 파라미터화해 동기/스레드 결과 일치 |
| 7 | 라이브 평면만 플래그 뒤집기 | 6단계 테스트로 통제 | — |

**그다음에야 Phase 1b(상주):** 전환 ADR, `settle()`의 여섯 책임을 하나씩 루프로 해체,
킬스위치가 살아남도록 `take(timeout)`, `SIGINT`/`SIGTERM`, 그리고 `EndOfDay` 추월 문제.

> 마지막 항목은 **`EndOfDay`를 클럭이 아니라 Actor 2가 리밸런스를 끝낸 뒤 보내면 저절로
> 풀린다.** 문서가 이미 첫 후보로 적어 둔 안이고, 결정 11의 "수신자가 자기 일을 끝낸 뒤 새
> 과거형 통지를 보낸다"와도 일관된다.

---

## 7. 소견 요약

| # | 소견 | 등급 | 근거 |
| --- | --- | --- | --- |
| B1 | 실행기 outbox가 Actor 1의 쓰기 경로 — 결정 5의 재발 | 차단 | 확인 |
| B2 | 모드는 세 사실인데 가드가 둘 | 차단 | 확인 |
| B3 | cron 단발에서 `settle()`이 리밸런스보다 먼저 돎 | 차단 | 확인 |
| B4 | 두 평면이 다른 메인 스레드 구조를 요구 | 차단 | 분석 |
| M1 | 자가복구 논거가 6종 중 1종만 덮음 · 결정 8과 8-a 모순 | 주요 | 분석 |
| M2 | 결정 3 표와 락 인벤토리가 사실과 다름 · 게이트웨이 락 경합 | 주요 | 확인 |
| M3 | §3 소유권표가 공유 인프라 4종을 빠뜨림 | 주요 | 확인 |
| M4 | 오류 전파 미정의 · 두 모드가 실패에서 비동형 | 주요 | 확인 |
| M5 | `Thread` 이름공간 위험 3건(1건은 살아 있는 버그) | 주요 | 재현 |
| M6 | 결정 1 계약 미강제 · 훅 2/3 미배선 · 토픽 8/10 생산자 없음 | 주요 | 확인 |
| m1~m5 | docstring·인용 낡음, `stats` 클로저, map §6 상태 | 경미 | 확인 |
