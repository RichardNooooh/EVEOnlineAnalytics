"""In-memory, keyed descriptor exploration; no plotting or persistence.

Input keys are unique tuples, with their focal week start supplied separately.
Rows with nonfinite active features are ineligible. Callers build the weekly bank.
"""

import hashlib
import json
import secrets
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_samples
from sklearn.preprocessing import StandardScaler

MAGNITUDES = frozenset(
    (
        "price_log_change",
        "median_shift",
        "upward_excursion",
        "downward_excursion",
        "mean_relative_range",
        "terminal_settling",
        "price_activity_alignment",
        "focal_prior_price",
        "next_prior_price",
    )
)
RATIOS = frozenset(("volume_ratio", "order_count_ratio", "next_volume_ratio", "next_order_count_ratio"))


def _id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _run_record(run_id, rep_id, rep, k, params, seed, keys):
    """Initialize a clustering record with its representation's status."""
    return {
        "id": run_id,
        "representation_id": rep_id,
        "k": k,
        "params": params,
        "seed": seed,
        "status": rep["status"],
        "reason": rep["reason"],
        "keys": keys,
        "fit_seconds": 0.0,
    }


def _failed(record, exc, *, started=None):
    """Record failure, preserving an already measured fit-only duration."""
    if started is not None and not record["fit_seconds"]:
        record["fit_seconds"] = perf_counter() - started
    record.update(status="failed", reason=f"{type(exc).__name__}: {exc}")


def _notify(progress, record):
    if progress is not None:
        progress(record)


def prepare(raw, features, *, fit_rows=None, bound_ratios=True, strength=1.5):
    """Fit on fit_rows and transform all rows; returns transformed matrix and scaler.

    All passed rows must be finite. Filter eligibility before calling. Constant
    training columns are rejected, matching the notebook's full-fit behavior.
    """
    x = np.asarray(raw, dtype=float)
    if x.ndim != 2 or x.shape[1] != len(features) or not np.isfinite(x).all():
        raise ValueError("Expected finite rows matching feature names")
    if not np.isfinite(strength) or strength <= 0:
        raise ValueError("Transformation strength must be finite and positive")
    if len(set(features)) != len(features):
        raise ValueError("Duplicate features")
    train = x if fit_rows is None else x[fit_rows]
    if len(train) == 0 or np.any(np.std(train, axis=0) == 0):
        raise ValueError("Empty training set or constant features")
    scaler = StandardScaler().fit(train)
    z = scaler.transform(x)
    mi = [i for i, f in enumerate(features) if f in MAGNITUDES]
    ri = [i for i, f in enumerate(features) if f in RATIOS]
    z[:, mi] = strength * np.arcsinh(z[:, mi] / strength)
    if bound_ratios:
        if np.any(x[:, ri] < 0):
            raise ValueError("Activity ratios must be nonnegative")
        z[:, ri] = (x[:, ri] - 1) / (x[:, ri] + 1)
    return z, scaler


def calendar_split(weeks):
    """Last 20% of distinct focal weeks validate; purge overlapping 21-day support."""
    days = np.asarray(weeks, dtype="datetime64[D]")
    if np.isnat(days).any():
        raise ValueError("Missing week start")
    unique = np.unique(days)
    if len(unique) < 2:
        raise ValueError("Calendar validation requires multiple weeks")
    n = max(1, int(np.ceil(len(unique) * 0.2)))
    validation = np.isin(days, unique[-n:])
    # [week-7, week+13] inclusive. Compare against every validation support.
    overlap = np.zeros(len(days), dtype=bool)
    for d in unique[-n:]:
        overlap |= (days - np.timedelta64(7, "D") <= d + np.timedelta64(13, "D")) & (
            days + np.timedelta64(13, "D") >= d - np.timedelta64(7, "D")
        )
    train = ~overlap
    if not train.any():
        raise ValueError("No training rows remain after calendar support purge")
    return train, validation


@dataclass(frozen=True)
class Settings:
    """Fit grids and advisory budgets; method grids override legacy dimensions.

    With neither override, PCA uses (3, 6, 10), UMAP and AE use (3, 6).
    The default full-width PCA is skipped when the prepared control is selected;
    an explicit dimension grid can request it. Budgets never limit execution.
    """

    dimensions: tuple | None = None
    clusters: tuple = (3, 4, 6, 8, 12)
    neighbors: tuple = (15, 50, 150)
    methods: tuple = ("prepared", "pca", "umap", "ae")
    ae_enabled: bool = False
    ae_weight_decays: tuple = (1e-4,)
    seed: int | None = 42  # None creates and retains a random master seed
    repetitions: int = 1
    bound_ratios: bool = True
    strength: float = 1.5
    umap_min_dist: float = 0.1
    kmeans_n_init: int = 5
    ae_max_epochs: int = 100
    ae_patience: int = 10
    pca_dimensions: tuple | None = None
    umap_dimensions: tuple | None = None
    ae_dimensions: tuple | None = None
    learned_representation_budget: int = 10
    clustering_budget: int = 60


def _validate_grid_duplicates(settings):
    for name in (
        "methods",
        "dimensions",
        "pca_dimensions",
        "umap_dimensions",
        "ae_dimensions",
        "neighbors",
        "clusters",
        "ae_weight_decays",
    ):
        values = getattr(settings, name)
        if values is not None and len(set(values)) != len(values):
            raise ValueError(f"Duplicate entries in {name} grid")


def _dimensions(settings, method):
    specific = getattr(settings, f"{method}_dimensions")
    if specific is not None:
        return specific
    if settings.dimensions is not None:
        return settings.dimensions
    return (3, 6, 10) if method == "pca" else (3, 6)


def _valid_dimension(dim, width):
    return isinstance(dim, (int, np.integer)) and 0 < dim <= width


def _duplicate_default_pca(settings, method, dim, width):
    return (
        method == "pca"
        and dim == width
        and "prepared" in settings.methods
        and settings.dimensions is None
        and settings.pca_dimensions is None
    )


def _budget_report(settings, learned, clustering):
    return {
        "learned_representation_budget": settings.learned_representation_budget,
        "clustering_budget": settings.clustering_budget,
        "learned_representation_over_budget": learned > settings.learned_representation_budget,
        "clustering_over_budget": clustering > settings.clustering_budget,
    }


def plan(raw, settings=Settings()):
    """Estimate work before fitting from a descriptor matrix and batch settings.

    Counts are planned attempts, not guaranteed successes. Learned fits exclude
    the unreduced space, disabled methods, invalid dimensions and default full PCA
    duplicated by the control. Clustering counts include each prepared repetition.
    Budget flags apply to this plan only. Memory excludes models and temporaries.
    """
    _validate_grid_duplicates(settings)
    raw = np.asarray(raw, dtype=float)
    if raw.ndim != 2:
        raise ValueError("Expected a two-dimensional descriptor matrix")
    eligible = int(np.isfinite(raw).all(axis=1).sum())
    enabled = skipped = invalid = duplicate = embedding_width = 0
    spaces = int("prepared" in settings.methods)
    for method in settings.methods:
        if method == "prepared":
            continue
        multiplier = (
            len(settings.neighbors) if method == "umap" else len(settings.ae_weight_decays) if method == "ae" else 1
        )
        dimensions = _dimensions(settings, method)
        count = len(dimensions) * multiplier * settings.repetitions
        if method == "ae" and not settings.ae_enabled:
            skipped += count
        else:
            valid_width = [dim for dim in dimensions if _valid_dimension(dim, raw.shape[1])]
            valid = [dim for dim in valid_width if not _duplicate_default_pca(settings, method, dim, raw.shape[1])]
            invalid += (len(dimensions) - len(valid_width)) * multiplier * settings.repetitions
            duplicate += (len(valid_width) - len(valid)) * multiplier * settings.repetitions
            enabled += len(valid) * multiplier * settings.repetitions
            embedding_width += sum(valid) * multiplier * settings.repetitions
    skipped += invalid + duplicate
    clustering = (enabled + spaces * settings.repetitions) * len(settings.clusters)
    return {
        "input_rows": len(raw),
        "eligible_rows": eligible,
        "representation_fits": enabled,
        "learned_representation_fits": enabled,
        "unreduced_spaces": spaces,
        "representation_skipped": skipped,
        "invalid_dimension_skipped": invalid,
        "duplicate_full_pca_skipped": duplicate,
        "clustering_fits": clustering,
        "clustering_skipped": skipped * len(settings.clusters),
        **_budget_report(settings, enabled, clustering),
        "prepared_bytes": eligible * raw.shape[1] * 8,
        "embedding_bytes_approx": eligible * embedding_width * 8,
        "memory_note": "Excludes models, assignments, distances and temporary allocations.",
        "runtime": "Unknown without calibration; UMAP compilation and AE training can dominate.",
    }


def _fit_params(method, dim, option, repetition, settings):
    params = {"method": method, "dimension": dim, "repetition": repetition}
    if method == "pca":
        params.update(whiten=False)
    elif method == "umap":
        params.update(neighbors=option, min_dist=settings.umap_min_dist, metric="euclidean")
    else:
        params.update(
            architecture=["features", 32, 16, dim, 16, 32, "features"],
            hidden_activation="relu",
            bottleneck_activation="linear",
            output_activation="linear",
            optimizer="adam",
            learning_rate=0.001,
            weight_decay=option,
            loss="mse",
            batch_size=256,
            max_epochs=settings.ae_max_epochs,
            patience=settings.ae_patience,
            validation="last 20% of calendar weeks; 21-day support purge",
            refit="full data for best validation epoch",
            device="cpu",
        )
    return params


@dataclass
class Batch:
    master_seed: int
    population_id: str
    keys: tuple
    features: tuple
    eligible: np.ndarray
    prepared: np.ndarray
    sample_indices: np.ndarray
    weeks: np.ndarray
    input_metadata: object
    transformation: dict
    representations: dict = field(default_factory=dict)
    runs: dict = field(default_factory=dict)
    estimate: dict = field(default_factory=dict)

    def run(self, run_id):
        """Retrieve retained results without fitting or generating seeds."""
        return self.runs[run_id]


@dataclass
class Execution:
    """One retained fit and the caller's matching input snapshots.

    ``options`` captures fit arguments outside Settings, such as DTW controls.
    ``cache`` belongs solely to this execution, even when run IDs overlap.
    """

    id: str
    created_at: datetime
    label: str | None
    settings: Settings
    resolved_seed: int
    batch: Batch
    preparation: object
    source: object
    options: dict
    cache: dict = field(default_factory=dict)


class ExecutionRegistry:
    """In-memory retained fits; selection and deletion never trigger fitting.

    Call retain immediately after a fit, passing the settings and snapshots used
    for that fit. Snapshots and options are copied to isolate later input edits.
    Retaining does not change the active selection.
    """

    def __init__(self):
        self._executions = {}
        self._active_id = None

    def retain(self, batch, settings, *, preparation, source, label=None, options=None):
        execution = Execution(
            id=uuid4().hex,
            created_at=datetime.now(UTC),
            label=label,
            settings=deepcopy(settings),
            resolved_seed=batch.master_seed,
            batch=batch,
            preparation=deepcopy(preparation),
            source=deepcopy(source),
            options=deepcopy(options) if options is not None else {},
        )
        self._executions[execution.id] = execution
        return execution

    def list(self):
        """Return retained executions in creation order."""
        return tuple(self._executions.values())

    def get(self, execution_id):
        return self._executions[execution_id]

    @property
    def active_id(self):
        return self._active_id

    @property
    def active(self):
        return None if self._active_id is None else self.get(self._active_id)

    def select(self, execution_id):
        """Select a retained execution, or clear the selection with None."""
        execution = None if execution_id is None else self.get(execution_id)
        self._active_id = execution_id
        return execution

    def delete(self, execution_ids):
        """Delete listed executions atomically; active and unknown IDs are rejected."""
        ids = set(execution_ids)
        if self._active_id is not None and self._active_id in ids:
            raise ValueError("Cannot delete the active execution")
        for execution_id in ids:
            if execution_id not in self._executions:
                raise KeyError(execution_id)
        for execution_id in ids:
            del self._executions[execution_id]


def _seed(master, *parts):
    return int(_id([master, *parts])[:8], 16)


def _ae(raw, features, weeks, dim, seed, settings, weight_decay):
    # Optional dependency is deliberately imported only when enabled.
    import torch
    from torch import nn

    train, val = calendar_split(weeks)
    x, scaler = prepare(raw, features, fit_rows=train, bound_ratios=settings.bound_ratios, strength=settings.strength)
    torch.manual_seed(seed)

    def model():
        return nn.Sequential(
            nn.Linear(x.shape[1], 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, dim),
            nn.Linear(dim, 16),
            nn.ReLU(),
            nn.Linear(16, 32),
            nn.ReLU(),
            nn.Linear(32, x.shape[1]),
        )

    def optimize(net, data, epochs, validation=None):
        opt = torch.optim.Adam(net.parameters(), lr=0.001, weight_decay=weight_decay)
        gen = torch.Generator().manual_seed(seed)
        best, best_epoch, stale = float("inf"), 0, 0
        best_state = None
        history = []
        for epoch in range(epochs):
            net.train()
            for ix in torch.randperm(len(data), generator=gen).split(256):
                opt.zero_grad()
                loss = ((net(data[ix]) - data[ix]) ** 2).mean()
                loss.backward()
                opt.step()
            if validation is not None:
                net.eval()
                with torch.no_grad():
                    score = float(((net(validation) - validation) ** 2).mean())
                history.append(score)
                if score < best:
                    best, best_epoch, stale = score, epoch + 1, 0
                    best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
                else:
                    stale += 1
                    if stale >= settings.ae_patience:
                        break
        if best_state is not None:
            net.load_state_dict(best_state)
        return best_epoch, history

    net = model()
    best_epoch, history = optimize(
        net,
        torch.tensor(x[train], dtype=torch.float32),
        settings.ae_max_epochs,
        torch.tensor(x[val], dtype=torch.float32),
    )

    def reconstruction_summary(network, values):
        tensor = torch.tensor(values, dtype=torch.float32)
        network.eval()
        with torch.no_grad():
            squared_error = (network(tensor) - tensor).square()
            return {
                "features": tuple(features),
                "units": "squared prepared-coordinate units",
                "count": len(values),
                "mse_by_feature": squared_error.mean(dim=0).tolist(),
                "mse": float(squared_error.mean()),
            }

    validation_reconstruction = reconstruction_summary(net, x[val])
    full, full_scaler = prepare(raw, features, bound_ratios=settings.bound_ratios, strength=settings.strength)
    torch.manual_seed(seed)
    net = model()
    optimize(net, torch.tensor(full, dtype=torch.float32), best_epoch)
    net.eval()
    with torch.no_grad():
        embedding = net[:5](torch.tensor(full, dtype=torch.float32)).numpy()
    full_reconstruction = reconstruction_summary(net, full)
    return (
        embedding,
        net,
        {
            "best_epoch": best_epoch,
            "best_validation_loss": min(history),
            "validation_loss": history,
            "reconstruction": {
                "full": full_reconstruction,
                "validation": validation_reconstruction,
            },
            "torch_version": torch.__version__,
            "device": "cpu",
            "train_mask": train,
            "validation_mask": val,
            "validation_scaler_mean": scaler.mean_.copy(),
            "validation_scaler_scale": scaler.scale_.copy(),
            "full_scaler_mean": full_scaler.mean_.copy(),
            "full_scaler_scale": full_scaler.scale_.copy(),
            "preprocessing": {
                "features": tuple(features),
                "bound_ratios": settings.bound_ratios,
                "strength": settings.strength,
            },
        },
    )


def _diagnostics(x, labels, sample, *, precomputed=False):
    labels = np.asarray(labels)
    unique, counts = np.unique(labels, return_counts=True)
    out = {
        "group_counts": dict(zip(unique.tolist(), counts.tolist(), strict=True)),
        "largest_fraction": float(counts.max() / len(labels)),
        "silhouette": None,
        "silhouette_reason": None,
        "sample_silhouette": None,
    }
    sampled = labels[sample]
    if len(np.unique(sampled)) < 2 or len(np.unique(sampled)) >= len(sampled):
        out["silhouette_reason"] = "sample requires 2 through n-1 distinct groups"
    else:
        values = x[np.ix_(sample, sample)] if precomputed else x[sample]
        vals = silhouette_samples(values, sampled, metric="precomputed" if precomputed else "euclidean")
        out["silhouette"] = float(vals.mean())
        out["sample_silhouette"] = vals
    return out


def explore(
    keys,
    raw,
    features,
    weeks,
    settings=Settings(),
    *,
    input_metadata=None,
    progress=None,
    seed_namespace=None,
    shared_preprocessing=None,
):
    """Fit configured representations once each, then cluster; return a Batch.

    keys, raw and weeks are positionally aligned; keys must be unique. Every
    representation and run retains exactly the eligible population in this order.
    input_metadata describes observation and preparation provenance, not fitting
    controls; it is snapshotted and contributes to population identity.
    progress, if supplied, receives each completed representation or run record.
    An explicit seed_namespace pairs seeds across comparable treatment populations;
    population and run identities still include their actual inputs. The default
    preserves the population-derived seed schedule.
    shared_preprocessing supplies already prepared columns and scaler statistics
    for unchanged coordinates in a matched population. AE is not supported with
    this override because its internal validation has separate preprocessing.
    """
    keys = tuple(tuple(k) if isinstance(k, (tuple, list)) else (k,) for k in keys)
    features = tuple(features)
    raw = np.asarray(raw, dtype=float)
    weeks = np.asarray(weeks, dtype="datetime64[D]")
    if raw.ndim != 2 or raw.shape != (len(keys), len(features)) or len(weeks) != len(keys):
        raise ValueError("Key, feature, and week populations must align")
    if len(set(keys)) != len(keys) or np.isnat(weeks).any():
        raise ValueError("Keys must be unique and weeks present")
    if settings.repetitions < 1 or settings.ae_max_epochs < 1 or settings.ae_patience < 1:
        raise ValueError("Repetitions, epochs and patience must be positive")
    if not set(settings.methods) <= {"prepared", "pca", "umap", "ae"}:
        raise ValueError("Unknown representation method")
    if settings.kmeans_n_init < 1 or not 0 <= settings.umap_min_dist <= 1:
        raise ValueError("Invalid KMeans n_init or UMAP min_dist")
    if (
        not settings.ae_weight_decays
        or any(not np.isfinite(value) or value < 0 for value in settings.ae_weight_decays)
        or len(set(settings.ae_weight_decays)) != len(settings.ae_weight_decays)
    ):
        raise ValueError("AE weight decays must be distinct, finite and nonnegative")
    estimate = plan(raw, settings)
    mask = np.isfinite(raw).all(axis=1)
    eligible_keys = tuple(k for k, keep in zip(keys, mask, strict=True) if keep)
    raw = raw[mask]
    weeks = weeks[mask]
    prepared, scaler = prepare(raw, features, bound_ratios=settings.bound_ratios, strength=settings.strength)
    if shared_preprocessing is not None:
        if "ae" in settings.methods and settings.ae_enabled:
            raise ValueError("shared preprocessing is not supported for AE")
        for feature, reference in shared_preprocessing.items():
            if feature not in features:
                raise ValueError("shared preprocessing feature is not active")
            index = features.index(feature)
            values = np.asarray(reference["prepared"], dtype=float)
            mean, scale = float(reference["mean"]), float(reference["scale"])
            if (
                values.shape != (len(raw),)
                or not np.isfinite(values).all()
                or not np.isfinite(mean)
                or not np.isfinite(scale)
                or scale <= 0
            ):
                raise ValueError("invalid shared preprocessing")
            prepared[:, index] = values
            scaler.mean_[index], scaler.scale_[index] = mean, scale
    input_metadata = deepcopy(input_metadata)
    master = settings.seed if settings.seed is not None else secrets.randbits(32)
    population_id = _id(
        {
            "keys": eligible_keys,
            "weeks": weeks.astype(str).tolist(),
            "raw": raw.tolist(),
            "features": features,
            "metadata": input_metadata,
            "bound_ratios": settings.bound_ratios,
            "strength": settings.strength,
        }
    )
    if shared_preprocessing is not None:
        population_id = _id([population_id, prepared.tolist(), scaler.mean_.tolist(), scaler.scale_.tolist()])
    seed_population = population_id if seed_namespace is None else seed_namespace
    sample = np.sort(
        np.random.default_rng(_seed(master, seed_population, "sample")).choice(
            len(raw), min(1000, len(raw)), replace=False
        )
    )
    batch = Batch(
        master,
        population_id,
        eligible_keys,
        features,
        mask,
        prepared,
        sample,
        weeks.copy(),
        input_metadata,
        {
            "bound_ratios": settings.bound_ratios,
            "strength": settings.strength,
            "mean": scaler.mean_.copy(),
            "scale": scaler.scale_.copy(),
        },
    )
    batch.estimate = estimate
    for repetition in range(settings.repetitions):
        for method in settings.methods:
            for dim in (prepared.shape[1],) if method == "prepared" else _dimensions(settings, method):
                options = (
                    settings.neighbors if method == "umap" else settings.ae_weight_decays if method == "ae" else (None,)
                )
                for option in options:
                    params = (
                        {"method": "prepared", "dimension": dim, "geometry": "euclidean"}
                        if method == "prepared"
                        else _fit_params(method, dim, option, repetition, settings)
                    )
                    seed_params = (
                        params
                        if seed_namespace is None or method != "prepared"
                        else {key: value for key, value in params.items() if key != "dimension"}
                    )
                    seed = _seed(master, seed_population, seed_params)
                    rep_id = _id([population_id, master, params, seed])
                    rep = batch.representations.get(rep_id) if method == "prepared" else None
                    new_rep = rep is None
                    if new_rep:
                        rep = {
                            "id": rep_id,
                            "params": params,
                            "seed": seed,
                            "status": "ok",
                            "reason": None,
                            "keys": eligible_keys,
                            "embedding": None,
                            "model": None,
                            "details": {},
                        }
                        batch.representations[rep_id] = rep
                    start = perf_counter()
                    try:
                        if not new_rep:
                            pass
                        elif method == "ae" and not settings.ae_enabled:
                            rep.update(status="skipped", reason="autoencoder disabled")
                        elif method != "prepared" and not _valid_dimension(dim, prepared.shape[1]):
                            rep.update(
                                status="skipped", reason="dimension must be positive and no larger than input width"
                            )
                        elif _duplicate_default_pca(settings, method, dim, prepared.shape[1]):
                            rep.update(status="skipped", reason="full PCA duplicates the prepared-input control")
                        elif method == "prepared":
                            rep["embedding"] = prepared
                        elif method == "pca":
                            model = PCA(n_components=dim, whiten=False, random_state=seed)
                            rep["embedding"] = model.fit_transform(prepared)
                            rep["model"] = model
                        elif method == "umap":
                            from umap import UMAP

                            model = UMAP(
                                n_components=dim,
                                n_neighbors=option,
                                min_dist=settings.umap_min_dist,
                                metric="euclidean",
                                random_state=seed,
                            )
                            rep["embedding"] = model.fit_transform(prepared)
                            rep["model"] = model
                        else:
                            rep["embedding"], rep["model"], rep["details"] = _ae(
                                raw, features, weeks, dim, seed, settings, option
                            )
                    except Exception as exc:
                        _failed(rep, exc)
                    if new_rep:
                        rep["fit_seconds"] = (
                            perf_counter() - start if rep["status"] != "skipped" and method != "prepared" else 0.0
                        )
                        _notify(progress, rep)
                    for k in settings.clusters:
                        cluster_params = {"method": "kmeans", "n_clusters": k, "n_init": settings.kmeans_n_init}
                        if method == "prepared":
                            cluster_params["repetition"] = repetition
                        cluster_seed = (
                            _seed(master, rep_id, cluster_params)
                            if seed_namespace is None
                            else _seed(master, seed_population, seed_params, cluster_params)
                        )
                        run_id = _id([rep_id, cluster_params, cluster_seed])
                        run = _run_record(run_id, rep_id, rep, k, cluster_params, cluster_seed, eligible_keys)
                        batch.runs[run_id] = run
                        if rep["status"] != "ok":
                            _notify(progress, run)
                            continue
                        start = perf_counter()
                        try:
                            model = KMeans(n_clusters=k, n_init=settings.kmeans_n_init, random_state=cluster_seed)
                            labels = model.fit_predict(rep["embedding"])
                            run["fit_seconds"] = perf_counter() - start
                            distances = model.transform(rep["embedding"])
                            run.update(
                                status="ok",
                                model=model,
                                assignments=labels,
                                centroid_distances=distances,
                                native=_diagnostics(rep["embedding"], labels, sample),
                                common_input=_diagnostics(prepared, labels, sample),
                            )
                        except Exception as exc:
                            _failed(run, exc, started=start)
                        _notify(progress, run)
    return batch


def path_plan(paths, settings=Settings(), *, include_dtw=False):
    """Estimate a caller-selected joint-path batch before any distance computation."""
    _validate_grid_duplicates(settings)
    tensor = np.asarray(paths.tensor)
    if tensor.ndim != 3:
        raise ValueError("Expected a three-dimensional path tensor")
    n, days, channels = tensor.shape
    repetitions = settings.repetitions
    return {
        "input_rows": n,
        "eligible_rows": n,
        "aligned_dimension": days * channels,
        "representation_fits": 1 + int(include_dtw),
        "learned_representation_fits": 0,
        "unreduced_spaces": 1,
        "representation_skipped": int(not include_dtw),
        "invalid_dimension_skipped": 0,
        "duplicate_full_pca_skipped": 0,
        "clustering_fits": (1 + int(include_dtw)) * repetitions * len(settings.clusters),
        "clustering_skipped": int(not include_dtw) * repetitions * len(settings.clusters),
        **_budget_report(settings, 0, (1 + int(include_dtw)) * repetitions * len(settings.clusters)),
        "prepared_bytes": tensor.nbytes,
        "pairwise_bytes": n * n * np.dtype(np.float64).itemsize,
        "memory_note": "Pairwise bytes apply only when DTW is enabled; excludes clustering, diagnostics and temporary allocations.",
        "runtime": "Unknown without calibration; DTW is quadratic in path count and JIT compilation adds uncertainty.",
    }


def _medoids(distance, k, seed, max_iter, *, initial_indices=None):
    """Seeded alternating medoids; retain each medoid in its own group on ties."""
    n = len(distance)
    if not 1 <= k <= n or max_iter < 1:
        raise ValueError("Medoid count must be between 1 and population size; max_iter must be positive")
    medoids = (
        np.random.default_rng(seed).choice(n, k, replace=False)
        if initial_indices is None
        else np.asarray(initial_indices, dtype=int).copy()
    )
    if medoids.shape != (k,) or len(set(medoids)) != k or np.any(medoids < 0) or np.any(medoids >= n):
        raise ValueError("Initial medoids must be distinct valid observation indices")
    converged = False
    for iteration in range(1, max_iter + 1):
        iterations = iteration
        labels = np.argmin(distance[:, medoids], axis=1)
        labels[medoids] = np.arange(k)
        updated = np.array(
            [
                members[np.argmin(distance[np.ix_(members, members)].sum(axis=1))]
                for members in (np.flatnonzero(labels == group) for group in range(k))
            ]
        )
        if np.array_equal(updated, medoids):
            converged = True
            break
        medoids = updated
    labels = np.argmin(distance[:, medoids], axis=1)
    labels[medoids] = np.arange(k)
    objective = float(distance[np.arange(n), medoids[labels]].sum())
    return labels, medoids, {"iterations": iterations, "converged": converged, "objective": objective}


def compare_path_medoids(paths, *, clusters=(4, 8), dtw_band=2, max_iter=100, starts=3, seed=42):
    """Compare paired aligned and dependent-DTW medoids on the caller-selected paths.

    No sampling or scaling occurs. Each method and K retains every restart, with
    paired starts sharing initial keys. Selection minimizes each method's objective
    among its converged restarts only; objectives are not comparable across methods.
    Distance-matrix and restart failures remain visible in the returned records.
    """
    from sklearn.metrics import pairwise_distances

    from .behavior_paths import JointPaths, pairwise_dtw

    if not isinstance(paths, JointPaths):
        raise TypeError("paths must be a JointPaths instance")
    tensor = np.asarray(paths.tensor, dtype=float)
    if tensor.ndim != 3 or any(size == 0 for size in tensor.shape) or not np.isfinite(tensor).all():
        raise ValueError("Expected a nonempty finite path tensor")
    if len(paths.keys) != len(tensor) or paths.keys.isna().any().any() or paths.keys.duplicated().any():
        raise ValueError("Path keys must uniquely align with tensor rows")
    scales = np.asarray(paths.scales, dtype=float)
    if (
        len(paths.channels) != tensor.shape[2]
        or len(paths.transforms) != tensor.shape[2]
        or scales.shape != (tensor.shape[2],)
        or not np.isfinite(scales).all()
        or np.any(scales <= 0)
    ):
        raise ValueError("Path channel metadata and positive finite scales must match tensor")
    clusters = tuple(clusters)
    if (
        not clusters
        or len(set(clusters)) != len(clusters)
        or any(not isinstance(k, (int, np.integer)) or not 1 <= k <= len(tensor) for k in clusters)
        or not isinstance(starts, int)
        or starts < 1
        or not isinstance(max_iter, int)
        or max_iter < 1
        or not isinstance(dtw_band, int)
        or dtw_band < 0
        or not isinstance(seed, int)
        or seed < 0
    ):
        raise ValueError("Invalid clusters, starts, seed, iteration limit, or DTW band")
    keys = tuple(paths.keys.itertuples(index=False, name=None))
    provenance = {
        "keys": keys,
        "key_columns": tuple(paths.keys.columns),
        "channels": tuple(paths.channels),
        "transforms": tuple(paths.transforms),
        "scales": scales.tolist(),
        "subset_seed": paths.subset_seed,
    }
    population_id = _id({"tensor": tensor.tolist(), "provenance": provenance})
    matrices = {}
    distances = {}
    for method in ("aligned", "dtw"):
        start = perf_counter()
        try:
            matrix = (
                pairwise_distances(tensor.reshape(len(tensor), -1))
                if method == "aligned"
                else pairwise_dtw(tensor, band=dtw_band)
            )
            if np.asarray(matrix).shape != (len(tensor), len(tensor)) or not np.isfinite(matrix).all():
                raise ValueError("Distance matrix must be finite and match the population")
            matrices[method] = matrix
            distances[method] = {"status": "ok", "reason": None}
        except Exception as exc:
            distances[method] = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        distances[method]["fit_seconds"] = perf_counter() - start
    groups = {}
    for k in clusters:
        groups[k] = {}
        paired = []
        for restart in range(starts):
            init_seed = _seed(seed, population_id, {"k": k, "restart": restart, "purpose": "paired_medoids"})
            indices = np.random.default_rng(init_seed).choice(len(keys), k, replace=False)
            paired.append((init_seed, indices))
        for method in ("aligned", "dtw"):
            records = []
            for restart, (init_seed, indices) in enumerate(paired):
                record = {
                    "restart": restart,
                    "seed": init_seed,
                    "initial_medoid_keys": tuple(keys[i] for i in indices),
                    "status": "failed",
                    "reason": distances[method]["reason"],
                    "converged": None,
                    "objective": None,
                    "assignments": None,
                    "medoid_keys": None,
                    "fit_seconds": 0.0,
                }
                if method in matrices:
                    start = perf_counter()
                    try:
                        labels, medoids, details = _medoids(
                            matrices[method], k, init_seed, max_iter, initial_indices=indices
                        )
                        record.update(
                            status="ok" if details["converged"] else "optimization-incomplete",
                            reason=None if details["converged"] else "Medoid optimization did not converge",
                            assignments=labels,
                            medoid_keys=tuple(keys[i] for i in medoids),
                            **details,
                        )
                    except Exception as exc:
                        record["reason"] = f"{type(exc).__name__}: {exc}"
                    record["fit_seconds"] = perf_counter() - start
                records.append(record)
            converged = [r for r in records if r["status"] == "ok" and r["converged"]]
            best = min(converged, key=lambda r: r["objective"]) if converged else None
            groups[k][method] = {
                "status": "ok" if best is not None else "optimization-incomplete",
                "best_restart": best["restart"] if best else None,
                "restarts": records,
            }
    return {
        "population_id": population_id,
        "provenance": provenance,
        "seed": seed,
        "clusters": clusters,
        "starts": starts,
        "dtw_band": dtw_band,
        "max_iter": max_iter,
        "distances": distances,
        "groups": groups,
    }


def explore_paths(
    paths,
    settings=Settings(),
    *,
    include_dtw=False,
    dtw_band=2,
    medoid_max_iter=100,
    input_metadata=None,
    progress=None,
    seed_namespace=None,
):
    """Fit aligned KMeans and optionally dependent-DTW medoids on exactly paths.keys.

    No sampling or scaling is performed. Select any matched subset before calling.
    The single DTW matrix is shared by all cluster counts and repetitions.
    input_metadata describes observation and preparation provenance, not fitting
    controls; it is snapshotted and contributes to population identity. Pass DTW
    and medoid controls explicitly so only relevant identities depend on them.
    An explicit seed_namespace pairs cluster seeds across treatment populations;
    the default retains the population-derived schedule and identities.
    """
    from .behavior_paths import JointPaths, pairwise_dtw

    if not isinstance(paths, JointPaths):
        raise TypeError("paths must be a JointPaths instance")
    tensor = np.asarray(paths.tensor, dtype=float)
    if tensor.ndim != 3 or any(size == 0 for size in tensor.shape) or not np.isfinite(tensor).all():
        raise ValueError("Expected a nonempty finite path tensor")
    if len(paths.keys) != len(tensor) or paths.keys.isna().any().any() or paths.keys.duplicated().any():
        raise ValueError("Path keys must uniquely align with tensor rows")
    if len(paths.channels) != tensor.shape[2] or len(paths.transforms) != tensor.shape[2]:
        raise ValueError("Path channel metadata must match tensor")
    scales = np.asarray(paths.scales, dtype=float)
    if scales.shape != (tensor.shape[2],) or not np.isfinite(scales).all() or np.any(scales <= 0):
        raise ValueError("Path scales must be finite, positive and match channels")
    if (
        settings.repetitions < 1
        or settings.kmeans_n_init < 1
        or not isinstance(dtw_band, int)
        or dtw_band < 0
        or medoid_max_iter < 1
    ):
        raise ValueError("Invalid repetitions, clustering settings, or DTW settings")
    keys = tuple(paths.keys.itertuples(index=False, name=None))
    metadata = {
        "family": "joint_paths",
        "key_columns": tuple(paths.keys.columns),
        "channels": tuple(paths.channels),
        "transforms": tuple(paths.transforms),
        "scales": scales.tolist(),
        "subset_seed": paths.subset_seed,
        "caller": deepcopy(input_metadata),
    }
    population_id = _id({"keys": keys, "tensor": tensor.tolist(), "metadata": metadata})
    master = settings.seed if settings.seed is not None else secrets.randbits(32)
    seed_population = population_id if seed_namespace is None else seed_namespace
    sample = np.sort(
        np.random.default_rng(_seed(master, seed_population, "sample")).choice(
            len(tensor), min(1000, len(tensor)), replace=False
        )
    )
    flat = tensor.reshape(len(tensor), -1).copy()
    weeks = paths.keys["start"].to_numpy() if "start" in paths.keys else np.full(len(keys), None)
    batch = Batch(
        master,
        population_id,
        keys,
        tuple(paths.channels),
        np.ones(len(keys), dtype=bool),
        flat,
        sample,
        weeks,
        metadata,
        {"scales": scales.copy(), "transforms": tuple(paths.transforms), "rescaled": False},
    )
    batch.estimate = path_plan(paths, settings, include_dtw=include_dtw)
    for method in ("aligned", "dtw"):
        params = (
            {"method": "aligned", "dimension": flat.shape[1], "geometry": "euclidean"}
            if method == "aligned"
            else {"method": "dtw", "band": dtw_band, "distance": "root_accumulated_squared_dependent_dtw"}
        )
        rep_id = _id([population_id, params])
        rep = {
            "id": rep_id,
            "params": params,
            "seed": None,
            "status": "ok",
            "reason": None,
            "keys": keys,
            "embedding": flat if method == "aligned" else None,
            "model": None,
            "details": {},
            "fit_seconds": 0.0,
        }
        batch.representations[rep_id] = rep
        if method == "dtw":
            if not include_dtw:
                rep.update(status="skipped", reason="dependent DTW disabled")
            else:
                start = perf_counter()
                try:
                    rep["distance_matrix"] = pairwise_dtw(tensor, band=dtw_band)
                except Exception as exc:
                    _failed(rep, exc)
                rep["fit_seconds"] = perf_counter() - start
        _notify(progress, rep)
        for repetition in range(settings.repetitions):
            for k in settings.clusters:
                cluster_params = (
                    {"method": "kmeans", "n_clusters": k, "n_init": settings.kmeans_n_init, "repetition": repetition}
                    if method == "aligned"
                    else {
                        "method": "alternating_medoids",
                        "n_clusters": k,
                        "max_iter": medoid_max_iter,
                        "repetition": repetition,
                    }
                )
                seed_params = {key: value for key, value in params.items() if key != "dimension"}
                seed = (
                    _seed(master, rep_id, cluster_params)
                    if seed_namespace is None
                    else _seed(master, seed_population, seed_params, cluster_params)
                )
                run_id = _id([rep_id, cluster_params, seed])
                run = _run_record(run_id, rep_id, rep, k, cluster_params, seed, keys)
                batch.runs[run_id] = run
                if rep["status"] == "ok":
                    start = perf_counter()
                    try:
                        if method == "aligned":
                            model = KMeans(n_clusters=k, n_init=settings.kmeans_n_init, random_state=seed)
                            labels = model.fit_predict(flat)
                            run["fit_seconds"] = perf_counter() - start
                            distances = model.transform(flat)
                            run["model"] = model
                            native = _diagnostics(flat, labels, sample)
                        else:
                            matrix = rep["distance_matrix"]
                            labels, medoids, details = _medoids(matrix, k, seed, medoid_max_iter)
                            run["fit_seconds"] = perf_counter() - start
                            distances = matrix[:, medoids]
                            run.update(
                                medoid_indices=medoids,
                                medoid_keys=tuple(keys[i] for i in medoids),
                                medoid_paths=tensor[medoids].copy(),
                                details=details,
                            )
                            native = _diagnostics(matrix, labels, sample, precomputed=True)
                        run.update(
                            assignments=labels,
                            centroid_distances=distances,
                            native=native,
                            common_input=_diagnostics(flat, labels, sample),
                        )
                        if method == "dtw" and not details["converged"]:
                            run.update(status="optimization-incomplete", reason="Medoid optimization did not converge")
                    except Exception as exc:
                        _failed(run, exc, started=start)
                _notify(progress, run)
    return batch
