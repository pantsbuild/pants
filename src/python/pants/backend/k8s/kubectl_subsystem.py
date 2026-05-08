# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.core.util_rules.search_paths import ExecutableSearchPathsOptionMixin
from pants.engine.rules import collect_rules
from pants.option.option_types import BoolOption, StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class Kubectl(TemplatedExternalTool):
    name = "kubectl"
    options_scope = "kubectl"
    help = "Kubernetes command line tool"

    default_version = "1.32.0"
    default_known_versions = [
        "1.32.0|linux_arm64 |ba4004f98f3d3a7b7d2954ff0a424caa2c2b06b78c17b1dccf2acc76a311a896|55836824",
        "1.32.0|linux_arm64 |ba4004f98f3d3a7b7d2954ff0a424caa2c2b06b78c17b1dccf2acc76a311a896|55836824",
        "1.32.0|linux_x86_64|646d58f6d98ee670a71d9cdffbf6625aeea2849d567f214bc43a35f8ccb7bf70|57323672",
        "1.32.0|linux_x86_64|646d58f6d98ee670a71d9cdffbf6625aeea2849d567f214bc43a35f8ccb7bf70|57323672",
        "1.32.0|macos_arm64 |5bfd5de53a054b4ef614c60748e28bf47441c7ed4db47ec3c19a3e2fa0eb5555|57472706",
        "1.32.0|macos_arm64 |5bfd5de53a054b4ef614c60748e28bf47441c7ed4db47ec3c19a3e2fa0eb5555|57472706",
        "1.32.0|macos_x86_64|516585916f499077fac8c2fdd2a382818683f831020277472e6bcf8d1a6f9be4|58612096",
        "1.32.0|macos_x86_64|516585916f499077fac8c2fdd2a382818683f831020277472e6bcf8d1a6f9be4|58612096",
        "1.31.4|linux_arm64 |b97e93c20e3be4b8c8fa1235a41b4d77d4f2022ed3d899230dbbbbd43d26f872|54984856",
        "1.31.4|linux_x86_64|298e19e9c6c17199011404278f0ff8168a7eca4217edad9097af577023a5620f|56381592",
        "1.31.4|macos_arm64 |a756bb911298a85af35c0111c371728a26c532d504fe8b534eb684501fcaf996|56560802",
        "1.31.4|macos_x86_64|fd996e9f41fd42c6c1c781a5a85990f4d0d8337ede00a7719afa23be886e0abd|57637984",
        "1.30.8|linux_arm64 |e51d6a76fade0871a9143b64dc62a5ff44f369aa6cb4b04967d93798bf39d15b|49938584",
        "1.30.8|linux_x86_64|7f39bdcf768ce4b8c1428894c70c49c8b4d2eee52f3606eb02f5f7d10f66d692|51454104",
        "1.30.8|macos_arm64 |52b11bb032f88e4718cd4e3c8374a6b1fad29772aa1ce701276cc4e17d37642f|51395442",
        "1.30.8|macos_x86_64|46682e24c3aecfbe92f53b86fb15beb740c43a0fafe0a4e06a1c8bb3ce9e985b|52586352",
        "1.29.12|linux_arm64 |1cf2c00bb4f5ee6df69678e95af8ba9a4d4b1050ddefb0ae9d84b5c6f6c0e817|48758936",
        "1.29.12|linux_x86_64|35fc028853e6f5299a53f22ab58273ea2d882c0f261ead0a2eed5b844b12dbfb|50225304",
        "1.29.12|macos_arm64 |5d1c59d8ce4d619bdd78fa849201dbfc9180f6dddcfdb30f29b5bbe20799b897|50169474",
        "1.29.12|macos_x86_64|0df5932d0ba7a4665ea8033470f2f1a1db21637c3fabc709faa19db0fc62b5ec|51333056",
        "1.28.15|linux_arm64 |7d45d9620e67095be41403ed80765fe47fcfbf4b4ed0bf0d1c8fe80345bda7d3|48169112",
        "1.28.15|linux_x86_64|1f7651ad0b50ef4561aa82e77f3ad06599b5e6b0b2a5fb6c4f474d95a77e41c5|49623192",
        "1.28.15|macos_arm64 |06a276bdb6da95af148d589f6c983ec8ea10c38f277ced6d97123938c8146078|49593410",
        "1.28.15|macos_x86_64|3180c84131002037d60fe7322794c20297d0e1b1514eaea20e33f77a00d8f2f4|50716416",
        "1.27.16|linux_arm64 |2f50cb29d73f696ffb57437d3e2c95b22c54f019de1dba19e2b834e0b4501eb9|47644824",
        "1.27.16|linux_x86_64|97ea7cd771d0c6e3332614668a40d2c5996f0053ff11b44b198ea84dba0818cb|49066136",
        "1.27.16|macos_arm64 |d6bc47098bcb13a0ff5c267b30021b499aff4d960bd92610c2b0bc6f6e7246c9|49017698",
        "1.27.16|macos_x86_64|8d7f339660ba9b33ed56d540bed41b37babc945975a9e7027010697249b9ac5a|50145152",
        "1.26.15|linux_arm64 |1396313f0f8e84ab1879757797992f1af043e1050283532e0fd8469902632216|46661632",
        "1.26.15|linux_x86_64|b75f359e6fad3cdbf05a0ee9d5872c43383683bb8527a9e078bb5b8a44350a41|48148480",
        "1.26.15|macos_arm64 |c20b920d7e8e3ce3209c7c109fcfc4c09ad599613bc04b72c3f70d9fee598b68|53860082",
        "1.26.15|macos_x86_64|ad4e980f9c304840ec9227a78a998e132ea23f3ca1bc0df7718ed160341bad0b|54047120",
        "1.25.16|linux_arm64 |d6c23c80828092f028476743638a091f2f5e8141273d5228bf06c6671ef46924|43581440",
        "1.25.16|linux_x86_64|5a9bc1d3ebfc7f6f812042d5f97b82730f2bdda47634b67bddf36ed23819ab17|45658112",
        "1.25.16|macos_arm64 |d364f73df218b02642d06f3fa9b7345d64c03567b96ca21d361b487f48a33ccc|50416738",
        "1.25.16|macos_x86_64|34e87fdf0613502edbd2a2b00de5ee8c7789ab10e33257d14423dc6879321920|50954608",
        "1.24.17|linux_arm64 |66885bda3a202546778c77f0b66dcf7f576b5a49ff9456acf61329da784a602d|44630016",
        "1.24.17|linux_x86_64|3e9588e3326c7110a163103fc3ea101bb0e85f4d6fd228cf928fa9a2a20594d5|46706688",
        "1.24.17|macos_arm64 |7addbe3f1e22a366fa05aed4f268e77e83d902b40a5854e192b4205ed92e5f8d|52955666",
        "1.24.17|macos_x86_64|1eb904b2c1148ff8431b0bd86677287a48bff000f93fd2d36377fbe956bd1e49|53481056",
        "1.23.17|linux_arm64 |c4a48fdc6038beacbc5de3e4cf6c23639b643e76656aabe2b7798d3898ec7f05|43778048",
        "1.23.17|linux_x86_64|f09f7338b5a677f17a9443796c648d2b80feaec9d6a094ab79a77c8a01fde941|45174784",
        "1.23.17|macos_arm64 |3b4590d67b31e3a94a9633064571c981907555da5376c34960cddfcd552f6114|51181986",
        "1.23.17|macos_x86_64|7ece6543e3ca2ae9698ef61bbb2a4e249aa21319df4ea1b27c136a9b005dd7d8|51721104",
        "1.22.17|linux_arm64 |8fc2f8d5c80a6bf60be06f8cf28679a05ce565ce0bc81e70aaac38e0f7da6259|43515904",
        "1.22.17|linux_x86_64|7506a0ae7a59b35089853e1da2b0b9ac0258c5309ea3d165c3412904a9051d48|46944256",
        "1.22.17|macos_arm64 |b2d881bd6d3c688645cbc9e5b4cf4fe8945e1cfc3f2c07c795d2ee605ce4e568|52098562",
        "1.22.17|macos_x86_64|c3b8ae5ad48e1e126b5db2e7e22bb1e6ac54901a7f94ce499d12316f705e5e15|53133440",
        "1.21.14|linux_arm64 |a23151bca5d918e9238546e7af416422b51cda597a22abaae5ca50369abfbbaa|43319296",
        "1.21.14|linux_x86_64|0c1682493c2abd7bc5fe4ddcdb0b6e5d417aa7e067994ffeca964163a988c6ee|46686208",
        "1.21.14|macos_arm64 |e0e6e413e19abc9deb15f9bd3c72f73ff5539973758e64ebca0f5eb085de6a00|51872962",
        "1.21.14|macos_x86_64|30c529fe2891eb93dda99597b5c84cb10d2318bb92ae89e1e6189b3ae5fb6296|52867344",
    ]
    version_constraints = ">=1,<2"

    default_url_template = "https://dl.k8s.io/release/v{version}/bin/{platform}/kubectl"
    default_url_platform_mapping = {
        "linux_arm64": "linux/arm64",
        "linux_x86_64": "linux/amd64",
        "macos_arm64": "darwin/arm64",
        "macos_x86_64": "darwin/amd64",
    }

    pass_context = BoolOption(
        default=True,
        help=softwrap(
            """
            Pass `--context` argument to `kubectl` command.
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
        default=[
            "HOME",
            "KUBECONFIG",
            "KUBERNETES_SERVICE_HOST",
            "KUBERNETES_SERVICE_PORT",
        ],
        advanced=True,
    )

    class EnvironmentAware(ExecutableSearchPathsOptionMixin, Subsystem.EnvironmentAware):
        executable_search_paths_help = softwrap(
            """
            The PATH value that will be used to find kubectl binary.
            """
        )


def rules():
    return collect_rules()
