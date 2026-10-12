import random

import numpy as np
import pytest

from marketintel.metrics.latency import LatencyHistogram, WindowedLatency, _index, _upper


def test_bucket_bounds_are_consistent():
    for v in list(range(0, 5000)) + [random.Random(1).randrange(1, 2**50) for _ in range(5000)]:
        i = _index(v)
        assert v <= _upper(i)
        if i > 0:
            assert v > _upper(i - 1)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_percentiles_within_relative_error(seed):
    rng = np.random.default_rng(seed)
    data = rng.lognormal(mean=10, sigma=1.5, size=50_000).astype(np.int64)  # ~ 22 us median, heavy tail
    h = LatencyHistogram()
    for v in data:
        h.record(int(v))
    for q in (0.5, 0.9, 0.95, 0.99, 0.999):
        exact = np.quantile(data, q, method="inverted_cdf")
        got = h.percentile(q)
        assert got >= exact * (1 - 1e-9)           # bucket upper bound never under-reports
        assert got <= exact * (1 + 1 / 32) + 1     # within one sub-bucket
    assert h.max == data.max() and h.min == data.min() and h.count == len(data)


def test_small_values_exact_and_edge_cases():
    h = LatencyHistogram()
    assert h.percentile(0.5) == 0 and h.summary_us()["p50"] is None
    for v in (5, 5, 7, 63, -3):
        h.record(v)
    assert h.min == 0 and h.max == 63
    assert h.percentile(0.5) == 5
    assert h.percentile(1.0) == 63 and h.percentile(0) == 0


def test_merge_and_windows():
    a, b = LatencyHistogram(), LatencyHistogram()
    for v in range(1000):
        a.record(v)
        b.record(v + 1000)
    a.merge(b)
    assert a.count == 2000 and a.max == 1999 and a.min == 0
    w = WindowedLatency("x")
    w.record(1000)
    assert w.summary()["window"]["partial"] and w.summary()["window"]["count"] == 1
    assert w.summary()["lifetime"]["count"] == 1
    w.roll()
    w.record(3000)
    s = w.summary()
    assert s["window"]["count"] == 1 and not s["window"]["partial"] and s["lifetime"]["count"] == 2
    w.roll()
    assert w.summary()["window"]["max"] == 3.0


@pytest.mark.parametrize("seed", range(5))
def test_vectorised_nanmedian_matches_numpy(seed):
    import warnings

    from marketintel.strategies.anomalies import nanmedian_rows
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(30, 1 + seed * 40))
    x[rng.random(x.shape) < 0.3] = np.nan
    x[0] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ref = np.nanmedian(x, axis=1)
    assert np.allclose(nanmedian_rows(x), ref, equal_nan=True)
