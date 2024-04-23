# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Functionality for formatting vulnerability results as a set of human-readable columns."""

from __future__ import annotations

from itertools import zip_longest
from typing import Any, Iterable


def tabulate(rows: Iterable[Iterable[Any]]) -> tuple[list[str], list[int]]:
    """Return a list of formatted rows and a list of column sizes. For example::

    >>> tabulate([['foobar', 2000], [0xdeadbeef]])
    (['foobar     2000', '3735928559'], [10, 4])
    """
    rows = [tuple(map(str, row)) for row in rows]
    sizes = [max(map(len, col)) for col in zip_longest(*rows, fillvalue="")]
    table = [" ".join(map(str.ljust, row, sizes)).rstrip() for row in rows]
    return table, sizes


def generate_header(sizes: Iterable[int]) -> str:
    """Return a dashed header string."""
    headers = []
    for column_size in sizes:
        column_header = "-" * column_size
        headers.append(column_header)
    return " ".join(headers)


def format_results(
    result: dict[str, list[dict[str:Any]]],
) -> str:
    """Returns a column formatted string for a given mapping of dependencies to vulnerability
    results."""
    vuln_data: list[list[Any]] = []
    header = ["Dependency", "ID", "Fix Versions", "Link"]
    vuln_data.append(header)
    for dep, vulns in result.items():
        for vuln in vulns:
            vuln_data.append([dep, vuln.vuln_id, vuln.fixed_in, vuln.link])
    columns_string = ""

    # If it's just a header, don't bother adding it to the output
    if len(vuln_data) > 1:
        vuln_strings, sizes = tabulate(vuln_data)

        if len(vuln_data) > 0:
            vuln_strings.insert(1, generate_header(sizes))

        for row in vuln_strings:
            if columns_string:
                columns_string += "\n"
            columns_string += row

    return columns_string
