from __future__ import annotations

from ingest.cli.parser import build_parser
from ingest.logging import configure_logging, log_runtime_context


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    log_runtime_context()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args, parser)
