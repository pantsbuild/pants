# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from abc import ABC
from typing import ClassVar, Iterable, List

import pkg_resources

from pants.engine.fs import FileContent, FilesContent, InputFilesContent

_PACKAGE: List[str] = __name__.split(".")[:-1]


class PexTool(ABC):
    _entry_point: ClassVar[str]
    _module_names: ClassVar[Iterable[str]]

    @classmethod
    def entry_point(cls):
        return f"{'.'.join(_PACKAGE)}.{cls._entry_point}"

    @classmethod
    def files(cls) -> InputFilesContent:
        return InputFilesContent(
            FilesContent(
                FileContent(
                    path=f"{os.path.join(*_PACKAGE, module_name)}.py",
                    content=pkg_resources.resource_string(__name__, f"{module_name}.py"),
                )
                for module_name in cls._module_names
            )
        )
