from __future__ import annotations

from eve_ingest.cli.parser import build_parser
from eve_ingest.logging_config import configure_logging, log_cli_dispatch, log_runtime_context


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    log_runtime_context()
    parser = build_parser()
    args = parser.parse_args(argv)
    log_cli_dispatch(
        provider=getattr(args, "command", None),
        subcommand=getattr(args, "sub_command", None),
        pipeline_module=getattr(args, "pipeline_module", None),
    )
    return args.handler(args, parser)
