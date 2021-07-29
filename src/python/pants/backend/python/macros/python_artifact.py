# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections.abc
from typing import Any, Dict, List, Union

from pants.base.deprecated import deprecated


def _normalize_entry_points(
    all_entry_points: Dict[str, Union[List[str], Dict[str, str]]]
) -> Dict[str, Dict[str, str]]:
    """Ensure any entry points are in the form Dict[str, Dict[str, str]]."""
    if not isinstance(all_entry_points, collections.abc.Mapping):
        raise ValueError(
            f"The `entry_points` in `setup_py()` must be a dictionary, "
            f"but was {all_entry_points!r} with type {type(all_entry_points).__name__}."
        )

    def _values_to_entry_points(values):
        if isinstance(values, collections.abc.Mapping):
            return values
        if isinstance(values, collections.abc.Iterable) and not isinstance(values, str):
            for entry_point in values:
                if not isinstance(entry_point, str) or "=" not in entry_point:
                    raise ValueError(
                        f"Invalid `entry_point`, expected `<name> = <entry point>`, "
                        f"but got {entry_point!r}."
                    )

            return dict(tuple(map(str.strip, entry_point.split("=", 1))) for entry_point in values)
        raise ValueError(
            f"The values of the `entry_points` dictionary in `setup_py()` must be "
            f"a list of strings or a dictionary of string to string, "
            f"but got {values!r} of type {type(values).__name__}."
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
                f"The `name` in `setup_py()` must be a string, but was {repr(name)} with type "
                f"{type(name)}."
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

    @deprecated(
        "2.8.0.dev0",
        """Use `python_distribution(entry_points={"console_scripts":{...}})` instead of
        `python_distribution(provides=setup_py().with_binaries(...))`.

        The entry points field was added as a more generic mechanism than
        `.with_binaries()`. Whereas `.with_binaries()` would only add `console_scripts` to your
        generated `setup.py`, you can now add other types of entry points like `gui_scripts`. You
        can also now add a setuptools entry point like `path.to.module:func`, in addition to still
        being able to sue a Pants target address to a `pex_binary` target.

        Entry points are specified as a nested dictionary, with a dictionary for each type of entry
        point like `console_scripts` and `gui_scripts`. Each dictionary maps the entry point name to
        either a setuptools entry point or an address to a `pex_binary` target.

        Any entry point that either starts with `:` or has `/` in it, is considered a target
        address. Use `//` as prefix for target addresses if you need to disambiguate.

        To migrate, add a dictionary for `console_scripts` with the same entry point name and
        `pex_binary` address you were using before.

        Example migration, before:

            pex_binary(name="binary", entry_point="app.py:main")

            python_distribution(
                name="dist",
                provides=setup_py(...).with_binaries({'my_command': ':binary'})
            )

        after:

            pex_binary(name="binary", entry_point="app.py:main")

            python_distribution(
                name="dist",
                entry_points={'console_scripts': {'my_command': ':binary'}},
                provides=setup_py(...),
            )

        As before, Pants will infer a dependency on the `pex_binary`. You can confirm this by
        running

            ./pants dependencies path/to:python_distribution

        """,
    )
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
