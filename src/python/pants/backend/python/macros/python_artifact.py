# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections.abc
from typing import Any, Dict, List, Union

from pants.util.strutil import softwrap


def _normalize_entry_points(
    all_entry_points: Dict[str, Union[List[str], Dict[str, str]]]
) -> Dict[str, Dict[str, str]]:
    """Ensure any entry points are in the form Dict[str, Dict[str, str]]."""
    if not isinstance(all_entry_points, collections.abc.Mapping):
        raise ValueError(
            softwrap(
                f"""
                The `entry_points` in `setup_py()` must be a dictionary,
                but was {all_entry_points!r} with type {type(all_entry_points).__name__}.
                """
            )
        )

    def _values_to_entry_points(values):
        if isinstance(values, collections.abc.Mapping):
            return values
        if isinstance(values, collections.abc.Iterable) and not isinstance(values, str):
            for entry_point in values:
                if not isinstance(entry_point, str) or "=" not in entry_point:
                    raise ValueError(
                        softwrap(
                            f"""
                            Invalid `entry_point`, expected `<name> = <entry point>`,
                            but got {entry_point!r}.
                            """
                        )
                    )

            return dict(tuple(map(str.strip, entry_point.split("=", 1))) for entry_point in values)
        raise ValueError(
            softwrap(
                f"""
                The values of the `entry_points` dictionary in `setup_py()` must be
                a list of strings or a dictionary of string to string,
                but got {values!r} of type {type(values).__name__}.
                """
            )
        )

    return {
        category: _values_to_entry_points(values) for category, values in all_entry_points.items()
    }


class PythonArtifact:
    """Represents a Python setup.py-based project."""

    def __init__(self, **kwargs):
        """
        :param kwargs: Passed to `setuptools.setup
          <https://pythonhosted.org/setuptools/setuptools.html>`_.
        """
        if "name" not in kwargs:
            raise ValueError("`setup_py()` requires `name` to be specified.")
        name = kwargs["name"]
        if not isinstance(name, str):
            raise ValueError(
                softwrap(
                    f"""
                    The `name` in `setup_py()` must be a string, but was {repr(name)} with type
                    {type(name)}.
                    """
                )
            )

        if "entry_points" in kwargs:
            # coerce entry points from Dict[str, List[str]] to Dict[str, Dict[str, str]]
            kwargs["entry_points"] = _normalize_entry_points(kwargs["entry_points"])

        self._kw: Dict[str, Any] = kwargs
        self._binaries = {}
        self._name: str = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def kwargs(self) -> Dict[str, Any]:
        return self._kw

    @property
    def binaries(self):
        return self._binaries

    def __str__(self) -> str:
        return self.name
