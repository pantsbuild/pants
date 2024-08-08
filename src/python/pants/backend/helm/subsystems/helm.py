# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Any, Iterable

from pants.backend.helm.resolve.remotes import HelmRemotes
from pants.backend.helm.target_types import HelmChartTarget, HelmRegistriesField
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    DictOption,
    StrListOption,
    StrOption,
)
from pants.util.memo import memoized_method
from pants.util.strutil import bullet_list, help_text, softwrap

_VALID_PASSTHROUGH_FLAGS = [
    "--atomic",
    "--cleanup-on-fail",
    "--create-namespace",
    "--debug",
    "--force",
    "--wait",
    "--wait-for-jobs",
]

_VALID_PASSTHROUGH_OPTS = [
    "--kubeconfig",
    "--kube-context",
    "--kube-apiserver",
    "--kube-as-group",
    "--kube-as-user",
    "--kube-ca-file",
    "--kube-token",
    "--timeout",
]


class InvalidHelmPassthroughArgs(Exception):
    def __init__(self, args: Iterable[str], *, extra_help: str = "") -> None:
        super().__init__(
            softwrap(
                f"""
                The following command line arguments are not valid: {' '.join(args)}.

                Only the following passthrough arguments are allowed:

                {bullet_list([*_VALID_PASSTHROUGH_FLAGS, *_VALID_PASSTHROUGH_OPTS])}

                {extra_help}
                """
            )
        )


registries_help = help_text(
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

    Registries also participate in resolving third party Helm charts uploaded to those registries.
    """
)


class HelmSubsystem(TemplatedExternalTool):
    options_scope = "helm"
    help = "The Helm command line (https://helm.sh)"

    default_version = "3.14.3"
    default_known_versions = [
        "3.14.3|linux_arm64|85e1573e76fa60af14ba7e9ec75db2129b6884203be866893fa0b3f7e41ccd5e|14558415",
        "3.14.3|linux_x86_64|3c90f24e180f8c207b8a18e5ec82cb0fa49858a7a0a86e4ed52a98398681e00b|16134525",
        "3.14.3|macos_arm64|dff794152b62b7c1a9ff615d510f8657bcd7a3727c668e0d9d4955f70d5f7573|16104367",
        "3.14.3|macos_x86_64|4d5d01a94c7d6b07e71690dc1988bf3229680284c87f4242d28c6f1cc99653be|16944220",
        "3.13.3|linux_arm64|44aaa094ae24d01e8c36e327e1837fd3377a0f9152626da088384c5bc6d94562|14495979",
        "3.13.3|linux_x86_64|bbb6e7c6201458b235f335280f35493950dcd856825ddcfd1d3b40ae757d5c7d|16188560",
        "3.13.3|macos_arm64|61ba210cd65c53be5c0021c8fc8e0b94f4c122aff32f5ed0e4ea81728108ea20|16172665",
        "3.13.3|macos_x86_64|da654c9e0fd4fcb50cc5dba051c1c9cf398e21ffa5064b47ac89a9697e139d39|16999788",
        "3.12.3|linux_arm64|79ef06935fb47e432c0c91bdefd140e5b543ec46376007ca14a52e5ed3023088|14355040",
        "3.12.3|linux_x86_64|1b2313cd198d45eab00cc37c38f6b1ca0a948ba279c29e322bdf426d406129b5|16028423",
        "3.12.3|macos_arm64|240b0a7da9cae208000eff3d3fb95e0fa1f4903d95be62c3f276f7630b12dae1|16019570",
        "3.12.3|macos_x86_64|1bdbbeec5a12dd0c1cd4efd8948a156d33e1e2f51140e2a51e1e5e7b11b81d47|16828211",
        "3.12.2|linux_arm64|cfafbae85c31afde88c69f0e5053610c8c455826081c1b2d665d9b44c31b3759|14350624",
        "3.12.2|linux_x86_64|2b6efaa009891d3703869f4be80ab86faa33fa83d9d5ff2f6492a8aebe97b219|16028750",
        "3.12.2|macos_arm64|b60ee16847e28879ae298a20ba4672fc84f741410f438e645277205824ddbf55|16021202",
        "3.12.2|macos_x86_64|6e8bfc84a640e0dc47cc49cfc2d0a482f011f4249e2dff2a7e23c7ef2df1b64e|16824814",
        "3.11.3|linux_arm64|0816db0efd033c78c3cc1c37506967947b01965b9c0739fe13ec2b1eea08f601|14475471",
        "3.11.3|linux_x86_64|ca2d5d40d4cdfb9a3a6205dd803b5bc8def00bd2f13e5526c127e9b667974a89|15489735",
        "3.11.3|macos_arm64|267e4d50b68e8854b9cc44517da9ab2f47dec39787fed9f7eba42080d61ac7f8|15451086",
        "3.11.3|macos_x86_64|9d029df37664b50e427442a600e4e065fa75fd74dac996c831ac68359654b2c4|16275303",
        "3.11.2|linux_arm64|444b65100e224beee0a3a3a54cb19dad37388fa9217ab2782ba63551c4a2e128|14090242",
        "3.11.2|linux_x86_64|781d826daec584f9d50a01f0f7dadfd25a3312217a14aa2fbb85107b014ac8ca|15026301",
        "3.11.2|macos_arm64|f61a3aa55827de2d8c64a2063fd744b618b443ed063871b79f52069e90813151|14932800",
        "3.11.2|macos_x86_64|404938fd2c6eff9e0dab830b0db943fca9e1572cd3d7ee40904705760faa390f|15759988",
        "3.11.1|linux_arm64 |919173e8fb7a3b54d76af9feb92e49e86d5a80c5185020bae8c393fa0f0de1e8|13484900",
        "3.11.1|linux_x86_64|0b1be96b66fab4770526f136f5f1a385a47c41923d33aab0dcb500e0f6c1bf7c|15023104",
        "3.11.1|macos_arm64 |43d0198a7a2ea2639caafa81bb0596c97bee2d4e40df50b36202343eb4d5c46b|14934852",
        "3.11.1|macos_x86_64|2548a90e5cc957ccc5016b47060665a9d2cd4d5b4d61dcc32f5de3144d103826|15757902",
        "3.10.0|linux_arm64 |3b72f5f8a60772fb156d0a4ab93272e8da7ef4d18e6421a7020d7c019f521fc1|13055719",
        "3.10.0|linux_x86_64|bf56beb418bb529b5e0d6d43d56654c5a03f89c98400b409d1013a33d9586474|14530566",
        "3.10.0|macos_arm64 |f7f6558ebc8211824032a7fdcf0d55ad064cb33ec1eeec3d18057b9fe2e04dbe|14446277",
        "3.10.0|macos_x86_64|1e7fd528482ac2ef2d79fe300724b3e07ff6f846a2a9b0b0fe6f5fa05691786b|15237557",
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

    _registries = DictOption[Any](help=registries_help, fromfile=True)
    lint_strict = BoolOption(default=False, help="Enables strict linting of Helm charts")
    lint_quiet = BoolOption(default=False, help="Only print warnings and errors for Helm charts")
    default_registry_repository = StrOption(
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
    extra_env_vars = StrListOption(
        help=softwrap(
            """
            Additional environment variables that would be made available to all Helm processes
            or during value interpolation.
            """
        ),
        advanced=True,
    )
    tailor_charts = BoolOption(
        default=True,
        help="If true, add `helm_chart` targets with the `tailor` goal.",
        advanced=True,
    )
    tailor_unittests = BoolOption(
        default=True,
        help="If true, add `helm_unittest_tests` targets with the `tailor` goal.",
        advanced=True,
    )

    infer_docker_image_dependencies = BoolOption(
        default=True,
        help="If true, parse k8s manifests generated by helm to find docker image references.",
        advanced=True,
    )

    args = ArgsListOption(
        example="--force",
        passthrough=True,
        extra_help=softwrap(
            f"""
            Additional arguments to pass to Helm command line.

            Only a subset of Helm arguments are considered valid as passthrough arguments as most of them
            have equivalents in the form of fields of the different target types.

            The list of valid arguments is as follows:

            {bullet_list([*_VALID_PASSTHROUGH_FLAGS, *_VALID_PASSTHROUGH_OPTS])}

            Before attempting to use passthrough arguments, check the reference of each of the available target types
            to see what fields are accepted in each of them.

            To pass `--dry-run`, use the `--experimental-deploy-dry-run` flag.
            """
        ),
    )

    @memoized_method
    def valid_args(self, *, extra_help: str = "") -> tuple[str, ...]:
        valid, invalid = _cleanup_passthrough_args(self.args)
        if invalid:
            raise InvalidHelmPassthroughArgs(invalid, extra_help=extra_help)
        return tuple(valid)

    def generate_exe(self, plat: Platform) -> str:
        mapped_plat = self.default_url_platform_mapping[plat.value]
        bin_path = os.path.join(mapped_plat, "helm")
        return bin_path

    @memoized_method
    def remotes(self) -> HelmRemotes:
        return HelmRemotes.from_dict(self._registries)


def _cleanup_passthrough_args(args: Iterable[str]) -> tuple[list[str], list[str]]:
    valid_args: list[str] = []
    removed_args: list[str] = []

    skip = False
    for arg in args:
        if skip:
            valid_args.append(arg)
            skip = False
            continue

        if arg in _VALID_PASSTHROUGH_FLAGS:
            valid_args.append(arg)
        elif "=" in arg and arg.split("=")[0] in _VALID_PASSTHROUGH_OPTS:
            valid_args.append(arg)
        elif arg in _VALID_PASSTHROUGH_OPTS:
            valid_args.append(arg)
            skip = True
        else:
            removed_args.append(arg)

    return (valid_args, removed_args)
