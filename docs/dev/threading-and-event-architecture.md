# Threading and Event Architecture

VMTrader의 스레드·이벤트 아키텍처 현황과, 전략 실행기 `BaseStrategyExecutor` 설계안.

- Updated: 2026-08-24
- Status: **설계안 v2 확정 — 미구현.** §1~§2는 현황(as-is)이고 §3 이하는 목표 구조(to-be)다.
  v1 검토에서 반려했던 두 항목을 **사용자 결정으로 해제**했다 — 실행기의 `Thread` 직접 상속(결정 2),
  실행기 스레드 `daemon=True`(결정 3). 각 결정에 그것이 안전하게 성립하는 전제 조건을 함께 기록한다.
  결정 2·4는 이후 **재검토를 거쳐 같은 형태(Thread 상속 + 플래그)로 재확정**하되, 위험 조합을
  막는 **런타임 가드 2개를 필수 조건**으로 추가했다(결정 4).
  `vmtrader/alpha_model/base_strategy_executor.py`의 현재 내용은 스텁이며 **재작성 대상**이다(부록 A-1).

## 0. Overview

**목표 구조:** 주문 이벤트(체결·거절·상태 변화)는 **2단 큐 파이프라인**
(브로커 메일박스 큐 → BaseStrategyExecutor 큐)을 통과하고, 각 큐는 **단일 소비자 스레드**를 가져
락 없이 상호배제·순서·원자성을 확보한다. **액터 2개를 이은 구조**다 —
Actor 1(브로커)은 **빠른 주문 처리**, Actor 2(전략 실행기)는 **느린 전략 처리**를 맡아 분리된다.
백테스트 — 그리고 현행 cron 단발 라이브(§4 결정 5) — 에서는 큐를 우회해 동기 실행으로 전환되어
**동일한 핸들러 코드**를 결정론적으로 재사용한다.

**현재 상태와의 거리:** 이 파이프라인은 아직 없다. 지금의 라이브 평면은 cron 단발이고
([ADR-0009](adr/0009-cron-oneshot-live-session.md)), 스레드는 fill pump 워커 하나뿐이며
([ADR-0008](adr/0008-task-queue-fill-pump.md)), 전략은 메인 스레드가 `qts(dt)` 한 줄로 동기
호출한다([`architecture-map.md`](architecture-map.md) §2). 그 간극을 §4~§7의 설계로 메운다.

---

## 1. 스레드 관련 클래스 — 현황

### 1-1. `Thread`를 직접 상속하는 클래스 — 현재 0개, 설계상 1개 예정

현재는 없다. 이 설계안의 `BaseStrategyExecutor(Thread)`가 첫 사례가 된다(§4 결정 2).
**첫이자 유일한 사례로 유지한다** — 두 번째 Thread 상속이 필요해 보이면 이 문서를 먼저 갱신한다.

스텁 `alpha_model/base_strategy_executor.py`는 `Thread` 상속과 `daemon=True`(결정 2·3)까지만
담고 있다 — 철자(`BaseStrategyExcutor`)와 큐·`run()` 루프·가드(결정 4)가 남았으며 §5 스케치대로
재작성한다.

### 1-2. 스레드를 생성·소유하는 클래스 (composition) — 1개

| 클래스 | 위치 | 스레드 이름 | 수명 | daemon |
|---|---|---|---|---|
| `TaskQueueWorker` | `broker/live/worker.py:140` | `fill-pump` | 리밸런스 1사이클 | **False** (의도적 — [ADR-0008](adr/0008-task-queue-fill-pump.md)) |

소유자는 `LiveBroker`다. 워커의 task는 venue를 조회해 **버퍼에 append만** 하고,
`Portfolio` 기표는 메인 스레드가 드레인 배리어(`join_tasks`) 뒤에 한다 — 회계 단일 작성자.
종료는 poison pill(None 센티넬) + `join`이며, `stop()`은 이미 게시된 task를 전부 소화한 뒤
끝난다(체결 유실 0의 종료 시퀀스). **이 워커의 daemon=False는 이 설계안에서 변하지 않는다**
(§4 결정 3의 비대칭 참조).

### 1-3. 락 인벤토리 — 1개

`LiveBroker._buffer_lock`(`live_broker.py:147`). 워커 → 메인 스레드의 체결 핸드오프 버퍼
하나를 지킨다. **이 락이 유일해야 한다는 것이 D2의 감시 항목이다** — 두 번째 락이 필요해지는
순간 단일 소비자 전제가 깨진 것이므로, 락을 더할 게 아니라 왜 깨졌는지를 찾는다
([`architecture-principles.md`](architecture-principles.md) D2 불변식 2).

---

## 2. `threading.Event` 인벤토리 — 0개

없다. 종료 신호는 poison pill, 드레인 배리어는 `Queue.join`/`unfinished_tasks`,
중단 신호는 파일 킬스위치(매번 다시 읽음, `broker/live/guards.py`)로 푼다.

`threading.Event`가 처음 필요해지는 시점은 **상주 프로세스 전환**(§7 Phase 1)이다.
그때 킬스위치 폴링을 이벤트 객체로 승격할지, `SIGINT`/`SIGTERM` 핸들러와 함께 결정한다
([보고서 20260822-01 §7](reports/20260822-01-worker-lifecycle-and-shutdown.md)).

---

## 3. 목표 구조 — 이벤트 처리 큐 파이프라인 (to-be)

주문 이벤트는 **브로커 → 메일박스 큐 → BaseStrategyExecutor 큐 → 전략 콜백** 순으로 2번 큐잉된다.

```
┌── Actor 1: Broker ─────────────────┐
│ 메일박스: 브로커 이벤트 큐 (유계)     │   빠르고 정확해야 한다
│ 스레드:   브로커 소비자 1개           │   daemon=False — 유실 0 종료
│ 상태:     주문 추적, 현금, 포지션     │
└───────────────┬────────────────────┘
                │ executor.post_event()  ← 액터 간 메시지 (fire-and-forget)
                ▼
┌── Actor 2: BaseStrategyExecutor ───┐
│ 메일박스: executor 큐 (무제한+계측)   │   느려도 된다
│ 스레드:   strategy-executor 1개      │   daemon=True — 종료를 막지 않는다
│ 상태:     전략(BaseStrategy), 사용자 코드│
└────────────────────────────────────┘
```

**왜 2단으로 나눴나 — 책임 분리 (이 설계의 중심 결정):**

- Actor 1은 **빠르고 정확해야** 한다 (브로커 상태 정합성). 느리면 이벤트 유실.
- Actor 2는 **느려도 된다** (사용자 전략 코드가 뭘 할지 모름 — 외부 API 호출, 무거운 계산).

전략 코드가 5초 걸려도 브로커 이벤트 수신은 멈추지 않는다.
액터 모델에서 흔한 **"빠른 수집기 + 느린 처리기"** 분리 패턴이다.
두 액터의 손실 허용도가 다르다는 이 비대칭이 §4 결정 3(daemon 정책의 비대칭)의 근거가 된다.

**메일박스 계층의 역할** — 한 줄 요약:
**"브로커마다 제각각인 주문 상태 변화 통지 방식을, 단일 스레드에서 직렬 처리되는 하나의
이벤트 메일박스로 정규화하는 어댑터 계층."** 이 클래스가 하는 일을 정확히 부르면
**단일 소비자 이벤트 버스**, 또는 액터 모델의 **메일박스**다(§6.4의 구분 참조 —
액터 인스턴스로 주소 지정하므로 메일박스 쪽이 더 정확하다).

**현행 코드와의 대응:** Actor 1의 자리는 오늘 `LiveBroker` + `TaskQueueWorker`가 변형된
형태로 채우고 있다 — 상태를 독점하는 것이 소비자 스레드가 아니라 **메인 스레드**라는 배치
역전이 있을 뿐, 단일 작성자라는 목적은 같다([`architecture-map.md`](architecture-map.md) §6 D2 행).
Actor 2가 이 문서의 신설 대상이다.

---

## 4. `BaseStrategyExecutor` 설계 — 결정 8개 (v2)

v1 검토는 실행기의 `Thread` 상속과 `daemon=True`를 반려했으나, **사용자 결정으로 두 항목을
해제하고 채택한다**(결정 2·3). 대신 각 결정이 안전하게 성립하는 전제 조건을 명시하고
테스트로 고정한다(부록 A). 나머지 결정(1, 4~8)은 v1과 같다.

### 결정 1 — 전략 계보와 실행기의 분리: `BaseStrategy(AlphaModel)` + 실행기는 전략을 소유

```
AlphaModel (ABC, __call__(dt) — 무변경)
   └ BaseStrategy(AlphaModel)     ← 훅 표면: on_start / on_fill / on_stop (기본 무동작)
        ▲
        │ 소유 (인자로 주입)
BaseStrategyExecutor(Thread)      ← 전략이 이것을 상속하지 않는다
```

- `AlphaModel` ABC는 `__call__(dt) -> dict{str: float}` 하나로 순수하게 유지 — 기존 ABC 15종과
  `FixedSignals` 등 구현체 전부 무변경, `test_abstract_base_classes.py`도 무변경.
- `BaseStrategy`가 중간 계층으로 훅을 **기본 무동작(no-op)** 으로 제공하고, 사용자는 필요한
  훅만 override한다. 훅 표면의 확장은 이 한 클래스에서 끝난다.
- 실행기는 전략의 상위 클래스가 아니다 — **전략을 인자로 받아 소유**한다. 전략 작성자는
  스레드 API(`start`/`join`)를 보지 않는다.

### 결정 2 — 실행기는 `Thread`를 직접 상속한다 (v1의 상속 금지 **해제** — 사용자 결정)

`BaseStrategyExecutor(Thread)`. 액터의 정체성이 곧 전용 스레드이므로 is-a로 표현한다.

재검토에서 composition + dispatcher 주입 대안(모드가 "어느 dispatcher를 꽂았나" 한 사실로
모이고, `TaskQueueWorker` 재사용으로 루프 중복이 없는 안)과 비교한 뒤 **상속 유지로
재확정**했다(사용자 결정). 비교에서 확인된 상속 쪽 추가 비용 — 실효 모드가 "플래그 + start
여부" 두 사실의 조합이 되는 것 — 은 결정 4의 런타임 가드가 상쇄한다.

상속이 지우지 않는 사실 두 가지는 규약으로 관리한다:

1. **`Thread`는 1회용이다** — `start()` 2회는 `RuntimeError`. 재시작 의미론을 주지 않는다:
   **정지한 executor의 재시작 = 새 인스턴스 생성**이다. cron 단발에서는 기동마다 새 프로세스라
   자연히 지켜지고, 상주(Phase 1)에서는 이 규약을 세션 코드가 지킨다.
2. **`run()` 소비 루프를 자체 구현한다** — `TaskQueueWorker`의 루프 규약(poison pill, 핸들러
   예외를 삼키고 `on_error` 보고, 루프는 죽지 않음)을 §6.7대로 동일하게 지키되 구현은 별도다.
   두 소비 루프가 미묘하게 달라지는 것이 이 선택의 비용이므로, 루프 규약을 **양쪽 모두
   테스트로 고정**한다(부록 A-3).

### 결정 3 — 실행기 스레드는 `daemon=True`, fill-pump는 여전히 `daemon=False` (사용자 결정)

daemon 정책은 전역이 아니라 **액터별로 갈린다.** 근거는 §3의 비대칭이다:

| | Actor 1 (fill-pump / 브로커) | Actor 2 (strategy-executor) |
|---|---|---|
| 책임 | 주문·체결·회계 | 전략 콜백 (사용자 코드) |
| 손실 허용도 | **유실 0** — join이 곧 회계 배리어 | 잘려도 회계 무손상 (아래 전제) |
| daemon | **False** ([ADR-0008](adr/0008-task-queue-fill-pump.md) 불변) | **True** — 프로세스 종료를 막지 않는다 |

- **daemon=True가 안전하기 위한 전제 = 결정 6.** executor는 `Portfolio`를 절대 만지지 않으므로,
  종료 시점에 전략 콜백이 잘려도 회계는 오염되지 않는다. 잘릴 수 있는 것은 진행 중이던
  콜백 1건뿐이고, 그 안에서 주문을 내는 중이었다면 접수됐거나 안 됐거나 둘 중 하나이며
  **다음 기동의 `reconcile()`이 정산한다** — 복구 경로가 일상 경로라는 ADR-0009의 성질이
  이 결정을 받친다. **결정 6이 깨지면 이 결정도 함께 재검토한다.**
- **daemon은 최후 안전판이지 종료 경로가 아니다.** 정상 종료는 여전히
  poison pill → `join(timeout)`이다. daemon 플래그는 "사용자 전략 코드가 외부 API에 걸려
  영원히 안 돌아오는" 사태에서 프로세스가 못 죽는 것을 막을 뿐이다.
- 참고 좌표: 참조 모델 D2 불변식 3은 "전부 데몬", ADR-0008은 "fill-pump 비데몬"이었다.
  v2는 제3의 선택 — **액터의 손실 허용도에 따라 daemon을 가르는 비대칭 정책**이다.
  D13(읽기 관대·쓰기 엄격)과 같은 정신의 비대칭이다.
- 워커의 기존 부채(플래그 직접 단언 테스트 없음)를 반복하지 않는다 — executor 도입 커밋에
  **`daemon=True` 단언 테스트**를 함께 넣는다(부록 A-3).

### 결정 4 — 모드 결정은 조립부 **한 곳**에서, 구조는 두 액터 분리로 고정 (D3)

- 라이브의 고정 구조는 §3의 2단 파이프라인이다 — 빠른 주문 처리(Actor 1)와 느린 전략
  처리(Actor 2)의 분리.
- 동기/비동기 선택은 생성자 인자 `synchronous` **하나**로 주입하고, 세션 조립부
  (`trading/backtest.py` · `trading/live.py`)에서만 정한다. 호출부 플래그
  (`post_event(..., sync=True)`)는 금지 — 새 이벤트를 추가하는 사람이 플래그를 빠뜨려
  결정론을 깨뜨린다(D3 불변식 2).
- 동기 모드에서 executor 인스턴스는 존재하되 `start()`되지 않고, `post_event()`가 호출
  스레드에서 즉시 `_handle()`을 탄다. **두 모드가 같은 `_handle(event)` 코드를 탄다**
  (D3 불변식 1) — 현행 D3 불채택(브로커 클래스 교체 방식)이 남긴 잔여 위험을 새 계층에서는
  만들지 않는다.

**재검토에서 확인된 약점과 가드 (필수):** 이 방식의 실효 모드는 `synchronous` 플래그와
`start()` 호출 여부, **두 사실의 조합**이다.

| `synchronous` | `start()` | 결과 |
|---|---|---|
| True | 안 함 | ✅ 동기 (의도) |
| False | 함 | ✅ 스레드 (의도) |
| True | **함** | ⚠️ 빈 큐를 영원히 대기하는 유령 스레드 |
| False | **안 함** | 🔴 이벤트가 큐에 쌓이기만 하고 아무도 소비하지 않음 — **조용한 유실** |

아래 두 불일치 조합은 발생 즉시 **시끄럽게 실패**시킨다. 상태 변경의 실패를 삼키지 않는
D13(쓰기 엄격)과, 조용히 버리는 큐를 금지하는 D2-a를 이 지점에 적용한 것이다.

- **가드 1:** `synchronous=False`인데 소비자 스레드가 살아 있지 않은 상태의 `post_event()`는
  적재하지 않고 `RuntimeError`를 낸다 — 조용한 유실 칸을 봉쇄한다. 정지(`stop()`) 후의
  게시도 같은 가드에 걸린다(재시작 = 새 인스턴스 규약과 일관, 결정 2).
- **가드 2:** `synchronous=True`에서 `start()`는 `RuntimeError`를 낸다 — 유령 스레드 칸을
  봉쇄한다.

두 가드는 부록 A-3에서 테스트로 고정한다. **가드 없는 안 B는 채택되지 않았다** — 가드는
구현 편의가 아니라 이 결정의 성립 조건이다.

### 결정 5 — ADR-0009(cron 단발) 아래에서 executor 스레드는 돌 일이 없다

- 상주 스레드가 값을 내는 것은 push 이벤트(실시간 시세 WS, 비동기 체결 통지)가 있을 때다.
  현행 라이브는 폴링 + 단발이라 이벤트 생산자가 사실상 메인 스레드뿐이고, 전략 호출은
  사이클당 `qts(now)` 1회다. 지금 스레드를 켜면 **스레드 1개가 이벤트 0건을 기다리는**
  구조가 된다.
- 따라서 구현을 2단계로 나눈다(§7): **Phase 0**은 `synchronous=True`로 합류점 호출을
  executor 경유로 바꾸고(스레드 0개), **Phase 1**(상주 + 실시간 시세)에서
  `synchronous=False` + `start()`를 켠다.
- Phase 0에서도 이 계층을 먼저 넣는 이유: **D3 불변식 1을 코드로 미리 고정**해, 상주 전환
  날에 핸들러 경로가 두 갈래로 갈라질 자리를 없앤다. 리밸런스·EOD 같은 생명주기 훅도
  이벤트로 정의해 같은 메일박스를 태우면, 훅 진입 시 큐 배수(D14 불변식 3)가 Phase 1에서
  구조적으로 공짜가 된다.

### 결정 6 — 회계 단일 작성자 경계: executor는 `Portfolio`를 만지지 않는다

- ADR-0008의 "워커는 포트폴리오를 만지지 않는다"가 executor에 그대로 확장된다.
  executor가 받는 이벤트는 **과거형 통지**("체결됐다")이고, 전략이 내고 싶은 주문은
  브로커의 공개 API 호출(= 액터 간 메시지)로 돌아간다. 다른 액터의 상태를 직접 읽거나
  쓰지 않는다는 액터 규칙(§6.3) 그대로다.
- 전략이 잔고·포지션을 봐야 할 때는 브로커의 조회 API(스냅샷 반환)를 쓴다.
- **이 결정은 결정 3(daemon=True)의 안전 전제다.** 여덟 결정 중 가장 깨져서는 안 되는 것.

### 결정 7 — 이벤트 타입 ≠ 주문 상태값 (D4)

- 이벤트 토픽과 원장 상태 enum을 **처음부터 분리**한다. `order.status = EVENT_FILLED` 같은
  대입이 생기지 않도록 이벤트는 자체 타입(dataclass)으로 정의하고, 상태는
  `broker/live/ledger.py`의 것을 그대로 쓴다. 한 상수가 두 개념을 겸직하면 이후 어느 쪽도
  독립적으로 바꿀 수 없다(D4 "흔한 설계 부채").
- 모든 이벤트에 **상관관계 ID**(`order_no`)와 발신 정보를 싣는다 — 스택 트레이스가 큐에서
  끊기는 약점(§6.7 ④)의 완화이자, 원장의 멱등키와 이어지는 추적 고리다.

### 결정 8 — 백프레셔: executor 큐는 무제한, 단 깊이를 계측한다

- 생산자가 브로커 액터 1개이고 게시량이 미결 주문 수로 유계인 동안은 무제한 큐가 안전하다
  — D2-a에 대한 현행 판단([`architecture-map.md`](architecture-map.md) §6)과 같은 논리다.
- WS 시세 구독이 들어오는 Phase 1에서 이 판단은 실효된다. 그때 정책을 다시 정할 수 있도록
  **큐 깊이·처리 지연 계측을 Phase 0부터** 넣는다 — "조용히 버리는(또는 조용히 부푸는)
  큐는 사고의 온상"(D2-a).

---

## 5. 인터페이스 스케치

비규범적이다 — 구현하며 조정될 수 있고, 계약으로 고정되는 것은 §4의 결정 8개다.

```python
# vmtrader/alpha_model/  (스텁 재작성 — 부록 A-1)

class BaseStrategy(AlphaModel):
    """훅 표면. 전부 기본 무동작 — 사용자는 필요한 훅만 override한다."""
    def on_start(self): ...
    def on_fill(self, event): ...
    def on_stop(self): ...


class BaseStrategyExecutor(Thread):
    """전략 액터. Thread 직접 상속(결정 2), daemon=True(결정 3).

    전략이 이것을 상속하지 않는다 — 전략은 인자로 들어온다(결정 1).
    정지한 executor는 재시작하지 않는다 — 재시작 = 새 인스턴스(결정 2).
    """

    def __init__(self, strategy, synchronous=False, on_error=None):
        super().__init__(name='strategy-executor', daemon=True)   # 결정 3
        self._strategy = strategy
        self._synchronous = synchronous   # 조립부 한 곳에서만 결정 (결정 4, D3)
        self._on_error = on_error
        self._queue = queue.Queue()       # 무제한 + 깊이 계측 (결정 8)

    # ── 브로커 액터가 부르는 면 (fire-and-forget) ──
    def post_event(self, event):
        if self._synchronous:
            self._handle(event)           # 백테스트·cron 단발: 큐 우회, 스레드 0개
        elif not self.is_alive():
            raise RuntimeError(           # 가드 1: 소비자 없는 적재 = 조용한 유실 금지
                'threaded executor가 시작되지 않았거나 이미 정지했다'
            )
        else:
            self._queue.put(event)

    def start(self):
        if self._synchronous:
            raise RuntimeError(           # 가드 2: 동기 모드에 유령 스레드 금지
                'synchronous 모드의 executor는 start()할 수 없다'
            )
        super().start()

    # ── 소비 루프 — §6.7 규약을 직접 지킨다 (결정 2의 비용) ──
    def run(self):
        while True:
            event = self._queue.get()
            if event is None:             # poison pill
                break
            try:
                self._handle(event)
            except Exception as error:    # 소비자 루프는 죽지 않는다 (§6.7 ②)
                logger.error(...)
                if self._on_error is not None:
                    self._on_error(error)
        self._strategy.on_stop()

    # ── 두 모드가 공유하는 유일한 핸들러 경로 (D3 불변식 1) ──
    def _handle(self, event): ...
        # 이벤트 타입별로 전략 훅 디스패치. Portfolio에는 절대 기표하지 않는다(결정 6)

    # ── 세션 조립부가 부르는 면 ──
    def stop(self, timeout=None):
        """정상 종료 경로: poison pill → join. daemon은 안전판이지 이 경로가 아니다."""
        self._queue.put(None)
        self.join(timeout)
        # timeout 초과 시에도 프로세스 종료는 막히지 않는다 — daemon=True (결정 3)
```

**전략 콜백 안의 금지 규칙 2개:**

1. `post_event`의 결과를 **기다리지 않는다** — 소비자 스레드가 자기 자신을 기다리는
   데드락이 된다(§6.7 ③). API 자체를 fire-and-forget으로만 두어 구조적으로 막는다.
2. `Portfolio`를 직접 만지지 않는다(§4 결정 6). **daemon=True의 안전 전제이므로 예외 없다.**

---

## 6. 개념 정리: 단일 소비자 이벤트 버스 & 액터 모델

### 6.1 출발점 — 이 패턴들이 푸는 문제

멀티스레드에서 공유 상태를 다루는 방법은 근본적으로 두 갈래다.

| 접근 | 방식 | 대표 도구 |
|---|---|---|
| **A. 공유 + 보호** | 모두가 같은 데이터를 만지되 락으로 순서를 강제 | `Lock`, `RLock`, `synchronized` |
| **B. 비공유 + 전달** | 데이터를 **한 스레드만** 소유. 나머지는 "메시지"를 보냄 | 큐, 메일박스, 채널 |

A는 락 순서 실수 → 데드락, 락 누락 → 레이스 컨디션이 생기고,
코드가 커질수록 "이 필드는 어느 락이 지키지?"를 아무도 모르게 된다.
**B는 락을 아예 없앤다** — 데이터를 만지는 스레드가 하나뿐이면 경쟁 자체가 성립하지 않는다.

### 6.2 단일 소비자 이벤트 버스

알고 있는 패턴들의 조합이다.

```text
Observer 패턴  (이벤트 발행/구독)
      +
Producer-Consumer  (스레드 안전 큐)
      +
소비자 스레드를 딱 1개로 제한   ← 핵심
```

Observer만 쓰면 **발행자의 스레드에서 콜백이 실행**된다.
WebSocket 스레드가 `notify()`를 호출하면 구독자 코드가 그 WS 스레드에서 돌고,
구독자가 공유 상태를 만지면 곧바로 락이 필요해진다.

큐를 끼우고 소비자를 1개로 묶으면:

```
[WebSocket 스레드 ]  ─┐
[폴링       스레드 ]  ─┼─ → [Queue] ──→ [소비자 스레드 1개] ──→ 핸들러 실행
[타이머     스레드 ]  ─┘                    ↑
                                       여기서만 상태를 만짐 = 락 불필요
```

**"단일 소비자"가 공짜로 주는 것:**

| 보장 | 설명 |
|---|---|
| **상호배제** | 두 이벤트가 절대 동시에 실행 안 됨 → 락 불필요 |
| **순서 보장** | FIFO. 체결 → 취소가 뒤집히지 않음 |
| **원자성** | 핸들러 하나가 끝날 때까지 중간 상태가 남에게 안 보임 |

락 3~4개로 만들어야 할 보장을 **"소비자를 1개로 둔다"** 한 줄의 규칙으로 얻는다.

### 6.3 액터 모델 & 메일박스

1973년 Carl Hewitt가 제안한 동시성 모델.
**"모든 것은 액터다"** — OOP의 "모든 것은 객체다"에 대응한다.

**액터 = 상태 + 메일박스 + 행동**

```
┌─────────────── Actor ─────────────┐
│  메일박스 (큐)                      │  ← 외부에서 볼 수 있는 유일한 창구
│     │                             │
│     ▼ 한 번에 하나씩 꺼냄            │
│  Behavior (메시지 처리 함수)        │
│     │                             │
│     ▼                             │
│  State (내부 상태)                 │  ← 외부에서 직접 접근 절대 불가
└───────────────────────────────────┘
```

**규칙은 3개뿐이다.** 액터가 메시지 하나를 받으면 할 수 있는 일:

1. 다른 액터에게 메시지 보내기 (비동기, fire-and-forget)
2. 새 액터 만들기
3. 다음 메시지를 처리할 행동 바꾸기 (상태 전이)

**절대 못 하는 것:** 다른 액터의 상태를 직접 읽거나 쓰기.
물어보고 싶으면 메시지를 보내고 답장을 기다려야 한다.

액터는 사실 **OOP의 원래 의도를 스레드까지 확장한 것**이다.

|       | 일반 객체                             | 액터                                         |
|---    |---                                   |---                                          |
| 캡슐화 | private 필드                          | private 필드 **+ 전용 스레드**                |
| 호출   | `obj.method()` — 호출자 스레드에서 실행 | `actor ! msg` — **액터 자신의 스레드**에서 실행 |
| 반환   | 즉시 값                               | 없음 (필요하면 답장 메시지)                     |
| 동시성 | 호출자가 락 걱정                        | 액터 내부는 **항상 싱글스레드**                 |

Alan Kay의 "객체지향의 본질은 메시지 전달"이 문자 그대로 구현된 형태다.

### 6.4 이벤트 버스 vs 메일박스

```
이벤트 버스:  "주문이 체결됐다!"        → 관심 있는 놈들이 알아서 받음 (주소 = 토픽)
메일박스:    "브로커야, 이거 처리해라"  → 특정 액터 하나에게 (주소 = 액터 참조)
```

| 구분        | 단일소비자 이벤트 버스                      | 액터 메일박스                         |
|---        |---                                        |---                                  |
| 주소 지정  | **토픽/이벤트 타입**                         | **액터 인스턴스**                     |
| 구독자 수  | 원래는 N개 가능                              | 항상 1개 (그 액터)                    |
| 메시지 의미 | "무슨 일이 **일어났다**" (과거형)             | "이걸 **해달라**" (명령형) 또는 사실 통보 |
| 인스턴스 수 | 보통 앱당 1개                               | 수천~수백만 개 (Erlang은 경량 프로세스) |
| 대표 구현   | Guava EventBus, Spring `ApplicationEvent` | Erlang/Elixir, Akka, Orleans, Ray   |

### 6.5 이 패턴의 적용 판단

**적합**

- 여러 스레드가 만든 이벤트를 **하나의 상태 기계**에 반영해야 할 때 (주문 상태 관리가 전형)
- **순서가 중요**할 때 (체결 후 취소 ≠ 취소 후 체결)
- 처리 로직이 복잡해서 락으로 감싸면 데드락이 무서울 때

**부적합**

- 처리가 CPU 바운드이고 **병렬화가 이득**일 때 → 단일 소비자가 병목
- 즉시 응답이 필요할 때 → 메시지는 비동기라 왕복 지연 발생
- 이벤트가 초당 수십만 건 → 큐 오버헤드가 락보다 비쌀 수 있음

### 6.6 실무 적용

이 저장소의 to-be 구조는 정확히는 "액터가 2개뿐"인 형태다 — §3의 그림.
인터페이스는 액터, 실행 모델도 액터, 다만 수천 개가 아니라 딱 2개.

### 6.7 주의사항

**① 백프레셔 — 큐가 가득 차면?**

| 전략 | 대가 |
|---|---|
| **버리기** | 데이터 유실. 폴링 브로커는 다음 사이클이 복구하지만 WS 전용은 안 됨 |
| **블로킹** | 생산자(WS 스레드)가 멈춤 → 벤더 연결이 끊길 수 있음 |
| **무제한 큐** | 메모리 폭주 |

어느 쪽이든 유실·깊이를 **계측해 노출**한다(§4 결정 8).

**② 소비자 스레드가 죽으면 시스템 전체가 멎음**

단일 소비자의 최대 약점. 핸들러 예외를 전부 삼켜서 방어한다 —
`TaskQueueWorker.__loop`이 이미 이 규약이고, `BaseStrategyExecutor.run()`도 같은 규약을
직접 지킨다(§5, 결정 2의 비용).

**③ 자기 자신에게 메시지를 보내는 데드락**

소비자 스레드에서 `dispatch()`를 호출하고 그 결과를 **기다리면** 영원히 멈춘다.
→ executor의 공개 API를 fire-and-forget으로만 둔다(§5 금지 규칙 1).

**④ 디버깅이 어려움**

스택 트레이스가 "누가 이 이벤트를 보냈는지"에서 끊긴다.
→ 모든 이벤트에 상관관계 ID·발신 정보를 싣는다(§4 결정 7).

---

## 7. 적용 시나리오 — 단계별 도입

| Phase | 전제 | 모드 (조립부에서 결정) | 추가 스레드 | 진입 조건 |
|---|---|---|---|---|
| **0** | 현행 — 백테스트 + cron 단발 라이브 | `synchronous=True` (두 평면 모두, `start()` 안 함) | **0** | 이 설계안 채택 |
| **1** | 상주 프로세스 + push 이벤트 (WS 실시간 시세 / 체결 통지) | 라이브만 `synchronous=False` + `start()`, 백테스트는 동기 유지 | **+1** (`strategy-executor`, daemon) | **ADR-0009 전제 변경 — 새 ADR 필요** |

**Phase 0이 실제로 바꾸는 것:** 합류점 `qts(dt)` 직접 호출 → executor 경유
(`post_event(RebalanceDue(dt))` → 동기 → `_handle` → `qts(dt)`).
동작은 오늘과 비트 단위로 같아야 하며(`.dat` 완전 일치 e2e가 그대로 통과), 얻는 것은
**두 평면이 공유하는 단일 핸들러 경로**라는 구조다.

**Phase 1에서 함께 재검토해야 하는 것** (전제가 바뀌므로 되살아나는 축들):

- D2-a 백프레셔 — WS 생산자가 생기면 "유계 게시량" 논리가 실효 (결정 8)
- `threading.Event` / `SIGINT`·`SIGTERM` 핸들러 (§2, [보고서 20260822-01 §7](reports/20260822-01-worker-lifecycle-and-shutdown.md))
- 종료 순서: 생산자(브로커 액터) 먼저 정지 → executor `stop(timeout)` (기동의 역순).
  join timeout 초과 시 daemon 플래그가 프로세스 종료를 보장한다 — 잘린 콜백의 주문은
  다음 기동 `reconcile()`이 정산 (결정 3)

---

## 부록 A. 액션 아이템

구현 착수 시 순서대로. 각 항목은 같은 커밋에서 문서·테스트가 함께 움직인다
([`architecture-map.md`](architecture-map.md) §7 규칙).

1. **스텁 완성** — `alpha_model/base_strategy_executor.py`를 §5 스케치대로.
   철자 교정(`BaseStrategyExcutor` → `BaseStrategyExecutor`), 큐·`run()` 루프·런타임 가드 2개
   (결정 4) 구현, `BaseStrategy` 신설(`alpha_model/base_strategy.py`).
2. **이벤트 타입 정의** — dataclass, 상관관계 ID 포함, 원장 상태 enum과 분리(결정 7).
3. **테스트로 고정할 것** (Phase 0):
   - 동일 이벤트열에 대해 동기/스레드 모드 처리 결과 동일 — 동형성(원칙 2, D3 불변식 1)
   - 동기 모드 반복 실행의 결정론 — 기존 `.dat` 완전 일치 e2e 통과가 그대로 증거
   - **`daemon=True` 플래그 직접 단언** — 사용자 결정(결정 3)을 코드로 고정.
     fill-pump 쪽 `daemon=False` 단언도 이 기회에 함께 추가(기존 부채 해소)
   - `run()` 루프 규약: 핸들러 예외가 루프를 죽이지 않음 + `on_error` 보고, poison pill 종료,
     FIFO 순서 — `TaskQueueWorker`와 **같은 규약을 양쪽 모두** 단언(결정 2의 비용 관리)
   - **런타임 가드 2건**(결정 4의 성립 조건): 비동기 모드에서 미기동/정지 상태의
     `post_event`가 raise(가드 1), 동기 모드의 `start()`가 raise(가드 2)
   - `stop()` 이후 `start()` 재호출이 거부됨 — 재시작 = 새 인스턴스 규약
   - executor 경로가 `Portfolio`에 기표하지 않음 — **결정 3의 안전 전제이므로 최우선**
     (기존 vendor-boundary AST 테스트 방식 참고)
4. **훅 표면 확정** — `BaseStrategy`의 `on_start`/`on_fill`/`on_stop` 시그니처와 호출 시점.
   ABC(`AlphaModel`)는 건드리지 않으므로 `test_abstract_base_classes.py` 무변경.
5. **채택 시 문서 갱신** — `architecture-map.md` §3(모듈 지도)·§4(확장점)·§6(D2/D3 행 상태
   재평가 — 특히 daemon 비대칭 정책을 D2 불변식 3 행에 기록), 이 문서의 Status를 "구현됨"으로.
6. **Phase 1 진입 시** — 새 ADR(상주 전환) 작성, §7의 재검토 목록 처리.

## 부록 B. 관련 문서

| 문서 | 관련 |
|---|---|
| [`architecture-principles.md`](architecture-principles.md) D1~D3, D13, D14 | 직렬 실행·단일 소비자·모드 전환·비대칭 정책·생명주기 — 이 설계의 잣대 |
| [`architecture-map.md`](architecture-map.md) §2·§4·§6 | 현행 실행 순서, ABC 목록, D2/D3 적용 상태(정본) |
| [ADR-0006](adr/0006-decouple-submit-from-fill.md) | 접수·체결 분리 — executor가 받는 이벤트의 발원지 |
| [ADR-0008](adr/0008-task-queue-fill-pump.md) | `TaskQueueWorker`·fill-pump daemon=False·회계 단일 작성자 — 결정 3 비대칭의 한쪽 축, 결정 6의 근거 |
| [ADR-0009](adr/0009-cron-oneshot-live-session.md) | cron 단발 전제 — 결정 5와 Phase 게이트, 그리고 "reconcile이 잘린 콜백을 정산한다"(결정 3)의 근거 |
| [보고서 20260822-01](reports/20260822-01-worker-lifecycle-and-shutdown.md) | 워커 수명·종료 시퀀스 분석 |
| [`testing.md`](testing.md) | 부록 A-3의 테스트가 따를 작성 규약 |
