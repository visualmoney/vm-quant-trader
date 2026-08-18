# `statistics/performance.py` 결함 2건 — 발견 보고서

| 항목 | 내용 |
| --- | --- |
| 문서 ID | `20260818-03-performance-module-defects` |
| 작성일 | 2026-08-18 |
| 관점 | Software Architect |
| 상태 | **결함 확인 · 특성 테스트로 고정 완료 · 수정 미실시** |
| 발견 경위 | [20260818-01](20260818-01-codebase-comprehension-strategy.md) §6의 **T5**(성과 지표 단위 테스트 작성) 수행 중 |
| 관련 커밋 | `tests/unit/statistics/test_performance.py` 신규 (19 케이스) |

---

## 1. 요약

`qstrader/statistics/performance.py`는 커버리지 26%로 방치되어 있던 모듈이다. 단위 테스트를 작성하는 과정에서 **결함 2건**이 드러났다.

| # | 결함 | 심각도 | 수정 규모 |
| --- | --- | --- | --- |
| **D1** | `aggregate_returns`가 잘못된 인자에 대해 예외를 던지지 않고 `None`을 반환 | 낮음 | 1줄 |
| **D2** | `create_drawdowns`가 곡선의 **첫 값을 고점으로 인정하지 않아** 최대 낙폭과 지속 기간을 과소 보고 | **중간** | 2줄 |

두 결함 모두 **사용자가 의사결정에 직접 쓰는 숫자**에 영향을 준다. D2는 실제 시장 데이터로 최대 **5.44%p**의 과소 보고를 재현했다(§3.3).

> **이 보고서는 결함을 고치지 않는다.** 현재 동작은 특성 테스트(characterization test)로 고정해 두었으므로, 수정 시 어떤 테스트를 함께 바꿔야 하는지가 §5에 명시되어 있다.

### 발견 경위가 말해 주는 것

두 결함은 코드를 **읽어서** 발견된 것이 아니라, **손계산한 기대값과 실제 반환값을 대조하다가** 드러났다. 보고서 01 §6.0의 설계 원칙 1("기계가 판정할 수 있는 성공 기준")이 실제로 작동한 사례다. 26% 커버리지 모듈에 테스트를 넣는 작업의 기대 수익이 왜 높은지를 보여준다.

---

## 2. D1 — `aggregate_returns`의 발생하지 않는 `ValueError`

### 2.1 코드

`qstrader/statistics/performance.py:14-26`

```python
if convert_to == 'weekly':
    ...
elif convert_to == 'monthly':
    ...
elif convert_to == 'yearly':
    ...
else:
    ValueError('convert_to must be weekly, monthly or yearly')   # ← raise 누락
```

`ValueError` 인스턴스를 **생성만 하고 버린다.** `raise` 키워드가 없다.

### 2.2 증상

```python
>>> aggregate_returns(returns, 'daily')
None
```

함수가 끝까지 떨어져 `None`을 반환한다. 오류 메시지는 어디에도 나타나지 않는다.

호출부가 결과를 바로 쓰면 한참 뒤에 `AttributeError: 'NoneType' object has no attribute ...`로 터지고, 진짜 원인인 오타는 스택 트레이스에 등장하지 않는다. 더 나쁜 경우는 `None`을 조건문에서 falsy로 취급해 **조용히 빈 결과로 진행**하는 것이다.

### 2.3 영향 범위

| 호출부 | 인자 | 위험 |
| --- | --- | --- |
| `json_statistics.py:152, 170` | `'monthly'` 리터럴 | 없음 |
| `json_statistics.py:203` | `'yearly'` 리터럴 | 없음 |
| `tearsheet.py:144` | `'monthly'` 리터럴 | 없음 |
| `tearsheet.py:187` | `'yearly'` 리터럴 | 없음 |

**패키지 내부 호출은 전부 리터럴이므로 현재 이 경로는 도달하지 않는다.** 위험은 이 함수를 직접 호출하는 사용자 코드와 확장 모듈에 있다. `performance.py`의 함수들은 `__init__.py`를 거치지 않는 공개 모듈 수준 함수이며, 커스텀 `Statistics` 구현체가 재사용하도록 설계된 지점이다.

`else` 분기가 내부적으로 도달 불가였다는 점이 바로 26% 커버리지 아래 숨어 있던 이유다.

### 2.4 수정안

```diff
     else:
-        ValueError('convert_to must be weekly, monthly or yearly')
+        raise ValueError(
+            "'convert_to' must be 'weekly', 'monthly' or 'yearly', not '%s'." % convert_to
+        )
```

메시지에 실제로 전달된 값을 포함시킬 것을 권고한다. 원본 메시지는 무엇이 잘못되었는지는 말하지만 무엇이 들어왔는지는 말하지 않는다.

### 2.5 심각도 판정: **낮음**

내부 도달 불가, 수정 1줄, 회귀 위험 없음. 다만 **고치지 않을 이유도 없다.**

---

## 3. D2 — `create_drawdowns`가 첫 값을 고점으로 인정하지 않음

### 3.1 코드

`qstrader/statistics/performance.py:82-92`

```python
idx = returns.index
hwm = np.zeros(len(idx))          # ← hwm[0] 이 0.0 으로 초기화되고

for t in range(1, len(idx)):      # ← 루프가 t=1 부터 시작하므로
    hwm[t] = max(hwm[t - 1], returns.iloc[t])   # ← hwm[0] 은 영원히 0.0

perf = pd.DataFrame(index=idx)
perf["Drawdown"] = (hwm - returns) / hwm
perf.loc[perf.index[0], 'Drawdown'] = 0.0       # ← 0 나눗셈 결과를 덮어씀
```

고점(High Water Mark) 배열이 `0.0`으로 시작하고 루프가 인덱스 1부터 돌기 때문에, **HWM은 `curve[1:]`의 누적 최댓값**이 된다. 곡선의 첫 값 `curve[0]`은 고점 후보에서 완전히 제외된다.

92행이 첫 행의 낙폭을 `0.0`으로 강제 대입하는 것은 `(0 - curve[0]) / 0 = -inf`를 지우기 위한 것으로, **원인이 아니라 증상을 덮는 처리**다.

### 3.2 왜 문제인가

두 호출부 모두 **1.0에서 시작하도록 정규화된 누적 수익 곡선**을 넘긴다.

```python
# tearsheet.py:52  /  json_statistics.py 도 동일 형태
equity_df["cum_returns"] = np.exp(np.log(1 + equity_df["returns"]).cumsum())
# returns[0] = 0.0 이므로 cum_returns[0] = 1.0
```

즉 **모든 백테스트의 출발점 1.0이 고점 후보에서 빠진다.** 전략이 시작 직후 하락하고 그 하락 이전 수준을 회복하지 못하면, 낙폭은 1.0이 아니라 `max(curve[1:])`를 기준으로 측정된다.

과소 보고의 상한은 대략 **첫 기간의 손실률**이다. 일간 곡선에서는 보통 작지만, 첫날이 곧 전역 고점이면서 큰 손실이 나는 경우에는 무시할 수 없다.

### 3.3 실측 정량화

`data/SPY.csv`(1993-01-29 ~ 2026-08-14, 8,443행)의 조정 종가를 시작일 기준 1.0으로 정규화하여, 현행 구현과 **HWM을 첫 값으로 시딩한 정정 구현**을 비교했다. 재현 스크립트는 부록 A에 있다.

| 시작일 | 종료일 | 현행 max DD | 정정 max DD | 과소 보고 |
| --- | --- | --- | --- | --- |
| 2003-09-30 (60/40 예제와 동일) | 2019-12-31 | 0.5519 | 0.5519 | **0.00%p** |
| 2007-10-09 (금융위기 직전 고점) | 2013-12-31 | 0.5515 | 0.5519 | 0.04%p |
| 2020-02-19 (코로나 직전 고점) | 2020-12-31 | 0.3344 | 0.3372 | 0.27%p |
| **2020-03-13 (다음 거래일 −10.94%)** | 2020-12-31 | **0.1129** | **0.1673** | **5.44%p** |

지속 기간(`duration`)도 함께 어긋난다.

| 곡선 | 현행 duration | 정정 duration |
| --- | --- | --- |
| `[1.0, 0.9, 0.8, 0.7]` (단조 하락) | 2 | **3** |
| `[2.0, 1.0, 1.0]` (즉시 반토막) | 0 | 2 |

마지막 행이 가장 극적이다. 곡선이 시작 직후 **반토막 나고 회복하지 않는데 최대 낙폭 0.0, 지속 기간 0**으로 보고된다.

### 3.4 심각도 판정: **중간**

| 근거 | 평가 |
| --- | --- |
| 전형적인 장기 일간 백테스트 | 영향 미미 (0.00 ~ 0.27%p). 첫날 수익률이 작고, 대개 이후에 더 높은 고점이 생긴다 |
| 짧은 백테스트, 하락장 시작, 저빈도 곡선 | **실질적 영향** (실측 5.44%p) |
| 최대 낙폭의 성격 | 리스크 지표는 **보수적으로 과대 보고**되어야 하는데 이 결함은 **과소 보고** 방향이다. 오류의 부호가 나쁘다 |
| 검출 가능성 | 낮음. 그럴듯한 값이 나오므로 눈으로는 알 수 없다 |

"평소에는 거의 맞지만 가장 필요한 순간(급락장에서 시작한 백테스트)에 틀린다"는 점이 이 결함의 성격이다.

### 3.5 수정안

```diff
     idx = returns.index
     hwm = np.zeros(len(idx))
+    hwm[0] = returns.iloc[0]

     # Create the high water mark
     for t in range(1, len(idx)):
         hwm[t] = max(hwm[t - 1], returns.iloc[t])

     # Calculate the drawdown and duration statistics
     perf = pd.DataFrame(index=idx)
     perf["Drawdown"] = (hwm - returns) / hwm
-    perf.loc[perf.index[0], 'Drawdown'] = 0.0
```

HWM을 첫 값으로 시딩하면 첫 행의 낙폭이 자연히 `(curve[0] - curve[0]) / curve[0] = 0.0`이 되므로, **92행의 강제 대입도 함께 제거할 수 있다.** 0 나눗셈이 사라지는 것은 부수 효과다.

> **주의**: 곡선의 첫 값이 `0.0`이면 여전히 0 나눗셈이 된다. 두 호출부 모두 정규화된 누적 수익(첫 값 1.0)을 넘기므로 현재는 도달 불가지만, 함수 자체는 `create_drawdowns`를 직접 호출하는 사용자에게 공개되어 있다. 방어 코드를 넣을지는 §6의 결정 사항이다.

또한 파라미터 이름을 고칠 것을 권고한다. 현재 시그니처는 `create_drawdowns(returns)`이고 docstring도 "period percentage returns"라고 적혀 있지만, **실제로 받는 것은 누적 수익 곡선(equity curve)**이다. 이름과 문서가 실제 계약과 정반대다.

---

## 4. 수정 시 회귀 위험 — 낮음

`create_drawdowns`의 출력을 검증하는 **기존 테스트가 하나도 없다.**

| 소비자 | 커버리지 | 기존 테스트 |
| --- | --- | --- |
| `statistics/tearsheet.py` | 13% | 없음 (`test_abstract_base_classes.py`가 인터페이스 구현 여부만 확인) |
| `statistics/json_statistics.py` | 0% | 없음 |
| `tests/integration/trading/test_backtest_e2e.py` | — | 포트폴리오 이력과 보유 내역만 검사. 성과 지표는 검사하지 않음 |

즉 D2를 고쳐도 **e2e 픽스처는 영향을 받지 않는다.** 바뀌는 것은 §5에 나열한 특성 테스트 2건뿐이다.

이는 양날의 검이다. 수정이 안전하다는 뜻이기도 하지만, **애초에 이 결함이 몇 년간 살아남을 수 있었던 이유**이기도 하다.

---

## 5. 현재 고정된 특성 테스트

수정 시 **함께 교체해야 하는** 테스트다. 각 테스트의 docstring에 "이것은 승인이 아니라 기록"이라는 취지를 명시해 두었다.

| 테스트 | 고정 대상 | 수정 후 조치 |
| --- | --- | --- |
| `test_aggregate_returns_with_unknown_period_returns_none` | D1 — `None` 반환 | `pytest.raises(ValueError)`로 교체 |
| `test_create_drawdowns_never_treats_the_opening_value_as_a_peak` | D2 — `[2.0, 1.0, 1.0]` → max DD 0.0 | max DD 0.5, duration 2를 단언하도록 교체 |

나머지 17개 케이스는 정상 동작을 검증하므로 **수정 후에도 그대로 통과해야 한다.** 특히 아래 두 건은 D2 수정의 회귀 안전망 역할을 한다.

- `test_create_drawdowns` — 곡선 `[1.0, 1.5, 0.75, 1.2, 1.0, 2.0]`. 첫 값이 전역 고점이 아니므로 수정 전후 결과가 동일해야 한다 (max DD 0.5, duration 3)
- `test_create_drawdowns_on_a_monotonically_rising_curve` — 상승 곡선. 수정 전후 모두 max DD 0.0, duration 0

---

## 6. 결정이 필요한 사항

| # | 질문 | 권고 |
| --- | --- | --- |
| 1 | D1과 D2를 한 PR로 묶을 것인가 | **묶는다.** 같은 파일, 같은 성격(테스트 공백에서 자란 결함), 합쳐야 CHANGELOG 서술이 자연스럽다 |
| 2 | `create_drawdowns`의 파라미터 이름을 `equity`로 바꿀 것인가 | **바꾼다.** 위치 인자로만 호출되고 있어(`tearsheet.py:57, 217`, `json_statistics.py:314`) 호환성 문제가 없다 |
| 3 | 첫 값이 `0.0`인 곡선에 대한 방어 코드를 넣을 것인가 | **넣지 않는다.** 현재 도달 불가이며, 명시적 검증 없이 방어만 추가하면 또 다른 조용한 실패 경로가 생긴다. 필요하다면 `ValueError`로 즉시 실패시킬 것 |
| 4 | 버전을 올릴 것인가 | **올린다** (0.3.12 또는 후속). 이 저장소는 0.3.1 이후 모든 변경에 버전과 CHANGELOG 항목을 부여해 왔다 |
| 5 | `tearsheet.py` / `json_statistics.py`에도 테스트를 추가할 것인가 | **별건.** 두 모듈의 커버리지 13% / 0%는 별도 과제이며, 이 PR에 섞으면 검토 범위가 흐려진다 |

---

## 7. 권고 우선순위

1. **D2 수정** — 리스크 지표가 잘못된 방향(과소)으로 틀리며 실측 영향이 확인되었다
2. **D1 수정** — 1줄, 위험 없음. D2와 함께 처리
3. `create_drawdowns` 파라미터 이름·docstring 정정 — 계약과 문서가 정반대인 상태 해소
4. (별건) `tearsheet.py` / `json_statistics.py` 테스트 — 보고서 01 §7.1의 커버리지 공백 지도 참조

---

## 부록 A. 재현 스크립트

```python
import numpy as np
import pandas as pd
from itertools import groupby
from qstrader.statistics.performance import create_drawdowns


def corrected(curve):
    """create_drawdowns 와 동일하되 HWM 을 첫 값으로 시딩한 구현."""
    hwm = np.zeros(len(curve))
    hwm[0] = curve.iloc[0]
    for t in range(1, len(curve)):
        hwm[t] = max(hwm[t - 1], curve.iloc[t])
    dd = pd.Series((hwm - curve.values) / hwm, index=curve.index)
    check = np.where(dd == 0, 0, 1)
    duration = max(sum(1 for i in g if i == 1) for k, g in groupby(check))
    return dd.max(), duration


spy = pd.read_csv(
    'data/SPY.csv', index_col='Date', parse_dates=True
).sort_index()['Adj Close']

for start, end in [
    ('2003-09-30', '2019-12-31'),
    ('2007-10-09', '2013-12-31'),
    ('2020-02-19', '2020-12-31'),
    ('2020-03-13', '2020-12-31'),   # 다음 거래일이 -10.94%
]:
    window = spy.loc[start:end]
    curve = window / window.iloc[0]          # cum_returns 와 동일하게 1.0 에서 시작
    _, current_max, current_dur = create_drawdowns(curve)
    fixed_max, fixed_dur = corrected(curve)
    print('%s~%s  현행 %.4f (dur %d) | 정정 %.4f (dur %d) | 차이 %.2f%%p' % (
        start, end, current_max, current_dur,
        fixed_max, fixed_dur, (fixed_max - current_max) * 100
    ))
```

`data/SPY.csv`는 `uv run python examples/download_data.py`로 내려받는다.

---

*본 보고서는 발견 시점의 기록이며 수정을 포함하지 않는다. §3.3의 수치는 2026-08-18에 내려받은 SPY 데이터(1993-01-29 ~ 2026-08-14) 기준이므로, 데이터가 갱신되면 소수점 이하가 달라질 수 있다.*
