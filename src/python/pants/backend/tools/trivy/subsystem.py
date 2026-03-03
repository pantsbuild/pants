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

    default_version = "0.69.2"
    default_known_versions = [
        "0.69.2|linux_arm64 |c73b97699c317b0d25532b3f188564b4e29d13d5472ce6f8eb078082546a6481|43702248",
        "0.69.2|linux_x86_64|affa59a1e37d86e4b8ab2cd02f0ab2e63d22f1bf9cf6a7aa326c884e25e26ce3|48327305",
        "0.69.2|macos_arm64 |320c0e6af90b5733b9326da0834240e944c6f44091e50019abdf584237ff4d0c|45881045",
        "0.69.2|macos_x86_64|41f6eac3ebe3a00448a16f08038b55ce769fe2d5128cb0d64bdf282cdad4831a|49275481",
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
