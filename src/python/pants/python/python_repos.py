# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems import repos
from pants.base.deprecated import warn_or_error


def __getattr__(name):
    if name == "__path__":
        raise AttributeError()
    warn_or_error(
        "2.10.0.dev0",
        f"the {name} class",
        f"{name} moved to the {repos.__name__} module.",
    )
    return getattr(repos, name)
