"""Hypothesis profiles.

The local default stays fast enough to run on every save; CI turns the example count up
because the whole point of a property test is the input nobody thought of, and finding
it is a function of how many are tried.

``derandomize`` is on so a CI failure reproduces exactly from the reported seed.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, Phase, settings

settings.register_profile(
    "dev",
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "ci",
    max_examples=500,
    deadline=None,
    derandomize=True,
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.target, Phase.shrink],
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
