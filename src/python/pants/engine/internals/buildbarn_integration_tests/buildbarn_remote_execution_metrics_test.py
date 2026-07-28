# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.engine.internals.buildbarn_integration_tests.metrics import (
    PrometheusMetricKey,
    _parse_prometheus_metrics,
    assert_counter_delta,
)


def test_parse_prometheus_metrics_selects_complete_label_set() -> None:
    metrics = """# HELP grpc_server_handled_total Total number of RPCs completed on the server.
grpc_server_handled_total{grpc_code="OK",grpc_method="Execute",grpc_service="execution.v2.Execution"} 3
grpc_server_handled_total{grpc_code="Unavailable",grpc_method="Execute",grpc_service="execution.v2.Execution"} 1
"""
    snapshot = _parse_prometheus_metrics(metrics)

    assert (
        snapshot[
            (
                "grpc_server_handled_total",
                (
                    ("grpc_code", "OK"),
                    ("grpc_method", "Execute"),
                    ("grpc_service", "execution.v2.Execution"),
                ),
            )
        ]
        == 3
    )


def test_assert_counter_delta_reports_missing_series() -> None:
    with pytest.raises(AssertionError, match="Missing Prometheus metric series"):
        assert_counter_delta({}, {}, "grpc_server_handled_total", {"grpc_code": "OK"}, True)


def test_assert_counter_delta_checks_expected_change() -> None:
    labels = {"grpc_code": "OK"}
    before: dict[PrometheusMetricKey, float] = {
        ("grpc_server_handled_total", (("grpc_code", "OK"),)): 3.0
    }
    after: dict[PrometheusMetricKey, float] = {
        ("grpc_server_handled_total", (("grpc_code", "OK"),)): 4.0
    }

    assert_counter_delta(before, after, "grpc_server_handled_total", labels, True)
    with pytest.raises(AssertionError, match="Expected no increase"):
        assert_counter_delta(before, after, "grpc_server_handled_total", labels, False)
