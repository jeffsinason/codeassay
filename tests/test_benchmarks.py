from codeassay.turnover import load_benchmarks, Benchmarks


def test_load_benchmarks_returns_expected_shape():
    b = load_benchmarks()
    assert isinstance(b, Benchmarks)
    assert b.pre_ai_baseline == 0.033
    assert b.industry_2026 == 0.057
    assert b.healthy_target == 0.04
    assert isinstance(b.sources, list)
    assert len(b.sources) >= 1


def test_benchmark_values_are_sensible():
    b = load_benchmarks()
    assert 0 < b.pre_ai_baseline < b.healthy_target < b.industry_2026 < 1.0
