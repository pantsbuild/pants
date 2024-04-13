# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


# TODO: We may want to support different sets of env vars for different types of process.
#  Can be done via scoped subsystems, possibly.  However we should only do this if there
#  is a real need.
class SubprocessEnvironment(Subsystem):
    options_scope = "subprocess-environment"
    help = "Environment settings for forked subprocesses."

    class EnvironmentAware:
        _env_vars = StrListOption(
            default=["LANG", "LC_CTYPE", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR"],
            help=softwrap(
                f"""
                Environment variables to set for process invocations.

                Entries are either strings in the form `ENV_VAR=value` to set an explicit value;
                or just `ENV_VAR` to copy the value from Pants's own environment.

                See {doc_url('docs/using-pants/key-concepts/options#addremove-semantics')} for how to add and remove Pants's
                default for this option.
                """
            ),
            advanced=True,
        )

        @property
        def env_vars_to_pass_to_subprocesses(self) -> Tuple[str, ...]:
            return tuple(sorted(set(self._env_vars)))


@dataclass(frozen=True)
class SubprocessEnvironmentVars:
    vars: FrozenDict[str, str]


@rule
async def get_subprocess_environment(
    subproc_env: SubprocessEnvironment.EnvironmentAware,
) -> SubprocessEnvironmentVars:
    return SubprocessEnvironmentVars(
        await Get(
            EnvironmentVars, EnvironmentVarsRequest(subproc_env.env_vars_to_pass_to_subprocesses)
        )
    )


def rules():
    return collect_rules()
