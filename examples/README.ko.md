# QSTrader 예제

*Read this in [English](README.md).*

예제 백테스트 5개를 난이도 순으로 배열했습니다. 각 예제는 `BacktestTradingSession`을 구성해 실행하고 tearsheet을 출력하는 독립 실행 스크립트이며, **직전 예제에 개념을 하나씩만 더하도록** 짜여 있습니다. 순서대로 읽으면 QSTrader API를 훑는 안내서 역할을 합니다.

설치, 데이터 다운로드, tearsheet 옵션은 메인 README의 [Running the Examples](../README.md#running-the-examples) 절을 참고하세요. 이 문서는 각 예제가 **무엇을 하는지**를 다룹니다.

## 목차

1. [시작하기 전에](#시작하기-전에)
2. [권장 실행 순서](#권장-실행-순서)
3. 예제 (쉬운 것부터):
   1. [`buy_and_hold.py`](#1-buy_and_holdpy) — 가장 단순한 백테스트
   2. [`sixty_forty.py`](#2-sixty_fortypy) — 리밸런싱과 벤치마크
   3. [`sixty_forty_fees.py`](#3-sixty_forty_feespy) — 거래 비용
   4. [`long_short.py`](#4-long_shortpy) — 공매도와 레버리지
   5. [`momentum_taa.py`](#5-momentum_taapy) — 시그널과 커스텀 알파 모델
4. [지원 모듈](#지원-모듈)
5. [공통 옵션](#공통-옵션)
6. [직접 만들어 보기](#직접-만들어-보기)

## 시작하기 전에

모든 예제는 `QSTRADER_CSV_DATA_DIR`(미설정 시 현재 디렉토리)에서 `<심볼>.csv` 가격 데이터를 읽습니다. 필요한 데이터를 받은 뒤 예제를 실행하며, 둘 다 **저장소 루트에서** 실행합니다.

```bash
python examples/download_data.py --data SPY,AGG
python examples/sixty_forty.py
```

별도 언급이 없으면 5개 모두 동일한 기본값을 씁니다. 초기 자본 **$1,000,000**, tearsheet은 창을 띄우지 않고 `out/tearsheet-<예제명>-<yyyymmdd-hhmmss>.png`로 저장됩니다. 창으로 보려면 `--show`를 붙이세요.

아래에 나오는 성과 수치는 **근사치**입니다. 배당 조정가 기준이고 Yahoo! Finance가 이를 소급 수정하기 때문에, 직접 실행하시면 근사한 값이 나오되 정확히 일치하지는 않습니다.

## 권장 실행 순서

표를 위에서 아래로 따라가시면 됩니다. 각 행은 위 행들의 개념을 이미 안다고 가정하며, 필요한 데이터도 조금씩 누적되도록 배치했습니다.

| # | 예제 | 새로 등장하는 개념 | 리밸런싱 | 받을 심볼 |
| - | ---- | ----------------- | -------- | --------- |
| 1 | [`buy_and_hold.py`](#1-buy_and_holdpy) | 백테스트의 4가지 필수 구성요소 | 없음 | `GLD` |
| 2 | [`sixty_forty.py`](#2-sixty_fortypy) | 리밸런싱, 벤치마크 비교 | 월말 | `SPY,AGG` |
| 3 | [`sixty_forty_fees.py`](#3-sixty_forty_feespy) | 수수료 모델 | 월말 | — 위와 동일 |
| 4 | [`long_short.py`](#4-long_shortpy) | 공매도 포지션, 총 레버리지 | 월말 | `TLT,IEI,SPY` |
| 5 | [`momentum_taa.py`](#5-momentum_taapy) | 시그널, 커스텀 알파 모델, 동적 유니버스, burn-in | 월말 | `XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY` |

한 번에 모두 받으시려면:

```bash
python examples/download_data.py --data GLD,SPY,AGG,TLT,IEI,XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY
```

예제 2·4·5는 `SPY`를 벤치마크로 함께 쓰는데, 이는 2단계 다운로드에 이미 포함됩니다.

---

## 1. `buy_and_hold.py`

**난이도: 출발점.** 저장소에서 가장 작은 완결형 백테스트입니다.

**무엇을 보여주는가.** 모든 백테스트에 반드시 필요한 최소 구성요소만 담았습니다.

- 거래 대상 자산을 지정하는 `StaticUniverse`
- `BacktestDataHandler`에 데이터를 공급하는 `CSVDailyBarDataSource`
- 고정 목표 비중을 유지하는 `FixedSignalsAlphaModel`
- 이들을 묶는 `BacktestTradingSession`

`rebalance='buy_and_hold'`는 시작 시점에 포지션을 한 번 잡고 이후 건드리지 않는다는 뜻이라, 아직 따라갈 스케줄링 로직이 없습니다.

**파라미터.** 2004-11-19 ~ 2019-12-31, `EQ:GLD` 100%, 현금 버퍼 1%.

```bash
python examples/download_data.py --data GLD
python examples/buy_and_hold.py
```

**무엇을 볼 것인가.** 벤치마크가 없어 tearsheet에 전략 하나만 나옵니다. 해당 기간 금을 그냥 들고 있었을 때의 총수익과 그 과정의 낙폭입니다. 최대 낙폭(MDD)을 기억해 두시면 아래 분산 포트폴리오들과 비교하기 좋습니다.

## 2. `sixty_forty.py`

**난이도: 리밸런싱 추가.** 고전적인 60/40 주식·채권 포트폴리오이며, 메인 README의 퀵스타트에 쓰이는 예제입니다.

**무엇을 보여주는가.** 예제 1에 두 가지가 추가됩니다.

- **리밸런싱.** `rebalance='end_of_month'`를 주면 QSTrader가 매월 마지막 영업일에 주문을 생성해, 가격 변동으로 어긋난 비중을 60/40 목표로 되돌립니다.
- **벤치마크.** 동일 기간에 대해 독립적인 `BacktestTradingSession`을 하나 더 실행하고, 그 자산곡선을 `TearsheetStatistics`의 `benchmark_equity`로 넘깁니다. 예제 3·4·5가 그대로 재사용하는 표준 패턴입니다.

**파라미터.** 2003-09-30 ~ 2019-12-31, `EQ:SPY` 60% / `EQ:AGG` 40%, 현금 버퍼 1%. 벤치마크: SPY 100% 단순 보유.

```bash
python examples/download_data.py --data SPY,AGG
python examples/sixty_forty.py
```

**무엇을 볼 것인가.** 총수익은 주식 100% 벤치마크에 뒤지지만, 연변동성이 약 17%에서 10%로, 최대 낙폭이 약 55%에서 35%로 낮아집니다. **수익을 일부 포기하고 완만한 여정을 사는** 이 맞교환이 60/40 배분의 존재 이유이며, 자산곡선·낙폭·통계 패널에서 세 수치를 나란히 확인할 수 있습니다.

## 3. `sixty_forty_fees.py`

**난이도: 개념 하나 추가.** 예제 2와 동일한 60/40 포트폴리오를 거래 비용 유무로 두 번 돌립니다.

**무엇을 보여주는가.** 수수료 모델링입니다. 전략에는 `PercentFeeModel(commission_pct=0.1%, tax_pct=0.5%)`을, 벤치마크에는 `ZeroFeeModel()`을 넘깁니다. 기간·유니버스·알파 모델·리밸런싱 주기가 전부 동일하므로 두 곡선의 격차는 **오직 비용 때문**입니다. 여기서의 벤치마크는 SPY가 아니라 **비용이 없는 자기 자신**이라는 점에 유의하세요.

**파라미터.** `sixty_forty.py`와 동일합니다.

```bash
python examples/sixty_forty_fees.py
```

**무엇을 볼 것인가.** 매 거래마다 수수료·세금 합계 0.6%를 낼 때 월간 리밸런싱이 치르는 대가입니다. 두 자산곡선은 같이 출발해 꾸준히 벌어지며, CAGR 차이(**연 0.2%p 안팎**)가 연환산 손실분입니다. 한 해로 보면 작지만 16년이 쌓이면 무시하기 어렵습니다. 리밸런싱 주기가 그 회전율만큼의 값어치를 하는지 따져볼 때 이 예제를 복사해 쓰시면 됩니다.

## 4. `long_short.py`

**난이도: 롱온리 제약 해제.** 듀레이션이 다른 두 국채 ETF 간의 레버리지 상대가치 거래입니다.

**무엇을 보여주는가.** 본격적인 포트폴리오 구성을 가능하게 하는 두 설정입니다.

- `long_only=False` — 음수 목표 비중을 허용
- `gross_leverage=5.0` — 총 익스포저를 자기자본의 5배로 확대

눈여겨볼 점이 있습니다. 이 예제는 롱온리 예제들이 쓰는 `cash_buffer_percentage` **대신** `gross_leverage`를 넘깁니다. 자본을 얼마나 투입할지 정하는 두 가지 대안적 방식입니다.

**파라미터.** 2007-01-31 ~ 2020-05-31, `EQ:TLT` +100% / `EQ:IEI` −70%, 월말 리밸런싱, 총 레버리지 5배. 벤치마크: SPY 100% 단순 보유.

```bash
python examples/download_data.py --data TLT,IEI,SPY
python examples/long_short.py
```

**무엇을 볼 것인가.** 20년 이상 장기 국채를 사고 3~7년 중기 국채를 파는 것은 채권 시장의 **방향**이 아니라 **수익률 곡선의 형태**에 거는 베팅이라, 수익 프로파일이 주식 벤치마크와 전혀 다릅니다. 레버리지는 양방향을 모두 증폭시켜 연변동성이 벤치마크 20% 대비 37% 수준까지 오르고 최대 낙폭도 더 깊어지는데, **정작 샤프 지수는 거의 같게 나옵니다.** 위험조정 수익은 그대로인데 여정만 훨씬 험해진 상황으로, 총수익률 숫자 하나로는 가려지고 낙폭 패널에서 드러나는 전형적인 사례입니다.

## 5. `momentum_taa.py`

**난이도: API 전체 활용.** SPDR 미국 섹터 ETF 10종 중 6개월 모멘텀 상위 3개를 보유하는 전술적 자산배분(TAA)입니다. 자체 알파 모델을 정의하는 유일한 예제이고, 훑어보기보다 처음부터 끝까지 읽어볼 만한 유일한 예제이기도 합니다.

**무엇을 보여주는가.** 새로운 개념 네 가지가 한꺼번에 등장하며, 그래서 마지막에 배치했습니다.

- **커스텀 `AlphaModel`.** `TopNMomentumAlphaModel`이 파일 안에 직접 정의돼 있습니다. `__call__`이 유니버스를 모멘텀으로 정렬해 상위 N개에 균등 비중을, 나머지에는 0을 부여합니다.
- **시그널.** 126 영업일(약 6개월) 룩백의 `MomentumSignal`을 `SignalsCollection`으로 감싸 세션에 `signals=`로 넘깁니다. 백테스트가 진행되는 동안 QSTrader가 이를 계속 갱신합니다.
- **`DynamicUniverse`.** `XLC`는 2018-06-18 이전에는 존재하지 않았습니다. 자산별 편입 가능 시점을 담은 딕셔너리를 넘겨, 아직 상장되지 않은 ETF에 포지션을 잡는 일이 없도록 합니다.
- **Burn-in 기간.** `burn_in_dt`를 `start_dt`보다 1년 뒤로 두어, 첫 포지션을 잡기 전에 모멘텀 룩백이 채워질 시간을 줍니다. 통계도 burn-in 시점부터 집계되고 벤치마크 세션도 같은 시점에 시작해 비교가 공정해집니다.

**파라미터.** 백테스트 시작 1998-12-22, burn-in 종료 1999-12-22, 종료 2020-12-31. 룩백 126일, 10개 섹터 중 상위 3개, 월말 리밸런싱, 현금 버퍼 1%. 벤치마크: burn-in 시점부터 SPY 100% 단순 보유.

```bash
python examples/download_data.py --data XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY,SPY
python examples/momentum_taa.py
```

**무엇을 볼 것인가.** 모멘텀 전략은 추세장에서 벌고 급반전에서 토해내는 성향이 있습니다. 여기서는 월별 수익률 히트맵이 핵심 패널입니다. 2008~2009년과 2020년 초 구간을 찾아 SPY 단순 보유 벤치마크와 비교해 보세요.

---

## 지원 모듈

아래 두 파일은 `examples/`에 있지만 **예제가 아닙니다.** 위 5개 스크립트를 짧고 일관되게 유지하기 위해 존재합니다.

| 파일 | 역할 |
| ---- | ---- |
| [`download_data.py`](download_data.py) | Yahoo! Finance에서 일봉 OHLCV를 받아 QSTrader용 CSV로 저장하는 독립 CLI. 직접 실행하며, 어떤 파일도 이를 import 하지 않습니다. `yfinance`가 필요합니다 — `pip3 install -r requirements/examples.txt`, 또는 `uv sync` (`examples` 의존성 그룹을 기본으로 설치합니다) |
| [`tearsheet_output.py`](tearsheet_output.py) | 예제 5개가 모두 import 합니다. 공통 인자 `--show` / `--no-save` / `--output` / `--output-dir`를 제공하고 tearsheet 저장 위치를 결정합니다 |

두 파일이 함께 쓰는 `.env` 로딩 기능은 패키지 쪽인 [`qstrader/env_file.py`](../qstrader/env_file.py)에 있습니다. [`scripts/static_backtest.py`](../scripts/static_backtest.py)도 이를 필요로 하기 때문입니다. 이 스크립트는 자산 배분을 코드가 아닌 커맨드라인으로 받으며, 설명은 [메인 README](../README.md#4-the-static-allocation-script)에 있습니다. `click`이 필요합니다 — `pip3 install -r requirements/scripts.txt`, 또는 `uv sync` (`scripts` 의존성 그룹을 기본으로 설치합니다)

## 공통 옵션

예제 5개 모두 동일한 출력 인자를 받습니다. 전체 목록은 아무 예제에나 `--help`를 붙여 확인하세요.

```bash
python examples/sixty_forty.py                              # 저장만 (기본값)
python examples/sixty_forty.py --show                       # 저장 + 창 표시
python examples/sixty_forty.py --show --no-save             # 창만 표시
python examples/sixty_forty.py --output out/my-chart.png    # 경로 직접 지정
```

## 직접 만들어 보기

`sixty_forty.py`를 복사한 뒤 유니버스와 알파 모델을 바꾸시면 됩니다. 실제 백테스트에 필요한 요소를 모두 갖춘 것 중 가장 짧은 예제입니다. 커스텀 `AlphaModel`, 실시간 갱신되는 시그널, 시간에 따라 변하는 유니버스가 필요해지면 `momentum_taa.py`를 참고 자료로 삼으세요.
