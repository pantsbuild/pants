# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from collections.abc import Mapping, Sequence
from typing import Optional

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.core.util_rules.search_paths import ExecutableSearchPathsOptionMixin
from pants.engine.internals.native_engine import Digest
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope
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
        "1.0.7|linux_x86_64|78fa9a5628ae29b091ea0bbab58635fe899fd0c5c01646fb2bf7b6dff6097b70|19387320",
        "1.0.7|macos_x86_64|f40f5606ff24e97b9df926febb6f490ba138ddd9cfb8c1d132036408b7181d87|19136448",
        "1.1.8|linux_x86_64|b2222986e9f05da8091a16134022d243b3c46a5899486d1b775dbc950ebf36cd|22589688",
        "1.1.8|macos_x86_64|da67619ec248a480db20d0704680e0ea91fe0787c8070f342d570c70d957e060|22097696",
        "1.10.13|linux_arm64|f52bd7804bec8dadb64af1610bb5c89fd2f2c37a4533c4723df04edb937d0f87|52620142",
        "1.10.13|linux_x86_64|0157b02fe9f42a6a5fc738597259d9d22f2d1cb4235d96347e01d1cf7b984980|55100736",
        "1.10.13|macos_x86_64|94ec5409ac6715dfec11309795da9b30254b9d818f8b1d38d1ca2e914945868d|54670032",
        "1.11.10|linux_arm64|8bbf7e9b666a8c639907e839fad226b46604fd22f8a33a0fc85acda248d571a9|54746905",
        "1.11.10|linux_x86_64|fe1a101b476e54515458f98bb0747f2ddfefb69861fe9786a88d7b5ce61e6f45|55461388",
        "1.11.10|macos_x86_64|cf27dd3e8d5a13439de2214b7a07e2371cdbeaf151ee4c7d63e7e7c34ebbf117|54985744",
        "1.12.10|linux_arm64|c306e470c31227d4de7c3c0cecb06a694501563d1332301d4ac2080422870021|56618322",
        "1.12.10|linux_x86_64|b1250b8cadea0e8ad2896f6379abd52bcbbfa2d8ff3253d86d7e705003d83da4|57361431",
        "1.12.10|macos_x86_64|67acf17bf77b0a9729d17ad5c058a358c0cbd12dbf46478c37111cdd97a0828c|56860112",
        "1.13.12|linux_arm64|47ffe9064318c6a9613f6ac5a5f96ffb43dec6dc4a37ea4b2992bf378c8e6f02|36593184",
        "1.13.12|linux_x86_64|3578dbaec9fd043cf2779fbc54afb4297f3e8b50df7493191313bccbb8046300|39271904",
        "1.13.12|macos_x86_64|ddbdc7591569f321b8b0a01dcbd679f6b0a7756f1427a51a39eadfce8d34bea7|44353656",
        "1.14.10|linux_arm64|7927cfdbf6c793626d0e437ca2c45dd2c1431b6629193ef17f798e81a76b4234|41337728",
        "1.14.10|linux_x86_64|7729c6612bec76badc7926a79b26e0d9b06cc312af46dbb80ea7416d1fce0b36|43119424",
        "1.14.10|macos_x86_64|43d2c24eafb2ef09a6ac77c2b99070668e83edaa325a16a362e304ba578fdc48|48716328",
        "1.15.12|linux_arm64|ef9a4272d556851c645d6788631a2993823260a7e1176a281620284b4c3406da|41228416",
        "1.15.12|linux_x86_64|a32b762279c33cb8d8f4198f3facdae402248c3164e9b9b664c3afbd5a27472e|43059232",
        "1.15.12|macos_x86_64|1b06cab9ee7988f8e71c48dd1d9379aa7c14123cbbc63e12ab5342c3e9130972|48668112",
        "1.16.15|linux_arm64|74719f137dc6d589a3b8a667bcb0f3c57eebd8f050dd2f7ad5b59ceb892a7b99|40697856",
        "1.16.15|linux_x86_64|e8913069293156ddf55f243814a22d2384fc18b165efb6200606fdeaad146605|42967040",
        "1.16.15|macos_x86_64|aff54bfaaed905813f61a2d0ca039176d6d309e59f92ebdb297c7da1df105485|48907792",
        "1.17.17|linux_arm64|6ffc1749adbda24474e67678fcc4a1e704c4e1b9354508965bbab3578bd801ba|41091072",
        "1.17.17|linux_x86_64|8329fac94c66bf7a475b630972a8c0b036bab1f28a5584115e8dd26483de8349|43458560",
        "1.17.17|macos_x86_64|e76b57bbed823a8572f7ccbf9caae56855048434d818dc13559e89ead5f91578|49542736",
        "1.18.20|linux_arm64|31e6bbc657b13ce1b932bf7589bca41a25b0612b4d897b1f363dc9c5a8080a22|41680896",
        "1.18.20|linux_x86_64|66a9bb8e9843050340844ca6e72e67632b75b9ebb651559c49db22f35450ed2f|43958272",
        "1.18.20|macos_x86_64|bc709378c27da458b31395787a74cd9ac58dce7dbe2a7ba92f8bc2221eeed0be|50095696",
        "1.19.16|linux_arm64|6ad55694db34b9ffbc3cb41761a50160eea0a962eb86899410593931b4e602d0|39845888",
        "1.19.16|linux_x86_64|6b9d9315877c624097630ac3c9a13f1f7603be39764001da7a080162f85cbc7e|42950656",
        "1.19.16|macos_x86_64|7fdbc38bb9d93514cfc20e7770991a9f726836f800778647211a4802959fcf01|49406176",
        "1.2.7|linux_x86_64|d5585f95aba909e80d8364523a198d9c70327c3563c4d1b3fa6c9cb66c8d5efc|41025232",
        "1.2.7|macos_x86_64|6a9ce64210aea84349ebd9296d7f53d05c734d65e166a6392b96af2588dfa860|40468352",
        "1.20.15|linux_arm64|d479febfb2e967bd86240b5c0b841e40e39e1ef610afd6f224281a23318c13dc|37158912",
        "1.20.15|linux_x86_64|d283552d3ef3b0fd47c08953414e1e73897a1b3f88c8a520bb2e7de4e37e96f3|40243200",
        "1.20.15|macos_x86_64|6b6cf555a34271379b45013dfa9b580329314254aafc91b543bf2d83ebd1db74|46242192",
        "1.21.14|linux_arm64|a23151bca5d918e9238546e7af416422b51cda597a22abaae5ca50369abfbbaa|43319296",
        "1.21.14|linux_x86_64|0c1682493c2abd7bc5fe4ddcdb0b6e5d417aa7e067994ffeca964163a988c6ee|46686208",
        "1.21.14|macos_arm64|e0e6e413e19abc9deb15f9bd3c72f73ff5539973758e64ebca0f5eb085de6a00|51872962",
        "1.21.14|macos_x86_64|30c529fe2891eb93dda99597b5c84cb10d2318bb92ae89e1e6189b3ae5fb6296|52867344",
        "1.22.17|linux_arm64|8fc2f8d5c80a6bf60be06f8cf28679a05ce565ce0bc81e70aaac38e0f7da6259|43515904",
        "1.22.17|linux_x86_64|7506a0ae7a59b35089853e1da2b0b9ac0258c5309ea3d165c3412904a9051d48|46944256",
        "1.22.17|macos_arm64|b2d881bd6d3c688645cbc9e5b4cf4fe8945e1cfc3f2c07c795d2ee605ce4e568|52098562",
        "1.22.17|macos_x86_64|c3b8ae5ad48e1e126b5db2e7e22bb1e6ac54901a7f94ce499d12316f705e5e15|53133440",
        "1.23.17|linux_arm64|c4a48fdc6038beacbc5de3e4cf6c23639b643e76656aabe2b7798d3898ec7f05|43778048",
        "1.23.17|linux_x86_64|f09f7338b5a677f17a9443796c648d2b80feaec9d6a094ab79a77c8a01fde941|45174784",
        "1.23.17|macos_arm64|3b4590d67b31e3a94a9633064571c981907555da5376c34960cddfcd552f6114|51181986",
        "1.23.17|macos_x86_64|7ece6543e3ca2ae9698ef61bbb2a4e249aa21319df4ea1b27c136a9b005dd7d8|51721104",
        "1.24.17|linux_arm64|66885bda3a202546778c77f0b66dcf7f576b5a49ff9456acf61329da784a602d|44630016",
        "1.24.17|linux_x86_64|3e9588e3326c7110a163103fc3ea101bb0e85f4d6fd228cf928fa9a2a20594d5|46706688",
        "1.24.17|macos_arm64|7addbe3f1e22a366fa05aed4f268e77e83d902b40a5854e192b4205ed92e5f8d|52955666",
        "1.24.17|macos_x86_64|1eb904b2c1148ff8431b0bd86677287a48bff000f93fd2d36377fbe956bd1e49|53481056",
        "1.25.16|linux_arm64|d6c23c80828092f028476743638a091f2f5e8141273d5228bf06c6671ef46924|43581440",
        "1.25.16|linux_x86_64|5a9bc1d3ebfc7f6f812042d5f97b82730f2bdda47634b67bddf36ed23819ab17|45658112",
        "1.25.16|macos_arm64|d364f73df218b02642d06f3fa9b7345d64c03567b96ca21d361b487f48a33ccc|50416738",
        "1.25.16|macos_x86_64|34e87fdf0613502edbd2a2b00de5ee8c7789ab10e33257d14423dc6879321920|50954608",
        "1.26.15|linux_arm64|1396313f0f8e84ab1879757797992f1af043e1050283532e0fd8469902632216|46661632",
        "1.26.15|linux_x86_64|b75f359e6fad3cdbf05a0ee9d5872c43383683bb8527a9e078bb5b8a44350a41|48148480",
        "1.26.15|macos_arm64|c20b920d7e8e3ce3209c7c109fcfc4c09ad599613bc04b72c3f70d9fee598b68|53860082",
        "1.26.15|macos_x86_64|ad4e980f9c304840ec9227a78a998e132ea23f3ca1bc0df7718ed160341bad0b|54047120",
        "1.27.16|linux_arm64|2f50cb29d73f696ffb57437d3e2c95b22c54f019de1dba19e2b834e0b4501eb9|47644824",
        "1.27.16|linux_x86_64|97ea7cd771d0c6e3332614668a40d2c5996f0053ff11b44b198ea84dba0818cb|49066136",
        "1.27.16|macos_arm64|d6bc47098bcb13a0ff5c267b30021b499aff4d960bd92610c2b0bc6f6e7246c9|49017698",
        "1.27.16|macos_x86_64|8d7f339660ba9b33ed56d540bed41b37babc945975a9e7027010697249b9ac5a|50145152",
        "1.28.15|linux_arm64|7d45d9620e67095be41403ed80765fe47fcfbf4b4ed0bf0d1c8fe80345bda7d3|48169112",
        "1.28.15|linux_x86_64|1f7651ad0b50ef4561aa82e77f3ad06599b5e6b0b2a5fb6c4f474d95a77e41c5|49623192",
        "1.28.15|macos_arm64|06a276bdb6da95af148d589f6c983ec8ea10c38f277ced6d97123938c8146078|49593410",
        "1.28.15|macos_x86_64|3180c84131002037d60fe7322794c20297d0e1b1514eaea20e33f77a00d8f2f4|50716416",
        "1.29.12|linux_arm64|1cf2c00bb4f5ee6df69678e95af8ba9a4d4b1050ddefb0ae9d84b5c6f6c0e817|48758936",
        "1.29.12|linux_x86_64|35fc028853e6f5299a53f22ab58273ea2d882c0f261ead0a2eed5b844b12dbfb|50225304",
        "1.29.12|macos_arm64|5d1c59d8ce4d619bdd78fa849201dbfc9180f6dddcfdb30f29b5bbe20799b897|50169474",
        "1.29.12|macos_x86_64|0df5932d0ba7a4665ea8033470f2f1a1db21637c3fabc709faa19db0fc62b5ec|51333056",
        "1.3.10|linux_arm64|0c35abb5bf70ffa40b02a1c03c914067bf703e37fb0f53392bcce2476df005f0|55720280",
        "1.3.10|linux_x86_64|2e72c96b86074dd969b9c49867874a97e8f594fb3e39d3f0ed2ac7add353666d|56525120",
        "1.3.10|macos_x86_64|d2f482cae5aefa2fd6afa5b3d8ecb8de8c5a49b22c42c3dce1b5300a05b0109f|55862352",
        "1.30.8|linux_arm64|e51d6a76fade0871a9143b64dc62a5ff44f369aa6cb4b04967d93798bf39d15b|49938584",
        "1.30.8|linux_x86_64|7f39bdcf768ce4b8c1428894c70c49c8b4d2eee52f3606eb02f5f7d10f66d692|51454104",
        "1.30.8|macos_arm64|52b11bb032f88e4718cd4e3c8374a6b1fad29772aa1ce701276cc4e17d37642f|51395442",
        "1.30.8|macos_x86_64|46682e24c3aecfbe92f53b86fb15beb740c43a0fafe0a4e06a1c8bb3ce9e985b|52586352",
        "1.31.4|linux_arm64|b97e93c20e3be4b8c8fa1235a41b4d77d4f2022ed3d899230dbbbbd43d26f872|54984856",
        "1.31.4|linux_x86_64|298e19e9c6c17199011404278f0ff8168a7eca4217edad9097af577023a5620f|56381592",
        "1.31.4|macos_arm64|a756bb911298a85af35c0111c371728a26c532d504fe8b534eb684501fcaf996|56560802",
        "1.31.4|macos_x86_64|fd996e9f41fd42c6c1c781a5a85990f4d0d8337ede00a7719afa23be886e0abd|57637984",
        "1.32.0|linux_arm64|ba4004f98f3d3a7b7d2954ff0a424caa2c2b06b78c17b1dccf2acc76a311a896|55836824",
        "1.32.0|linux_arm64|ba4004f98f3d3a7b7d2954ff0a424caa2c2b06b78c17b1dccf2acc76a311a896|55836824",
        "1.32.0|linux_x86_64|646d58f6d98ee670a71d9cdffbf6625aeea2849d567f214bc43a35f8ccb7bf70|57323672",
        "1.32.0|linux_x86_64|646d58f6d98ee670a71d9cdffbf6625aeea2849d567f214bc43a35f8ccb7bf70|57323672",
        "1.32.0|macos_arm64|5bfd5de53a054b4ef614c60748e28bf47441c7ed4db47ec3c19a3e2fa0eb5555|57472706",
        "1.32.0|macos_arm64|5bfd5de53a054b4ef614c60748e28bf47441c7ed4db47ec3c19a3e2fa0eb5555|57472706",
        "1.32.0|macos_x86_64|516585916f499077fac8c2fdd2a382818683f831020277472e6bcf8d1a6f9be4|58612096",
        "1.32.0|macos_x86_64|516585916f499077fac8c2fdd2a382818683f831020277472e6bcf8d1a6f9be4|58612096",
        "1.4.12|linux_arm64|5fc307700d3f2b4682e7a662f251f6dd534f3e12d9a84c20697a73cb6c6a7f22|78167368",
        "1.4.12|linux_x86_64|e0376698047be47f37f126fcc4724487dcc8edd2ffb993ae5885779786efb597|79558032",
        "1.4.12|macos_x86_64|9c7c5525fe77ebed45dcc949990fcb8998eb6fe0b2441a75c1d58ee7268116d3|63405984",
        "1.5.8|linux_arm64|a459fd0e5bd2b002d1423d092c7f1613e095e5485cdda032eaf34303f57adfc3|52137665",
        "1.5.8|linux_x86_64|647e233fe0b935300a981b61245b29c7dae6af772dc1f2243cfa1970d2e90219|50372958",
        "1.5.8|macos_x86_64|3a4c98ad33892831026a59af6161a2cca0b9928ae098436d88e5224264535e64|50036704",
        "1.6.13|linux_arm64|cb891241dbc7e043cafacf6a504a09c2fd4c582798d47235fb5ca64517d2d04b|73688363",
        "1.6.13|linux_x86_64|17e29707dcdaac878178d4b137c798cb37993a8a7f0ae214835af4f8e322bafa|70704763",
        "1.6.13|macos_x86_64|4623929aaf3037489b2d96561cef4037ad3399f16bdd1469cc5fc9becb4581aa|70232912",
        "1.7.16|linux_arm64|123e3f8d0ddfd2b75cb56f76c0b75c56a1960aba73c9a212a153bd425a206b20|70997024",
        "1.7.16|linux_x86_64|67e27be929afa1aa103eec0978a2a50ef3df1bd1454b979bb776e472a73c21b2|72497289",
        "1.7.16|macos_x86_64|91618ff648ffa9878a64091d7d9440199475855e0fcfae30dab5812c67ea50ac|71985600",
        "1.8.15|linux_arm64|ec6d8b93dc74555822dd741eace7e99431d9efc7c3490b4bc46c0bfe24a54b82|52079389",
        "1.8.15|linux_x86_64|ac6c59308b91536bc1482c094576bf8685dc5372509a383fb4833ac7299b0e56|53284738",
        "1.8.15|macos_x86_64|0a876863dbee07130ead4bd87baf6b5bac7ca63a59d3c0417444a78a145ee3bd|52881856",
        "1.9.11|linux_arm64|dd9308db2a76efacff10e9b214f8c04752daa5fa1d1b432c97150bf883e5f091|65530300",
        "1.9.11|linux_x86_64|3aa80b62fbd9cfa082aa26ae6a141a6ac209543d31e6f88ad5df47842ed8ddc3|68375438",
        "1.9.11|macos_x86_64|b3e46e2a4ba5e29bc43251e9902c8ff6bc21cdbe8c2e20c79efb94bb3d954c02|67840704",
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

    def apply_configs(
        self,
        paths: Sequence[str],
        input_digest: Digest,
        platform: Platform,
        env: Optional[Mapping[str, str]] = None,
        context: Optional[str] = None,
    ) -> Process:
        argv: tuple[str, ...] = (self.generate_exe(platform),)

        if context is not None:
            argv += ("--context", context)

        argv += ("apply", "-o", "yaml")

        for path in paths:
            argv += ("-f", path)

        return Process(
            argv=argv,
            input_digest=input_digest,
            cache_scope=ProcessCacheScope.PER_SESSION,
            description=f"Applying kubernetes config {paths}",
            env=env,
        )


def rules():
    return collect_rules()
