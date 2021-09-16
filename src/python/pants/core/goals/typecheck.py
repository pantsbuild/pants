# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.base.deprecated import deprecated_conditional
from pants.core.goals import check
from pants.core.goals.lint import REPORT_DIR as REPORT_DIR  # noqa: F401


def __getattr__(name):
    is_deprecated_name = "Typecheck" in name
    deprecated_conditional(
        lambda: is_deprecated_name,
        "2.10.0.dev0",
        f"the {name} class",
        f"Typecheck-related classes were renamed: s/Typecheck/Check/ and moved to the {check.__name__} module.",
    )
    if is_deprecated_name:
        return getattr(check, name.replace("Typecheck", "Check"))
    raise AttributeError(f"module {__name__} has no attribute {name}")
