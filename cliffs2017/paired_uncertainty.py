"""Paired source-household resampling of explicitly weighted contributions.

No model, data file or bootstrap runs on import. This measures conditional
source-cluster variability with calibration weights held fixed; it does not
measure policy-encoding, imputation or survey-design uncertainty.
"""

from dataclasses import dataclass
import math


class UncertaintyError(ValueError):
    """Lineage, weighting or paired contribution state is incomplete."""


def align_source_clusters(table, native_household_ids, household_index, *, namespace):
    """Align prepared household lineage by ID, never by assumed table row order.

    The caller source-qualifies namespace. Legacy asec/puf_tax_detail channels
    describe clone roles, so they must not split a shared source household.
    No clone index enters any cluster key.
    """
    import pandas as pd

    columns = {"household_id", "household_source_id", "household_support_channel"}
    if not columns.issubset(table.columns) or table[list(columns)].isna().any().any():
        raise UncertaintyError("Complete source household lineage is required")
    if table["household_id"].duplicated().any():
        raise UncertaintyError("Source household IDs must be unique")
    if not all(
        pd.api.types.is_integer_dtype(table[name].dtype)
        for name in ("household_id", "household_source_id")
    ):
        raise UncertaintyError(
            "Source lineage IDs must preserve their integer encoding"
        )
    ids = pd.Index(native_household_ids)
    if not pd.api.types.is_integer_dtype(ids.dtype):
        raise UncertaintyError("Native household IDs must preserve integer encoding")
    if (
        not ids.is_unique
        or len(ids) != len(table)
        or set(ids) != set(table["household_id"])
    ):
        raise UncertaintyError("Native and prepared full household cohorts differ")
    if len(household_index) != len(ids) or not household_index.is_unique:
        raise UncertaintyError("Bind the actual household contribution index")
    aligned = table.set_index("household_id").reindex(ids)
    channels = aligned["household_support_channel"].map(
        lambda value: value.decode("utf-8") if isinstance(value, bytes) else value
    )
    if not channels.map(lambda value: isinstance(value, str) and bool(value)).all():
        raise UncertaintyError("Source channels must be complete text labels")
    if namespace == "global_source_id":
        labels = aligned["household_source_id"].copy()
    elif namespace == "physical_channel_source_id":
        if (
            "household_spine_source_id" not in table
            and channels.isin({"asec", "puf_tax_detail"}).any()
        ):
            raise UncertaintyError(
                "Legacy operator channels would split clone siblings"
            )
        labels = pd.Series(
            list(zip(channels, aligned["household_source_id"])), index=ids
        )
    else:
        raise UncertaintyError("Declare the source-qualified cluster namespace")
    labels.index = household_index.copy()
    return labels


class HouseholdContributionSink:
    """Apply weights exactly once through maintained MicroSeries.weight().

    Its public method returns a plain pandas Series of weighted contributions.
    All subsequent grouping/dot products operate on that explicit weighted
    ledger, not on MicroSeries values with their weights stripped.
    """

    def __init__(self, clusters, *, is_weighted):
        import pandas as pd

        if (
            type(clusters) is not pd.Series
            or clusters.isna().any()
            or not clusters.index.is_unique
        ):
            raise UncertaintyError("Provide complete aligned source cluster labels")
        if not callable(is_weighted):
            raise UncertaintyError("Use the actual MicroSeries type predicate")
        self.clusters = clusters.copy(deep=True)
        self.is_weighted = is_weighted
        self._columns, self._points, self._mapped_points = {}, {}, {}

    def __call__(self, key, series, *, point_total=None):
        import pandas as pd

        if (
            not isinstance(key, tuple)
            or len(key) != 4
            or not all(isinstance(item, str) for item in key)
            or key in self._columns
        ):
            raise UncertaintyError("Use a unique amount/cutoff/scenario/metric key")
        if not self.is_weighted(series) or not series.index.equals(self.clusters.index):
            raise UncertaintyError(
                "Contributions must be aligned household MicroSeries"
            )
        if (
            series.isna().any()
            or ((series < 0) | (series == math.inf) | (series == -math.inf)).any()
        ):
            raise UncertaintyError("Count contributions must be finite and nonnegative")
        weighted = series.weight()
        if type(weighted) is not pd.Series or not weighted.index.equals(
            self.clusters.index
        ):
            raise UncertaintyError(
                "MicroSeries.weight must return its explicit weighted ledger"
            )
        if (
            weighted.isna().any()
            or ((weighted == math.inf) | (weighted == -math.inf)).any()
        ):
            raise UncertaintyError("Weighted contributions must also be finite")
        mapped_point = float(series.sum())
        if float(weighted.sum()) != mapped_point:
            raise UncertaintyError("Weighted ledger and MicroSeries.sum disagree")
        point = mapped_point if point_total is None else float(point_total)
        if not math.isfinite(point) or point < 0:
            raise UncertaintyError(
                "The original aggregate must be finite and nonnegative"
            )
        self._columns[key] = weighted.copy(deep=True)
        self._points[key], self._mapped_points[key] = point, mapped_point

    def cluster_totals(self):
        import pandas as pd

        if not self._columns:
            raise UncertaintyError("No actual contribution vectors were collected")
        ledger = pd.DataFrame(self._columns, index=self.clusters.index)
        return ledger.groupby(self.clusters, sort=False, dropna=False).sum()

    def point_totals(self):
        import pandas as pd

        return pd.Series(self._points, dtype=float)

    def mapping_residuals(self):
        """Keep any person-versus-household summation difference visible."""
        import pandas as pd

        return pd.Series(
            {key: self._points[key] - self._mapped_points[key] for key in self._points},
            dtype=float,
        )


def totals_from_multiplicities(cluster_totals, multiplicities):
    """Apply one common draw matrix to every already-weighted metric column."""
    import pandas as pd

    if (
        type(cluster_totals) is not pd.DataFrame
        or not cluster_totals.index.is_unique
        or len(cluster_totals) < 2
        or cluster_totals.isna().any().any()
    ):
        raise UncertaintyError("At least two complete source clusters are required")
    if ((cluster_totals == math.inf) | (cluster_totals == -math.inf)).any().any():
        raise UncertaintyError("Cluster totals must be finite already-weighted values")
    if not multiplicities.columns.equals(cluster_totals.index):
        raise UncertaintyError(
            "Resample counts must use the exact source cluster order"
        )
    if not all(pd.api.types.is_integer_dtype(dtype) for dtype in multiplicities.dtypes):
        raise UncertaintyError("Cluster multiplicities must be actual integers")
    if (multiplicities < 0).any().any() or not (
        multiplicities.sum(axis=1) == len(cluster_totals)
    ).all():
        raise UncertaintyError(
            "Each draw resamples exactly the full source-cluster count"
        )
    return multiplicities.dot(cluster_totals)


@dataclass(frozen=True)
class BootstrapResult:
    summary: object
    replicates: object
    contract: dict


def paired_cluster_bootstrap(
    cluster_totals, *, point_totals=None, draws=5000, seed=0, batch_size=128, rng=None
):
    """Future admitted aggregation: one common cluster draw across all metrics.

    The input is a plain already-weighted cluster ledger produced by the sink.
    Calibration weights remain fixed; no weight projection, model rerun or
    household microdata are read. Tests use tiny explicit toy draw matrices.
    """
    import numpy as np
    import pandas as pd

    if (
        type(draws) is not int
        or draws < 2
        or type(seed) is not int
        or seed < 0
        or type(batch_size) is not int
        or batch_size < 1
    ):
        raise UncertaintyError("Declare finite draws, seed and positive batch size")
    groups = len(cluster_totals)
    if (
        type(cluster_totals) is not pd.DataFrame
        or groups < 2
        or not cluster_totals.index.is_unique
        or cluster_totals.isna().any().any()
    ):
        raise UncertaintyError("At least two complete source clusters are required")
    generator = np.random.default_rng(seed) if rng is None else rng
    probabilities = np.full(groups, 1 / groups)
    batches = []
    for start in range(0, draws, batch_size):
        count = min(batch_size, draws - start)
        sampled = generator.multinomial(groups, probabilities, size=count)
        multiplicities = pd.DataFrame(sampled, columns=cluster_totals.index)
        batches.append(totals_from_multiplicities(cluster_totals, multiplicities))
    replicates = pd.concat(batches, ignore_index=True)
    point = cluster_totals.sum(axis=0) if point_totals is None else point_totals
    if not point.index.equals(cluster_totals.columns):
        raise UncertaintyError(
            "Original point totals must retain every metric in order"
        )
    summary = pd.DataFrame(
        {
            "point": point,
            "bootstrap_se": replicates.std(axis=0, ddof=1),
            "lower_95": replicates.quantile(0.025),
            "upper_95": replicates.quantile(0.975),
            "cluster_sum_residual": point - cluster_totals.sum(axis=0),
        }
    )
    return BootstrapResult(
        summary,
        replicates,
        {
            "method": "paired source-household cluster bootstrap; fixed calibration weights",
            "draws": draws,
            "seed": seed,
            "clusters": groups,
            "batch_size": batch_size,
            "common_resample_all_scenarios_cutoffs": True,
            "interval": "percentile95",
            "not_covered": "survey-design, imputation, calibration-fit and policy-encoding uncertainty",
        },
    )
