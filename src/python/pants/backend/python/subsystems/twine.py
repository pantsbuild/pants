# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from pathlib import Path

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption, StrOption
from pants.util.docutil import git_url
from pants.util.strutil import softwrap


class TwineSubsystem(PythonToolBase):
    options_scope = "twine"
    name = "Twine"
    help = "The utility for publishing Python distributions to PyPi and other Python repositories."

    default_version = "twine>=3.7.1,<3.8"
    default_main = ConsoleScript("twine")

    # This explicit dependency resolves a weird behavior in poetry, where it would include a sys
    # platform constraint on "Windows" when this was included transitively from the twine
    # requirements.
    # See: https://github.com/pantsbuild/pants/pull/13594#issuecomment-968154931
    default_extra_requirements = ["colorama>=0.4.3"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "twine.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/twine.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("publish")
    args = ArgsListOption(example="--skip-existing")
    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a .pypirc config file to use.
            (https://packaging.python.org/specifications/pypirc/)

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        "--config-discovery",
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include all relevant config files during runs (`.pypirc`).

            Use `[{cls.options_scope}].config` instead if your config is in a non-standard location.
            """
        ),
    )
    ca_certs_path = StrOption(
        "--ca-certs-path",
        advanced=True,
        default="<inherit>",
        help=softwrap(
            """
            Path to a file containing PEM-format CA certificates used for verifying secure
            connections when publishing python distributions.

            Uses the value from `[GLOBAL].ca_certs_path` by default. Set to `"<none>"` to
            not use the default CA certificate.
            """
        ),
    )

    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://twine.readthedocs.io/en/latest/#configuration for how config files are
        # discovered.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[".pypirc"],
        )

    def ca_certs_digest_request(self, default_ca_certs_path: str | None) -> CreateDigest | None:
        ca_certs_path: str | None = self.ca_certs_path
        if ca_certs_path == "<inherit>":
            ca_certs_path = default_ca_certs_path
        if not ca_certs_path or ca_certs_path == "<none>":
            return None

        # The certs file will typically not be in the repo, so we can't digest it via a PathGlobs.
        # Instead we manually create a FileContent for it.
        ca_certs_content = Path(ca_certs_path).read_bytes()
        chrooted_ca_certs_path = os.path.basename(ca_certs_path)
        return CreateDigest((FileContent(chrooted_ca_certs_path, ca_certs_content),))


class TwineLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = TwineSubsystem.options_scope


@rule
def setup_twine_lockfile(
    _: TwineLockfileSentinel, twine: TwineSubsystem, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(twine, use_pex=python_setup.generate_lockfiles_with_pex)


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, TwineLockfileSentinel),
    )
