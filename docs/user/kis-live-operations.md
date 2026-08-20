# KIS 라이브 운용 가이드

| 항목 | 내용 |
| --- | --- |
| 문서 ID | `user/kis-live-operations` |
| 작성일 | 2026-08-20 |
| 독자 | 이 엔진으로 실제 계좌를 운용하는 사람 |
| 상태 | **모의투자(vps) 기준** — 실전(`prod`) 전환은 별도 판단 사안 |
| 근거 설계 | [spec/kis-broker-design.md](../dev/spec/kis-broker-design.md), [ADR-0009](../dev/adr/0009-cron-oneshot-live-session.md) |

---

## 1. 이 문서가 다루는 것

라이브 세션은 **상주 데몬이 아니라 cron 단발**이다([ADR-0009](../dev/adr/0009-cron-oneshot-live-session.md)). 하루에 두 번 프로세스가 떴다 죽으며, 그 사이의 대기는 cron이 한다. 따라서 운용이란 곧 **cron 두 줄을 올바르게 걸고, 실행 결과를 확인하고, 필요할 때 멈추는 것**이다.

---

## 2. 준비물

| 항목 | 내용 | 확인 방법 |
| --- | --- | --- |
| KIS 모의투자 계좌 | 앱키·앱시크릿·계좌번호 | KIS 개발자센터에서 발급 |
| OTA 클론 | `koreainvestment/open-trading-api` 저장소 클론. **PyPI 패키지가 아니다** | `export OTA_HOME=~/github.com/open-trading-api` |
| OTA 인증 설정 | OTA가 요구하는 `kis_devlp.yaml`에 앱키·계좌 기입 | OTA 문서 참조 |
| 파이썬 | 3.10 이상 | 이 저장소는 uv로 관리한다 |

**앱키는 저장소에 커밋하지 않는다.** OTA 설정 파일은 저장소 밖에 두고 권한을 `600`으로 둔다.

---

## 3. cron 두 줄

호스트의 기존 봇들과 같은 `cron_run.sh` + `flock` 관례를 따른다. **두 기동은 같은 잠금 파일을 공유**해 겹쳐 도는 것을 막는다.

```cron
TZ=Asia/Seoul

# A. 리밸런싱 — 평일 10:00
0 10 * * 1-5 flock -n /home/ec2-user/lock/vmtrader.lock \
  /path/to/run_live.sh rebalance >> /home/ec2-user/log/vmtrader/rebalance.log 2>&1

# B. 장 마감 후 평가 — 평일 15:40
40 15 * * 1-5 flock -n /home/ec2-user/lock/vmtrader.lock \
  /path/to/run_live.sh eod >> /home/ec2-user/log/vmtrader/eod.log 2>&1
```

**시각을 10:00으로 둔 이유**: 개장 직후는 변동성과 VI 발동이 잦아 시장가 슬리피지가 가장 나쁘고, 종가 근처는 미체결이 그대로 다음 날로 넘어간다. 10:00이면 마감까지 5시간 이상 남아 시간 예산에 여유가 있다.

**동거 봇과 겹치지 않게 한다.** 같은 호스트의 다른 봇이 주문을 내는 시간대(14:30~15:20)를 피한다.

---

## 4. 기동 스크립트가 하는 일

```python
from vmtrader.broker.kis_broker import KisBroker
from vmtrader.broker.kis.guards import SafetyGuard
from vmtrader.broker.kis.ledger import OrderLedger
from vmtrader.broker.fee_model.korea_fee_model import KoreaStockFeeModel
from vmtrader.data.live_data_handler import LiveDataHandler
from vmtrader.exchange.krx_exchange import KrxExchange
from vmtrader.trading.live import LiveTradingSession

import sys
sys.path.insert(0, 'scripts')
from kis_gateway import KisGateway

gateway = KisGateway.connect(svr='vps')          # 실전은 svr='prod' — 명시해야만 된다
data_handler = LiveDataHandler(gateway)
broker = KisBroker(
    start_dt=pd.Timestamp.now(),
    exchange=KrxExchange(holidays=holidays),      # §5 참조
    data_handler=data_handler,
    client=gateway,
    ledger=OrderLedger('/home/ec2-user/data/vmtrader/ledger.db'),
    fee_model=KoreaStockFeeModel(commission_pct=0.00015, tax_pct=0.0018),
    guard=SafetyGuard(
        kill_switch_path='/home/ec2-user/lock/vmtrader.HALT',
        max_order_value=5000000.0,
        max_orders_per_session=20,
    ),
)
session = LiveTradingSession(broker, qts)         # qts는 백테스트와 동일한 것
session.run_rebalance()                            # 또는 run_end_of_day()
```

**`svr='vps'`가 기본값이다.** 실전 계좌는 `svr='prod'`를 코드에 직접 써야만 닿는다 — 설정 파일이나 환경변수로 조용히 실전에 연결되는 경로는 없다.

---

## 5. 휴장일

KRX 휴장일은 KIS의 **국내휴장일조회**(`chk_holiday`)가 알려준다. 다만 KIS가 **1일 1회 호출을 권고**하므로, 매일 한 번 받아 캐시해 두고 `KrxExchange(holidays=...)`에 넘긴다. 캐시가 없으면 주말만 걸러지고 공휴일에 주문을 시도하게 된다.

---

## 6. 거래를 멈추는 방법

**플래그 파일을 만든다.**

```bash
touch /home/ec2-user/lock/vmtrader.HALT     # 중단
rm    /home/ec2-user/lock/vmtrader.HALT     # 재개
```

파일을 쓴 것이 신호다. 프로세스가 항상 떠 있지 않으므로 시그널이나 소켓으로는 세션 사이에 멈출 수 없고, 파일이면 세션 중이든 사이든 동일하게 동작한다. 엔진은 기동 직후·주문 직전·폴링 반복마다 확인하므로, 가장 오래 무시되는 시간은 브로커 왕복 1회다.

**멈추면 미체결 주문은 취소하지 않는다.** 취소도 주문이라, 종료 경로에서 실패하면 처리할 곳이 없다. 원장에 STALE로 남고 다음 기동이 정리한다.

---

## 7. 실행 후 확인할 것

| 확인 | 방법 | 정상 |
| --- | --- | --- |
| 세션이 돌았는가 | 로그의 `live session:` 줄 | reconcile 요약 → settle 완료 |
| 대조 결과 | `reconcile: … halt=False` | `halt=True`면 **사람이 봐야 한다**(§8) |
| 체결 | 원장 `fills` 테이블 | 주문마다 증분 기록 |
| 미체결 | 원장 `orders`의 `STALE` | 있으면 다음 리밸런싱이 흡수 |
| 자본곡선 | 원장 `equity_curve` | 거래일마다 1행 |

원장은 SQLite이므로 그대로 열어 볼 수 있다.

```bash
sqlite3 -header -column ledger.db \
  "SELECT order_id, symbol, quantity, state, note FROM orders ORDER BY created_at DESC LIMIT 10;"
```

---

## 8. `halt=True`가 나왔을 때

대조가 거래를 멈추는 경우는 둘이고, 둘 다 **엔진이 자기 눈으로 확인할 수 없는 곳에서 그림이 틀렸다**는 뜻이다.

| 상황 | 의미 | 조치 |
| --- | --- | --- |
| **과대 계상** — 로컬 보유 > 브로커 보유 | 없는 주식을 팔려 들 수 있다 | 브로커 잔고를 직접 확인하고, 차이의 출처(수동 매매? 누락된 체결?)를 확인한 뒤 재기동 |
| **주문번호 없는 의도** | 접수 도중 프로세스가 죽었다. 그 주문은 **살아 있을 수도 있다** | HTS/MTS에서 해당 종목의 당일 주문 내역을 직접 확인. 실제로 접수됐다면 잔고 대조로 정리된다 |

두 경우 모두 엔진이 자동으로 정정 주문을 내지 않는다. 잘못된 추정으로 낸 정정 주문이 원래 문제보다 나쁘기 때문이다.

---

## 9. 안전장치 요약

| 장치 | 설정 | 효과 |
| --- | --- | --- |
| 킬스위치 | `kill_switch_path` | 파일 존재 시 전면 중단 |
| 주문 1건 한도 | `max_order_value` | 금액 초과 주문 거부 |
| 세션 주문 수 한도 | `max_orders_per_session` | 폭주 차단 |
| 공매도 차단 | 코드 내장 | 보유 초과 매도는 보유량으로 클램프 |
| 현금 클램프 | 코드 내장 | 가용 현금 초과 매수는 감액 |
| 시간 예산 | `LiveTradingSession(time_budget=...)` | 기본 60분, 장 마감 10분 전 중 이른 쪽 |
| 서버 기본값 | `svr='vps'` | 실전은 명시해야만 닿는다 |

---

## 10. 모의투자 스모크 (A-3·A-4·A-5)

라이브를 처음 붙일 때 한 번 수행한다. 여기까지는 전부 가짜 브로커로 검증됐고, 스모크가 확인하는 것은 **KIS가 실제로 파서의 가정대로 응답하는가**다.

`scripts/kis_smoke.py`는 **모의투자 서버만** 받는다 — `--server prod`는 인자로도 통하지 않는다. 원장과 킬스위치 파일도 운용 경로와 분리된 `out/` 아래를 쓰므로 실제 배치 이력에 섞이지 않는다.

### 순서

```bash
# 1) 읽기 전용 — 인증·잔고·시세·휴장일·일봉이 파싱되는지. 주문 없음.
python scripts/kis_smoke.py --stage connect

# 2) A-3 — 실제 리밸런싱 1회. 장중(09:00~15:30)에만 동작한다.
python scripts/kis_smoke.py --stage rebalance --place-orders --budget 1000000

# 3) A-4 — 재기동 복구. 잔고로 재구성하고 이중 반영이 없는지.
python scripts/kis_smoke.py --stage restart

# 4) A-5 — 안전장치 실증. 주문을 내지 않는다.
python scripts/kis_smoke.py --stage safety
```

`--place-orders`가 없으면 2단계는 **인증 전에** 거부된다. 아무 생각 없이 실행해서 거래되는 일이 없도록 한 것이다.

### 무엇을 기록할 것인가

스모크의 산출물은 통과/실패만이 아니라 **미확인 항목의 실측값**이다. 다음을 로그에서 확인해 스펙 §8과 해당 이슈에 적는다.

| 관찰 | 어디에 |
| --- | --- |
| 당일 매수분이 `hldg_qty`에 즉시 반영되는가 (2단계의 `MISMATCH` 출력) | 스펙 §8, 설계 §10.5-⑥ |
| 동거 봇과 동시간대에 `EGW00201`이 나는가 | [#31](https://github.com/visualmoney/vm-quant-trader/issues/31) |
| 수정주가가 백테스트 CSV의 조정과 일치하는가 | [ADR-0012](../dev/adr/0012-signal-history-from-venue.md) 결과 절 |

4단계는 **원장에 킬스위치 거부 기록을 남긴다.** 이것이 [ADR-0013](../dev/adr/0013-real-money-promotion-criteria.md)의 `kill-switch-exercised` 기준을 충족하는 증거이므로, 스모크용 원장이 아니라 **운용 원장으로도 한 번** 수행해 두는 편이 낫다.

---

## 11. 실전 계좌로 옮기려면

실전 전환은 이 프로젝트에서 **되돌릴 수 없는 유일한 행동**이다. 기준은 [ADR-0013](../dev/adr/0013-real-money-promotion-criteria.md)에 있고, 자동으로 확인할 수 있는 절반은 도구가 판정한다.

```bash
python scripts/promotion_check.py /home/ec2-user/data/vmtrader/ledger.db
```

원장을 **읽기 전용**으로 열어 7개 기준(운용 일수, 실제 접수·체결 여부, 미해결 고아 의도, STALE 비율, 멱등키 중복, 킬스위치 발동 이력)을 판정하고, 사람만 확인할 수 있는 5개 항목을 함께 출력한다. **자동 통과는 승인이 아니다** — 수동 항목이 남아 있다.

특히 토큰 발급 주체 항목을 넘기지 말 것. KIS는 동일 앱키의 **60초 내 재발급을 거부**하므로, 같은 앱키를 쓰는 다른 봇이 있다면 이 엔진이 토큰을 새로 발급하는 순간 **그쪽 토큰이 깨진다**.

---

## 12. 아직 하지 않은 것

- **실전(`prod`) 운용** — 인수 기준은 모의투자까지만 요구한다. 승격 기준은 §11.
- **지정가·정정·취소 주문** — 시장가만 지원한다. 미체결은 취소 대신 시간 예산으로 다룬다.
- **텔레그램 대화형 운용** — 설계는 있으나([ADR-0010](../dev/adr/0010-telegram-gateway-plane.md)) 미구현이다.
- **다중 계좌·다중 전략** — 단일 프로세스·단일 전략 전제다.
