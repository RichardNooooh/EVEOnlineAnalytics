import argparse

from eve_ingest.logging_config import log_cli_run_start

from eve_ingest.cli.config_builders import (
    build_ducklake_bootstrap_config,
    build_everef_config,
    build_everef_references_config,
)
from eve_ingest.util import (
    DEFAULT_DATA_ROOT,
    DEFAULT_DUCKLAKE_CATALOG,
    DEFAULT_DUCKLAKE_LOCK_WAIT_TIMEOUT_SECONDS,
    DEFAULT_DUCKLAKE_METADATA_SCHEMA,
    DEFAULT_DUCKLAKE_PG_POOL_ACQUIRE_MODE,
    DEFAULT_DUCKLAKE_PG_POOL_MAX_CONNECTIONS,
    DEFAULT_DUCKLAKE_PG_POOL_WAIT_TIMEOUT_MILLIS,
    DEFAULT_RAW_LEDGER_URL,
)


def _provider_has_no_commands(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> int:
    parser.error(f"Provider '{args.command}' does not have any commands yet.")


def _command_not_implemented(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> int:
    config_builder = getattr(args, "config_builder", None)
    if config_builder is not None:
        try:
            config_builder(args)
        except ValueError as exc:
            parser.error(str(exc))

    parser.error(args.not_implemented_message)


def _run_pipeline(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> int:
    from importlib import import_module

    module = import_module(args.pipeline_module)
    config_builder = getattr(args, "config_builder", None)
    if config_builder is None:
        parser.error("config_builder not set")
    try:
        config = config_builder(args)
    except ValueError as exc:
        parser.error(str(exc))

    log_cli_run_start(
        provider=getattr(args, "command", None),
        subcommand=getattr(args, "sub_command", None),
        pipeline_module=getattr(args, "pipeline_module", None),
        config=config,
    )

    return module.run_pipeline(config)


def _run_bootstrap(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> int:
    from eve_ingest.ducklake.bootstrap import run_raw_bootstrap

    config_builder = getattr(args, "config_builder", None)
    if config_builder is None:
        parser.error("config_builder not set")
    try:
        config = config_builder(args)
    except ValueError as exc:
        parser.error(str(exc))

    log_cli_run_start(
        provider=getattr(args, "command", None),
        subcommand=getattr(args, "sub_command", None),
        pipeline_module="eve_ingest.ducklake.bootstrap",
        config=config,
    )
    return run_raw_bootstrap(config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EVE market ingestion jobs.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    shared_parents = _build_shared_parents()

    everef_parser = subparsers.add_parser(
        "everef",
        help="Run Everef ingestion commands.",
    )
    everef_parser.set_defaults(handler=_provider_has_no_commands)
    everef_subparsers = everef_parser.add_subparsers(dest="sub_command")
    everef_subparsers.required = False

    everef_market_history_parser = everef_subparsers.add_parser(
        "market-history",
        help="Ingest daily market history CSV archives.",
        parents=[
            shared_parents["date_range"],
            shared_parents["runtime"],
            shared_parents["ducklake"],
        ],
    )
    everef_market_history_parser.set_defaults(
        handler=_run_pipeline,
        config_builder=build_everef_config,
        pipeline_module="eve_ingest.sources.everef.market_history",
    )

    everef_market_orders_parser = everef_subparsers.add_parser(
        "market-orders",
        help="Ingest market order archives.",
        parents=[
            shared_parents["date_range"],
            shared_parents["runtime"],
            shared_parents["ducklake"],
        ],
    )
    everef_market_orders_parser.set_defaults(
        handler=_run_pipeline,
        config_builder=build_everef_config,
        pipeline_module="eve_ingest.sources.everef.market_orders",
    )

    everef_fuzzwork_orders_parser = everef_subparsers.add_parser(
        "fuzzwork-orders",
        help="Ingest Fuzzwork market order archives.",
        parents=[
            shared_parents["date_range"],
            shared_parents["runtime"],
            shared_parents["ducklake"],
        ],
    )
    everef_fuzzwork_orders_parser.set_defaults(
        handler=_run_pipeline,
        config_builder=build_everef_config,
        pipeline_module="eve_ingest.sources.everef.fuzzwork_orders",
    )

    everef_references_parser = everef_subparsers.add_parser(
        "references",
        help="Ingest latest EVE reference data tarball.",
        parents=[
            shared_parents["runtime"],
            shared_parents["ducklake"],
        ],
    )
    everef_references_parser.set_defaults(
        handler=_run_pipeline,
        config_builder=build_everef_references_config,
        pipeline_module="eve_ingest.sources.everef.reference_data",
    )

    ducklake_parser = subparsers.add_parser(
        "ducklake",
        help="Run DuckLake bootstrap commands.",
    )
    ducklake_parser.set_defaults(handler=_provider_has_no_commands)
    ducklake_subparsers = ducklake_parser.add_subparsers(dest="sub_command")
    ducklake_subparsers.required = False

    ducklake_bootstrap_parser = ducklake_subparsers.add_parser(
        "bootstrap",
        help="Bootstrap DuckLake schemas and support tables.",
    )
    ducklake_bootstrap_parser.set_defaults(handler=_provider_has_no_commands)
    ducklake_bootstrap_subparsers = ducklake_bootstrap_parser.add_subparsers(dest="bootstrap_target")
    ducklake_bootstrap_subparsers.required = False

    ducklake_bootstrap_raw_parser = ducklake_bootstrap_subparsers.add_parser(
        "raw",
        help="Bootstrap the raw DuckLake schema and provenance tables.",
        parents=[shared_parents["runtime"], shared_parents["ducklake"]],
    )
    ducklake_bootstrap_raw_parser.set_defaults(
        handler=_run_bootstrap,
        config_builder=build_ducklake_bootstrap_config,
    )

    esi_parser = subparsers.add_parser(
        "esi",
        help="Run ESI ingestion commands.",
    )
    esi_parser.set_defaults(handler=_provider_has_no_commands)
    esi_subparsers = esi_parser.add_subparsers(dest="sub_command")
    esi_subparsers.required = False

    return parser


def _build_shared_parents() -> dict[str, argparse.ArgumentParser]:
    date_range_parent = argparse.ArgumentParser(add_help=False)
    date_range_parent.add_argument(
        "--start-date",
        required=True,
        help="Inclusive YYYY-MM-DD date.",
    )
    date_range_parent.add_argument(
        "--end-date",
        required=True,
        help="Inclusive YYYY-MM-DD date.",
    )

    runtime_parent = argparse.ArgumentParser(add_help=False)
    runtime_parent.add_argument(
        "--data-root",
        default=DEFAULT_DATA_ROOT,
        help="Mounted runtime data root.",
    )
    runtime_parent.add_argument(
        "--raw-ledger-url",
        default=DEFAULT_RAW_LEDGER_URL,
        help="Raw source-file ledger URL.",
    )

    ducklake_parent = argparse.ArgumentParser(add_help=False)
    ducklake_parent.add_argument(
        "--ducklake-catalog",
        default=DEFAULT_DUCKLAKE_CATALOG,
        help="DuckLake catalog URL.",
    )
    ducklake_parent.add_argument(
        "--ducklake-metadata-schema",
        default=DEFAULT_DUCKLAKE_METADATA_SCHEMA,
        help="DuckLake metadata schema name.",
    )
    ducklake_parent.add_argument(
        "--ducklake-lock-wait-timeout-seconds",
        default=DEFAULT_DUCKLAKE_LOCK_WAIT_TIMEOUT_SECONDS,
        help="DuckLake advisory lock wait timeout in seconds.",
    )
    ducklake_parent.add_argument(
        "--ducklake-pg-pool-max-connections",
        default=DEFAULT_DUCKLAKE_PG_POOL_MAX_CONNECTIONS,
        help="DuckDB Postgres extension pool max connections before DuckLake attach.",
    )
    ducklake_parent.add_argument(
        "--ducklake-pg-pool-wait-timeout-millis",
        default=DEFAULT_DUCKLAKE_PG_POOL_WAIT_TIMEOUT_MILLIS,
        help="DuckDB Postgres extension pool wait timeout in milliseconds.",
    )
    ducklake_parent.add_argument(
        "--ducklake-pg-pool-acquire-mode",
        default=DEFAULT_DUCKLAKE_PG_POOL_ACQUIRE_MODE,
        choices=("force", "wait", "try"),
        help="DuckDB Postgres extension pool acquire mode.",
    )

    return {
        "date_range": date_range_parent,
        "runtime": runtime_parent,
        "ducklake": ducklake_parent,
    }
