"""Structured logging tests."""

import json
import logging

from bios.common.logutil import JsonFormatter


def test_json_formatter_emits_parseable_lines() -> None:
    record = logging.LogRecord(
        name="bios.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="collected %d items",
        args=(5,),
        exc_info=None,
    )
    record.source_id = "src_sec_press"  # extra context
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "collected 5 items"
    assert payload["level"] == "INFO"
    assert payload["source_id"] == "src_sec_press"
    assert payload["ts"].endswith("+00:00")
