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

## 무엇을 어디에 쓰는가

위에서부터 읽고 **처음 "예"에서 멈춘다.**

| # | 쓰려는 것 | 어디에 | 그 폴더의 규칙 |
| --- | --- | --- | --- |
| 1 | 되돌리기 비싼 선택 하나와, 대안을 기각한 이유 | `dev/adr/{nnnn}-{topic}.md` | 뒤집히면 **새 ADR + `Superseded`**. 본문은 고치지 않는다 |
| 2 | 특정 시점에 재거나 조사한 결과 (수치·실측·"기준: vX.Y.Z") | `dev/reports/{yyyymmdd}-{nn}-{topic}.md` | **갱신하지 않는다.** 후속은 아래 색인의 상태 열 |
| 3 | 아직 만들지 않은 것에 대한 합의 | `dev/spec/{topic}.md` + `{topic}-design.md` | 코드가 들어오면 함께 갱신 |
| 4 | 코드가 바뀌면 같이 바뀌어야 하는 규칙·계약·현황 | `dev/` 직하 flat 파일 | **틀리면 고쳐 쓴다.** 측정값은 담지 않는다 |
| 5 | 엔진 내부를 몰라도 읽어야 하는 사람이 독자 | `user/{topic}.md` | — |
| 6 | "언제까지 누가 무엇을" | **문서가 아니라 GitHub 이슈** | 정본을 참조만 하고 복사하지 않는다 |

애매하면:

- **ADR인가 spec인가** — 결정 하나면 ADR, 요구 여러 건이면 spec. ADR이 80줄을 넘기 시작하면 spec을 쓸 신호다.
- **spec인가 report인가** — 미래형("~한다")이면 spec, 과거형("~였다")이면 report.
- **`dev/` 직하인가 report인가** — 본문에 숫자가 있으면 report.

## `dev/` — 엔진 기여자용

VMTrader 자체를 **수정하는** 사람을 위한 문서.

| 무엇을 찾는가 | 어디에 |
| --- | --- |
| 무엇이 어디에 있는가 (진입점) | [`dev/architecture-map.md`](dev/architecture-map.md) |
| 왜 이렇게 만들었는가 (되돌리기 비싼 결정) | [`dev/adr/`](#devadr--설계-결정-기록) |
| 무엇을 만들 것인가 (요구와 설계) | [`dev/spec/`](#devspec--요구사항-명세와-설계안) |
| 무엇이 검증을 강제하는가 (테스트 정책) | [`dev/testing.md`](dev/testing.md) |
| 그때 무엇을 재고 무엇을 발견했는가 | [`dev/reports/`](#devreports--시점별-조사-보고서) |

**읽는 순서**는 [architecture-map.md](dev/architecture-map.md) §1 → ADR → [testing.md](dev/testing.md)다.
[architecture-principles.md](dev/architecture-principles.md)는 참조용이지 필독이 아니다.

### `dev/` 직하 — 살아있는 문서

코드와 **같은 커밋에서** 갱신한다. 틀린 절은 지우고 고쳐 쓴다 — 폐기 표기를 남기는 `adr/`, 본문을 갱신하지 않는 `reports/`와 정반대다. 그래서 이 표의 상태 열에는 **수치가 들어가지 않는다.**

| 문서 | 성격 | 요약 |
| --- | --- | --- |
| [architecture-map.md](dev/architecture-map.md) | **현황 · 진입점** | 이 저장소가 실제로 어떻게 생겼는가 — 30초 요약, 두 평면의 실행 순서와 합류점(`qts(dt)`), 모듈 지도, 확장점, **§5 계약 ↔ 테스트 링크 표**, **§6 `architecture-principles.md` 적용 검토** |
| [architecture-principles.md](dev/architecture-principles.md) | **잣대 · 일반 참조 모델** | 기반원칙 2개와 설계 결정 15축(D1~D15), 안티패턴 카탈로그, 도입 체크리스트. **이 저장소의 규칙이 아니다** — 일반 원리를 서술한 잣대이며, 실제 적용 상태의 정본은 [architecture-map.md §6](dev/architecture-map.md)이다. 일부 축은 전제가 달라 **의도적으로 불채택**했다 |
| [testing.md](dev/testing.md) | **정책 · 수치 없음** | 무엇이 테스트로 강제되고 있으며 왜 그것이 강제되는가 — 테스트 계층과 배치 규칙, 네트워크·SDK 무의존(AST import 경계), 주입 규약(가짜 클라이언트·시계·`sleep`), 스레드 경계, 커버리지 정책과 **의도적 예외 3건**, e2e 안전망의 한계 |

`dev/` 직하의 flat 파일은 **5개를 넘지 않는다.** 넘을 것 같으면 폴더를 파고, 폴더를 먼저 파고 채울 것을 찾지 않는다.

### `dev/spec/` — 요구사항 명세와 설계안

구현 **이전**에 무엇을 만들 것인지 합의하는 문서. 코드가 들어오면 함께 갱신한다.

한 주제는 **두 파일로 짝을 이룬다** — `{topic}.md`가 *무엇을·왜*(범위, FR/NFR, 제약, 인수기준)를, `{topic}-design.md`가 *어떻게*(모듈, 시퀀스, 실패 모드, 구현 단계)를 맡는다. **폴더는 나누지 않는다.** ADR 다수가 두 문서를 머리 표에서 한 쌍으로 인용하고 있고, 어느 문단이 요구이고 어느 문단이 설계인지는 쓰는 시점에 늘 갈리지 않기 때문이다. 설계안이 너무 커지면 **폴더가 아니라 파일을 쪼갠다**(`{topic}-design-{aspect}.md`).

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
| [0013](dev/adr/0013-real-money-promotion-criteria.md) | **채택됨** | 실전 승격은 자동 검증 7항 + 수동 확인 5항을 통과해야 한다 — 자동분은 원장으로 기계가 판정한다 |
| [0014](dev/adr/0014-holiday-calendar-from-real-account.md) | **채택됨** | 휴장일은 실전 계좌로 1일 1회 조회해 파일로 캐시한다 — 모의 서버는 이 엔드포인트를 제공하지 않으며, 조회 프로세스는 자기 `HOME`으로 토큰을 격리한다 |
| [0015](dev/adr/0015-venue-neutral-live-package.md) | **채택됨** | 라이브 인프라를 벤더 중립 `broker/live/`와 벤더 고유 `broker/kis/`로 분리하고 `KisBroker`를 `LiveBroker`로 개명한다 (**파괴적 변경**) — 두 번째 증권사는 게이트웨이 파일 하나로 붙는다 |
| [0016](dev/adr/0016-drop-funding-from-broker-abc.md) | **채택됨** | 자금 이체 4종을 `Broker` ABC에서 제외한다 (**파괴적 변경**, 추상 13 → 9) — 시뮬레이터에만 의미가 있고 라이브에서는 거절만 하던 계약 |
| [0017](dev/adr/0017-paper-is-a-mode-not-a-broker.md) | **채택됨** | 모의투자는 브로커가 아니라 **모드**다 — `PaperBroker`를 만들지 않고 `BrokerClient`가 `venue`/`mode`를 선언하며, 원장이 배포 신원을 기억하고 다른 배포를 거부한다. ETF 증권거래세 면제도 함께 |

### `dev/reports/` — 시점별 조사 보고서

`reports/`를 제외한 `dev/`의 모든 문서는 코드와 함께 갱신되는 **살아있는 문서**다.
반면 `reports/`는 특정 시점의 **스냅샷**이며 갱신하지 않는다. 낡은 조사 결과가 현재 명세처럼 읽히는 것을 막기 위해 분리한다.

파일명 규칙: `{yyyymmdd}-{nn}-{topic}.md` — 같은 날 여러 건이면 `nn`을 증가시킨다.

보고서 본문은 갱신하지 않으므로, 이후 조치는 아래 표의 **상태** 열에서 추적한다. 보고서가 지적한 결함이 이미 수정되었는지를 본문을 열어 보지 않고 알 수 있어야 하기 때문이다. 각 보고서 머리말에도 같은 내용의 후속 안내가 한 줄 붙는다.

| 보고서 | 상태 | 요약 |
| --- | --- | --- |
| [20260818-01-codebase-comprehension-strategy.md](dev/reports/20260818-01-codebase-comprehension-strategy.md) | **대체됨 — 20260823-01** | 아키텍처 지도, 4단계 학습 경로, **실습 과제 10종(T1~T10)**, 확장 지점 15개, 커버리지 공백 및 기술부채 지도 (기준: `b94c6c0` / v0.3.10). §8-1은 v0.3.12에서, §8-7의 일부는 v0.3.13에서 해소. T5~T10 수행 완료. §8-5·§8-7의 심각도 판단은 보고서 06의 실측으로 뒤집혔다 |
| [20260818-02-transaction-cost-consolidation.md](dev/reports/20260818-02-transaction-cost-consolidation.md) | **v0.3.13 구현 완료** | `Transaction.cost_with_commission`를 `Portfolio`가 사용하도록 통합하는 구현 준비서 — 동치성 분석, 변경 설계, 테스트 계획 |
| [20260818-03-performance-module-defects.md](dev/reports/20260818-03-performance-module-defects.md) | **v0.3.13 수정 완료** | `statistics/performance.py`의 **결함 2건** — 발생하지 않는 `ValueError`, 최대 낙폭 과소 보고(실측 최대 5.44%p) |
| [20260818-04-execution-and-cost-layer-limits.md](dev/reports/20260818-04-execution-and-cost-layer-limits.md) | **부분 수정** | T7 실험 — 사이저의 **수수료 과대 추정**(성과 손실의 22.2%)과 실행 알고리즘 주입 지점 부재는 v0.3.13에서 수정. **시간 분할 실행 불가(L1)는 구조적 한계로 남음** |
| [20260818-05-data-source-contract.md](dev/reports/20260818-05-data-source-contract.md) | **v0.3.13 수정 완료** | T8 실험 — `DataSource` ABC 신설과 인메모리 구현체 추가, 역추출한 계약, `adjusted` 인자 불일치 해소, **시작일 이전 조회가 미래 가격을 반환하던 룩어헤드 결함** |
| [20260818-06-safety-net-and-profiling.md](dev/reports/20260818-06-safety-net-and-profiling.md) | **권고 1~3 적용됨** | T9·T10 — 변형 주입으로 측정한 e2e 안전망의 검출 범위(유효 12건 중 5건), **e2e가 전면적 룩어헤드를 통과시키는 이유**, 그리고 §8-5·§8-7 추정을 뒤집은 프로파일링 실측 |
| [20260822-01-worker-lifecycle-and-shutdown.md](dev/reports/20260822-01-worker-lifecycle-and-shutdown.md) | 유효 · **F-5·F-1② 조치** | smtm 대조 — 정산 워커가 **non-daemon인 이유**와 `SIGINT`/`SIGTERM` 수신 시의 실측 동작(exit 130/143), 사이클이 10~20분일 때·**텔레그램이 리밸런싱을 강제할 때**의 재검토, cron 대 systemd. 소견 9건 중 **위험 3건**(무한 hang, 상주 전환 시 리셋 지점 소실, 자동 재시작의 이중 주문). F-5(죽은 코드)와 F-1②(`stop()` 유한 timeout + 초과 로그)는 조치 완료, F-9(`task_done()` 위치가 배리어 의미를 정한다)는 smtm 이력 추적에서 추가. §11은 주문 처리 7단계 중 워커가 놓이는 칸(5·6)과 나머지를 넘기지 말아야 하는 이유, §12는 단일 파일 봇과의 대조로 본 **기록의 시점과 복잡도의 출처** |
| [20260823-01-codebase-comprehension-strategy.md](dev/reports/20260823-01-codebase-comprehension-strategy.md) | **유효 · v0.3.17 기준으로 갱신됨** | **20260818-01의 대체판** — 백테스트·라이브 **2평면** 아키텍처, ADR을 먼저 읽는 5단계 학습 경로, 실습 과제 11종(B1~B5·**L1~L5**·C1), 확장 지점 ABC 16 + **`BrokerClient` Protocol**. §5가 **`Broker` 인터페이스 리뷰** — 시뮬레이션·모의투자·KIS 실전은 동작하고 **DB증권은 붙지 않는다**. venue 추상화(6메서드)는 이미 중립이며 DBS API 6개 중 5개가 그대로 대응하나, 중립 코드 6모듈이 `broker/kis/` 이름 아래 있고 코어가 그것을 import한다(소견 B-1~B-5, 권고 R1~R8). §5.6은 **모의투자를 브로커가 아니라 모드로 다루는 결정**(ADR-0017)과 ETF 증권거래세 면제. R1~R3·자금이체 제거는 **적용됨**([ADR-0015](dev/adr/0015-venue-neutral-live-package.md)·[0016](dev/adr/0016-drop-funding-from-broker-abc.md)·[0017](dev/adr/0017-paper-is-a-mode-not-a-broker.md)), R4·R6·R7·R8 미해소. 실측: 734 케이스 / 83.71% (기준: v0.3.17). **§2·§3·§4·§8은 [architecture-map.md](dev/architecture-map.md)로 승격됐고 현행 서술의 정본은 그쪽이다** — 이 보고서는 v0.3.17 시점에 고정된다. §8.1이 지적한 "의도적 커버리지 예외가 어디에도 적혀 있지 않다"는 부채는 [testing.md §5.1](dev/testing.md)로 해소 |
| [20260826-01-two-actor-phase-1-readiness.md](dev/reports/20260826-01-two-actor-phase-1-readiness.md) | 유효 · **B1~B4 조치** | Phase 0 완료 직후의 독립 아키텍처 검토 — **Phase 0은 Actor 2만 만들었고 Actor 1(돈을 소유한 절반)은 만들지 않았다.** 소견 15건 중 **진입 차단 4건**: 실행기의 outbox가 `qts.size_and_submit`에 묶여 **철회된 결정 5가 의존성 주입을 타고 재발**(B1), 모드가 세 사실인데 가드는 둘(B2), 스레드 모드에서 `settle()`이 리밸런스보다 먼저 돌아 **리밸런스가 조용히 일어나지 않음**(B3), cron 단발과 상주가 **다른 메인 스레드 구조**를 요구(B4). 주요 6건 — 결정 8의 자가복구 논거가 6종 중 1종만 덮고 **결정 8과 8-a가 결정 12 아래에서 모순**(M1), 결정 3 표·§1-3 락 인벤토리가 사실과 다르며 게이트웨이 `_CALL_LOCK`이 **느린 전략으로 주문 제출을 멈출 수 있음**(M2), §3 소유권표가 `data_handler`·벤더 클라이언트 등 **공유 인프라 4종을 빠뜨림**(M3), 오류 전파 미정의로 두 모드가 실패에서 비동형(M4), `Thread` 이름공간 위험 3건(M5), 훅 2/3 미배선·토픽 8/10 생산자 없음(M6). 차단·주요 소견의 사실 주장은 전부 재현·확인함(§2). §6에 **Phase 1a/1b 분할 계획** (기준: `16b9d0f` / 796 passed) |
| [20260826-02-stop-and-shutdown-protocol.md](dev/reports/20260826-02-stop-and-shutdown-protocol.md) | 유효 · **S2·S6·S13 조치** | 중단·종료 프로토콜 전용 검토 — **킬스위치를 당겨도 조용히 성공으로 끝나고, 그 대가로 미체결 주문의 복구 고리가 영구히 끊긴다.** 중단 메커니즘이 넷이 아니라 **일곱**이며 그중 둘(`trading_halted` 래치, `KillSwitchEngaged` 재전파)은 설계 문서가 중단으로 인식조차 하지 않는다. 차단 5건 — Actor 1에 stop이 없어 배리어가 관습에 그침(S1), 사이클에 `finally`가 없고 `stop()`이 전역이 아니라 넣을 수도 없음(S2), `drain()`이 **킬스위치를 삼킴**(S3), 수행 0건에 `traded=True`(S4), 전략 예산이 간섭을 제한 못 함(S5). 주요 — **킬스위치 정지가 살아 있는 주문을 `STALE`로 종결해 `reconcile()`이 영영 재조회하지 않으며 운영 문서 §6과 정반대**(S6), 선행 보고서의 F-2 미적용으로 `flock`을 쥔 **조용한 hang**이 남아 있음(S8). §8은 **`SIGINT` 등록 질문에 대한 답** — 메인 스레드 확인은 필수이나 **핸들러가 `Mailbox.close()`를 부르면 데드락**(실증, exit 124)이므로 플래그만 세워야 하고, 등록 위치는 생성자가 아니라 진입점이며, 실익은 `SIGTERM`에 있다. `threading.Event`는 1a에 불필요하고 1b에 정확히 하나. §9에 스레드별 권고 프로토콜. 차단·주요의 사실 주장은 전부 재현·확인함(§2) (기준: `25f028b` / 813 passed) |
