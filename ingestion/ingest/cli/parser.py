import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EVE market ingestion jobs.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    everef_parser = subparsers.add_parser(
        "everef",
        help="Run Everef ingestion commands.",
    )
    everef_subparsers = everef_parser.add_subparsers(dest="sub_command")
    everef_subparsers.required = True

    everef_market_history_parser = everef_subparsers.add_parser(
        "market-history",
        help="Ingest daily market history CSV archives.",
    )
    add_everef_market_history_flags(everef_market_history_parser)

    return parser


def add_everef_market_history_flags(parser: argparse.ArgumentParser) -> None:
    del parser
