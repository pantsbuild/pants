# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.target import BoolField
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    FileOption,
    SkipOption,
    StrListOption,
)
from pants.util.strutil import softwrap


class Trivy(TemplatedExternalTool):
    options_scope = "trivy"
    name = "Trivy"
    help = "Find vulnerabilities, misconfigurations, secrets, SBOM in containers, Kubernetes, code repositories, clouds and more"

    default_version = "0.57.0"
    default_known_versions = [
        "0.57.0|linux_arm64 |29012fdb5ba18da506d1c8b6f389c2ec9d113db965c254971f35267ebb45dd64|37315561",
        "0.57.0|linux_x86_64|cf08a8cd861e5192631fc03bb21efde27c1d93e4407ab70bab32e572bafcbf07|40466119",
        "0.57.0|macos_arm64 |61230c8a56e463e8eba2bf922bc688b7bd40352187e1f725c79861b0801437f0|39193442",
        "0.57.0|macos_x86_64|e7955b6d38d8125d4aa8936e6af51b0de2b0e0840b4feb90b44002bf7f47bf13|41286618",
    ]

    default_url_template = "https://github.com/aquasecurity/trivy/releases/download/v{version}/trivy_{version}_{platform}.tar.gz"
    default_url_platform_mapping = {
        "macos_arm64": "macOS-ARM64",
        "macos_x86_64": "macOS-64bit",
        "linux_arm64": "Linux-ARM64",
        "linux_x86_64": "Linux-64bit",
    }

    skip = SkipOption("lint")
    args = ArgsListOption(example="--scanners vuln")

    severity = StrListOption(
        default=None,
        help=softwrap(
            """
            Severities of security issues to be displayed (UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL)
            """
        ),
    )

    extra_env_vars = StrListOption(
        help=softwrap(
            """
            Additional environment variables that would be made available to all Terraform processes.
            """
        ),
        advanced=True,
    )

    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include all relevant config files during runs.

            Use `[{cls.options_scope}].config` instead if your config is in a non-standard location
            """
        ),
    )
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            """
            Path to the Trivy config file.

            Setting this option will disable config discovery for the config file. Use this option if the config is located in a non-standard location.
            """
        ),
    )

    def config_request(self) -> ConfigFilesRequest:
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=["trivy.yaml"],
        )

    @property
    def cache_dir(self) -> str:
        return "__trivy_cache"

    @property
    def append_only_caches(self) -> dict[str, str]:
        return {"trivy_cache": self.cache_dir}


class SkipTrivyField(BoolField):
    alias = "skip_trivy"
    default = False
    help = "If true, don't run Trivy on this target's Terraform files"
