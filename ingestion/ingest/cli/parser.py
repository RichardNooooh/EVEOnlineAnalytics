import argparse

from ingest.cli.builders import (
    build_everef_market_history_config,
    build_everef_market_orders_config,
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
            shared_parents["raw_cache"],
            shared_parents["ducklake"],
        ],
    )
    everef_market_history_parser.set_defaults(
        handler=_command_not_implemented,
        config_builder=build_everef_market_history_config,
        not_implemented_message="Everef market-history command is not implemented yet.",
    )

    everef_market_orders_parser = everef_subparsers.add_parser(
        "market-orders",
        help="Ingest market order archives.",
        parents=[
            shared_parents["date_range"],
            shared_parents["raw_cache"],
            shared_parents["ducklake"],
        ],
    )
    everef_market_orders_parser.set_defaults(
        handler=_command_not_implemented,
        config_builder=build_everef_market_orders_config,
        not_implemented_message="Everef market-orders command is not implemented yet.",
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

    raw_cache_parent = argparse.ArgumentParser(add_help=False)
    raw_cache_parent.add_argument(
        "--raw-root",
        default=None,
        help="Raw source-file cache root.",
    )
    raw_cache_parent.add_argument(
        "--raw-ledger-url",
        default=None,
        help="Raw source-file ledger URL.",
    )
    raw_cache_parent.add_argument(
        "--raw-max-copies-per-date",
        type=int,
        default=None,
        help="Maximum raw file copies to keep per source date; 0 disables deletion.",
    )

    ducklake_parent = argparse.ArgumentParser(add_help=False)
    ducklake_parent.add_argument(
        "--ducklake-name",
        default=None,
        help="DuckLake attach name.",
    )
    ducklake_parent.add_argument(
        "--ducklake-catalog",
        default=None,
        help="DuckLake catalog URL.",
    )
    ducklake_parent.add_argument(
        "--ducklake-storage",
        default=None,
        help="DuckLake storage URL.",
    )

    return {
        "date_range": date_range_parent,
        "raw_cache": raw_cache_parent,
        "ducklake": ducklake_parent,
    }
