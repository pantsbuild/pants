# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Tuple

from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.engine.rules import collect_rules, rule
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict

# Names of env vars that can be set on all subprocesses via config.
SETTABLE_ENV_VARS = (
    # Customarily used to control i18n settings.
    "LANG",
    "LC_CTYPE",
    "LC_ALL",
    # Customarily used to control proxy settings in various processes.
    "http_proxy",
    "https_proxy",
    "ftp_proxy",
    "all_proxy",
    "no_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "FTP_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    # Allow Requests to verify SSL certificates for HTTPS requests
    # https://requests.readthedocs.io/en/master/user/advanced/#ssl-cert-verification
    "REQUESTS_CA_BUNDLE",
)


# TODO: We may want to support different sets of env vars for different types of process.
#  Can be done via scoped subsystems, possibly.  However we should only do this if there
#  is a real need.
class SubprocessEnvironment(Subsystem):
    """Environment settings for forked subprocesses."""

    options_scope = "subprocess-environment"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--lang",
            type=str,
            default=os.environ.get("LANG"),
            advanced=True,
            help="Override the `LANG` environment variable for any forked subprocesses.",
            removal_version="2.1.0.dev0",
            removal_hint="Use the env_vars option in this scope instead.",
        )
        register(
            "--lc-all",
            type=str,
            default=os.environ.get("LC_ALL"),
            advanced=True,
            help="Override the `LC_ALL` environment variable for any forked subprocesses.",
            removal_version="2.1.0.dev0",
            removal_hint="Use the env_vars option in this scope instead.",
        )
        register(
            "--env-vars",
            type=list,
            member_type=str,
            default=["LANG", "LC_CTYPE", "LC_ALL"],
            advanced=True,
            help=(
                "Environment variables to set for process invocations. "
                "Entries are either strings in the form `ENV_VAR=value` to set an explicit value; "
                "or just `ENV_VAR` to copy the value from Pants's own environment.\n\nEach ENV_VAR "
                f"must be one of {', '.join(f'`{v}`' for v in SETTABLE_ENV_VARS)}."
            ),
        )

    @property
    def env_vars_to_pass_to_subprocesses(self) -> Tuple[str, ...]:
        ret = set(self.options.env_vars)

        # Inject values from the old --lang, --lc-all options if explicitly set, rather than the
        # default.
        env_var_names = {env_var.split("=", 1)[0] for env_var in self.options.env_vars}

        def handle_deprecated(env_var_name: str):
            old_configured = not self.options.is_default(env_var_name.lower())
            new_configured = env_var_name in env_var_names and not self.options.is_default(
                "env_vars"
            )
            if old_configured and new_configured:
                raise ValueError(
                    "Conflicting options used. You used the new, preferred "
                    f"[{self.options_scope}].env_vars option, but also used the deprecated "
                    f"[{self.options_scope}].{env_var_name.lower()}.\n\nPlease use only one of "
                    "these."
                )
            if old_configured:
                val = self.options[env_var_name.lower()]
                # NB: We will have already validated that the user did not override `env_vars`,
                # which means that they will be using the default values where we only use the env
                # var name, and not a value, e.g. `LANG`.
                if env_var_name in env_var_names:
                    ret.discard(env_var_name)
                ret.add(f"{env_var_name}={val}")

        handle_deprecated("LANG")
        handle_deprecated("LC_ALL")

        return tuple(sorted(ret))


@dataclass(frozen=True)
class SubprocessEnvironmentVars:
    vars: FrozenDict[str, str]


@rule
def get_subprocess_environment(
    subproc_env: SubprocessEnvironment, pants_env: PantsEnvironment
) -> SubprocessEnvironmentVars:
    return SubprocessEnvironmentVars(
        pants_env.get_subset(
            subproc_env.env_vars_to_pass_to_subprocesses, allowed=SETTABLE_ENV_VARS
        )
    )


def rules():
    return collect_rules()
