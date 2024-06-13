# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Any, Mapping, Protocol


class FilePathOracle(Protocol):
    def filepath(self) -> str: ...


class ParseContext:
    """The build file context that context aware objects - aka BUILD macros - operate against.

    All fields of the ParseContext must be assumed to be mutable by macros, and should
    thus only be consumed in the context of a macro's `__call__` method (rather than
    in its `__init__`).
    """

    def __init__(
        self, build_root: str, type_aliases: Mapping[str, Any], filepath_oracle: FilePathOracle
    ) -> None:
        """Create a ParseContext.

        :param build_root: The absolute path to the build root.
        :param type_aliases: A dictionary of BUILD file symbols.
        :param filepath_oracle: An oracle than can be queried for the current BUILD file name.
        """
        self._build_root = build_root
        self._type_aliases = type_aliases
        self._filepath_oracle = filepath_oracle

    def create_object(self, alias: str, *args: Any, **kwargs: Any) -> Any:
        """Constructs the type with the given alias using the given args and kwargs.

        :API: public

        :param alias: The type alias.
        :param args: These pass through to the underlying callable object.
        :param kwargs: These pass through to the underlying callable object.
        :returns: The created object.
        """
        object_type = self._type_aliases.get(alias)
        if object_type is None:
            raise KeyError(f"There is no type registered for alias {alias}")
        if not callable(object_type):
            raise TypeError(
                f"Asked to call {alias} with args {args} and kwargs {kwargs} but it is not "
                f"callable, its a {type(alias).__name__}."
            )
        return object_type(*args, **kwargs)

    @property
    def rel_path(self) -> str:
        """Relative path from the build root to the directory of the BUILD file being parsed.

        :API: public
        """
        return os.path.dirname(self._filepath_oracle.filepath())

    @property
    def build_root(self) -> str:
        """Absolute path of the build root."""
        return self._build_root
