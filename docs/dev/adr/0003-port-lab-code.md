# ADR-0003: `vm-quant-lab` 코드는 의존이 아니라 이식(port)한다

| 항목 | 내용 |
| --- | --- |
| 상태 | **제안됨 (Proposed)** — 미구현 |
| 작성일 | 2026-08-19 |
| 맥락 | [spec/kis-broker-design.md](../spec/kis-broker-design.md) §3.2 |
| 관련 요구 | NFR-1·NFR-2·NFR-3 ([spec/kis-broker.md](../spec/kis-broker.md)) |

## 맥락

같은 사용자의 별도 저장소 `vm-quant-lab`이 KIS 연동을 실계좌에서 가동 중이다. 파서(`adapters/live/kis.py`), 원장(`ledger.py`), 대조(`reconcile.py`), 가드(`guards.py`), 레이트리밋 재시도(`brokers/kis/ratelimit.py`)가 이미 존재한다. 이 자산을 어떻게 가져올 것인가.

## 결정

**복사·번역해 이식한다.** vmtrader 규약(4-space 들여쓰기, numpy-style docstring, 영문 코드 주석)에 맞추어 옮기고, **lab 패키지를 의존성으로 추가하지 않는다.**

## 검토한 대안

| 대안 | 내용 |
| --- | --- |
| 대안 1 | `vmquant.adapters.live`를 pip 의존으로 추가 |
| 대안 2 | 스펙만 참고해 백지 재구현 |

## 근거

**대안 1 — 도메인 모델이 다르다.** lab은 `Fill`/`Side`/`TargetWeights`/`MarketSlice`(`vmquant.core.contracts`)를 쓰고 vmtrader는 `Order`/`Transaction`/`Position`을 쓴다. lab 어댑터를 그대로 쓰면 두 모델 사이 변환 계층이 생겨 **오히려 코드가 늘어난다.** 게다가 lab은 별개 라이프사이클의 사유 저장소라 vmtrader 릴리스가 거기 묶인다.

**대안 2 — 실계좌에서 이미 밟은 함정을 버린다.** 문서를 읽어서는 나오지 않고 실패해 봐야 알 수 있는 지식이 최소 세 가지 있다.

| 함정 | 내용 |
| --- | --- |
| `order_cash`는 비멱등 | 재시도하면 중복 주문이 된다 (NFR-1) |
| 조회 직후 주문은 실패한다 | vps 초당 제한에 걸려 접수 자체가 거부된다 → 주문 전 정착 대기 필요 |
| 체결조회 빈 응답의 모호성 | 정상 미체결과 레이트리밋을 구분할 수 없다 → 재시도 금지 (설계안 F4) |

## 결과

- **코드 중복**이 생긴다. lab에서 버그가 고쳐져도 자동 전파되지 않는다.
- 완화책: 이식한 모듈의 docstring에 **출처 파일 경로와 이식 시점**을 명기하고, `docs/dev/`에 대응표를 유지한다.
- 반대급부로 vmtrader는 KIS 연동에 대해 **자기완결적**이 된다 — OTA도, lab도 설치 없이 전 테스트가 통과한다 (NFR-2).
