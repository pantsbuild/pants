# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.engine.rules import collect_rules, rule
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict


# TODO: We may want to support different sets of env vars for different types of process.
#  Can be done via scoped subsystems, possibly.  However we should only do this if there
#  is a real need.
class SubprocessEnvironment(Subsystem):
    options_scope = "subprocess-environment"
    help = "Environment settings for forked subprocesses."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--env-vars",
            type=list,
            member_type=str,
            default=["LANG", "LC_CTYPE", "LC_ALL"],
            advanced=True,
            help=(
                "Environment variables to set for process invocations. "
                "Entries are either strings in the form `ENV_VAR=value` to set an explicit value; "
                "or just `ENV_VAR` to copy the value from Pants's own environment."
            ),
        )

    @property
    def env_vars_to_pass_to_subprocesses(self) -> Tuple[str, ...]:
        return tuple(sorted(set(self.options.env_vars)))


@dataclass(frozen=True)
class SubprocessEnvironmentVars:
    vars: FrozenDict[str, str]


@rule
def get_subprocess_environment(
    subproc_env: SubprocessEnvironment, pants_env: PantsEnvironment
) -> SubprocessEnvironmentVars:
    return SubprocessEnvironmentVars(
        pants_env.get_subset(subproc_env.env_vars_to_pass_to_subprocesses)
    )


def rules():
    return collect_rules()
