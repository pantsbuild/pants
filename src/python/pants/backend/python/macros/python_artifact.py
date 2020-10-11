# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any, Dict


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
