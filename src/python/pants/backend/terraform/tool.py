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

    # TODO: Possibly there should not be a default version, since terraform state is sensitive to
    #  the version that created it, so you have to be deliberate about the version you select.
    default_version = "1.0.7"
    default_url_template = (
        "https://releases.hashicorp.com/terraform/{version}/terraform_{version}_{platform}.zip"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin_arm64",
        "macos_x86_64": "darwin_amd64",
        "linux_x86_64": "linux_amd64",
        "linux_arm64": "linux_arm64",
    }

    @classproperty
    def default_known_versions(cls):
        return [
            "1.3.5|macos_x86_64|6bf684dbc19ecbf9225f5a2409def32e5ef7d37af3899726accd9420a88a6bcd|20848406",
            "1.3.5|macos_arm64|33b25ad89dedbd98bba09cbde69dcf9e928029f322ae9494279cf2c8ce47db89|19287887",
            "1.3.5|linux_x86_64|ac28037216c3bc41de2c22724e863d883320a770056969b8d211ca8af3d477cf|19469337",
            "1.3.5|linux_arm64|ba5b1761046b899197bbfce3ad9b448d14550106d2cc37c52a60fc6822b584ed|17502759",
            "1.3.4|macos_x86_64|03e0d7f629f28e2ea31ec2c69408b500f00eac674c613f7f1097536dcfa2cf6c|20847508",
            "1.3.4|macos_arm64|7b4401edd8de50cda97d76b051c3a4b1882fa5aa8e867d4c4c2770e4c3b0056e|19284666",
            "1.3.4|linux_x86_64|b24210f28191fa2a08efe69f54e3db2e87a63369ac4f5dcaf9f34dc9318eb1a8|19462529",
            "1.3.4|linux_arm64|65381c6b61b2d1a98892199f649a5764ff5a772080a73d70f8663245e6402c39|17494667",
            "1.3.3|macos_x86_64|e544aefb984fd9b19de250ac063a7aa28cbfdce2eda428dd2429a521912f6a93|20843907",
            "1.3.3|macos_arm64|1850df7904025b20b26ac101274f30673b132adc84686178d3d0cb802be4597e|19268812",
            "1.3.3|linux_x86_64|fa5cbf4274c67f2937cabf1a6544529d35d0b8b729ce814b40d0611fd26193c1|19451941",
            "1.3.3|linux_arm64|b940a080c698564df5e6a2f1c4e1b51b2c70a5115358d2361e3697d3985ecbfe|17488660",
            "1.3.2|macos_x86_64|edaed5a7c4057f1f2a3826922f3e594c45e24c1e22605b94de9c097b683c38bd|20843900",
            "1.3.2|macos_arm64|ff92cd79b01d39a890314c2df91355c0b6d6815fbc069ccaee9da5d8b9ff8580|19270064",
            "1.3.2|linux_x86_64|6372e02a7f04bef9dac4a7a12f4580a0ad96a37b5997e80738e070be330cb11c|19451510",
            "1.3.2|linux_arm64|ce1a8770aaf27736a3352c5c31e95fb10d0944729b9d81013bf6848f8657da5f|17485206",
            "1.3.1|macos_x86_64|5f5967e12e75a3ca1720be3eeba8232b4ba8b42d2d9e9f9664eff7a68267e873|20842029",
            "1.3.1|macos_arm64|a525488cc3a26d25c5769fb7ffcabbfcd64f79cec5ebbfc94c18b5ec74a03b35|19269260",
            "1.3.1|linux_x86_64|0847b14917536600ba743a759401c45196bf89937b51dd863152137f32791899|19450765",
            "1.3.1|linux_arm64|7ebb3d1ff94017fbef8acd0193e0bd29dec1a8925e2b573c05a92fdb743d1d5b|17486534",
            "1.3.0|macos_x86_64|6502dbcbd7d1a356fa446ec12c2859a9a7276af92c89ce3cef7f675a8582a152|20842934",
            "1.3.0|macos_arm64|6a3512a1b1006f2edc6fe5f51add9a6e1ef3967912ecf27e66f22e70b9ad7158|19255975",
            "1.3.0|linux_x86_64|380ca822883176af928c80e5771d1c0ac9d69b13c6d746e6202482aedde7d457|19450952",
            "1.3.0|linux_arm64|0a15de6f934cf2217e5055412e7600d342b4f7dcc133564690776fece6213a9a|17488551",
            "1.2.9|macos_x86_64|46206e564fdd792e709b7ec70eab1c873c9b1b17f4d33c07a1faa9d68955061b|21329275",
            "1.2.9|macos_arm64|e61195aa7cc5caf6c86c35b8099b4a29339cd51e54518eb020bddb35cfc0737d|19773052",
            "1.2.9|linux_x86_64|0e0fc38641addac17103122e1953a9afad764a90e74daf4ff8ceeba4e362f2fb|19906116",
            "1.2.9|linux_arm64|6da7bf01f5a72e61255c2d80eddeba51998e2bb1f50a6d81b0d3b71e70e18531|17946045",
            "1.2.8|macos_x86_64|0f8eecc764b57a938aa115a3ce2baa0d245479f17c28a4217bcf432ee23c2c5d|21332730",
            "1.2.8|macos_arm64|d6b900682d33aff84f8f63f69557f8ea8537218748fcac6f12483aaa46959a14|19770539",
            "1.2.8|linux_x86_64|3e9c46d6f37338e90d5018c156d89961b0ffb0f355249679593aff99f9abe2a2|19907515",
            "1.2.8|linux_arm64|26c05cadb05cdaa8ac64b90b982b4e9350715ec2e9995a6b03bb964d230de055|17947439",
            "1.2.7|macos_x86_64|acc781e964be9b527101b00eb6e7e63e7e509dd1355ff8567b80d0244c460634|21330075",
            "1.2.7|macos_arm64|e4717057e1cbb606f1e089261def9a17ddd18b78707d9e212c768dc0d739a220|19773241",
            "1.2.7|linux_x86_64|dfd7c44a5b6832d62860a01095a15b53616fb3ea4441ab89542f9364e3fca718|19907183",
            "1.2.7|linux_arm64|80d064008d57ba5dc97e189215c87275bf39ca14b1234430eae2f114394ea229|17943724",
            "1.2.6|macos_x86_64|94d1efad05a06c879b9c1afc8a6f7acb2532d33864225605fc766ecdd58d9888|21328767",
            "1.2.6|macos_arm64|452675f91cfe955a95708697a739d9b114c39ff566da7d9b31489064ceaaf66a|19774190",
            "1.2.6|linux_x86_64|9fd445e7a191317dcfc99d012ab632f2cc01f12af14a44dfbaba82e0f9680365|19905977",
            "1.2.6|linux_arm64|322755d11f0da11169cdb234af74ada5599046c698dccc125859505f85da2a20|17943213",
            "1.2.5|macos_x86_64|d196f94486e54407524a0efbcb5756b197b763863ead2e145f86dd6c80fc9ce8|21323818",
            "1.2.5|macos_arm64|77dd998d26e578aa22de557dc142672307807c88e3a4da65d8442de61479899f|19767100",
            "1.2.5|linux_x86_64|281344ed7e2b49b3d6af300b1fe310beed8778c56f3563c4d60e5541c0978f1b|19897064",
            "1.2.5|linux_arm64|0544420eb29b792444014988018ae77a7c8df6b23d84983728695ba73e38f54a|17938208",
            "1.2.4|macos_x86_64|3e04343620fb01b8be01c8689dcb018b8823d8d7b070346086d7df22cc4cd5e6|21321939",
            "1.2.4|macos_arm64|e596dcdfe55b2070a55fcb271873e86d1af7f6b624ffad4837ccef119fdac97a|19765021",
            "1.2.4|linux_x86_64|705ea62a44a0081594dad6b2b093eefefb12d54fa5a20a66562f9e082b00414c|19895510",
            "1.2.4|linux_arm64|11cfa2233dc708b51b16d5b923379db67e35c22b1b988773e5b31a7c2e251471|17936883",
            "1.2.3|macos_x86_64|2962b0ebdf6f431b8fb182ffc1d8b582b73945db0c3ab99230ffc360d9e297a2|21318448",
            "1.2.3|macos_arm64|601962205ad3dcf9b1b75f758589890a07854506cbd08ca2fc25afbf373bff53|19757696",
            "1.2.3|linux_x86_64|728b6fbcb288ad1b7b6590585410a98d3b7e05efe4601ef776c37e15e9a83a96|19891436",
            "1.2.3|linux_arm64|a48991e938a25bfe5d257f4b6cbbdc73d920cc34bbc8f0e685e28b9610ad75fe|17933271",
            "1.2.2|macos_x86_64|bd224d57718ed2b6e5e3b55383878d4b122c6dc058d65625605cef1ace9dcb25|21317982",
            "1.2.2|macos_arm64|4750d46e47345809a0baa3c330771c8c8a227b77bec4caa7451422a21acefae5|19758608",
            "1.2.2|linux_x86_64|2934a0e8824925beb956b2edb5fef212a6141c089d29d8568150a43f95b3a626|19889133",
            "1.2.2|linux_arm64|9c6202237d7477412054dcd36fdc269da9ee66ecbc45bb07d0d63b7d36af7b21|17932829",
            "1.2.1|macos_x86_64|d7c9a677efb22276afdd6c7703cbfee87d509a31acb247b96aa550a35154400a|21309907",
            "1.2.1|macos_arm64|96e3659e89bfb50f70d1bb8660452ec433019d00a862d2291817c831305d85ea|19751670",
            "1.2.1|linux_x86_64|8cf8eb7ed2d95a4213fbfd0459ab303f890e79220196d1c4aae9ecf22547302e|19881618",
            "1.2.1|linux_arm64|972ea512dac822274791dedceb6e7f8b9ac2ed36bd7759269b6806d0ab049128|17922073",
            "1.2.0|macos_x86_64|f608b1fee818988d89a16b7d1b6d22b37cc98892608c52c22661ca6cbfc3d216|21309982",
            "1.2.0|macos_arm64|d4df7307bad8c13e443493c53898a7060f77d661bfdf06215b61b65621ed53e9|19750767",
            "1.2.0|linux_x86_64|b87de03adbdfdff3c2552c8c8377552d0eecd787154465100cf4e29de4a7be1f|19880608",
            "1.2.0|linux_arm64|ee80b8635d8fdbaed57beffe281cf87b8b1fd1ddb29c08d20e25a152d9f0f871|17920355",
            "1.1.9|macos_x86_64|c902b3c12042ac1d950637c2dd72ff19139519658f69290b310f1a5924586286|20709155",
            "1.1.9|macos_arm64|918a8684da5a5529285135f14b09766bd4eb0e8c6612a4db7c121174b4831739|19835808",
            "1.1.9|linux_x86_64|9d2d8a89f5cc8bc1c06cb6f34ce76ec4b99184b07eb776f8b39183b513d7798a|19262029",
            "1.1.9|linux_arm64|e8a09d1fe5a68ed75e5fabe26c609ad12a7e459002dea6543f1084993b87a266|17521011",
            "1.1.8|macos_x86_64|29ad0af72d498a76bbc51cc5cb09a6d6d0e5673cbbab6ef7aca57e3c3e780f46|20216382",
            "1.1.8|macos_arm64|d6fefdc27396a019da56cce26f7eeea3d6986714cbdd488ff6a424f4bca40de8|19371647",
            "1.1.8|linux_x86_64|fbd37c1ec3d163f493075aa0fa85147e7e3f88dd98760ee7af7499783454f4c5|18796132",
            "1.1.8|linux_arm64|10b2c063dcff91329ee44bce9d71872825566b713308b3da1e5768c6998fb84f|17107405",
            "1.1.7|macos_x86_64|5e7e939e084ae29af7fd86b00a618433d905477c52add2d4ea8770692acbceac|20213394",
            "1.1.7|macos_arm64|a36b6e2810f81a404c11005942b69c3d1d9baa8dd07de6b1f84e87a67eedb58f|19371095",
            "1.1.7|linux_x86_64|e4add092a54ff6febd3325d1e0c109c9e590dc6c38f8bb7f9632e4e6bcca99d4|18795309",
            "1.1.7|linux_arm64|2f72982008c52d2d57294ea50794d7c6ae45d2948e08598bfec3e492bce8d96e|17109768",
            "1.1.6|macos_x86_64|bbfc916117e45788661c066ec39a0727f64c7557bf6ce9f486bbd97c16841975|20168574",
            "1.1.6|macos_arm64|dddb11195fc413653b98e7a830ec7314f297e6c22575fc878f4ee2287a25b4f5|19326402",
            "1.1.6|linux_x86_64|3e330ce4c8c0434cdd79fe04ed6f6e28e72db44c47ae50d01c342c8a2b05d331|18751464",
            "1.1.6|linux_arm64|a53fb63625af3572f7252b9fb61d787ab153132a8984b12f4bb84b8ee408ec53|17069580",
            "1.1.5|macos_x86_64|7d4dbd76329c25869e407706fed01213beb9d6235c26e01c795a141c2065d053|20157551",
            "1.1.5|macos_arm64|723363af9524c0897e9a7d871d27f0d96f6aafd11990df7e6348f5b45d2dbe2c|19328643",
            "1.1.5|linux_x86_64|30942d5055c7151f051c8ea75481ff1dc95b2c4409dbb50196419c21168d6467|18748879",
            "1.1.5|linux_arm64|2fb6324c24c14523ae63cedcbc94a8e6c1c317987eced0abfca2f6218d217ca5|17069683",
            "1.1.4|macos_x86_64|c2b2500835d2eb9d614f50f6f74c08781f0fee803699279b3eb0188b656427f2|20098620",
            "1.1.4|macos_arm64|a753e6cf402beddc4043a3968ff3e790cf50cc526827cda83a0f442a893f2235|19248286",
            "1.1.4|linux_x86_64|fca028d622f82788fdc35c1349e78d69ff07c7bb68c27d12f8b48c420e3ecdfb|18695508",
            "1.1.4|linux_arm64|3c1982cf0d16276c82960db60c998d79ba19e413af4fa2c7f6f86e4994379437|16996040",
            "1.1.3|macos_x86_64|c54022e514a97e9b96dae24a3308227d034989ecbafb65e3293eea91f2d5edfb|20098660",
            "1.1.3|macos_arm64|856e435da081d0a214c47a4eb09b1842f35eaa55e7ef0f9fa715d4816981d640|19244516",
            "1.1.3|linux_x86_64|b215de2a18947fff41803716b1829a3c462c4f009b687c2cbdb52ceb51157c2f|18692580",
            "1.1.3|linux_arm64|ad5a1f2c132bedc5105e3f9900e4fe46858d582c0f2a2d74355da718bbcef65d|16996972",
            "1.1.2|macos_x86_64|214da2e97f95389ba7557b8fcb11fe05a23d877e0fd67cd97fcbc160560078f1|20098558",
            "1.1.2|macos_arm64|39e28f49a753c99b5e2cb30ac8146fb6b48da319c9db9d152b1e8a05ec9d4a13|19240921",
            "1.1.2|linux_x86_64|734efa82e2d0d3df8f239ce17f7370dabd38e535d21e64d35c73e45f35dfa95c|18687805",
            "1.1.2|linux_arm64|088e2226d1ddb7f68a4f65c704022a1cfdbf20fe40f02e0c3646942f211fd746|16994702",
            "1.1.1|macos_x86_64|85fa7c90359c4e3358f78e58f35897b3e466d00c0d0648820830cac5a07609c3|20094218",
            "1.1.1|macos_arm64|9cd8faf29095c57e30f04f9ca5fa9105f6717b277c65061a46f74f22f0f5907e|19240711",
            "1.1.1|linux_x86_64|07b8dc444540918597a60db9351af861335c3941f28ea8774e168db97dd74557|18687006",
            "1.1.1|linux_arm64|d6fd14da47af9ec5fa3ad5962eaef8eed6ff2f8a5041671f9c90ec5f4f8bb554|16995635",
            "1.1.0|macos_x86_64|6fb2af160879d807291980642efa93cc9a97ddf662b17cc3753065c974a5296d|20089311",
            "1.1.0|macos_arm64|f69e0613f09c21d44ce2131b20e8b97909f3fc7aa90c443639475f5e474a22ec|19240009",
            "1.1.0|linux_x86_64|763378aa75500ce5ba67d0cba8aa605670cd28bf8bafc709333a30908441acb5|18683106",
            "1.1.0|linux_arm64|6697e9a263e264310373f3c91bf83f4cbfeb67b13994d2a8f7bcc492b554552e|16987201",
            "1.0.11|macos_x86_64|92f2e7eebb9699e23800f8accd519775a02bd25fe79e1fe4530eca123f178202|19340098",
            "1.0.11|macos_arm64|0f38af81641b00a2cbb8d25015d917887a7b62792c74c28d59e40e56ce6f265c|18498208",
            "1.0.11|linux_x86_64|eeb46091a42dc303c3a3c300640c7774ab25cbee5083dafa5fd83b54c8aca664|18082446",
            "1.0.11|linux_arm64|30c650f4bc218659d43e07d911c00f08e420664a3d12c812228e66f666758645|16148492",
            "1.0.10|macos_x86_64|e7595530a0dcdaec757621cbd9f931926fd904b1a1e5206bf2c9db6b73cee04d|33021017",
            "1.0.10|macos_arm64|eecea1343888e2648d5f7ea25a29494fd3b5ecde95d0231024414458c59cb184|32073869",
            "1.0.10|linux_x86_64|a221682fcc9cbd7fde22f305ead99b3ad49d8303f152e118edda086a2807716d|32674953",
            "1.0.10|linux_arm64|b091dbe5c00785ae8b5cb64149d697d61adea75e495d9e3d910f61d8c9967226|30505040",
            "1.0.9|macos_x86_64|fb791c3efa323c5f0c2c36d14b9230deb1dc37f096a8159e718e8a9efa49a879|33017665",
            "1.0.9|macos_arm64|aa5cc13903be35236a60d116f593e519534bcabbb2cf91b69cae19307a17b3c0|32069384",
            "1.0.9|linux_x86_64|f06ac64c6a14ed6a923d255788e4a5daefa2b50e35f32d7a3b5a2f9a5a91e255|32674820",
            "1.0.9|linux_arm64|457ac590301126e7b151ea08c5b9586a882c60039a0605fb1e44b8d23d2624fd|30510941",
            "1.0.8|macos_x86_64|e2493c7ae12597d4a1e6437f6805b0a8bcaf01fc4e991d1f52f2773af3317342|33018420",
            "1.0.8|macos_arm64|9f0e1366484748ecbd87c8ef69cc4d3d79296b0e2c1a108bcbbff985dbb92de8|32068918",
            "1.0.8|linux_x86_64|a73459d406067ce40a46f026dce610740d368c3b4a3d96591b10c7a577984c2e|32681118",
            "1.0.8|linux_arm64|01aaef769f4791f9b28530e750aadbc983a8eabd0d55909e26392b333a1a26e4|30515501",
            "1.0.7|macos_x86_64|80ae021d6143c7f7cbf4571f65595d154561a2a25fd934b7a8ccc1ebf3014b9b|33020029",
            "1.0.7|macos_arm64|cbab9aca5bc4e604565697355eed185bb699733811374761b92000cc188a7725|32071346",
            "1.0.7|linux_x86_64|bc79e47649e2529049a356f9e60e06b47462bf6743534a10a4c16594f443be7b|32671441",
            "1.0.7|linux_arm64|4e71a9e759578020750be41e945c086e387affb58568db6d259d80d123ac80d3|30529105",
            "1.0.6|macos_x86_64|3a97f2fffb75ac47a320d1595e20947afc8324571a784f1bd50bd91e26d5648c|33022053",
            "1.0.6|macos_arm64|aaff1eccaf4099da22fe3c6b662011f8295dad9c94a35e1557b92844610f91f3|32080428",
            "1.0.6|linux_x86_64|6a454323d252d34e928785a3b7c52bfaff1192f82685dfee4da1279bb700b733|32677516",
            "1.0.6|linux_arm64|2047f8afc7d0d7b645a0422181ba3fe47b3547c4fe658f95eebeb872752ec129|30514636",
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
async def setup_terraform_process(
    request: TerraformProcess, terraform: TerraformTool, platform: Platform
) -> Process:
    downloaded_terraform = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        terraform.get_request(platform),
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
