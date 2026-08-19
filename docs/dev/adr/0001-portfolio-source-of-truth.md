# ADR-0001: 진실원본은 로컬 `Portfolio`, 브로커 잔고가 이를 정정한다

| 항목 | 내용 |
| --- | --- |
| 상태 | **제안됨 (Proposed)** — 미구현 |
| 작성일 | 2026-08-19 |
| 맥락 | [spec/kis-broker-design.md](../spec/kis-broker-design.md) §3, §5 |
| 관련 요구 | FR-5·FR-7·FR-8, NFR-1 ([spec/kis-broker.md](../spec/kis-broker.md)) |

## 맥락

라이브 브로커에는 상태가 두 벌 존재한다 — 엔진의 로컬 `Portfolio`와 KIS 계좌의 실제 잔고. 어느 쪽이 회계의 기준인지 정하지 않으면 두 상태가 조용히 발산한다.

`OrderSizer`는 리밸런싱 1회에 `get_portfolio_total_equity`(`long_short.py:73`)와 `get_portfolio_as_dict`(`:114`)를 각각 호출하고, `BacktestTradingSession._update_equity_curve`는 매 틱 `get_account_total_equity`를 호출한다(`backtest.py:342`).

## 결정

**실행 중 회계의 1차 진실원본은 로컬 `Portfolio`다.** 브로커 잔고는 두 곳에서만 쓴다.

1. **기동 시 시딩** — `inquire_balance`로 `Portfolio`를 재구성한다 (FR-7).
2. **주기적 대조·정정** — 불일치 시 **브로커가 이긴다** (FR-8).

## 검토한 대안

| 대안 | 내용 |
| --- | --- |
| 대안 1 | 브로커 잔고를 매번 조회해 그것만 쓴다 (`get_portfolio_as_dict`가 매 호출 API 조회) |
| 대안 2 | 로컬만 쓰고 대조하지 않는다 |

## 근거

**대안 1이 막히는 이유는 두 가지다.**

- **레이트리밋**: 위 호출 빈도를 그대로 API 호출로 바꾸면 NFR-1에 즉시 걸린다.
- **계약 불충족**: KIS 잔고 응답은 `unrealised_pnl`/`realised_pnl`을 주지 않는다. 이들은 `Position`이 계산하는 값이다(`position.py:249`, `:281`, `:295`). FR-5가 요구하는 5개 필드를 브로커 응답만으로는 만들 수 없다.

**대안 2**는 폴링 타임아웃(F2)과 프로세스 사망(F7·F8)으로 반드시 발산한다.

## 결과

- 상태가 둘이므로 **수렴 규칙이 필요하다** — 설계안 §7의 F7~F10이 그 규칙이다.
- 로컬이 실제보다 많이 보유했다고 믿는 경우(과대 계상)는 없는 주식을 팔려 드는 것이므로 **매매를 중단**한다(F9). 반대 방향(미추적 포지션)은 수동 매매일 수 있으므로 경보만 낸다(F10).
- lab의 `reconcile.py`도 동일한 결론에 도달했고, 모듈 docstring이 *"불일치 시 브로커가 진실"*을 규칙으로 명시한다.
