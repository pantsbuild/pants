# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.fs import CreateDigest
from pants.engine.rules import collect_rules
from pants.option.global_options import ca_certs_path_to_file_content
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption, StrOption
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap


class TwineSubsystem(PythonToolBase):
    options_scope = "twine"
    name = "Twine"
    help = "The utility for publishing Python distributions to PyPI and other Python repositories."

    default_version = "twine>=4,<5"
    default_main = ConsoleScript("twine")

    default_requirements = [
        "twine>=3.7.1,<5",
        # This explicit dependency resolves a weird behavior in poetry, where it would include a
        # sys platform constraint on "Windows" when this was included transitively from the twine
        # requirements.
        # See: https://github.com/pantsbuild/pants/pull/13594#issuecomment-968154931
        "colorama>=0.4.3",
    ]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.subsystems", "twine.lock")

    skip = SkipOption("publish")
    args = ArgsListOption(example="--skip-existing")
    config = FileOption(
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
        advanced=True,
        default="<inherit>",
        help=softwrap(
            f"""
            Path to a file containing PEM-format CA certificates used for verifying secure
            connections when publishing python distributions.

            Uses the value from `[GLOBAL].ca_certs_path` by default. Set to `"<none>"` to
            not use any certificates.

            Even when using the `docker_environment` and `remote_environment` targets, this path
            will be read from the local host, and those certs will be used in the environment.

            This option cannot be overridden via environment targets, so if you need a different
            value than what the rest of your organization is using, override the value via an
            environment variable, CLI argument, or `.pants.rc` file. See {doc_url('options')}.
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
        path = default_ca_certs_path if self.ca_certs_path == "<inherit>" else self.ca_certs_path
        if not path or path == "<none>":
            return None
        return CreateDigest((ca_certs_path_to_file_content(path),))


def rules():
    return collect_rules()
