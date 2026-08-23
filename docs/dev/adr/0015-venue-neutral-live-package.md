# ADR-0015: 라이브 인프라를 벤더 중립 패키지로 분리한다

| 항목 | 내용 |
| --- | --- |
| 상태 | **채택됨** (2026-08-23) |
| 성격 | **파괴적 변경** — 공개 클래스명·모듈 경로 변경 |
| 관련 | [ADR-0003](0003-port-lab-code.md), [ADR-0004](0004-promote-update-to-abc.md), [보고서 20260823-01 §5](../reports/20260823-01-codebase-comprehension-strategy.md) |

## 맥락

두 번째 증권사(DB증권) 연동을 검토하면서 브로커 계층을 리뷰한 결과, **venue 추상화 자체는 이미 되어 있으나 그 코드가 벤더 이름 아래 놓여 있다**는 것이 확인되었다.

관측된 사실 세 가지다.

1. **`KisBroker`는 KIS를 import하지 않는다.** 877줄 전체에서 벤더를 아는 것은 로그 접두어 `'kis broker: '` 문자열 하나뿐이었고, 나머지는 전부 `BrokerClient` Protocol을 통해 말한다. 즉 클래스는 이미 중립이고 이름만 벤더였다.

2. **`broker/kis/` 7모듈 중 6개가 venue 중립이다.** `client.py`(Protocol과 dataclass 3종), `worker.py`(범용 FIFO 워커), `guards.py`(주문 한도·킬스위치), `ledger.py`(SQLite 원장), `reconcile.py`(대조)는 KIS에 대해 아무것도 모른다. 실제로 벤더 고유한 것은 응답 필드명을 아는 `parse.py` 하나였다.

3. **그 벤더 이름이 엔진 코어로 새어 있었다.**

   ```text
   vmtrader/trading/live.py:19          from vmtrader.broker.kis.guards import KillSwitchEngaged
   vmtrader/trading/live.py:20          from vmtrader.broker.kis.reconcile import reconcile
   vmtrader/data/live_data_handler.py:1 from vmtrader.broker.kis.parse import KisParseError
   ```

   세 번째가 특히 나빴다. venue 중립이어야 할 `LiveDataHandler`가 가격을 얻지 못했을 때 **KIS 파서의 예외를 던졌다.** DB증권 게이트웨이를 붙이면 DB증권의 가격 실패가 KIS 오류로 보고된다.

이 상태로 두 번째 브로커를 붙이면 두 가지 중 하나가 된다 — `DbsBroker`가 `KisBroker`의 877줄을 복제하거나, `DbsBroker(KisBroker)`가 되어 "DB증권은 KIS의 일종"이라는 거짓 계층을 만들거나. 둘 다 나쁘다.

## 결정

**라이브 평면을 벤더 중립부와 벤더 고유부로 물리적으로 분리하고, 중립부에서 벤더 이름을 제거한다.**

| 이전 | 이후 |
| --- | --- |
| `vmtrader/broker/kis/client.py` | `vmtrader/broker/live/client.py` |
| `vmtrader/broker/kis/worker.py` | `vmtrader/broker/live/worker.py` |
| `vmtrader/broker/kis/guards.py` | `vmtrader/broker/live/guards.py` |
| `vmtrader/broker/kis/ledger.py` | `vmtrader/broker/live/ledger.py` |
| `vmtrader/broker/kis/reconcile.py` | `vmtrader/broker/live/reconcile.py` |
| `vmtrader/broker/kis_broker.py` → `KisBroker` | `vmtrader/broker/live_broker.py` → **`LiveBroker`** |
| `vmtrader/broker/kis/parse.py` | **그대로** — 유일한 벤더 고유 모듈 |
| — | `vmtrader/broker/live/errors.py` **신설** |

부수 결정 세 가지.

- **중립 예외를 신설한다.** `VenueError` / `VenueParseError` / `PriceUnavailable`. `LiveDataHandler`는 `PriceUnavailable`을 던지고, `KisParseError`는 `VenueParseError`를 상속한다. 상속 덕에 기존 `except KisParseError`는 전부 그대로 동작하며, DB증권 파서는 `DbsParseError(VenueParseError)`를 정의하면 된다.
- **로그 접두어를 주입받는다.** `LiveBroker(venue_name='kis')`. 클래스가 중립이 된 이상, 운용자가 읽는 로그에서 어느 증권사인지 알려 주는 것은 조립부의 책임이다. `account_id` 기본값도 `'kis'`에서 `'live'`로 바꾸고, KIS 조립부(`scripts/kis_smoke.py`, 운용 문서 예제)가 `account_id='kis'`를 명시한다.
- **경계를 테스트로 고정한다.** `tests/unit/test_vendor_import_boundary.py`가 AST로 패키지 전체를 읽어 (a) 어떤 모듈도 브로커 SDK를 import하지 않고, (b) 벤더 코드는 그 벤더 패키지 안에서만 import되며, (c) `broker/live/`는 어떤 벤더도 참조하지 않음을 검사한다. 스펙 NFR-3이 요구하던 검사다.

## 대안과 기각 사유

| 대안 | 기각 사유 |
| --- | --- |
| **아무것도 하지 않고 DB증권을 붙인다** | 위 셋 중 하나가 된다 — 877줄 복제, 거짓 상속, 또는 코어에 벤더 분기. 세 번째가 되면 브로커가 늘 때마다 코어가 커진다 |
| **`DbsBroker(KisBroker)` 상속** | "DB증권은 KIS의 일종"은 거짓이다. 공통 로직이 상위에 있을 뿐이며, 그 상위의 올바른 이름은 `LiveBroker`다 |
| **개명 없이 이동만 한다** (`broker/live/`로 옮기되 `KisBroker`는 유지) | 파일 위치와 클래스명이 어긋난다. 파괴적 변경을 두 번 하게 되므로 한 번에 한다 |
| **하위호환 alias를 남긴다** (`KisBroker = LiveBroker`) | 이름을 지우는 것이 목적인데 이름이 남는다. 저장소가 1.0 이전이고 [ADR-0011](0011-package-rename-vmtrader.md)에서 패키지 전체를 개명한 전례가 있다. CHANGELOG로 알린다 |
| **`reconcile.py`는 `kis/`에 남긴다** | `trading/live.py`가 이것을 import하므로 코어의 벤더 참조가 남는다. 이 ADR의 목적이 달성되지 않는다 |

## 결과

**좋은 점**

- DB증권 연동이 **게이트웨이 파일 하나**로 축소된다. `scripts/dbs_gateway.py`가 `BrokerClient` 6개를 구현하고, 조립부가 `LiveBroker(client=DbsGateway(...), venue_name='dbs')`로 넣는다. 엔진 코드는 변경 없다.
- 코어에서 벤더 이름이 사라진다. `grep -rn "broker\.kis" vmtrader/` 가 `broker/kis/` 밖에서 0건이다.
- 재사용 가능한 코드를 알아볼 수 있게 된다. `TaskQueueWorker`와 `SafetyGuard`는 KIS와 무관한데 이름 때문에 그렇게 읽히지 않았다.

**나쁜 점 / 비용**

- **파괴적 변경이다.** `from vmtrader.broker.kis_broker import KisBroker`를 쓰던 코드는 전부 깨진다. 영향 범위는 저장소 안에서 소스 6, 테스트 6, 스크립트 3, 문서 1개였고 전부 갱신했다. 외부 사용자는 CHANGELOG로 안내한다.
- **`account_id` 기본값이 바뀐다.** 로컬 `Portfolio`의 식별자이며 원장에는 기록되지 않으므로 회계에 영향은 없으나, 생략하던 조립부의 로그 표기가 달라진다.
- 아직 남은 결합이 있다. `reconcile()`은 여전히 `LiveBroker`의 비공개 메서드 4종(`_now`·`_poll_once`·`_drain_fill_buffer`·`_close_order`)을 호출하고, `LiveTradingSession`이 의존하는 브로커 멤버 7개 중 `Broker` ABC가 보장하는 것은 1개뿐이다. **이 ADR은 그것을 고치지 않는다** — 보고서 20260823-01의 R4·R5에 해당하며 별도 결정이 필요하다.

**검증**

- 이동·개명 전후로 테스트 수와 결과가 동일하다: **514 케이스 전부 통과.** 순수 이동이라는 주장의 근거다.
- 경계 테스트 201건이 추가되어 **715 케이스**가 되었다. 음성 대조로 실제 위반(코어에 `broker.kis` import 1줄 추가)을 검출함을 확인했다.
- `uv run ruff check` 통과.
