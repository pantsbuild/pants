# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import cast

from pants.backend.helm.resolve.registries import OCI_REGISTRY_PROTOCOL, HelmRegistries
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.util.memo import memoized_method
from pants.util.strutil import bullet_list


class HelmSubsystem(TemplatedExternalTool):
    options_scope = "helm"
    help = "The Helm command line (https://helm.sh)"

    default_version = "3.8.0"
    default_known_versions = [
        "3.8.0|linux_arm64 |23e08035dc0106fe4e0bd85800fd795b2b9ecd9f32187aa16c49b0a917105161|12324642",
        "3.8.0|linux_x86_64|8408c91e846c5b9ba15eb6b1a5a79fc22dd4d33ac6ea63388e5698d1b2320c8b|13626774",
        "3.8.0|macos_arm64 |751348f1a4a876ffe089fd68df6aea310fd05fe3b163ab76aa62632e327122f3|14078604",
        "3.8.0|macos_x86_64|532ddd6213891084873e5c2dcafa577f425ca662a6594a3389e288fc48dc2089|14318316",
        "3.7.2|linux_arm64 |b0214eabbb64791f563bd222d17150ce39bf4e2f5de49f49fdb456ce9ae8162f|12272309",
        "3.7.2|linux_x86_64|4ae30e48966aba5f807a4e140dad6736ee1a392940101e4d79ffb4ee86200a9e|13870692",
        "3.7.2|macos_arm64 |260d4b8bffcebc6562ea344dfe88efe252cf9511dd6da3cccebf783773d42aec|13978034",
        "3.7.2|macos_x86_64|5a0738afb1e194853aab00258453be8624e0a1d34fcc3c779989ac8dbcd59436|14529117",
    ]
    default_url_template = "https://get.helm.sh/helm-v{version}-{platform}.tar.gz"
    default_url_platform_mapping = {
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
    }

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        registries_help = (
            dedent(
                """\
                Configure Helm OCI registries. The schema for a registry entry is as follows:
                    {
                        "registry-alias": {
                            "address": "oci://registry-domain:port",
                            "default": bool,
                        },
                        ...
                    }
                """
            )
            + (
                "If no registries are provided in a `helm_chart` target, then all default "
                "addresses will be used when publishing charts, if there are any configured.\n"
                "The `helm_chart.registries` may be provided with a list of registry addresses "
                "and registry aliases prefixed with `@` to be used instead of the defaults.\n"
                "A configured registry is marked as default either by setting `default = true` "
                'or with an alias of `"default"`.'
            )
        )
        default_repository_help = (
            "Configure the default repository name used in the Helm chart OCI registry.\n\n"
            "The value is formatted and may reference these variables:\n\n"
            + bullet_list(["name", "directory", "parent_directory"])
            + "\n\n"
            'Example: `--default-repository="{directory}/{name}"`.\n\n'
            "The `name` variable is the `docker_image`'s target name, `directory` and "
            "`parent_directory` are the name of the directory in which the BUILD file is for the "
            "target, and its parent directory respectively.\n\n"
            "Use the `repository` field to set this value directly on a `helm_chart` "
            "target.\nAny registries are added to the chart name as required, and should "
            "not be part of the repository name."
        )

        register("--registries", type=dict, fromfile=True, help=registries_help)
        register(
            "--default-repository",
            type=str,
            default="charts",
            help=default_repository_help,
        )
        register("--strict", type=bool, default=False, help="Enables strict linting of Helm charts")

    def generate_exe(self, plat: Platform) -> str:
        mapped_plat = self.default_url_platform_mapping[plat.value]
        return f"./{mapped_plat}/helm"

    @memoized_method
    def registries(self) -> HelmRegistries:
        return HelmRegistries.from_dict(self.options.registries)

    def strip_default_repository_from_oci_address(self, ref: str) -> str:
        if ref.startswith(OCI_REGISTRY_PROTOCOL) and ref.rstrip("/").endswith(
            self.default_repository
        ):
            return ref[: -(len(self.default_repository) + 1)]
        else:
            return ref

    @property
    def default_repository(self) -> str:
        return cast("str", self.options.default_repository).rstrip("/")

    @property
    def strict(self) -> bool:
        return cast("bool", self.options.strict)
