# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections.abc
import copy
import json
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
                The `entry_points` in `python_artifact()` must be a dictionary,
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
                The values of the `entry_points` dictionary in `python_artifact()` must be
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

    def __init__(self, **kwargs) -> None:
        """
        :param kwargs: Passed to `setuptools.setup
          <https://setuptools.pypa.io/en/latest/setuptools.html>`_.
        """
        if "entry_points" in kwargs:
            # coerce entry points from Dict[str, List[str]] to Dict[str, Dict[str, str]]
            kwargs["entry_points"] = _normalize_entry_points(kwargs["entry_points"])

        self._kw: Dict[str, Any] = copy.deepcopy(kwargs)
        # The kwargs come from a BUILD file, and can contain somewhat arbitrary nested structures,
        # so we don't have a principled way to make them into a hashable data structure.
        # E.g., we can't naively turn all lists into tuples because distutils checks that some
        # fields (such as ext_modules) are lists, and doesn't accept tuples.
        # Instead we stringify and precompute a hash to use in our own __hash__, since we know
        # that this object is immutable.
        self._hash: int = hash(json.dumps(kwargs, sort_keys=True))

    @property
    def kwargs(self) -> Dict[str, Any]:
        return self._kw

    def asdict(self) -> Dict[str, Any]:
        return self.kwargs

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, PythonArtifact):
            return False
        return self._kw == other._kw

    def __hash__(self) -> int:
        return self._hash
