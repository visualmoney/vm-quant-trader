# 0.3.16

* Tests rebalance membership against a frozenset rather than scanning the schedule list. _is_rebalance_event runs once per simulation event, and comparing Pandas Timestamps is expensive enough that 8,482 events against a 196 entry schedule measured at 7.5% of runtime in isolation. End to end the saving is larger: five runs of the sixteen year 60/40 backtest give a median of 3.464 seconds before and 2.688 after, a 22% reduction, with the final equity identical to the cent. The ordered list stays as the public 'rebalance_schedule' attribute; only the membership test moves.
* Adds the only test that drives the price padding policy through the engine. Task T9 found that switching the lookup from 'pad' to 'backfill', which makes every price query look into the future, left all four end-to-end tests passing, because the simulation engine emits events at exactly the timestamps the bar conversion writes and so never reaches the policy at all. The new test gives the engine bars with a day missing and prices that jump from 120 to 500 across the gap, so padding backwards and filling forwards cannot be confused.
* Adds an end-to-end backtest that charges fees. Every existing one left the default ZeroFeeModel in place, so mutating the PercentFeeModel commission by a factor of one hundred left them all passing. The new test runs the same 60/40 session with and without a 0.1% commission and 0.5% tax, and checks that charging leaves the account worse off, that each position carries the commission it was charged including the sale side, and the resulting holdings.
* Records the outcome in report 06 and corrects one heading in it. The two remaining recommendations, tests for tearsheet.py and json_statistics.py and a searchsorted price lookup, are not addressed.

# 0.3.15

* Adds a report measuring what the end-to-end fixture tests actually catch, and profiling the engine. Both tasks existed to check estimates made in report 01, and both estimates turned out to be wrong.
* Thirteen mutations were injected into the engine one at a time and the suite run against each. Of the twelve that changed behaviour, the end-to-end tests caught five and the whole suite caught nine. The three nothing catches are the volatility signal, the tearsheet and the JSON statistics, which is what 0% and 13% coverage means in practice. Three of the four caught only by unit tests are caught by tests added during this exercise; before it the suite would have caught six of twelve rather than nine.
* The mutation worth recording is that switching the price lookup from 'pad' to 'backfill', which makes every price query in the engine look into the future, passes all four end-to-end tests. The simulation engine emits events only at 14:30 and 21:00 and the CSV source converts bars to exactly those timestamps, so every query is an exact index match and the padding policy is never exercised. Only a unit test that queries between two bars can see it.
* Profiling puts 85% of runtime in the price lookup, within which pandas' Index.get_indexer takes 0.29ms per call. The lru_cache that exists to relieve it achieves a 6.4% hit rate on get_bid and 0% on get_ask, since a backtest asks for each timestamp and asset pair roughly once; it retains 16,960 entries for a single run and keeps every data source instance alive, which a weakref check confirms. Report 01 called it an intended optimisation for a single backtest, which the measurement does not support.
* The 'dt in list' rebalance check that report 01 dismissed as negligible is 7.54% of runtime: 8,482 events against a 196 entry list, where a set is 40 times faster. Neither severity estimate survived being measured, in opposite directions.
* No engine code is changed. The recommendations, including the one-line set conversion, are recorded in the report rather than applied.

# 0.3.14

* Adds a status column to the report index in docs/README.md. Report bodies are snapshots and are never updated, which is deliberate, but it left the index describing report 02 as unimplemented and report 03 as unfixed after both had landed in 0.3.13, and describing the defects in reports 04 and 05 as though they were current. Status now lives in one structured column rather than inside prose that would have to be rewritten on every fix, so a reader can tell whether a report's findings still stand without opening it.
* Adds the same follow-up note to report 01 that reports 02 to 05 already carry, recording that its §8-1 was resolved in 0.3.12 and part of §8-7 in 0.3.13, that tasks T5 to T8 have been carried out, and that its figures are those of v0.3.10.

# 0.3.13

* Raises a ValueError from aggregate_returns for an unrecognised 'convert_to'. The branch constructed the exception and never raised it, so a typo returned None and surfaced much later as an AttributeError with the real cause absent from the traceback, or not at all if the caller treated the None as falsy. The message now names the value that was supplied.
* Seeds the high water mark in create_drawdowns with the opening value of the curve. The array was initialised to zero and the loop started at index 1, so the first value could never become a peak, and since both callers pass a cumulative return curve normalised to 1.0, the starting point of every backtest was excluded from the peak search. Measured against SPY this changes nothing over a long rising sample and reports 16.73% rather than 11.29% for a backtest starting the day before the 10.94% fall of 16 March 2020. A risk figure erring towards the optimistic was the wrong direction for the error. The parameter is renamed from 'returns' to 'equity', since it was documented as period returns while every caller passes a curve.
* Returns NaN, rather than the last price of the series, for a price queried before an asset's first bar. 'index.get_indexer(method="pad")' returns -1 when nothing precedes the timestamp and iloc takes -1 as the final row, so a query for AGG on 2000-01-03 returned its closing price from 2026-08-14 and a backtest starting before an asset's data began traded it on look-ahead. Both order sizers carry a guard that raises on a NaN price whose message names this exact cause; it could not fire while the lookup answered with a number, and now does.
* Estimates order sizing fees on the size of the trade rather than on the whole target position. Both sizers priced the entire position at every rebalance as though it were being bought from scratch, producing 2,027,438 dollars of estimated fees against 34,673 actually charged on a monthly rebalanced 60/40. Since the estimate is deducted from the target before truncation, it left the portfolio permanently under-invested by roughly the fee rate, worth 20,897 dollars of the performance drag on a figure that was never spent; 20,168 of that is recovered. The sizers already held a broker reference, so this needs no change to the OrderSizer interface. It also resolves the 'est_quantity = 0' marker, since an estimated trade quantity is now available to pass to fee models that charge per unit.
* Uses Transaction.cost_with_commission in Portfolio.transact_asset, which recomputed the same figure inline. One accounting rule lived in two places and the copy that was actually used was the one without tests. The redundant 'if self.commission == 0.0' branch goes too, and transaction.py reaches 100% coverage.
* Makes the portfolio optimiser and the execution algorithm injectable, through both QuantTradingSystem and BacktestTradingSession, as the fee model already was. They were constructed inside _initialise_models with no way to supply either, so replacing an execution algorithm meant monkeypatching the module, and EqualWeightPortfolioOptimiser shipped with the package while being unreachable through a backtest session.
* Adds FixedFeeModel, which charges a flat commission and tax per transaction. Both existing models are purely proportional and so cannot distinguish one order from five smaller ones covering the same value: splitting every order five ways across a sixteen year backtest moved the total commission by 19 dollars. Against a 10 dollar per-order charge the same split costs 31,544 dollars, so over-trading can now be charged for.
* Records the fixes in the four reports that documented these defects. The report bodies are snapshots and are left as written; only their status lines are updated, so that a reader is not misled into thinking the behaviour they describe is current.
* Raises the test suite from 268 cases to 288 and coverage from 76.79% to 77.78%.

# 0.3.12

* Gives the data layer the abstract base class every other extension point already had. BacktestDataHandler and CSVDailyBarDataSource were joined by duck typing alone, with the contract between them written down nowhere, so writing a second data source meant reading the first one to find out what it is. 'DataSource' now states that contract, along with the four rules that were only implicit: symbols are QSTrader symbols rather than bare tickers, timestamps are UTC, a source may raise for an asset it does not carry because the handler converts that into a NaN, and the range query omits unknown assets rather than returning columns of NaN. BacktestDataHandler still does not check isinstance, so an existing user-defined source keeps working.
* Splits CSVDailyBarDataSource in two. 'DailyBarDataSource' holds everything that does not depend on where the bars came from, the conversion of each daily bar into separately timestamped open and close prices and the queries over the result, leaving the CSV class with only the loading. The moved code is unchanged and the public surface is identical, which the end-to-end fixture test passing unaltered demonstrates.
* Fixes the signature mismatch that declaring the interface exposed. BacktestDataHandler called get_assets_historical_closes with an 'adjusted' keyword that the CSV source did not accept, so the call raised TypeError; nothing in the package called it, which is why it went unnoticed. The parameter is now part of the contract and selects the 'Adj Close' column, raising a ValueError naming the asset when that column is absent.
* Adds InMemoryDailyBarDataSource, which takes bar DataFrames directly rather than reading files. This suits a database or API client that has already built them, a parameter sweep that would otherwise re-read and re-convert the same CSVs on every run, and tests that should not depend on files. Since the caller supplies the frames rather than the source reading a known format, it validates them at construction rather than letting a missing column surface later as a KeyError from inside the bar conversion.
* Adds unit tests for statistics/performance.py, which sat at 26% coverage, the lowest of any module carrying figures a user acts on: CAGR, Sharpe, Sortino and maximum drawdown were all effectively unverified. Nineteen cases take it to 100%, with every expected value derived by hand and the derivation recorded in the file, which also pins that np.std() on a Pandas Series applies ddof=0 rather than the ddof=1 that Series.std() would.
* Adds examples/sma_crossover.py, a sixth example and the second to define its own AlphaModel. It holds, in equal weight, every asset whose 50 day moving average sits above its 200 day one, and is deliberately shorter than TopNMomentumAlphaModel, so there is now an easier custom alpha model to copy. It allocates between the same two assets as the 60/40 benchmark it is compared against, so the comparison isolates the allocation rule rather than the choice of assets, and it is the only example that goes to cash.
* Adds docs/, divided by audience: docs/user/ for strategy developers, who should not need the engine internals, and docs/dev/ for engine contributors. docs/dev/reports/ is separated again, because the files directly under dev/ are meant to track the code while a report is a snapshot of one point in time, and mixing them lets a stale investigation read as the current specification.
* Adds five reports under docs/dev/reports/, covering the architecture and a reading path through it, a prepared consolidation of the duplicated transaction cost calculation, and three sets of findings from exercising the extension points. Four defects are recorded and deliberately left unfixed, each pinned by a characterization test that says so in its docstring: aggregate_returns builds a ValueError it never raises; create_drawdowns cannot treat the first value of a curve as a peak, understating the maximum drawdown by 5.44 percentage points for a backtest starting the day before the fall of 16 March 2020; the order sizer prices the whole target position rather than the trade, which leaves a portfolio permanently under-invested by the fee rate; and a price query before an asset's first bar returns the last price of the series rather than NaN, which is look-ahead and which also disables the guard whose message names that exact situation.
* Raises the test suite from 221 cases to 268 and coverage from 74.06% to 76.79%.

# 0.3.11

* Dual licenses the project under 'MIT OR Apache-2.0', where it was previously MIT alone. Users may comply with either. Apache-2.0 is offered for its explicit patent grant and its contribution terms, which MIT does not address at all.
* Splits 'LICENSE' into 'LICENSE-MIT' and 'LICENSE-APACHE'. The MIT text keeps the upstream 'Copyright (c) 2015-2024 QuantStart.com, QuarkGluon Ltd' notice unchanged: this project derives from the MIT-licensed upstream QSTrader, and MIT permits sublicensing under other terms but never permits removing that notice. Adding Apache-2.0 alongside it is therefore the only form a relicense can take here.
* Declares the licence in pyproject.toml as the PEP 639 SPDX expression 'license = "MIT OR Apache-2.0"' with 'license-files', and drops the 'License :: OSI Approved :: MIT License' classifier. Classifiers cannot express a choice between two licences, and PEP 639 forbids combining a licence expression with licence classifiers.
* Adds both licence files to MANIFEST.in, which still named the removed 'LICENSE'. Without this the source distribution would ship no licence text at all.
* Replaces the README licence badge, which read the licence from 'mhallsmoore/qstrader' rather than this repository, and so reported the upstream project's terms. This is the same defect 0.3.8 corrected for the Python version badge.
* Rewrites the README 'License Terms' section, which reproduced the MIT text inline, and corrects the two other places that described the project as MIT licensed.

# 0.3.10

* Tags the code fences in README.md. Eighteen of the nineteen blocks were untagged and so rendered without syntax highlighting, while examples/README.md and examples/README.ko.md have tagged theirs since they were written. Seventeen are shell commands and take 'bash'; the block showing the contents of a '.env' file takes 'ini', since it is file content rather than commands; the Python snippet was already tagged. No text inside any block changed.

# 0.3.9

* Converts the fifteen abstract base classes from the Python 2 '__metaclass__ = ABCMeta' idiom to 'abc.ABC'. Under Python 3 that assignment is an inert class attribute, so ABCMeta was never applied and not one of the 30 @abstractmethod markers in the package had any effect: every base class could be instantiated directly, and a subclass that forgot to implement the interface failed later, at the call site, with NotImplementedError rather than at construction. Asset stays instantiable because it declares no abstract methods, which is unchanged behaviour.
* Implements Statistics.update() and Statistics.save() on TearsheetStatistics, which previously provided only get_results() and plot_results(). Both were declared abstract but neither was enforced, so the gap went unnoticed. save() writes the tearsheet to a path without opening a window, reusing the headless path added in 0.3.1; update() is a documented no-op, since a tearsheet is derived entirely from the completed equity curves given to the constructor.
* Replaces the Rebalance.output_rebalances() abstract method with _generate_rebalances(). No subclass ever implemented output_rebalances() and nothing called it: the real contract is the 'rebalances' attribute that all four subclasses populate from _generate_rebalances(), which is what BacktestTradingSession reads. Making the base class enforce the method that is actually implemented turns a dead declaration into a live one.
* Adds the missing 'initial_weights' parameter to PortfolioOptimiser.__call__(). The base class declared __call__(self, dt) while both shipped optimisers take (self, dt, initial_weights), which is also how PortfolioConstructionModel invokes them.
* Adds the missing 'equity_df' parameter to Statistics.get_results(). The base class declared get_results(self) while TearsheetStatistics requires the equity curve to calculate from, so the only implementation of the interface could not be called through it. The two remaining differences between these base classes and their implementations, TradingSession.run() and Statistics.plot_results(), are subclasses adding optional parameters, which leaves the base contract callable and so is left alone.
* Documents the parameters and return values of all 30 abstract methods. 26 of them had no docstring whatsoever and the remaining 4 had one with no Parameters section, so the interfaces described neither what they take nor what they return. The text is taken from the concrete implementations, so an interface and its implementations now agree.
* Corrects three docstring defects found while checking parameter documentation against signatures: PortfolioConstructionModel._generate_rebalance_orders documented 'curent_portfolio', MarketOrderExecutionAlgorithm.__call__ documented 'rebalance_orders' for a parameter named 'initial_orders', and TearsheetStatistics.plot_results underlined its Parameters heading with '=' instead of '-', which numpydoc does not recognise as a section.
* Drops the redundant 'object' base class from the remaining 28 classes, 15 under qstrader/ and 13 in the test suite. Inheriting from object explicitly is the Python 2 spelling of a new-style class; under Python 3 every class is new-style and the base is implied.
* Removes the '#!local/bin/python3' shebang from examples/download_data.py. The path is relative, so it could never resolve, the file does not carry the executable bit, and none of the other example scripts declare one. They are run as 'python examples/<name>.py', which the README, examples/README.md and examples/README.ko.md all document.
* Removes a redundant pair of parentheses in Signal.update_assets().
* Adds tests/unit/test_abstract_base_classes.py, 56 cases pinning that each base class is a real ABC, that neither it nor an incomplete subclass can be instantiated, and that every shipped concrete class still can. Nothing previously caught the silent loss of enforcement.

# 0.3.8

* Removes requirements/ entirely. Both remaining files held a single package that duplicated a dependency group, and pip 25.1 can install those groups directly with 'pip install --group', so pyproject.toml is now the only place any dependency is declared and the drift 0.3.2 had to repair can no longer happen. The README, examples/README.md and examples/README.ko.md give the uv, modern pip and older pip forms in each of the five places that previously pointed at a requirements file.
* Restructures the Installation section around uv, which is what this repository's lockfile and CI are built on, with pip and conda kept below it. The section previously opened by recommending an Anaconda download.
* Corrects the supported Python versions. The README still advertised 3.9 through 3.12 and offered 'conda create -n backtest python==3.9', which since 0.3.4 has produced an environment QSTrader cannot be installed into. It now states 3.10 or later, tested through 3.14, in one place.
* Replaces the Python version badge, which read the upstream package's metadata from PyPI and so could never agree with this repository's supported range.
* Normalises the heading levels: the README had nine level one headings, of which only the title should be one. Anchors are generated from heading text, so the inbound links from examples/README.md are unaffected.

# 0.3.7

* Removes the four Dockerfiles under dockerfiles/. They were distro compatibility harnesses from 0.2.2, each ending in 'RUN pytest', and none of them could work: all four cloned mhallsmoore/qstrader rather than this repository, so they never exercised this code, and bionic, centos:8, fedora:33 and focal are all end of life with system interpreters too old for numpy>=2.0.0 and pandas>=2.2. GitHub Actions covers Python 3.10 to 3.14 against uv.lock, and uv supplies its own interpreter, so 'does this distribution's python work' is no longer a question the project needs to ask.
* Removes requirements/base.txt and requirements/tests.txt, whose only consumers were those Dockerfiles. CI installs from uv.lock, and the runtime dependencies are declared in pyproject.toml.
* Keeps requirements/examples.txt and requirements/scripts.txt, which the README points pip users at, and notes in both that they mirror the matching dependency group.

# 0.3.6

* Moves the CI workflow from actions/checkout@v4 and astral-sh/setup-uv@v5 to @v7 and @v10.0.1. Both of the old majors target Node.js 20, which GitHub Actions runners no longer provide: they were being forced onto Node.js 24 and every run carried a deprecation annotation. setup-uv is pinned to an exact version because it stopped publishing moving major tags after v7, so '@v10' does not resolve.

# 0.3.5

* Moves click out of the runtime dependencies and into a 'scripts' dependency group, mirrored by requirements/scripts.txt. No module under qstrader/ imports click: its only user is scripts/static_backtest.py, which the wheel does not ship, so every installation was pulling in a dependency it could not use. This follows the same reasoning that keeps yfinance out of the runtime dependencies. The 'dev' group includes the new group, so 'uv run python scripts/static_backtest.py' keeps working.
* Makes '--start-date', '--allocations', '--title' and '--id' required in scripts/static_backtest.py. Omitting any of them previously produced a pandas traceback, or silently wrote the results to 'None_monthly.json'.
* Parses the dates with click.DateTime, so a malformed date is reported as a usage error rather than raising DateParseError from inside pandas.
* Reports an unparseable '--allocations' string as a Click usage error, with exit code 2. The failure previously printed a message and called sys.exit() with no argument, which exits 0 and so looked like success to a shell or CI job. The allocations are now parsed as an option callback, before the backtest starts, and surrounding whitespace in 'SPY:0.6, AGG:0.4' is tolerated.
* Writes the JSON statistics into QSTRADER_OUTPUT_DIR, as the examples already do for tearsheets, rather than always into the current directory. Adds '--output-dir' to override it, creating the directory if it does not exist. With neither set the output stays in the current directory as before.
* Documents scripts/static_backtest.py in the README, which described only the examples.
* Removes the empty scripts/__init__.py. Nothing imports scripts/ and it is not distributed.

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
