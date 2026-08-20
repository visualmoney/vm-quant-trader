# VMTrader

| Development   | Details       |
| ------------- | ------------- |
| Test Status   | [![CI](https://img.shields.io/github/actions/workflow/status/visualmoney/vm-quant-trader/ci.yml?branch=master&style=flat-square&label=CI)](https://github.com/visualmoney/vm-quant-trader/actions/workflows/ci.yml) [![Coverage Status](https://img.shields.io/coverallsCoverage/github/visualmoney/vm-quant-trader?branch=master&style=flat-square&label=Coverage)](https://coveralls.io/github/visualmoney/vm-quant-trader?branch=master) |
| Version Info  | [![PyPI](https://img.shields.io/pypi/v/vmtrader?style=flat-square&label=PyPI&color=blue)](https://pypi.org/project/vmtrader) |
| Compatibility | [![Python Version](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue?style=flat-square)](https://github.com/visualmoney/vm-quant-trader/actions/workflows/ci.yml) |
| License       | [![License](https://img.shields.io/badge/License-MIT%20OR%20Apache--2.0-blue?style=flat-square)](#license-terms) |

VMTrader is a free Python-based open-source modular schedule-driven engine for long-short equities and ETF based systematic trading strategies. It began as a fork of [QSTrader](https://github.com/mhallsmoore/qstrader) by Michael Halls-Moore (QuantStart) and is being extended towards live execution.

VMTrader can be best described as a loosely-coupled collection of modules for carrying out end-to-end backtests with realistic trading mechanics.

The default modules provide useful functionality for certain types of systematic trading strategies and can be utilised without modification. However the intent of VMTrader is for the users to extend, inherit or fully replace each module in order to provide custom functionality for their own use case.

The software is currently under active development and is dual licensed under the MIT license and the Apache License, Version 2.0, at your option.

## Previous Version and Advanced Algorithmic Trading

Please note that the upstream QSTrader project, including the version utilised through the **Advanced Algorithmic Trading** ebook, is at [mhallsmoore/qstrader](https://github.com/mhallsmoore/qstrader). VMTrader is a separate distribution and is not maintained by QuantStart.

It has recently been updated to support Python 3.9, 3.10, 3.11 and 3.12 with up to date package dependencies.

## Installation

VMTrader requires **Python 3.10 or later**. Continuous integration tests every release against Python 3.10, 3.11, 3.12, 3.13 and 3.14.

Whichever tool you prefer, install VMTrader into an isolated [virtual environment](https://docs.python.org/3/tutorial/venv.html#virtual-environments-and-packages) rather than alongside your system Python.

Any issues with installation should be reported as issues [here](https://github.com/visualmoney/vm-quant-trader/issues).

### uv

[uv](https://docs.astral.sh/uv/) manages the interpreter, the virtual environment and the dependencies with one tool, and will download a suitable Python itself if you do not already have one.

To use VMTrader as a library in your own project:

```bash
uv add vmtrader
```

To run the bundled examples and scripts, work from a clone instead. `uv sync` creates `.venv`, installs VMTrader and every dependency group, and resolves them from the checked-in `uv.lock`, so you get the same versions CI does:

```bash
git clone https://github.com/visualmoney/vm-quant-trader.git
cd vm-quant-trader
uv sync
```

Prefix commands with `uv run` to use that environment without activating it:

```bash
uv run python examples/sixty_forty.py
```

### pip

[venv](https://docs.python.org/3/tutorial/venv.html#creating-virtual-environments) handles the environment creation and [pip](https://docs.python.org/3/tutorial/venv.html#managing-packages-with-pip) the package installation.

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip3 install vmtrader
```

### conda

[conda](https://docs.conda.io/projects/conda/en/latest/) is a command-line tool that comes with the Anaconda distribution. It allows you to manage virtual environments as well as packages _using the same tool_.

The following command creates a brand new environment called `backtest`. Name a supported interpreter explicitly, since the conda default may be older than VMTrader requires:

```bash
conda create -n backtest python=3.12
```

In order to start using VMTrader, you need to activate this new environment and install VMTrader using pip.

```bash
conda activate backtest
pip3 install vmtrader
```

## Full Documentation

Documentation for this fork lives under [docs/](docs/README.md). The upstream QSTrader tutorials on QuantStart.com — [https://www.quantstart.com/qstrader/](https://www.quantstart.com/qstrader/) — still describe the shared core concepts.

## Quickstart

This repository provides some simple example strategies at [/examples](https://github.com/visualmoney/vm-quant-trader/tree/master/examples).

Within this quickstart section a classic 60/40 equities/bonds portfolio will be backtested with monthly rebalancing on the last day of the calendar month.

Assuming that an appropriate Python environment exists and VMTrader has been installed (see **Installation** above), make sure to activate the virtual environment and clone the repository:

```bash
git clone https://github.com/visualmoney/vm-quant-trader.git
cd vm-quant-trader
```

The 60/40 script makes use of OHLC 'daily bar' data from Yahoo! Finance. In particular it requires the [SPY](https://finance.yahoo.com/quote/SPY/history?p=SPY) and [AGG](https://finance.yahoo.com/quote/AGG/history?p=AGG) ETF data. The bundled `download_data.py` helper fetches the full history for each and writes it into the CSV format expected by VMTrader:

It needs [yfinance](https://pypi.org/project/yfinance/), which is declared as the `examples` dependency group rather than a runtime dependency, since a backtest never uses it:

```bash
uv sync                          # uv installs the group already
uv run python examples/download_data.py
```

```bash
pip install --group examples     # pip 25.1 or later
python examples/download_data.py
```

On an older pip, name the package directly: `pip install "yfinance>=1.2.0"`.

This writes `SPY.csv` and `AGG.csv` into the current directory. Now run the backtest:

```bash
python examples/sixty_forty.py
```

You will then see some console output as the backtest simulation engine runs through each day and carries out the rebalancing logic once per month. Once the backtest is complete a tearsheet is saved to `out/tearsheet-sixty-forty-<yyyymmdd-hhmmss>.png`:

![Image of 60/40 Backtest](https://quantstartmedia.s3.amazonaws.com/images/qstrader_sixty_forty_backtest.png)

Saving to a file — rather than opening a window — is the default so that the examples also run on headless machines such as remote servers and CI. Add `--show` to open the tearsheet in an interactive window instead.

You can examine the commented ``sixty_forty.py`` file to see the current VMTrader backtesting API.

If you have any questions about the installation or example usage then please raise an issue [here](https://github.com/visualmoney/vm-quant-trader/issues).

## Running the Examples

Every example follows the same two steps: download the CSV data it needs, then run the script. Both are run from the repository root.

### 1. Downloading the data

`examples/download_data.py` downloads daily OHLCV bars from Yahoo! Finance and writes one VMTrader-compatible `<SYMBOL>.csv` per ticker. It needs [yfinance](https://pypi.org/project/yfinance/), which is kept out of the VMTrader runtime dependencies and declared as the `examples` dependency group instead. `uv sync` installs that group by default; on pip 25.1 or later use `pip install --group examples`, and on an older pip `pip install "yfinance>=1.2.0"`.

```bash
python examples/download_data.py                        # defaults to SPY and AGG
python examples/download_data.py --data SPY AGG QQQ     # space separated
python examples/download_data.py --data SPY,AGG,QQQ     # or comma separated
python examples/download_data.py --data SPY --start 2010-01-01 --end 2020-01-01
python examples/download_data.py --data SPY --output-dir /path/to/csvs
python examples/download_data.py --help
```

| Option | Description |
| ------ | ----------- |
| `-d`, `--data SYMBOL [SYMBOL ...]` | Tickers to download, space or comma separated. Defaults to `SPY AGG`. |
| `-o`, `--output-dir DIR` | Directory to write the CSV files into. Defaults to `VMTRADER_CSV_DATA_DIR` (from the environment or a `.env` file), or the current directory. Created if it does not exist. |
| `-p`, `--period PERIOD` | yfinance download period. Ignored when `--start` is given. Defaults to `max`. |
| `-s`, `--start YYYY-MM-DD` | Inclusive start date. |
| `-e`, `--end YYYY-MM-DD` | Exclusive end date. |

The examples read their CSV files from `VMTRADER_CSV_DATA_DIR`, falling back to the current directory, so the downloader and the example must agree on a location. Keeping the default for both — running each from the repository root — is the simplest option. To store the data elsewhere, set the environment variable once and both will honour it:

```bash
export VMTRADER_CSV_DATA_DIR=data
python examples/download_data.py
python examples/sixty_forty.py
```

Any directory that does not yet exist is created automatically, including nested paths, by both the downloader and the tearsheet output.

Keeping downloaded data and generated results apart is worth the one-line setting: `data` holds what was fetched, `out` holds what a backtest produced. `out` can then be deleted at any time without losing the price history, which takes a while to download again. Both `/data/` and `out` are listed in `.gitignore`.

### Configuration via a .env file

Rather than exporting variables in every shell, the examples will also read them from a `.env` file. This needs no extra packages — VMTrader parses the file itself, in `vmtrader/env_file.py`. Nothing is loaded implicitly: importing VMTrader never touches the environment, and only the scripts under `examples/` and `scripts/` call the loader.

A documented template is provided as [`.env.example`](https://github.com/visualmoney/vm-quant-trader/blob/master/.env.example). Copy it and edit to suit:

```bash
cp .env.example .env
```

```ini
# .env
VMTRADER_CSV_DATA_DIR=data
VMTRADER_OUTPUT_DIR=out
```

```bash
python examples/download_data.py     # writes into data/
python examples/sixty_forty.py       # reads from data/, saves the tearsheet into out/
```

Variables already present in the environment always take precedence, so an `export` on the command line still overrides the file. The `.env` file is looked up in this order, and the first one found is used:

1. The path given by `VMTRADER_ENV_FILE`, if set.
2. `.env` in the current directory.
3. `.env` in the repository root.

Blank lines and `#` comments are ignored, an `export ` prefix is allowed, and quoted values are supported. Note that `.env` is listed in `.gitignore` and should not be committed — commit changes to `.env.example` instead.

### 2. Running a backtest

| Example | Strategy | Required symbols |
| ------- | -------- | ---------------- |
| [`sixty_forty.py`](https://github.com/visualmoney/vm-quant-trader/blob/master/examples/sixty_forty.py) | 60/40 equities/bonds, rebalanced monthly | `SPY AGG` |
| [`sixty_forty_fees.py`](https://github.com/visualmoney/vm-quant-trader/blob/master/examples/sixty_forty_fees.py) | The same 60/40 portfolio, with and without commission | `SPY AGG` |
| [`buy_and_hold.py`](https://github.com/visualmoney/vm-quant-trader/blob/master/examples/buy_and_hold.py) | Buy & hold a single gold ETF | `GLD` |
| [`long_short.py`](https://github.com/visualmoney/vm-quant-trader/blob/master/examples/long_short.py) | Long/short leveraged treasury bond ETFs | `TLT IEI SPY` |
| [`momentum_taa.py`](https://github.com/visualmoney/vm-quant-trader/blob/master/examples/momentum_taa.py) | US sector momentum, top 3 sectors | `XLB XLC XLE XLF XLI XLK XLP XLU XLV XLY SPY` |
| [`sma_crossover.py`](https://github.com/visualmoney/vm-quant-trader/blob/master/examples/sma_crossover.py) | SPY/AGG 50/200 day moving average crossover, against a 60/40 benchmark | `SPY AGG` |

Each example is described in detail — what it demonstrates, its parameters and what to look for in the tearsheet — in [`examples/README.md`](examples/README.md) ([한국어](examples/README.ko.md)), which orders them from the simplest to the most involved.

For instance, to run the sector momentum strategy:

```bash
python examples/download_data.py --data XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY,SPY
python examples/momentum_taa.py
```

### 3. Tearsheet output

By default each example saves its tearsheet to `out/tearsheet-<example>-<yyyymmdd-hhmmss>.png` and does not open a window, so the examples run unchanged on headless machines. The timestamp means repeated runs never overwrite each other.

```bash
python examples/sixty_forty.py                              # save only (default)
python examples/sixty_forty.py --show                       # save and display
python examples/sixty_forty.py --show --no-save             # display only
python examples/sixty_forty.py --output out/my-chart.png    # explicit path
python examples/sixty_forty.py --output-dir /path/to/dir    # explicit directory
python examples/sixty_forty.py --help
```

| Option | Description |
| ------ | ----------- |
| `--show` | Open the tearsheet in an interactive Matplotlib window. Off by default. |
| `--no-save` | Do not write the tearsheet to disk. |
| `-o`, `--output PATH` | Save to an explicit file path instead of the timestamped default. |
| `--output-dir DIR` | Directory to save into. Defaults to `VMTRADER_OUTPUT_DIR` (from the environment or a `.env` file), or `out` at the repository root. Created if it does not exist. |

When writing your own script, the same behaviour is available directly on the tearsheet:

```python
tearsheet = TearsheetStatistics(
    strategy_equity=strategy_backtest.get_equity_curve(),
    title='My Strategy'
)
tearsheet.plot_results(filename='out/my-chart.png', show=False)
```

### 4. The static allocation script

`scripts/static_backtest.py` backtests an arbitrary fixed-weight portfolio against the 60/40 benchmark, taking the allocation on the command line rather than in code, and writes the results as JSON. It is run from a repository checkout and is not part of the installed package. It needs [click](https://pypi.org/project/click/), which for that reason is kept out of the VMTrader runtime dependencies and installed separately:

```bash
uv sync                          # uv installs the group already
uv run python scripts/static_backtest.py \
    --start-date 2010-01-01 \
    --allocations "SPY:0.6,AGG:0.4" \
    --title "60/40 US Equities/Bonds" \
    --id "6040-us-equitiesbonds"
```

With pip 25.1 or later, `pip install --group scripts` reads the same declaration out of `pyproject.toml`; on an older pip, `pip install "click>=8.0"`. Then run the script with `python` in place of `uv run python`.

| Option | Description |
| ------ | ----------- |
| `--start-date YYYY-MM-DD` | Backtest start date. Required. |
| `--end-date YYYY-MM-DD` | Backtest end date. Defaults to yesterday. |
| `--allocations "SYM:W,..."` | Comma-separated symbol/weight pairs. Required. |
| `--title TEXT` | Strategy title shown on the tearsheet and in the JSON. Required. |
| `--id TEXT` | Strategy ID, used for the `<id>_monthly.json` filename. Required. |
| `--output-dir DIR` | Directory for the JSON output. Defaults to `VMTRADER_OUTPUT_DIR` (from the environment or a `.env` file), or the current directory. Created if it does not exist. |
| `--tearsheet` | Open the tearsheet in an interactive window. Blocks until closed. |
| `--tearsheet-file PATH` | Save the tearsheet to this path. Needs no display, so it works on headless machines. Can be combined with `--tearsheet`. |

The CSV data is read from `VMTRADER_CSV_DATA_DIR` exactly as for the examples, and the benchmark always requires `SPY` and `AGG` in addition to the symbols being allocated to.

## Current Features

* **Backtesting Engine** - VMTrader employs a schedule-based portfolio construction approach to systematic trading. Signal generation is decoupled from portfolio construction, risk management, execution and simulated brokerage accounting in a modular, object-oriented fashion.

* **Performance Statistics** - VMTrader provides typical 'tearsheet' performance assessment of strategies. It also supports statistics export via JSON to allow external software to consume metrics from backtests.

* **Free Open-Source Software** - VMTrader has been released under two permissive open-source licenses, MIT and Apache 2.0, either of which you may choose. Both allow full usage in both research and commercial applications, without restriction, but with no warranty of any kind whatsoever (see **License Terms** below). VMTrader is completely free and costs nothing to download or use.

* **Software Development** - VMTrader is written in the Python programming language for straightforward cross-platform support. VMTrader contains a suite of unit and integration tests for the majority of its modules. Tests are continually added for new features.

## License Terms

VMTrader is dual licensed under either of

* the MIT license ([LICENSE-MIT](LICENSE-MIT) or <https://opensource.org/licenses/MIT>), or
* the Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE) or <https://www.apache.org/licenses/LICENSE-2.0>)

at your option. Its SPDX identifier is `MIT OR Apache-2.0`.

You need comply with only one of them. Apache 2.0 is offered for its explicit patent
grant and its contribution terms; MIT is retained because this project derives from the
MIT-licensed upstream [QSTrader](https://github.com/mhallsmoore/qstrader), whose
copyright notice and permission notice must be preserved in every copy:

Copyright (c) 2015-2024 QuantStart.com, QuarkGluon Ltd

Unless you explicitly state otherwise, any contribution intentionally submitted for
inclusion in VMTrader by you, as defined in the Apache 2.0 license, shall be dual
licensed as above, without any additional terms or conditions.

## Trading Disclaimer

Trading equities on margin carries a high level of risk, and may not be suitable for all investors. Past performance is not indicative of future results. The high degree of leverage can work against you as well as for you. Before deciding to invest in equities you should carefully consider your investment objectives, level of experience, and risk appetite. The possibility exists that you could sustain a loss of some or all of your initial investment and therefore you should not invest money that you cannot afford to lose. You should be aware of all the risks associated with equities trading, and seek advice from an independent financial advisor if you have any doubts.
