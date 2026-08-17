# 0.3.4

* Replaces the '.travis.yml' config with a GitHub Actions workflow at '.github/workflows/ci.yml'. Travis CI was unusable: travis-ci.org has been retired, the README badges pointed at the upstream repository rather than this one, and three of the four Python versions in the matrix (3.6, 3.7, 3.8) could not install numpy>=2.0.0 or pandas>=2.2 at all.
* Installs with 'uv sync --locked' in CI, so builds resolve from uv.lock instead of requirements/*.txt and fail if the lockfile has drifted from pyproject.toml. This also removes the need for the PYTHONPATH export Travis used, since the project is installed rather than imported from the working directory.
* Tests against Python 3.10 to 3.14. Raises requires-python from '>= 3.9' to '>= 3.10', since 3.9 reached end of life in October 2025 and was no longer being tested, and updates the classifiers to match the tested range.
* Sets 'fail_under = 70' in .coveragerc, so a pull request that drops coverage below the floor fails the build instead of only showing up on a dashboard. The suite currently sits at 72%.
* Uploads coverage to Coveralls from a single matrix leg via coverallsapp/github-action, and restores the coverage badge in the README pointing at this repository. The 'coveralls' PyPI package is dropped from the test dependencies: it read Travis-specific environment variables to identify a build, and the action supersedes it.
* Replaces flake8 with ruff, configured under [tool.ruff.lint] in pyproject.toml to reproduce the previous 'flake8 --ignore E501,F501,W504' rule set. Preview mode is enabled so that the whitespace rules the flake8 job enforced remain covered.
* Fixes the 14 lint violations that would have failed the build on its first run, including a '%'-escaping bug in DollarWeightedCashBufferedOrderSizer._check_cash_buffer_percentage, where the intended 'cash buffer percentage out of range' message was replaced at runtime by 'ValueError: incomplete format'.

# 0.3.3

* Moves the '.env' loader from examples/env_file.py into the package as qstrader/env_file.py, so that both examples/ and scripts/ can import it without sys.path manipulation. The search now walks upwards from the current directory rather than falling back to a path relative to the package, which was meaningless for an installed copy. Nothing is loaded on import; callers invoke load_env_file() explicitly.
* Adds unit tests for the '.env' loader covering value quoting, inline comments, malformed lines, environment precedence, upward search and QSTRADER_ENV_FILE.
* Updates scripts/static_backtest.py to read QSTRADER_CSV_DATA_DIR from a '.env' file, matching the examples.
* Adds a '--tearsheet-file' option to scripts/static_backtest.py, which saves the tearsheet without requiring a display. The existing '--tearsheet' flag still opens a blocking window and both can be combined.

# 0.3.2

* Aligns pyproject.toml with the requirements files, which the Dockerfiles and Travis config install from. Previously the two had drifted, and 'uv sync' would uninstall the test tooling because it was declared in requirements/tests.txt only.
* Adds a 'test' dependency group mirroring requirements/tests.txt, and an 'examples' group holding yfinance. The 'dev' group includes both, so uv keeps installing them by default.
* Relaxes the pytz lower bound from 2026.3.post1 to 2020.1. The tighter bound was pinned to whichever release happened to be installed, while qstrader only uses pytz.UTC. Adds pytz to requirements/base.txt, where it was missing despite qstrader/data/daily_bar_csv.py importing it.
* Realigns the click lower bound to 8.0 to match requirements/base.txt.
* Adds requirements/examples.txt for the yfinance dependency used by examples/download_data.py.

# 0.3.1

* Fixes the examples failing to load CSV data. Recent yfinance versions write a three-row MultiIndex header, which CSVDailyBarDataSource cannot parse, and default to auto_adjust=True, which omits the 'Adj Close' column.
* Adds a 'show' argument to TearsheetStatistics.plot_results(). When False the tearsheet is saved without opening a window, so the examples run on headless machines. The output directory is now created if it does not exist.
* Renames examples/download_data_spy_and_agg.py to examples/download_data.py and generalises it. Symbols are selected with '--data' (space or comma separated, defaulting to SPY and AGG), with '--output-dir', '--period', '--start', '--end' and '--help' also available.
* Adds examples/tearsheet_output.py. Every example now saves its tearsheet to 'out/tearsheet-<example>-<yyyymmdd-hhmmss>.png' by default and accepts '--show', '--no-save', '--output' and '--output-dir'.
* Adds examples/env_file.py, which loads QSTRADER_CSV_DATA_DIR and QSTRADER_OUTPUT_DIR from a '.env' file without requiring python-dotenv. Existing environment variables take precedence. Adds a documented '.env.example' template.
* Adds pytz to the package dependencies, which qstrader/data/daily_bar_csv.py imports, and yfinance to a dev dependency group for the data downloader.
* Documents the example workflow in the README, covering data download, the required symbols per example, tearsheet output options and '.env' configuration.
* Ignores the '/data/' and '.env' paths in .gitignore.

# 0.3.0

* Updates dependencies to use numpy v2.0.0. 
* Updates simulated_broker.py to change np.NaN to np.nan
* Updates backtest_data_handler.py to change np.NaN to np.nan
* Updates daily_bar_csv.py to change np.NaN to np.nan
* Updates tests

# 0.2.9

* Updates requirements file to use numpy v1.26.4 or lower. This is the last version of QSTrader that supports numpy<2.0.0.

# 0.2.8

* Updates BacktestTradingSession.get_target_allocations() to use burn_in_dt.date() instead of burn_in_dt Timestamp. Previous method compared a Timestamp to a datetime.date.
* Adds an integration test to check that target allocations match the expected output, including a date index.

# 0.2.7

* Updates the execution handler to update final orders ensuring an execution order is created in the event of a single submission without a further rebalance.
* Updates rebalance_buy_and_hold to check if the start_dt is a business day
    If start_dt is a business day rebalance_dates =  [start_dt]
    If start_dt is a weekend rebalance_dates = [next business day]
* Adds a unit test to check that the buisness day calculation is correct
* Adds an integration test to check that a backtest using buy_and_hold_rebalance generates execution orders on the correct dates


# 0.2.6

* Removed get_portfolio_total_non_cash_equity and get_account_total_non_cash_equity from broker/broker.py abstract base class. These methods are not implemented.
* Added save option to TearsheetStatistics class in statistics/tearsheet.py. The tearsheet output can now be saved to a given filename by passing the optional filename parameter as a string when calling the plot_results function.


# 0.2.5

* Moved build-backend system to Hatchling from setuptools
* Updated the python package requirements to work with click 8.1
* Updated ReadMe and ChangeLog.

# 0.2.4

* Fixed bug involving NaN at Timestamp in sixty_forty example.
* Removed support for python 3.7 and 3.8
* Updated the python package requirements to work with matplotlib 3.8, numpy 1.26 and pandas 2.2.0

# 0.2.3

* Updated the python package requirements to work with matplotlib 3.4, numpy 1.21 and pandas 1.3
* Removed support for python 3.6
* Added a Tactical Asset Allocation monthly momentum strategy to the examples

# 0.2.2

* Added link to full documentation at [https://www.quantstart.com/qstrader/](https://www.quantstart.com/qstrader/)
* Fixed bug where burn-in period was still allowing portfolio rebalances and trade executions
* Added QSTrader Dockerfiles for various Linux distributions
* Removed support for Python 3.5 and added support for Python 3.9
* Increased minimum supported Pandas version to 1.1.5 from 0.25.1
* Modified end-to-end backtest integration test to check for approximate equality of results to fix differences across Pandas versions
* Disallowed Matplotlib 3.3.3 temporarily to avoid deprecated functionality from causing errors
* Event print messages during backtests can now be disabled through a boolean setting

# 0.2.1

* Added VolatilitySignal class to calculate rolling annualised volatility of returns for an asset
* Removed errors for orders that exceed cash account balance in SimulatedBroker and Portfolio. Replaced with console warnings.

# 0.2.0

* Significant overhaul of Position, PositionHandler, Portfolio, Transaction and SimulatedBroker classes to correctly account for short selling of assets
* Addition of LongShortLeveragedOrderSizer to allow long/short leveraged portfolios
* Added a new long/short leveraged portfolio example backtest
* Added some unit and integration tests to improve test coverage slightly

# 0.1.4

* Added ValueError with more verbose description for NaN pricing data when backtest start date too early
* Removed usage of 'inspect' library for updating attributes of Position within PositionHandler
* Added unit tests for Cash asset, StaticUniverse, DynamicUniverse and string colour utility function
* Added two more statistics to the JSON statistics calculation

# 0.1.3

* Fixed bug involving DynamicUniverse not adding assets to momentum and signal calculation if not present at start of backtest
* Modified MomentumSignal and SMASignal to allow calculation if available prices less than lookbacks
* Added daily rebalancing capability
* Added some unit tests to improve test coverage slightly

# 0.1.2

* Added RiskModel class hierarchy
* Modified API for MomentumSignal and SMASignal to utilise inherited Signal object
* Added SignalsCollection entity to update data for derived Signal classes
* Removed unnecessary BufferAlphaModel
* Added some unit tests to improve test coverage slightly

# 0.1.1

* Removed the need to specify a CSV data directory as an environment variable by adding a default of the current working directory of the executed script
* Addes CI support for Python 3.5, 3.6 and 3.8 in addition to 3.7
* Added some unit tests to improve test coverage slightly

# 0.1.0

* Initial relase of QSTrader to PyPI
