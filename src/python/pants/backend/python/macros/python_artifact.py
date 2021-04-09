# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections.abc
from typing import Any, Dict, List, Optional, Union


def _normalize_entry_points(
    entry_points: Optional[Dict[str, Union[List[str], Dict[str, str]]]]
) -> Optional[Dict[str, Dict[str, str]]]:
    """Ensure any entry points are in the form Dict[str, Dict[str, str]]."""
    if not entry_points:
        return None

    if not isinstance(entry_points, collections.abc.Mapping):
        raise ValueError(
            f"The `entry_points` in `setup_py()` must be a dictionary, "
            f"but was {entry_points!r} with type {type(entry_points)}"
        )

    def _values_to_entry_points(values):
        if isinstance(values, collections.abc.Mapping):
            return values
        if isinstance(values, collections.abc.Iterable):
            for entry_point in values:
                if not isinstance(entry_point, str) or "=" not in entry_point:
                    raise ValueError(
                        f"Invalid `entry_point`, expected `<name> = [<package>.[<subpackage>.]]<module>[:<object>.<object>]`, but got {entry_point!r}"
                    )

            return dict(tuple(map(str.strip, entry_point.split("=", 1))) for entry_point in values)
        raise ValueError(
            f"The values of the `entry_points` dictionary in `setup_py()` must be a list of strings or a dictionary of string to string, but got {values!r} of type {type(values)}"
        )

    return {section: _values_to_entry_points(values) for section, values in entry_points.items()}


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
                f"The `name` in `setup_py()` must be a string, but was {repr(name)} with type "
                f"{type(name)}."
            )

        # coerce entry points from Dict[str, List[str]] to Dict[str, Dict[str, str]]
        entry_points = _normalize_entry_points(kwargs.get("entry_points"))
        if entry_points:
            kwargs["entry_points"] = entry_points

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

    def with_binaries(self, *args, **kw):
        """Add binaries tagged to this artifact.

        For example: ::

          provides = setup_py(
            name = 'my_library',
            zip_safe = True
          ).with_binaries(
            my_command = ':my_library_bin'
          )

        This adds a console_script entry_point for the pex_binary target
        pointed at by :my_library_bin.  Currently only supports
        pex_binaries that specify entry_point explicitly instead of source.

        Also can take a dictionary, e.g.
        with_binaries({'my-command': ':my_library_bin'})
        """
        for arg in args:
            if isinstance(arg, dict):
                self._binaries.update(arg)
        self._binaries.update(kw)
        return self
