# VMTrader 문서

문서는 독자에 따라 두 갈래로 나뉜다.

## `user/` — 전략 개발자·운용자용

VMTrader를 **사용해** 전략을 만들거나 실제로 굴리는 사람을 위한 문서. 엔진 내부 구현을 몰라도 읽을 수 있어야 한다.

설치, 데이터 준비, 백테스트 조립, 알파모델 작성, 결과 해석, 자주 밟는 함정.

| 문서 | 상태 | 요약 |
| --- | --- | --- |
| [kis-live-operations.md](user/kis-live-operations.md) | **모의투자 기준** | KIS 라이브 운용 — cron 두 줄, 휴장일 캐시, 킬스위치, 실행 후 확인 항목, 대조가 거래를 멈췄을 때의 조치 |

## 진행 중인 작업은 어디에 있는가

계획과 결정은 문서에, **추적은 GitHub 이슈**에 있다. 둘의 역할이 겹치지 않도록 정본을 한쪽에만 둔다.

| 라벨 | 무엇 | 정본 |
| --- | --- | --- |
| `phase` | 설계안 §9의 단계 | [설계안 §9](dev/spec/kis-broker-design.md) |
| `decision-gate` | 착수를 막는 미결 결정 | [설계안 §11](dev/spec/kis-broker-design.md) |
| `unknown` | 관측으로만 풀리는 미확인 사항 | [스펙 §8](dev/spec/kis-broker.md) |
| `blocked` | 미해소 게이트가 남은 작업 | — |

이슈는 정본을 **참조만** 하고 복사하지 않는다. 이슈 템플릿은 `.github/ISSUE_TEMPLATE/`에 있다.

## `dev/` — 엔진 기여자용

VMTrader 자체를 **수정하는** 사람을 위한 문서. 계약, 불변식, 테스트 정책, 기술부채.

### `dev/spec/` — 요구사항 명세와 설계안

구현 **이전**에 무엇을 만들 것인지 합의하는 문서. 코드가 들어오면 함께 갱신한다.

| 문서 | 상태 | 요약 |
| --- | --- | --- |
| [kis-broker.md](dev/spec/kis-broker.md) | **초안 · 미구현** | 한국투자증권 라이브 브로커 연동 요구사항 — 범위/비범위, 기능요구 26건(FR), 비기능요구 10건(NFR), 제약 15건(C), 인수기준 5건(A) |
| [kis-broker-design.md](dev/spec/kis-broker-design.md) | **초안 · 미구현** | 위 스펙에 대한 설계안 — 라이브를 가로막는 현행 구조 7종, 신규 모듈 13개, 인터페이스 매핑, 실패 모드 17종, 시간 모델·비동기 체결 재검토(§10), 3단계 구현 계획 |

### `dev/adr/` — 설계 결정 기록

되돌리기 비싼 **결정 하나**를 맥락·대안·근거·결과로 남긴다. 결정이 뒤집히면 새 ADR을 쓰고 기존 문서는 `Superseded`로 표시한다 — 본문을 고쳐 쓰지 않는다.

| ADR | 상태 | 결정 |
| --- | --- | --- |
| [0001](dev/adr/0001-portfolio-source-of-truth.md) | 제안됨 | 라이브 회계의 진실원본은 로컬 `Portfolio`, 브로커 잔고가 이를 정정한다 |
| [0002](dev/adr/0002-blocking-fill-polling.md) | **폐기됨** | ~~체결 폴링은 `submit_order()` 안에서 블로킹한다~~ — [0006](dev/adr/0006-decouple-submit-from-fill.md)이 대체 |
| [0003](dev/adr/0003-port-lab-code.md) | 제안됨 | `vm-quant-lab` 코드는 의존이 아니라 이식한다 |
| [0004](dev/adr/0004-promote-update-to-abc.md) | **채택됨** | `update(dt)`를 `Broker` ABC의 추상 메서드로 승격한다 (**파괴적 변경**) |
| [0005](dev/adr/0005-sell-side-transaction-tax.md) | **채택됨** | 매도 전용 증권거래세는 `quantity` 부호로 판정한다 |
| [0006](dev/adr/0006-decouple-submit-from-fill.md) | **채택됨** | 주문 접수와 체결 반영을 분리한다 — `submit_order()`는 접수만, 정산 단계가 시간 예산 안에서 체결을 수집한다 (0002 대체) |
| [0007](dev/adr/0007-engine-clock-timestamps.md) | **채택됨** | 엔진 회계의 타임스탬프는 단조 증가하는 엔진 시계를 쓴다 — 브로커 체결시각은 원장에만 기록한다 |
| [0008](dev/adr/0008-task-queue-fill-pump.md) | **채택됨** | 체결 수집의 실행 기반으로 단일 FIFO 태스크 큐 워커(smtm `worker.py` 이식)를 채택한다 — `Portfolio` 변경은 메인 스레드 전용 |
| [0009](dev/adr/0009-cron-oneshot-live-session.md) | **채택됨** | `LiveTradingSession`은 상주 프로세스가 아니라 cron 단발이다 — 기동 1회 = 사이클 1회, 자본곡선은 장 마감 후 별도 기동이 기록한다 |
| [0010](dev/adr/0010-telegram-gateway-plane.md) | 제안됨 | 대화형 운용(텔레그램 조회·킬스위치)은 분리 평면의 경량 게이트웨이 데몬이 제공한다 — 트레이딩 평면(0009 cron 단발)은 무변경 |
| [0011](dev/adr/0011-package-rename-vmtrader.md) | **채택됨** | 패키지·배포명을 `qstrader`에서 `vmtrader`로 개명한다 — 업스트림은 휴면(45커밋 앞섬), 배포 메타데이터 정정과 함께 시행 |
| [0012](dev/adr/0012-signal-history-from-venue.md) | **채택됨** | 신호용 과거 시세는 브로커 일봉 API에서 받고, cron 단발이라 **매 기동마다 신호 버퍼를 워밍업**한다 |

### `dev/reports/` — 시점별 조사 보고서

`dev/` 바로 아래의 문서는 코드와 함께 갱신되는 **살아있는 문서**다.
반면 `reports/`는 특정 시점의 **스냅샷**이며 갱신하지 않는다. 낡은 조사 결과가 현재 명세처럼 읽히는 것을 막기 위해 분리한다.

파일명 규칙: `{yyyymmdd}-{nn}-{topic}.md` — 같은 날 여러 건이면 `nn`을 증가시킨다.

보고서 본문은 갱신하지 않으므로, 이후 조치는 아래 표의 **상태** 열에서 추적한다. 보고서가 지적한 결함이 이미 수정되었는지를 본문을 열어 보지 않고 알 수 있어야 하기 때문이다. 각 보고서 머리말에도 같은 내용의 후속 안내가 한 줄 붙는다.

| 보고서 | 상태 | 요약 |
| --- | --- | --- |
| [20260818-01-codebase-comprehension-strategy.md](dev/reports/20260818-01-codebase-comprehension-strategy.md) | 유효 · 일부 해소 | 아키텍처 지도, 4단계 학습 경로, **실습 과제 10종(T1~T10)**, 확장 지점 15개, 커버리지 공백 및 기술부채 지도 (기준: `b94c6c0` / v0.3.10). §8-1은 v0.3.12에서, §8-7의 일부는 v0.3.13에서 해소. T5~T10 수행 완료. §8-5·§8-7의 심각도 판단은 보고서 06의 실측으로 뒤집혔다 |
| [20260818-02-transaction-cost-consolidation.md](dev/reports/20260818-02-transaction-cost-consolidation.md) | **v0.3.13 구현 완료** | `Transaction.cost_with_commission`를 `Portfolio`가 사용하도록 통합하는 구현 준비서 — 동치성 분석, 변경 설계, 테스트 계획 |
| [20260818-03-performance-module-defects.md](dev/reports/20260818-03-performance-module-defects.md) | **v0.3.13 수정 완료** | `statistics/performance.py`의 **결함 2건** — 발생하지 않는 `ValueError`, 최대 낙폭 과소 보고(실측 최대 5.44%p) |
| [20260818-04-execution-and-cost-layer-limits.md](dev/reports/20260818-04-execution-and-cost-layer-limits.md) | **부분 수정** | T7 실험 — 사이저의 **수수료 과대 추정**(성과 손실의 22.2%)과 실행 알고리즘 주입 지점 부재는 v0.3.13에서 수정. **시간 분할 실행 불가(L1)는 구조적 한계로 남음** |
| [20260818-05-data-source-contract.md](dev/reports/20260818-05-data-source-contract.md) | **v0.3.13 수정 완료** | T8 실험 — `DataSource` ABC 신설과 인메모리 구현체 추가, 역추출한 계약, `adjusted` 인자 불일치 해소, **시작일 이전 조회가 미래 가격을 반환하던 룩어헤드 결함** |
| [20260818-06-safety-net-and-profiling.md](dev/reports/20260818-06-safety-net-and-profiling.md) | **권고 1~3 적용됨** | T9·T10 — 변형 주입으로 측정한 e2e 안전망의 검출 범위(유효 12건 중 5건), **e2e가 전면적 룩어헤드를 통과시키는 이유**, 그리고 §8-5·§8-7 추정을 뒤집은 프로파일링 실측 |
