# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.option.custom_types import file_option, shell_str


class Hadolint(TemplatedExternalTool):
    options_scope = "hadolint"
    name = "hadolint"
    help = "A linter for Dockerfiles."

    default_version = "v2.8.0"
    # TODO: https://github.com/hadolint/hadolint/issues/411 tracks building and releasing
    #  hadolint for Linux ARM64.
    default_known_versions = [
        "v2.8.0|macos_x86_64|27985f257a216ecab06a16e643e8cb0123e7145b5d526cfcb4ce7a31fe99f357|2428944",
        "v2.8.0|macos_arm64 |27985f257a216ecab06a16e643e8cb0123e7145b5d526cfcb4ce7a31fe99f357|2428944",  # same as mac x86
        "v2.8.0|linux_x86_64|9dfc155139a1e1e9b3b28f3de9907736b9dfe7cead1c3a0ae7ff0158f3191674|5895708",
    ]
    default_url_template = (
        "https://github.com/hadolint/hadolint/releases/download/{version}/hadolint-{platform}"
    )
    default_url_platform_mapping = {
        "macos_arm64": "Darwin-x86_64",
        "macos_x86_64": "Darwin-x86_64",
        "linux_x86_64": "Linux-x86_64",
    }

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use Hadolint when running `./pants lint`.",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to Hadolint, e.g. `--hadolint-args='--format json'`.'"
            ),
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to an YAML config file understood by Hadolint "
                "(https://github.com/hadolint/hadolint#configure).\n\n"
                f"Setting this option will disable `[{cls.options_scope}].config_discovery`. Use "
                "this option if the config is located in a non-standard location."
            ),
        )
        register(
            "--config-discovery",
            type=bool,
            default=True,
            advanced=True,
            help=(
                "If true, Pants will include all relevant config files during runs "
                "(`.hadolint.yaml` and `.hadolint.yml`).\n\n"
                f"Use `[{cls.options_scope}].config` instead if your config is in a "
                "non-standard location."
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def config(self) -> str | None:
        return cast("str | None", self.options.config)

    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://github.com/hadolint/hadolint#configure for how config files are
        # discovered.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=cast(bool, self.options.config_discovery),
            check_existence=[".hadolint.yaml", ".hadolint.yml"],
        )
