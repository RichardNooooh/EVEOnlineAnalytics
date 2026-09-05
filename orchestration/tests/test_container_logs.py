from __future__ import annotations

import logging

import pytest
from eve_market_airflow.container_logs import ContainerLogLevelRouter


class RecordingLogSink:
    def __init__(self) -> None:
        self.records: list[tuple[int, object, tuple[object, ...]]] = []

    def info(self, msg: object, *args: object, **kwargs: object) -> None:
        self.records.append((logging.INFO, msg, args))

    def log(self, level: int, msg: object, *args: object, **kwargs: object) -> None:
        self.records.append((level, msg, args))


@pytest.mark.parametrize(
    ("prefix", "expected_level"),
    [
        ("DEBUG", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARNING", logging.WARNING),
        ("WARN", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
        ("FATAL", logging.CRITICAL),
    ],
)
def test_routes_container_prefix_to_matching_level(prefix: str, expected_level: int) -> None:
    sink = RecordingLogSink()
    router = ContainerLogLevelRouter(sink)

    router.info("%s", f"{prefix} [eve_ingest.test]: message")

    assert sink.records == [(expected_level, "%s", (f"{prefix} [eve_ingest.test]: message",))]


def test_unprefixed_lines_inherit_previous_container_level_until_reset() -> None:
    sink = RecordingLogSink()
    router = ContainerLogLevelRouter(sink)

    router.info("%s", "ERROR [eve_ingest.test]: failed")
    router.info("%s", "Traceback (most recent call last):")
    router.info("%s", '  File "pipeline.py", line 10, in run')
    router.info("%s", "INFO [eve_ingest.test]: recovered")
    router.info("%s", "continuation")
    router.reset()
    router.info("%s", "new stream")

    assert [level for level, _, _ in sink.records] == [
        logging.ERROR,
        logging.ERROR,
        logging.ERROR,
        logging.INFO,
        logging.INFO,
        logging.INFO,
    ]


def test_native_operator_messages_are_not_rerouted() -> None:
    sink = RecordingLogSink()
    router = ContainerLogLevelRouter(sink)
    router.info("%s", "ERROR [eve_ingest.test]: failed")

    router.info("Starting docker container from image %s", "image:tag")

    assert sink.records[-1] == (
        logging.INFO,
        "Starting docker container from image %s",
        ("image:tag",),
    )


def test_similar_words_do_not_count_as_log_level_prefixes() -> None:
    sink = RecordingLogSink()
    router = ContainerLogLevelRouter(sink)

    router.info("%s", "INFORMATIONAL output")

    assert sink.records == [(logging.INFO, "%s", ("INFORMATIONAL output",))]
