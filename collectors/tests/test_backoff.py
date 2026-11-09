import random

import pytest

from collectors.backoff import backoff_delays


def test_never_exceeds_cap():
    gen = backoff_delays(base=1, factor=2, cap=10, rng=random.Random(42))
    values = [next(gen) for _ in range(200)]
    assert all(0 <= v <= 10 for v in values)


def test_ceiling_grows():
    class MaxRng(random.Random):
        def uniform(self, a, b):
            return b

    gen = backoff_delays(base=1, factor=2, cap=10, rng=MaxRng())
    assert [next(gen) for _ in range(6)] == [1, 2, 4, 8, 10, 10]


@pytest.mark.parametrize("kwargs", [{"base": 0}, {"factor": 0.5}, {"base": 5, "cap": 1}])
def test_invalid_args(kwargs):
    with pytest.raises(ValueError):
        next(backoff_delays(**kwargs))
