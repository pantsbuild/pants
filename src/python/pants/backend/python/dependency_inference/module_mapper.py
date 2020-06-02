# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import Optional


def determine_module(stripped_path: PurePath) -> Optional[str]:
    if stripped_path.suffix != ".py":
        return None
    module_name_with_slashes = (
        stripped_path.parent
        if stripped_path.name == "__init__.py"
        else stripped_path.with_suffix("")
    )
    return module_name_with_slashes.as_posix().replace("/", ".")
