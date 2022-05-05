# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Any

from pants.backend.helm.resolve.remotes import HelmRemotes
from pants.backend.helm.target_types import HelmChartTarget, HelmRegistriesField
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import BoolOption, DictOption, StrOption
from pants.util.memo import memoized_method
from pants.util.strutil import softwrap

registries_help = softwrap(
    f"""
    Configure Helm OCI registries. The schema for a registry entry is as follows:

        {{
            "registry-alias": {{
                "address": "oci://registry-domain:port",
                "default": bool,
            }},
            ...
        }}

    If no registries are provided in either a `{HelmChartTarget.alias}` target, then all default
    addresses will be used, if any.

    The `{HelmChartTarget.alias}.{HelmRegistriesField.alias}` may be provided with a list of registry
    addresses and registry alias prefixed with `@` to be used instead of the defaults.

    A configured registry is marked as default either by setting `default = true`
    or with an alias of `"default"`.

    Registries also participate in resolving third party Helm charts uplodaded to those registries.
    """
)


class HelmSubsystem(TemplatedExternalTool):
    options_scope = "helm"
    help = "The Helm command line (https://helm.sh)"

    default_version = "3.8.0"
    default_known_versions = [
        "3.8.0|linux_arm64 |23e08035dc0106fe4e0bd85800fd795b2b9ecd9f32187aa16c49b0a917105161|12324642",
        "3.8.0|linux_x86_64|8408c91e846c5b9ba15eb6b1a5a79fc22dd4d33ac6ea63388e5698d1b2320c8b|13626774",
        "3.8.0|macos_arm64 |751348f1a4a876ffe089fd68df6aea310fd05fe3b163ab76aa62632e327122f3|14078604",
        "3.8.0|macos_x86_64|532ddd6213891084873e5c2dcafa577f425ca662a6594a3389e288fc48dc2089|14318316",
    ]
    default_url_template = "https://get.helm.sh/helm-v{version}-{platform}.tar.gz"
    default_url_platform_mapping = {
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
    }

    _registries = DictOption[Any]("--registries", help=registries_help, fromfile=True)
    lint_strict = BoolOption(
        "--lint-strict", default=False, help="Enables strict linting of Helm charts"
    )
    default_registry_repository = StrOption(
        "--default-registry-repository",
        default=None,
        help=softwrap(
            """
            Default location where to push Helm charts in the available registries
            when no specific one has been given.

            If no registry repository is given, charts will be pushed to the root of
            the OCI registry.
            """
        ),
    )
    tailor = BoolOption(
        "--tailor",
        default=True,
        help="If true, add `helm_chart` targets with the `tailor` goal.",
        advanced=True,
    )

    def generate_exe(self, plat: Platform) -> str:
        mapped_plat = self.default_url_platform_mapping[plat.value]
        bin_path = os.path.join(mapped_plat, "helm")
        return bin_path

    @memoized_method
    def remotes(self) -> HelmRemotes:
        return HelmRemotes.from_dict(self._registries)
