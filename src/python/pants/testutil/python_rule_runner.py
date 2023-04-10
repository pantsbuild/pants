# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable, Mapping

from pants.testutil.rule_runner import RuleRunner


class PythonRuleRunner(RuleRunner):
    """Set common python rule-specific options."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_options([])

    def set_options(
        self,
        args: Iterable[str],
        *,
        env: Mapping[str, str] | None = None,
        env_inherit: set[str] | None = None,
    ) -> None:
        env = dict(env) if env else {}
        if (
            not any("--python-interpreter-constraints=" in arg for arg in args)
            and "PANTS_PYTHON_INTERPRETER_CONSTRAINTS" not in env
        ):
            # We inject the test ICs via env and not args, because in a handful of cases
            # we have different behavior when the option is set via flag.
            env["PANTS_PYTHON_INTERPRETER_CONSTRAINTS"] = "['>=3.7,<3.10',]"
        super().set_options(args, env=env, env_inherit=env_inherit)
