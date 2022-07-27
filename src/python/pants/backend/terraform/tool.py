# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.fs import EMPTY_DIGEST, Digest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import collect_rules, rule
from pants.option.option_types import BoolOption
from pants.util.logging import LogLevel
from pants.util.meta import classproperty


class TerraformTool(TemplatedExternalTool):
    options_scope = "download-terraform"
    name = "terraform"
    help = "Terraform (https://terraform.io)"

    default_version = "1.0.7"
    default_url_template = (
        "https://releases.hashicorp.com/terraform/{version}/terraform_{version}_{platform}.zip"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin_arm64",
        "macos_x86_64": "darwin_amd64",
        "linux_x86_64": "linux_amd64",
    }

    @classproperty
    def default_known_versions(cls):
        return [
            "1.2.6|macos_x86_64|94d1efad05a06c879b9c1afc8a6f7acb2532d33864225605fc766ecdd58d9888|21328767",
            "1.2.6|macos_arm64|452675f91cfe955a95708697a739d9b114c39ff566da7d9b31489064ceaaf66a|19774190",
            "1.2.6|linux_x86_64|9fd445e7a191317dcfc99d012ab632f2cc01f12af14a44dfbaba82e0f9680365|19905977",
            "1.2.5|macos_x86_64|d196f94486e54407524a0efbcb5756b197b763863ead2e145f86dd6c80fc9ce8|21323818",
            "1.2.5|macos_arm64|77dd998d26e578aa22de557dc142672307807c88e3a4da65d8442de61479899f|19767100",
            "1.2.5|linux_x86_64|281344ed7e2b49b3d6af300b1fe310beed8778c56f3563c4d60e5541c0978f1b|19897064",
            "1.2.4|macos_x86_64|3e04343620fb01b8be01c8689dcb018b8823d8d7b070346086d7df22cc4cd5e6|21321939",
            "1.2.4|macos_arm64|e596dcdfe55b2070a55fcb271873e86d1af7f6b624ffad4837ccef119fdac97a|19765021",
            "1.2.4|linux_x86_64|705ea62a44a0081594dad6b2b093eefefb12d54fa5a20a66562f9e082b00414c|19895510",
            "1.2.3|macos_x86_64|2962b0ebdf6f431b8fb182ffc1d8b582b73945db0c3ab99230ffc360d9e297a2|21318448",
            "1.2.3|macos_arm64|601962205ad3dcf9b1b75f758589890a07854506cbd08ca2fc25afbf373bff53|19757696",
            "1.2.3|linux_x86_64|728b6fbcb288ad1b7b6590585410a98d3b7e05efe4601ef776c37e15e9a83a96|19891436",
            "1.2.2|macos_x86_64|bd224d57718ed2b6e5e3b55383878d4b122c6dc058d65625605cef1ace9dcb25|21317982",
            "1.2.2|macos_arm64|4750d46e47345809a0baa3c330771c8c8a227b77bec4caa7451422a21acefae5|19758608",
            "1.2.2|linux_x86_64|2934a0e8824925beb956b2edb5fef212a6141c089d29d8568150a43f95b3a626|19889133",
            "1.2.1|macos_x86_64|d7c9a677efb22276afdd6c7703cbfee87d509a31acb247b96aa550a35154400a|21309907",
            "1.2.1|macos_arm64|96e3659e89bfb50f70d1bb8660452ec433019d00a862d2291817c831305d85ea|19751670",
            "1.2.1|linux_x86_64|8cf8eb7ed2d95a4213fbfd0459ab303f890e79220196d1c4aae9ecf22547302e|19881618",
            "1.2.0|macos_x86_64|f608b1fee818988d89a16b7d1b6d22b37cc98892608c52c22661ca6cbfc3d216|21309982",
            "1.2.0|macos_arm64|d4df7307bad8c13e443493c53898a7060f77d661bfdf06215b61b65621ed53e9|19750767",
            "1.2.0|linux_x86_64|b87de03adbdfdff3c2552c8c8377552d0eecd787154465100cf4e29de4a7be1f|19880608",
            "1.1.9|macos_x86_64|c902b3c12042ac1d950637c2dd72ff19139519658f69290b310f1a5924586286|20709155",
            "1.1.9|macos_arm64|918a8684da5a5529285135f14b09766bd4eb0e8c6612a4db7c121174b4831739|19835808",
            "1.1.9|linux_x86_64|9d2d8a89f5cc8bc1c06cb6f34ce76ec4b99184b07eb776f8b39183b513d7798a|19262029",
            "1.1.8|macos_x86_64|29ad0af72d498a76bbc51cc5cb09a6d6d0e5673cbbab6ef7aca57e3c3e780f46|20216382",
            "1.1.8|macos_arm64|d6fefdc27396a019da56cce26f7eeea3d6986714cbdd488ff6a424f4bca40de8|19371647",
            "1.1.8|linux_x86_64|fbd37c1ec3d163f493075aa0fa85147e7e3f88dd98760ee7af7499783454f4c5|18796132",
            "1.1.7|macos_x86_64|5e7e939e084ae29af7fd86b00a618433d905477c52add2d4ea8770692acbceac|20213394",
            "1.1.7|macos_arm64|a36b6e2810f81a404c11005942b69c3d1d9baa8dd07de6b1f84e87a67eedb58f|19371095",
            "1.1.7|linux_x86_64|e4add092a54ff6febd3325d1e0c109c9e590dc6c38f8bb7f9632e4e6bcca99d4|18795309",
            "1.1.6|macos_x86_64|bbfc916117e45788661c066ec39a0727f64c7557bf6ce9f486bbd97c16841975|20168574",
            "1.1.6|macos_arm64|dddb11195fc413653b98e7a830ec7314f297e6c22575fc878f4ee2287a25b4f5|19326402",
            "1.1.6|linux_x86_64|3e330ce4c8c0434cdd79fe04ed6f6e28e72db44c47ae50d01c342c8a2b05d331|18751464",
            "1.1.5|macos_x86_64|7d4dbd76329c25869e407706fed01213beb9d6235c26e01c795a141c2065d053|20157551",
            "1.1.5|macos_arm64|723363af9524c0897e9a7d871d27f0d96f6aafd11990df7e6348f5b45d2dbe2c|19328643",
            "1.1.5|linux_x86_64|30942d5055c7151f051c8ea75481ff1dc95b2c4409dbb50196419c21168d6467|18748879",
            "1.1.4|macos_x86_64|c2b2500835d2eb9d614f50f6f74c08781f0fee803699279b3eb0188b656427f2|20098620",
            "1.1.4|macos_arm64|a753e6cf402beddc4043a3968ff3e790cf50cc526827cda83a0f442a893f2235|19248286",
            "1.1.4|linux_x86_64|fca028d622f82788fdc35c1349e78d69ff07c7bb68c27d12f8b48c420e3ecdfb|18695508",
            "1.1.3|macos_x86_64|c54022e514a97e9b96dae24a3308227d034989ecbafb65e3293eea91f2d5edfb|20098660",
            "1.1.3|macos_arm64|856e435da081d0a214c47a4eb09b1842f35eaa55e7ef0f9fa715d4816981d640|19244516",
            "1.1.3|linux_x86_64|b215de2a18947fff41803716b1829a3c462c4f009b687c2cbdb52ceb51157c2f|18692580",
            "1.1.2|macos_x86_64|214da2e97f95389ba7557b8fcb11fe05a23d877e0fd67cd97fcbc160560078f1|20098558",
            "1.1.2|macos_arm64|39e28f49a753c99b5e2cb30ac8146fb6b48da319c9db9d152b1e8a05ec9d4a13|19240921",
            "1.1.2|linux_x86_64|734efa82e2d0d3df8f239ce17f7370dabd38e535d21e64d35c73e45f35dfa95c|18687805",
            "1.1.1|macos_x86_64|85fa7c90359c4e3358f78e58f35897b3e466d00c0d0648820830cac5a07609c3|20094218",
            "1.1.1|macos_arm64|9cd8faf29095c57e30f04f9ca5fa9105f6717b277c65061a46f74f22f0f5907e|19240711",
            "1.1.1|linux_x86_64|07b8dc444540918597a60db9351af861335c3941f28ea8774e168db97dd74557|18687006",
            "1.1.0|macos_x86_64|6fb2af160879d807291980642efa93cc9a97ddf662b17cc3753065c974a5296d|20089311",
            "1.1.0|macos_arm64|f69e0613f09c21d44ce2131b20e8b97909f3fc7aa90c443639475f5e474a22ec|19240009",
            "1.1.0|linux_x86_64|763378aa75500ce5ba67d0cba8aa605670cd28bf8bafc709333a30908441acb5|18683106",
            "1.0.11|macos_x86_64|92f2e7eebb9699e23800f8accd519775a02bd25fe79e1fe4530eca123f178202|19340098",
            "1.0.11|macos_arm64|0f38af81641b00a2cbb8d25015d917887a7b62792c74c28d59e40e56ce6f265c|18498208",
            "1.0.11|linux_x86_64|eeb46091a42dc303c3a3c300640c7774ab25cbee5083dafa5fd83b54c8aca664|18082446",
            "1.0.10|macos_x86_64|e7595530a0dcdaec757621cbd9f931926fd904b1a1e5206bf2c9db6b73cee04d|33021017",
            "1.0.10|macos_arm64|eecea1343888e2648d5f7ea25a29494fd3b5ecde95d0231024414458c59cb184|32073869",
            "1.0.10|linux_x86_64|a221682fcc9cbd7fde22f305ead99b3ad49d8303f152e118edda086a2807716d|32674953",
            "1.0.9|macos_x86_64|fb791c3efa323c5f0c2c36d14b9230deb1dc37f096a8159e718e8a9efa49a879|33017665",
            "1.0.9|macos_arm64|aa5cc13903be35236a60d116f593e519534bcabbb2cf91b69cae19307a17b3c0|32069384",
            "1.0.9|linux_x86_64|f06ac64c6a14ed6a923d255788e4a5daefa2b50e35f32d7a3b5a2f9a5a91e255|32674820",
            "1.0.8|macos_x86_64|e2493c7ae12597d4a1e6437f6805b0a8bcaf01fc4e991d1f52f2773af3317342|33018420",
            "1.0.8|macos_arm64|9f0e1366484748ecbd87c8ef69cc4d3d79296b0e2c1a108bcbbff985dbb92de8|32068918",
            "1.0.8|linux_x86_64|a73459d406067ce40a46f026dce610740d368c3b4a3d96591b10c7a577984c2e|32681118",
            "1.0.7|macos_x86_64|80ae021d6143c7f7cbf4571f65595d154561a2a25fd934b7a8ccc1ebf3014b9b|33020029",
            "1.0.7|macos_arm64|cbab9aca5bc4e604565697355eed185bb699733811374761b92000cc188a7725|32071346",
            "1.0.7|linux_x86_64|bc79e47649e2529049a356f9e60e06b47462bf6743534a10a4c16594f443be7b|32671441",
            "1.0.6|macos_x86_64|3a97f2fffb75ac47a320d1595e20947afc8324571a784f1bd50bd91e26d5648c|33022053",
            "1.0.6|macos_arm64|aaff1eccaf4099da22fe3c6b662011f8295dad9c94a35e1557b92844610f91f3|32080428",
            "1.0.6|linux_x86_64|6a454323d252d34e928785a3b7c52bfaff1192f82685dfee4da1279bb700b733|32677516",
        ]

    tailor = BoolOption(
        default=True,
        help="If true, add `terraform_module` targets with the `tailor` goal.",
        advanced=True,
    )


@dataclass(frozen=True)
class TerraformProcess:
    """A request to invoke Terraform."""

    args: tuple[str, ...]
    description: str
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()


@rule
async def setup_terraform_process(request: TerraformProcess, terraform: TerraformTool) -> Process:
    downloaded_terraform = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        terraform.get_request(Platform.current),
    )

    immutable_input_digests = {"__terraform": downloaded_terraform.digest}

    return Process(
        argv=("__terraform/terraform",) + request.args,
        input_digest=request.input_digest,
        immutable_input_digests=immutable_input_digests,
        output_files=request.output_files,
        description=request.description,
        level=LogLevel.DEBUG,
    )


def rules():
    return collect_rules()
