# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import shlex
from pathlib import PurePath


def terraform_arg(name: str, value: str) -> str:
    """Format a Terraform arg."""
    return f"{name}={shlex.quote(value)}"


def terraform_relpath(chdir: str, target: str) -> str:
    """Compute the relative path of a target file to the Terraform deployment root."""
    return PurePath(target).relative_to(chdir).as_posix()
