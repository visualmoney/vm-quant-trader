# QSTrader

| Development   | Details       |
| ------------- | ------------- |
| Test Status   | [![CI](https://img.shields.io/github/actions/workflow/status/visualmoney/vm-quant-trader/ci.yml?branch=master&style=flat-square&label=CI)](https://github.com/visualmoney/vm-quant-trader/actions/workflows/ci.yml) [![Coverage Status](https://img.shields.io/coverallsCoverage/github/visualmoney/vm-quant-trader?branch=master&style=flat-square&label=Coverage)](https://coveralls.io/github/visualmoney/vm-quant-trader?branch=master) |
| Version Info  | [![PyPI](https://img.shields.io/pypi/v/qstrader?style=flat-square&label=PyPI&color=blue)](https://pypi.org/project/qstrader) [![PyPI Downloads](https://img.shields.io/pypi/dm/qstrader?style=flat-square&label=PyPI%20Downloads)](https://pypi.org/project/qstrader) |
| Compatibility | [![Python Version](https://img.shields.io/pypi/pyversions/qstrader?style=flat-square&label=Python%20Versions)](https://pypi.org/project/qstrader) |
| License       | ![GitHub](https://img.shields.io/github/license/mhallsmoore/qstrader?style=flat-square&label=License) |

QSTrader is a free Python-based open-source modular schedule-driven backtesting framework for long-short equities and ETF based systematic trading strategies.

QSTrader can be best described as a loosely-coupled collection of modules for carrying out end-to-end backtests with realistic trading mechanics.

The default modules provide useful functionality for certain types of systematic trading strategies and can be utilised without modification. However the intent of QSTrader is for the users to extend, inherit or fully replace each module in order to provide custom functionality for their own use case.

The software is currently under active development and is provided under a permissive "MIT" license.

# Previous Version and Advanced Algorithmic Trading

Please note that the previous version of QSTrader, which is utilised through the **Advanced Algorithmic Trading** ebook, can be found along with the appropriate installation instructions [here](https://github.com/mhallsmoore/qstrader/tree/advanced-algorithmic-trading).

It has recently been updated to support Python 3.9, 3.10, 3.11 and 3.12 with up to date package dependencies.

# Installation

Installation requires a Python3 environment. The simplest approach is to download a self-contained scientific Python distribution such as the [Anaconda Individual Edition](https://www.anaconda.com/products/individual#Downloads). You can then install QSTrader into an isolated [virtual environment](https://docs.python.org/3/tutorial/venv.html#virtual-environments-and-packages) using pip as shown below.

Any issues with installation should be reported to the development team as issues [here](https://github.com/mhallsmoore/qstrader/issues).

## conda

[conda](https://docs.conda.io/projects/conda/en/latest/) is a command-line tool that comes with the Anaconda distribution. It allows you to manage virtual environments as well as packages _using the same tool_.

The following command will create a brand new environment called `backtest`.

```
conda create -n backtest python
```
This will use the conda default Python version. At time of writing this was Python 3.12. QSTrader currently supports Python 3.9, 3.10, 3.11 and 3.12. Optionally you can specify a python version by substituting python==3.9 into the command as follows:

```
conda create -n backtest python==3.9
```

In order to start using QSTrader, you need to activate this new environment and install QSTrader using pip.

```
conda activate backtest
pip3 install qstrader
```

## pip

Alternatively, you can use [venv](https://docs.python.org/3/tutorial/venv.html#creating-virtual-environments) to handle the environment creation and [pip](https://docs.python.org/3/tutorial/venv.html#managing-packages-with-pip) to handle the package installation.

```
python -m venv backtest
source backtest/bin/activate  # Need to activate environment before installing package
pip3 install qstrader
```

# Full Documentation

Comprehensive documentation and beginner tutorials for QSTrader can be found on QuantStart.com at [https://www.quantstart.com/qstrader/](https://www.quantstart.com/qstrader/).

# Quickstart

The QSTrader repository provides some simple example strategies at [/examples](https://github.com/mhallsmoore/qstrader/tree/master/examples).

Within this quickstart section a classic 60/40 equities/bonds portfolio will be backtested with monthly rebalancing on the last day of the calendar month.

Assuming that an appropriate Python environment exists and QSTrader has been installed (see **Installation** above), make sure to activate the virtual environment and clone the repository:

```
git clone https://github.com/mhallsmoore/qstrader.git
cd qstrader
```

The 60/40 script makes use of OHLC 'daily bar' data from Yahoo! Finance. In particular it requires the [SPY](https://finance.yahoo.com/quote/SPY/history?p=SPY) and [AGG](https://finance.yahoo.com/quote/AGG/history?p=AGG) ETF data. The bundled `download_data.py` helper fetches the full history for each and writes it into the CSV format expected by QSTrader:

```
pip3 install -r requirements/examples.txt
python examples/download_data.py
```

This writes `SPY.csv` and `AGG.csv` into the current directory. Now run the backtest:

```
python examples/sixty_forty.py
```

You will then see some console output as the backtest simulation engine runs through each day and carries out the rebalancing logic once per month. Once the backtest is complete a tearsheet is saved to `out/tearsheet-sixty-forty-<yyyymmdd-hhmmss>.png`:

![Image of 60/40 Backtest](https://quantstartmedia.s3.amazonaws.com/images/qstrader_sixty_forty_backtest.png)

Saving to a file — rather than opening a window — is the default so that the examples also run on headless machines such as remote servers and CI. Add `--show` to open the tearsheet in an interactive window instead.

You can examine the commented ``sixty_forty.py`` file to see the current QSTrader backtesting API.

If you have any questions about the installation or example usage then please feel free to email [support@quantstart.com](mailto:support@quantstart.com) or raise an issue [here](https://github.com/mhallsmoore/qstrader/issues).

# Running the Examples

Every example follows the same two steps: download the CSV data it needs, then run the script. Both are run from the repository root.

## 1. Downloading the data

`examples/download_data.py` downloads daily OHLCV bars from Yahoo! Finance and writes one QSTrader-compatible `<SYMBOL>.csv` per ticker. It needs [yfinance](https://pypi.org/project/yfinance/), which is kept out of the QSTrader runtime dependencies and installed separately with `pip3 install -r requirements/examples.txt`.

```
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
| `-o`, `--output-dir DIR` | Directory to write the CSV files into. Defaults to `QSTRADER_CSV_DATA_DIR` (from the environment or a `.env` file), or the current directory. Created if it does not exist. |
| `-p`, `--period PERIOD` | yfinance download period. Ignored when `--start` is given. Defaults to `max`. |
| `-s`, `--start YYYY-MM-DD` | Inclusive start date. |
| `-e`, `--end YYYY-MM-DD` | Exclusive end date. |

The examples read their CSV files from `QSTRADER_CSV_DATA_DIR`, falling back to the current directory, so the downloader and the example must agree on a location. Keeping the default for both — running each from the repository root — is the simplest option. To store the data elsewhere, set the environment variable once and both will honour it:

```
export QSTRADER_CSV_DATA_DIR=data
python examples/download_data.py
python examples/sixty_forty.py
```

Any directory that does not yet exist is created automatically, including nested paths, by both the downloader and the tearsheet output.

Keeping downloaded data and generated results apart is worth the one-line setting: `data` holds what was fetched, `out` holds what a backtest produced. `out` can then be deleted at any time without losing the price history, which takes a while to download again. Both `/data/` and `out` are listed in `.gitignore`.

## Configuration via a .env file

Rather than exporting variables in every shell, the examples will also read them from a `.env` file. This needs no extra packages — QSTrader parses the file itself, in `qstrader/env_file.py`. Nothing is loaded implicitly: importing QSTrader never touches the environment, and only the scripts under `examples/` and `scripts/` call the loader.

A documented template is provided as [`.env.example`](https://github.com/mhallsmoore/qstrader/blob/master/.env.example). Copy it and edit to suit:

```
cp .env.example .env
```

```
# .env
QSTRADER_CSV_DATA_DIR=data
QSTRADER_OUTPUT_DIR=out
```

```
python examples/download_data.py     # writes into data/
python examples/sixty_forty.py       # reads from data/, saves the tearsheet into out/
```

Variables already present in the environment always take precedence, so an `export` on the command line still overrides the file. The `.env` file is looked up in this order, and the first one found is used:

1. The path given by `QSTRADER_ENV_FILE`, if set.
2. `.env` in the current directory.
3. `.env` in the repository root.

Blank lines and `#` comments are ignored, an `export ` prefix is allowed, and quoted values are supported. Note that `.env` is listed in `.gitignore` and should not be committed — commit changes to `.env.example` instead.

## 2. Running a backtest

| Example | Strategy | Required symbols |
| ------- | -------- | ---------------- |
| [`sixty_forty.py`](https://github.com/mhallsmoore/qstrader/blob/master/examples/sixty_forty.py) | 60/40 equities/bonds, rebalanced monthly | `SPY AGG` |
| [`sixty_forty_fees.py`](https://github.com/mhallsmoore/qstrader/blob/master/examples/sixty_forty_fees.py) | The same 60/40 portfolio, with and without commission | `SPY AGG` |
| [`buy_and_hold.py`](https://github.com/mhallsmoore/qstrader/blob/master/examples/buy_and_hold.py) | Buy & hold a single gold ETF | `GLD` |
| [`long_short.py`](https://github.com/mhallsmoore/qstrader/blob/master/examples/long_short.py) | Long/short leveraged treasury bond ETFs | `TLT IEI SPY` |
| [`momentum_taa.py`](https://github.com/mhallsmoore/qstrader/blob/master/examples/momentum_taa.py) | US sector momentum, top 3 sectors | `XLB XLC XLE XLF XLI XLK XLP XLU XLV XLY SPY` |

Each example is described in detail — what it demonstrates, its parameters and what to look for in the tearsheet — in [`examples/README.md`](examples/README.md) ([한국어](examples/README.ko.md)), which orders them from the simplest to the most involved.

For instance, to run the sector momentum strategy:

```
python examples/download_data.py --data XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY,SPY
python examples/momentum_taa.py
```

## 3. Tearsheet output

By default each example saves its tearsheet to `out/tearsheet-<example>-<yyyymmdd-hhmmss>.png` and does not open a window, so the examples run unchanged on headless machines. The timestamp means repeated runs never overwrite each other.

```
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
| `--output-dir DIR` | Directory to save into. Defaults to `QSTRADER_OUTPUT_DIR` (from the environment or a `.env` file), or `out` at the repository root. Created if it does not exist. |

When writing your own script, the same behaviour is available directly on the tearsheet:

```python
tearsheet = TearsheetStatistics(
    strategy_equity=strategy_backtest.get_equity_curve(),
    title='My Strategy'
)
tearsheet.plot_results(filename='out/my-chart.png', show=False)
```

# Current Features

* **Backtesting Engine** - QSTrader employs a schedule-based portfolio construction approach to systematic trading. Signal generation is decoupled from portfolio construction, risk management, execution and simulated brokerage accounting in a modular, object-oriented fashion.

* **Performance Statistics** - QSTrader provides typical 'tearsheet' performance assessment of strategies. It also supports statistics export via JSON to allow external software to consume metrics from backtests.

* **Free Open-Source Software** - QSTrader has been released under a permissive open-source MIT License. This allows full usage in both research and commercial applications, without restriction, but with no warranty of any kind whatsoever (see **License** below). QSTrader is completely free and costs nothing to download or use.

* **Software Development** - QSTrader is written in the Python programming language for straightforward cross-platform support. QSTrader contains a suite of unit and integration tests for the majority of its modules. Tests are continually added for new features.

# License Terms

Copyright (c) 2015-2024 QuantStart.com, QuarkGluon Ltd

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

# Trading Disclaimer

Trading equities on margin carries a high level of risk, and may not be suitable for all investors. Past performance is not indicative of future results. The high degree of leverage can work against you as well as for you. Before deciding to invest in equities you should carefully consider your investment objectives, level of experience, and risk appetite. The possibility exists that you could sustain a loss of some or all of your initial investment and therefore you should not invest money that you cannot afford to lose. You should be aware of all the risks associated with equities trading, and seek advice from an independent financial advisor if you have any doubts.
