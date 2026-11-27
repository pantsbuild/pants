# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import hashlib
import os.path
import shlex


def terraform_arg(name: str, value: str) -> str:
    """Format a Terraform arg."""
    return f"{name}={shlex.quote(value)}"


def terraform_relpath(chdir: str, target: str) -> str:
    """Compute the relative path of a target file to the Terraform deployment root."""
    return os.path.relpath(target, start=chdir)


def terraform_named_cache(path: str) -> str:
    """Turn the path to a module into a stable hash for use as the named cache.

    We don't use the path directly because that could pose problems for nested directories. We need
    to append the "/" so that Terraform will use it.
    """
    return hashlib.sha1(path.encode("utf-8")).hexdigest() + "/"
