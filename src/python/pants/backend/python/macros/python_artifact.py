# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections.abc
from typing import Any, Dict, List, Optional, Union

from pants.base.deprecated import deprecated


def _check_entry_points(
    entry_points: Optional[Dict[str, Union[List[str], Dict[str, str]]]]
) -> Optional[Dict[str, List[str]]]:
    """Ensure any entry points are on the form a dictionary of string -> list of strings."""
    if not entry_points:
        return None

    if not isinstance(entry_points, collections.abc.Mapping):
        raise ValueError(
            f"The `entry_points` in `setup_py()` must be a dictionary, "
            f"but was {entry_points!r} with type {type(entry_points)}"
        )

    return {
        section: [f"{name}={entry_point}" for name, entry_point in values.items()]
        if isinstance(values, collections.abc.Mapping)
        else list(values)
        for section, values in entry_points.items()
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

        # coerce entry points from dict of string -> dict of string -> string to
        # dict of string -> list of string
        entry_points = _check_entry_points(kwargs.get("entry_points"))
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

    @deprecated(
        "2.6.0dev0",
        """Use `python_distribution(entry_points={'console_scripts':{'<name>': '<entry
point>'}})` instead of
`python_distribution(provides=setup_py().with_binaries(...))`.

The syntax for entry points must follow that of setuptools, and is specified as
follows:

    <name> = [<package>.[<subpackage>.]]<module>[:<object>.<object>]

Example:

    entry_points={
      'console_scripts': {
        'my_command': 'my.library.bin:main'
      }
    }

The entry point must now be provided explicitly and are not derived from a
`pex_binary` target.

Pants will infer a dependency on the owner of the entry point module (usually a
`python_library` or `python_requirement_library`).

Please run the following command before and after migrating from
`.with_binaries()` to verify that the correct dependencies are inferred.

    ./pants dependencies --transitive path/to:python_distribution

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
