# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re

import requests

PrometheusMetricKey = tuple[str, tuple[tuple[str, str], ...]]

_PROMETHEUS_SAMPLE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+"
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?:\s+\d+)?$"
)
_PROMETHEUS_LABEL_RE = re.compile(r'(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)="(?P<value>(?:\\.|[^"\\])*)"')


def _parse_prometheus_labels(serialized_labels: str) -> tuple[tuple[str, str], ...]:
    labels: list[tuple[str, str]] = []
    position = 0
    while position < len(serialized_labels):
        match = _PROMETHEUS_LABEL_RE.match(serialized_labels, position)
        if match is None:
            raise ValueError(f"Invalid Prometheus labels: {serialized_labels!r}")
        labels.append(
            (
                match["name"],
                bytes(match["value"], "utf-8").decode("unicode_escape"),
            )
        )
        position = match.end()
        if position == len(serialized_labels):
            break
        if serialized_labels[position] != ",":
            raise ValueError(f"Invalid Prometheus labels: {serialized_labels!r}")
        position += 1
    return tuple(sorted(labels))


def scrape_prometheus_metrics(metrics_url: str) -> dict[PrometheusMetricKey, float]:
    response = requests.get(metrics_url, timeout=10)
    response.raise_for_status()
    exposition = response.text

    metrics: dict[PrometheusMetricKey, float] = {}
    for line in exposition.splitlines():
        if not line or line.startswith("#"):
            continue
        match = _PROMETHEUS_SAMPLE_RE.match(line)
        if match is None:
            continue
        metrics[(match["name"], _parse_prometheus_labels(match["labels"] or ""))] = float(
            match["value"]
        )
    return metrics


def _metric_value(
    snapshot: dict[PrometheusMetricKey, float], metric_name: str, labels: dict[str, str]
) -> float:
    key = (metric_name, tuple(sorted(labels.items())))
    try:
        return snapshot[key]
    except KeyError as error:
        available = sorted(key for key in snapshot if key[0] == metric_name)
        raise AssertionError(
            f"Missing Prometheus metric series {key!r}; available series: {available!r}"
        ) from error


def assert_counter_delta(
    before: dict[PrometheusMetricKey, float],
    after: dict[PrometheusMetricKey, float],
    metric_name: str,
    labels: dict[str, str],
    expect_increase: bool,
) -> None:
    before_value = _metric_value(before, metric_name, labels)
    after_value = _metric_value(after, metric_name, labels)
    delta = after_value - before_value
    expectation = "an increase" if expect_increase else "no increase"
    assert (delta > 0) == expect_increase, (
        f"Expected {expectation} for {metric_name}{labels!r}, but values changed "
        f"from {before_value} to {after_value} (delta {delta})."
    )
