"""Run synthetic counterfactual tests while refusing real PolicyEngine imports."""

import importlib.abc
import importlib.metadata
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.dont_write_bytecode = True


def _is_policyengine_module(name):
    return (
        name == "policyengine"
        or name.startswith("policyengine.")
        or name.startswith("policyengine_")
    )


class NoPolicyEngineImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if _is_policyengine_module(fullname):
            raise RuntimeError("Country/Core/model import forbidden: " + fullname)
        return None


def _check_loaded_modules():
    if any(_is_policyengine_module(name) for name in sys.modules):
        raise RuntimeError("A forbidden PolicyEngine module is already loaded")


sys.meta_path.insert(0, NoPolicyEngineImports())
_check_loaded_modules()
if sys.argv[1:]:
    raise RuntimeError("This runner accepts no test-path or pytest overrides")
if sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 13, 13):
    raise RuntimeError("The pure-test job requires CPython 3.13.13")
expected_versions = {
    "pytest": "9.2.0",
    "hypothesis": "6.170.15",
    "iniconfig": "2.3.1",
    "packaging": "26.3",
    "pluggy": "1.7.0",
    "pygments": "2.21.0",
    "sortedcontainers": "2.4.0",
}
for name, expected in expected_versions.items():
    if importlib.metadata.version(name) != expected:
        raise RuntimeError("Unexpected pure-test dependency version: " + name)

root = Path(__file__).resolve().parents[1]
if Path.cwd().resolve() != root:
    raise RuntimeError("Run this script from the repository root")
if os.environ.get("PYTEST_ADDOPTS") or os.environ.get("PYTEST_PLUGINS"):
    raise RuntimeError("The pure-test runner refuses pytest environment overrides")
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
os.environ["CLIFFS_MAX_EXAMPLES"] = "60"
sys.path.insert(0, str(root))

with TemporaryDirectory(prefix="cliffs-pure-tests-") as cache:
    os.environ["HYPOTHESIS_STORAGE_DIRECTORY"] = str(Path(cache) / "hypothesis")
    import pytest

    print(
        "ISOLATED_PURE_RUNTIME", sys.version.split()[0], expected_versions, flush=True
    )
    result = pytest.main(
        [
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_native_currency.py",
            "tests/test_native_periods.py",
            "tests/test_commissioned.py",
            "tests/test_resource_accounts_fake.py",
            "tests/test_managed_native.py",
            "tests/test_native_materializer.py",
            "tests/test_native_witness.py",
            "tests/test_wage_benchmark.py",
            "tests/test_health_valuation.py",
            "tests/test_native_runtime.py",
            "tests/test_native_health_hooks.py",
        ]
    )
    _check_loaded_modules()
    print("COUNTRY_CORE_IMPORT_BLOCK_ENFORCED", flush=True)

raise SystemExit(result)
