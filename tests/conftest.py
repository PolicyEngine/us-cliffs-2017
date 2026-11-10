import os

import pytest
from hypothesis import HealthCheck, settings

# Building the PolicyEngine-US system takes tens of seconds, so the
# property tests share one system and allow slow examples.
settings.register_profile(
    "cliffs",
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    max_examples=int(os.environ.get("CLIFFS_MAX_EXAMPLES", "60")),
)
settings.load_profile("cliffs")


@pytest.fixture(scope="session")
def system():
    from policyengine_us import CountryTaxBenefitSystem

    return CountryTaxBenefitSystem()


@pytest.fixture(scope="session")
def small_dataset():
    """About 300 Microcosm households (0.5% of the 2024 build), reweighted."""
    from huggingface_hub import hf_hub_download
    from policyengine_us.data.dataset_schema import USSingleYearDataset

    from cliffs2017.deflate import subsample
    from cliffs2017.run import FILENAME, REPO, REVISION

    path = hf_hub_download(REPO, FILENAME, repo_type="dataset", revision=REVISION)
    return subsample(USSingleYearDataset(path), 0.005, seed=1)
