# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path

import pants.backend
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.goal.builtin_goal import BuiltinGoal
from pants.option.option_types import BoolOption
from pants.option.options import Options
from pants.util.strutil import bullet_list


def discover_backends(experimental: bool) -> list[str]:
    pants_root = Path(pants.backend.__file__).parent.parent
    parent_root = f"{pants_root.parent}/"
    register_pys = pants_root.glob("**/register.py")
    backends = {
        str(register_py.parent).replace(parent_root, "").replace("/", ".")
        for register_py in register_pys
        if experimental or "/experimental/" not in str(register_py)
    }
    always_activated = {"pants.core", "pants.backend.project_info"}
    return sorted(backends - always_activated)


class ListBackendsBuiltinGoal(BuiltinGoal):
    name = "list-backends"
    help = "List all available backends."

    experimental = BoolOption(default=False, help="Include experimental backends")

    def run(self, *, options: Options, **kwargs) -> ExitCode:
        enabled = options.for_global_scope().backend_packages
        is_enabled = {True: "[x]", False: "[ ]"}
        backends = (
            f"{is_enabled[backend in enabled]} {backend}"
            for backend in discover_backends(self.experimental)
        )
        print(f"Enabled backends:\n\n{bullet_list(backends)}\n")
        return PANTS_SUCCEEDED_EXIT_CODE
