# QSTrader Examples

*Read this in [한국어](README.ko.md).*

Five example backtests, arranged as a progression. Each one is a self-contained script that builds a `BacktestTradingSession`, runs it and produces a tearsheet, and each adds exactly one new idea to the one before it — so read in order they double as a guided tour of the QSTrader API.

For installation, data download and tearsheet options, see the [Running the Examples](../README.md#running-the-examples) section of the main README. This document covers what each example actually does.

## Contents

1. [Before you start](#before-you-start)
2. [Recommended order](#recommended-order)
3. The examples, easiest first:
   1. [`buy_and_hold.py`](#1-buy_and_holdpy) — the minimum viable backtest
   2. [`sixty_forty.py`](#2-sixty_fortypy) — rebalancing and benchmarks
   3. [`sixty_forty_fees.py`](#3-sixty_forty_feespy) — transaction costs
   4. [`long_short.py`](#4-long_shortpy) — shorting and leverage
   5. [`momentum_taa.py`](#5-momentum_taapy) — signals and a custom alpha model
4. [Support modules](#support-modules)
5. [Common options](#common-options)
6. [Writing your own](#writing-your-own)

## Before you start

Every example reads `<SYMBOL>.csv` price data from `QSTRADER_CSV_DATA_DIR`, falling back to the current directory. Download what an example needs, then run it — both from the repository root:

```bash
python examples/download_data.py --data SPY,AGG
python examples/sixty_forty.py
```

All five share the same defaults unless noted: **$1,000,000** initial cash, and a tearsheet saved to `out/tearsheet-<example>-<yyyymmdd-hhmmss>.png` without opening a window. Add `--show` to display it instead.

Any performance figures quoted below are approximate. They come from dividend-adjusted prices, which Yahoo! Finance revises over time, so your run will land near these numbers rather than exactly on them.

## Recommended order

Work down the table. Each row assumes the concepts of the rows above it, and the data requirements grow gradually, so following this order also means each download builds on the last.

| # | Example | New concept introduced | Rebalance | Symbols to download |
| - | ------- | ---------------------- | --------- | ------------------- |
| 1 | [`buy_and_hold.py`](#1-buy_and_holdpy) | The four pieces every backtest needs | None | `GLD` |
| 2 | [`sixty_forty.py`](#2-sixty_fortypy) | Rebalancing, and comparing against a benchmark | Month end | `SPY,AGG` |
| 3 | [`sixty_forty_fees.py`](#3-sixty_forty_feespy) | Fee models | Month end | — same as above |
| 4 | [`long_short.py`](#4-long_shortpy) | Short positions and gross leverage | Month end | `TLT,IEI,SPY` |
| 5 | [`momentum_taa.py`](#5-momentum_taapy) | Signals, a custom alpha model, a dynamic universe, burn-in | Month end | `XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY` |

To fetch everything up front instead:

```bash
python examples/download_data.py --data GLD,SPY,AGG,TLT,IEI,XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY
```

Examples 2, 4 and 5 also use `SPY` as their benchmark, which the step 2 download already covers.

---

## 1. `buy_and_hold.py`

**Difficulty: starting point.** The smallest complete backtest in the repository.

**What it demonstrates.** The minimum set of pieces every backtest needs, and nothing else:

- a `StaticUniverse` naming the tradable assets,
- a `CSVDailyBarDataSource` feeding a `BacktestDataHandler`,
- a `FixedSignalsAlphaModel` holding a constant target weight,
- a `BacktestTradingSession` tying them together.

`rebalance='buy_and_hold'` means positions are established once at the start and never touched again, so there is no scheduling logic to follow yet.

**Parameters.** 2004-11-19 to 2019-12-31, 100% `EQ:GLD`, 1% cash buffer.

```bash
python examples/download_data.py --data GLD
python examples/buy_and_hold.py
```

**What to look for.** There is no benchmark, so the tearsheet shows the strategy alone — simply the total return of holding gold across the period, drawdowns included. Note its maximum drawdown; the diversified portfolios below are worth comparing against it.

## 2. `sixty_forty.py`

**Difficulty: adds rebalancing.** The classic 60/40 stock/bond portfolio, and the example used in the main README's quickstart.

**What it demonstrates.** Two new ideas on top of example 1:

- **Rebalancing.** `rebalance='end_of_month'` makes QSTrader generate orders on the last business day of each month, dragging the portfolio back to its 60/40 target as prices drift apart.
- **Benchmarks.** A second, independent `BacktestTradingSession` is run over the same dates, and its equity curve is passed to `TearsheetStatistics` as `benchmark_equity`. This is the standard pattern, reused by examples 3, 4 and 5.

**Parameters.** 2003-09-30 to 2019-12-31, 60% `EQ:SPY` / 40% `EQ:AGG`, 1% cash buffer. Benchmark: 100% SPY, buy and hold.

```bash
python examples/download_data.py --data SPY,AGG
python examples/sixty_forty.py
```

**What to look for.** The strategy trails the all-equity benchmark on total return, but annual volatility drops from roughly 17% to 10% and the maximum drawdown from roughly 55% to 35%. That trade-off — giving up return to buy a smoother ride — is the whole point of the 60/40 allocation, and the equity, drawdown and statistics panels show all three numbers side by side.

## 3. `sixty_forty_fees.py`

**Difficulty: one new concept.** The same 60/40 portfolio as example 2, run twice: with and without transaction costs.

**What it demonstrates.** Fee modelling. The strategy passes `PercentFeeModel(commission_pct=0.1%, tax_pct=0.5%)` while the benchmark passes `ZeroFeeModel()`. Everything else — dates, universe, alpha model, rebalance schedule — is identical, so the gap between the two curves is attributable to costs alone. Note that the benchmark here is the frictionless version of the strategy itself, not SPY.

**Parameters.** Identical to `sixty_forty.py`.

```bash
python examples/sixty_forty_fees.py
```

**What to look for.** How much a monthly rebalance costs when every trade pays 0.6% in combined commission and tax. The two equity curves start together and separate steadily, and the difference in CAGR — around 0.2 percentage points a year — is the annualised drag. Small per-year, meaningful over sixteen years. This is the example to copy when judging whether a rebalance schedule earns its turnover.

## 4. `long_short.py`

**Difficulty: relaxes the long-only constraint.** A leveraged relative-value trade between two treasury bond ETFs of different duration.

**What it demonstrates.** The two settings that unlock non-trivial portfolio construction:

- `long_only=False`, which permits negative target weights,
- `gross_leverage=5.0`, which scales gross exposure to five times equity.

Worth noticing: this example passes `gross_leverage` **instead of** `cash_buffer_percentage`, which every long-only example uses. The two are alternative ways of deciding how much capital gets deployed.

**Parameters.** 2007-01-31 to 2020-05-31, +100% `EQ:TLT` and −70% `EQ:IEI`, rebalanced monthly at 5× gross leverage. Benchmark: 100% SPY, buy and hold.

```bash
python examples/download_data.py --data TLT,IEI,SPY
python examples/long_short.py
```

**What to look for.** Long 20+ year treasuries against short 3–7 year treasuries is a bet on the shape of the yield curve rather than on the bond market's direction, so the return profile looks nothing like the equity benchmark. Leverage amplifies both sides — annual volatility lands near 37% against the benchmark's 20%, and the maximum drawdown is deeper — yet the Sharpe ratios come out close to identical. A much wilder path for the same risk-adjusted return is exactly the sort of thing the drawdown panel makes obvious and a headline return number hides.

## 5. `momentum_taa.py`

**Difficulty: the full API.** Tactical asset allocation across the ten SPDR US sector ETFs, holding the three with the strongest six-month momentum. This is the only example that defines its own alpha model, and the only one worth reading top to bottom rather than skimming.

**What it demonstrates.** Four new ideas at once, which is why it comes last:

- **A custom `AlphaModel`.** `TopNMomentumAlphaModel` is defined in the file itself. Its `__call__` ranks the universe by momentum and returns equal weights for the top N, zero for everything else.
- **Signals.** `MomentumSignal` with a 126 business day (roughly six month) lookback, wrapped in a `SignalsCollection` and passed to the session as `signals=`, so QSTrader keeps it updated as the backtest advances.
- **A `DynamicUniverse`.** `XLC` did not exist until 2018-06-18. An asset-dates dictionary tells QSTrader when each asset becomes eligible, so the backtest cannot take a position in an ETF that had not launched yet.
- **A burn-in period.** `burn_in_dt` is set one year after `start_dt`, giving the momentum lookback time to fill before any position is taken. Statistics only accrue from the burn-in date, and the benchmark session starts there too so the comparison is fair.

**Parameters.** Backtest starts 1998-12-22, burn-in ends 1999-12-22, runs to 2020-12-31. Lookback 126 days, top 3 of 10 sectors, monthly rebalance, 1% cash buffer. Benchmark: 100% SPY, buy and hold from the burn-in date.

```bash
python examples/download_data.py --data XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY,SPY
python examples/momentum_taa.py
```

**What to look for.** Momentum strategies tend to earn their keep in trending markets and give it back at sharp reversals. The monthly returns heatmap is the panel to read here: find the 2008–2009 and early 2020 columns and compare them against the buy-and-hold SPY benchmark.

---

## Support modules

These two files live in `examples/` but are **not** examples. They exist so the five scripts above stay short and consistent.

| File | Role |
| ---- | ---- |
| [`download_data.py`](download_data.py) | Standalone CLI that downloads daily OHLCV bars from Yahoo! Finance into QSTrader-compatible CSVs. Run it directly; nothing imports it. Needs `yfinance` — `pip3 install -r requirements/examples.txt`. |
| [`tearsheet_output.py`](tearsheet_output.py) | Imported by all five examples. Supplies the shared `--show` / `--no-save` / `--output` / `--output-dir` arguments and decides where the tearsheet is written. |

The `.env` loading both of them rely on lives in the package itself, at [`qstrader/env_file.py`](../qstrader/env_file.py), because `scripts/static_backtest.py` needs it too.

## Common options

Every example accepts the same output arguments. Run any of them with `--help` for the full list.

```bash
python examples/sixty_forty.py                              # save only (default)
python examples/sixty_forty.py --show                       # save and display
python examples/sixty_forty.py --show --no-save             # display only
python examples/sixty_forty.py --output out/my-chart.png    # explicit path
```

## Writing your own

Copy `sixty_forty.py` and change the universe and alpha model — it is the shortest example that still has every piece a real backtest needs. Reach for `momentum_taa.py` as the reference once you need a custom `AlphaModel`, live signals, or a universe that changes over time.
