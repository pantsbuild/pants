# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""# Terraform

## Caching: Pants uses the [provider cache](https://developer.hashicorp.com/terraform/cli/config/config-file#provider-plugin-cache) for caching providers.
These are the things that need to be downloaded, so this provides the most speedup.
We use the providers cache instead of identifying and caching the providers individually for a few reasons:
1. This leverages Terraform's existing caching mechanism
2. This is much simpler
3. This incurs almost no overhead, since it is done as part of `terraform init`. We don't need to run more analysers or separately download providers

We didn't use `terraform providers lock` for a few reasons:
1. `terraform providers lock` isn't designed for this usecase, it's designed to create mirrors of providers. It does more work (to set up manifests) and would require us to set more config settings
2. `terraform providers lock` doesn't use itself as a cache. So every time we would want to refresh the cache, we need to download _everything_ again. Even if nothing has changed.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.core.util_rules.system_binaries import BinaryShims, BinaryShimsRequest, GetentBinary
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import EMPTY_DIGEST, Digest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import collect_rules, rule
from pants.option.option_types import ArgsListOption, BoolOption, StrListOption
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import softwrap


class TerraformTool(TemplatedExternalTool):
    options_scope = "download-terraform"
    name = "terraform"
    help = "Terraform (https://terraform.io)"

    # TODO: Possibly there should not be a default version, since terraform state is sensitive to
    #  the version that created it, so you have to be deliberate about the version you select.
    default_version = "1.9.0"
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
            "1.9.0|linux_arm64|f5c0a49b482c008a6afd2248c08ca919e599c1154a850ff94809f4a85c86eb3b|24710285",
            "1.9.0|linux_x86_64|ab1358e73a81096bbe04201ef403a32e0765c5f6e360692d170d32d0889a4871|27010938",
            "1.9.0|macos_arm64|b7701c42a9b69524cfe79f0928d48ec4d648bc5e08794df12e8b41b56a0a395c|25718506",
            "1.9.0|macos_x86_64|b69196c831d6315b6e79178c96a66365d724cf4b922ad4a9763cd970aeeecd45|27940121",
            "1.8.5|linux_arm64|17b3a243ea24003a58ab324c197da8609fccae136bcb8a424bf61ec475b3a203|24450605",
            "1.8.5|linux_x86_64|bb1ee3e8314da76658002e2e584f2d8854b6def50b7f124e27b957a42ddacfea|26744662",
            "1.8.5|macos_arm64|627c5005ab4a2bee36316f4967a41f16d55f79ea737f78b6bb34325c728c73e1|25454927",
            "1.8.5|macos_x86_64|051c702e156a4d1a1c628783cf2ca0e1db8cca7b4c0f1686ea623558ed5560f9|27659471",
            "1.8.4|linux_arm64|76668e7742ee8f815fe6de28c8b84507e6171b26966426c2eb8eea8e64fe2f33|24451088",
            "1.8.4|linux_x86_64|12167574ae0deb219a1008bd4c15ff13dac7198d57870f48433d53fe2b0b28c4|26745153",
            "1.8.4|macos_arm64|6a54d2862c8244febe6077a1fc6e9e6cc4e65eee8169049e77ce08df233cf49a|25454007",
            "1.8.4|macos_x86_64|5968872b07677829002d0a7ad34cf0c4cd02893a1c131e4ca30236442ceec445|27659715",
            "1.8.3|linux_arm64|5fd3c4ee4cf23f79641f77006d29544b41fbcde5d22202566322266e6fca2607|24433179",
            "1.8.3|linux_x86_64|4ff78474d0407ba6e8c3fb9ef798f2822326d121e045577f80e2a637ec33f553|26721624",
            "1.8.3|macos_arm64|2622426fd6e8483db6d62605f52ea6eddb0e88a09e8cea1c24b9310879490227|25439736",
            "1.8.3|macos_x86_64|a4f695e64948ad66fe05e2f589cfe5221b8597ff16173ebed8055d3a90aaa739|27637539",
            "1.8.2|linux_arm64|e00726a0c8e4b06b31873446c639454358a0efb73a604198473f526d60e66100|24432938",
            "1.8.2|linux_x86_64|74f3cc4151e52d94e0ecbe900552adc9b8440b4a8dc12f7fdaab2d0280788acc|26721112",
            "1.8.2|macos_arm64|f871f4c91eafec6e6e88253dc3cc0b6a21d63fa56fee5ee1629f3ce68a605873|25437898",
            "1.8.2|macos_x86_64|a71ada335aba64ac1851ffbb2cf8f727a06013d02474dd70c4571f585b1fe522|27637114",
            "1.8.1|linux_arm64|dfc825bd488679163a2768f3c87261ce43b4747720a6cc4e2a63935961ce4582|24412348",
            "1.8.1|linux_x86_64|265d28a1a6dd81bdd5822eba55663613b7a51c582d663f9417f8777905d39002|26687165",
            "1.8.1|macos_arm64|27834a6450c4046af812dcc3faff3c0c56c8c499ca9990d7cd43ef7f844077ed|25408443",
            "1.8.1|macos_x86_64|89aace89147ca00d5200282aa766866e32268e191d97aceca7629fc2379aaab9|27610020",
            "1.8.0|linux_arm64|47cbde7184ce260160ff0355065d454ffa5628a2259ba325736dbcf740351193|24413500",
            "1.8.0|linux_x86_64|dcc4670379a22213e72faa6cb709b3391e7e54967e40288ecf591e2b83cfd39e|26690615",
            "1.8.0|macos_arm64|abfb06eb80f1acd19ab8a01f6d24a4a5f99ba9b628c3b00a3b0c898709eea3b3|25410972",
            "1.8.0|macos_x86_64|1aee4f880706edf98efb972d4f5cec2cd4c23904c17a26d51af6326d6f06a64e|27610301",
            "1.7.5|linux_arm64|08631c385667dd28f03b3a3f77cb980393af4a2fcfc2236c148a678ad9150c8c|23696490",
            "1.7.5|linux_x86_64|3ff056b5e8259003f67fd0f0ed7229499cfb0b41f3ff55cc184088589994f7a5|25959930",
            "1.7.5|macos_arm64|99c4d4feafb0183af2f7fbe07beeea6f83e5f5a29ae29fee3168b6810e37ff98|25902918",
            "1.7.5|macos_x86_64|0eaf64e28f82e2defd06f7a6f3187d8cea03d5d9fcd2af54f549a6c32d6833f7|27560118",
            "1.7.4|linux_arm64|36680616b54c5ce8c8222c7bf81c187727b3c5c1a3a6e3af5b5372caa28697b7|23686053",
            "1.7.4|linux_x86_64|285539a6fd62fb79f05edc15cc207ca90f282901c32261085ea0642a0d638dfd|25940915",
            "1.7.4|macos_arm64|3f25268a5d7677cc89d39a505362979acfb02f19ddb965d7ec0b33a6d9e64075|25891173",
            "1.7.4|macos_x86_64|fcf35c8b1d3f46fb84f688312ef5f829081d2d56c10444b9f6e290e21e68871c|27539134",
            "1.7.3|linux_arm64|e9a8a2f676b51a5334d00a0c3695b24ca75e30f4f449eb191e304fedfa099565|23682523",
            "1.7.3|linux_x86_64|617042989ce46b5dd07772237b49b57b8f8e97b1604c9dbbd85ead87effb51fe|25940403",
            "1.7.3|macos_arm64|85cddfd303c45989f0948a70ae03bb30f66c6e6106383697fe85ccd739137ca6|25892413",
            "1.7.3|macos_x86_64|4787f5a422439d3b277a889b159981e88049f48bcf9e41e70481620567a7fd9c|27538904",
            "1.7.2|linux_arm64|1fe2b047ac8354aca92a8037b57d813f5e60b7b0ba02acbecb899d990663326e|23683035",
            "1.7.2|linux_x86_64|e3965584b2347edd294ca97068af573654716abbb2ce5230d309692dab659267|25939436",
            "1.7.2|macos_arm64|d8c7b8b1aa7f0b38a2e437d9c9e4e632b2b258e3bf48bb6de4626f3b0afea5e4|25891861",
            "1.7.2|macos_x86_64|dad2fd54b3dda89b39978dcd27c8c62e13010efdc0507a04b6ad57257b57085e|27538796",
            "1.7.1|macos_x86_64|db05d272f5070eacab70fc14a091f5a9e6c734423794901d79ffd3c612933235|27539148",
            "1.7.1|macos_arm64|d4ee3a591d022fda26e1eb153a25e38ee4f0311720719c329ed38cf2ae8c14e5|25891566",
            "1.7.1|linux_x86_64|64ea53ae52a7e199bd6f647c31613ea4ef18f58116389051b4a34a29fb04624a|25939359",
            "1.7.1|linux_arm64|9067cd7e34b3f81aa6e1eca3496dae65573abe3b9e285ec651c1c2fd2f9c43cd|23681045",
            "1.7.0|macos_x86_64|621a2ef8d0ca4e5bb613632983b6b2cd53d542978117df779ac363422ce6802d|27539394",
            "1.7.0|macos_arm64|7c23ffbeba15c38ce547e62ba4ffbb2c3620cf5b38bf9fa8037cfa81544d1150|25891366",
            "1.7.0|linux_x86_64|2bac080244845ebd434baf5e8557bd06d53b3c8bc01b7e496b390a56cb40ac5c|25939419",
            "1.7.0|linux_arm64|33094b8c677460e7c6496a89770ae702bb8d9c6613d4a8485897da006d1919b5|23680807",
            "1.6.6|macos_x86_64|33376343c7e0279b674c1c8b8a31dc3174ac09dd796d32651cc5e3b98f220436|26507656",
            "1.6.6|macos_arm64|01e608fc04cf54869db687a212d60f3dc3d5c828298514857f9e29f8ac1354a9|24865571",
            "1.6.6|linux_x86_64|d117883fd98b960c5d0f012b0d4b21801e1aea985e26949c2d1ebb39af074f00|24976120",
            "1.6.6|linux_arm64|4066567f4ba031036d9b14c1edb85399aac1cfd6bbec89cdd8c26199adb2793b|22770688",
            "1.6.5|macos_x86_64|6595f56181b073d564a5f94510d4a40dab39cc6543e6a2c9825f785a48ddaf51|26503920",
            "1.6.5|macos_arm64|5c66fdc6adb6e7aa383b0979b1228c7c7b8d0b7d60989a13993ee8043b756883|24883132",
            "1.6.5|linux_x86_64|f6404dc264aff75fc1b776670c1abf732cfed3d4a1ce49b64bc5b5d116fe87d5|24979597",
            "1.6.5|linux_arm64|bad7aed9df3609599793f8c1f2df3ea6a5b4bf663813023989b9ee35632b6754|22781231",
            "1.6.4|macos_x86_64|0a93865c56fac0cec9faa739fa81bf69fe58614e9e8d74c088b6c414055b5453|26709007",
            "1.6.4|macos_arm64|c3c6196b71946c7825d1e9a1d7d03be1c68b07fd4528a7bbf918f718c4164ffa|25068075",
            "1.6.4|linux_x86_64|569fc3d526dcf57eb5af4764843b87b36a7cb590fc50f94a07757c1189256775|25178385",
            "1.6.4|linux_arm64|823606826b03c333689152c539892edb6ea81c085e4b3b7482ba7aa4b216b762|22936172",
            "1.6.3|macos_x86_64|6fbd1ba3d64daad05d9384568f7300ee9f15e18a5f3a19a33fe48b8d1b44385a|26250341",
            "1.6.3|macos_arm64|8cad19d5f34c6ab2af21219fc3968ba30084f5e39bf219230706d360869ed8e9|24617887",
            "1.6.3|linux_x86_64|caa432f110db519bf9b7c84df23ead398e59b6cc3da2938f010200f1ee8f2ae4|24744282",
            "1.6.3|linux_arm64|01d8dc9bda3d4de585d5901c5099d9155faeb0730fbd9dc6c6e13735cba76700|22546698",
            "1.6.2|macos_x86_64|361ffd98f0cdee631cb1475688471c5fb8f41bd6a4d8d300f29df384c82d6316|26240346",
            "1.6.2|macos_arm64|87345e9f2932c29c8d00c5ca9e0361fada18accc2573fd66883b3adb40949be8|24601764",
            "1.6.2|linux_x86_64|107142241b12ff78b6eb9c419757d406a8714704f7928750a662ba19de055e98|24738688",
            "1.6.2|linux_arm64|ac70f54865d1c0a945d3efa221074e32a3818c666a412148ee5f9f0b14fd330d|22545374",
            "1.6.1|macos_x86_64|48951cc7f15bc028a867642425db720c18f13491007ee218dcc54b5ea0519d17|26232033",
            "1.6.1|macos_arm64|85ad9903a48c1b997540d1b9fdd47d7b29cb6be740e7c34f6f8afc7581f4ac8e|24601376",
            "1.6.1|linux_x86_64|d1a778850cc44d9348312c9527f471ea1b7a9213205bb5091ec698f3dc92e2a6|24738770",
            "1.6.1|linux_arm64|ae328d5733657f35233fd228d9a14fccde3b1d19b99158eff1906888b3ca4935|22533578",
            "1.6.0|macos_x86_64|8993da0dac34cc8ba9b88f925c17d54ec490bea6d18f6f49b07d535e6264a608|26230769",
            "1.6.0|macos_arm64|aaf3f6639c9fd3864059955a36ccdadd7b54bab681fbe760525548a53cc0c7ec|24601489",
            "1.6.0|linux_x86_64|0ddc3f21786026e1f8522ba0f5c6ed27a3c8cc56bfac91e342c1f578f8af44a8|24735015",
            "1.6.0|linux_arm64|413006af67285f158df9e7e2ce1faf4460fd68aa7de612f550aa0e8d70d62e60|22536701",
            "1.5.7|macos_x86_64|b310ec0e626e9799000cfc8e30247cd827cf7f8030c8e0400257c7f111e93537|22296467",
            "1.5.7|macos_arm64|db7c33eb1a446b73a443e2c55b532845f7b70cd56100bec4c96f15cfab5f50cb|21020511",
            "1.5.7|linux_x86_64|c0ed7bc32ee52ae255af9982c8c88a7a4c610485cf1d55feeb037eab75fa082c|21019880",
            "1.5.7|linux_arm64|f4b4ad7c6b6088960a667e34495cae490fb072947a9ff266bf5929f5333565e4|19074897",
            "1.5.6|macos_x86_64|a65a994111b9d1c7fca8fdb76470430a54e1367c6342507228954d944e82f9db|22296410",
            "1.5.6|macos_arm64|c540d0ccbfb37884232dffd277c0ed08ab01ea7c05fe61b66951dddfc0dd802c|21020902",
            "1.5.6|linux_x86_64|3de5135eecbdb882c7c941920846cc63b0685209f9f8532c6fc1460d9c58e347|21020690",
            "1.5.6|linux_arm64|e36dd4cbb4e4ccb96134993b36e99ef5cd5baf84f70615020dc00d91150bc277|19075160",
            "1.5.5|macos_x86_64|6d61639e2141b7c23a9219c63994f729aa41f91110a1aa08b8a37969fb45e229|22294458",
            "1.5.5|macos_arm64|c7fdeddb4739fdd5bada9d45fd786e2cbaf6e9e364693eee45c83e95281dad3a|21021941",
            "1.5.5|linux_x86_64|ad0c696c870c8525357b5127680cd79c0bdf58179af9acd091d43b1d6482da4a|21018563",
            "1.5.5|linux_arm64|b055aefe343d0b710d8a7afd31aeb702b37bbf4493bb9385a709991e48dfbcd2|19072220",
            "1.5.4|macos_x86_64|27aca7551143d98be83b780fa0040b359c43a6704bdd49514ea582d942752718|22256529",
            "1.5.4|macos_arm64|6d68b0e1c0eab5f525f395ddaee360e2eccddff49c2af37d132e8c045b5001c5|20786134",
            "1.5.4|linux_x86_64|16d9c05137ecf7f427a8cfa14ca9e7c0e73cb339f2c88ee368824ac7b4d077ea|20983285",
            "1.5.4|linux_arm64|c087c129891816109296738d2bf83d46fdca110825a308d5192f330e80dad71a|19032505",
            "1.5.3|macos_x86_64|a5ecd11c8ed9b6c5182a84bce9c3c9c092f86916cf117bca855991853502af94|22256567",
            "1.5.3|macos_arm64|444e5565806041d9899a9ba50549840eaa2a2cb7d5b59bb08c5874f92bc4963d|20786372",
            "1.5.3|linux_x86_64|5ce4e0fc73d42b79f26ebb8c8d192bdbcff75bdc44e3d66895a48945b6ff5d48|20983262",
            "1.5.3|linux_arm64|776c78281c1b517d1e2d9e78b2e60900b8ef9ecd51c4a5d2ffa68f66fea35dd2|19032229",
            "1.5.2|macos_x86_64|0484b5c7d5daa17cfff476f29b027398d805c00a8c276f884734b4c6fadd15ec|22227436",
            "1.5.2|macos_arm64|75c5632f221adbba38d569bdaeb6c3cb90b7f82e26b01e39b3b7e1c16bb0e4d4|20764083",
            "1.5.2|linux_x86_64|781ffe0c8888d35b3f5bd0481e951cebe9964b9cfcb27e352f22687975401bcd|20957185",
            "1.5.2|linux_arm64|c39a081830f708fa9e50e5fe1462525ded4de1b4308dcf91f64914d6f4e988b3|19007656",
            "1.5.1|macos_x86_64|4f9f518b40399a9271dd8e449a6335ec94a4de60fc8789711ede7a4b9e630a47|22227975",
            "1.5.1|macos_arm64|f691b79319bd82daac2d8b6cbb595d3e8523296c4cd20bf7da0d12fe9eefdfa7|20764989",
            "1.5.1|linux_x86_64|31754361a9b16564454104bfae8dd40fc6b0c754401c51c58a1023b5e193aa29|20957843",
            "1.5.1|linux_arm64|7799fc8f167fa4071024b11cb2fc186fdab18d9bede761d3f1cdffad7ab19df0|19007417",
            "1.5.0|macos_x86_64|dd64d8a2a75519b933b4f1d76417675ea66bdb45c2a2672cf511825091eba789|22227929",
            "1.5.0|macos_arm64|0765371227ab09e1bb64d606fcfe3d157a2992ac3b82ffabfb9976db53bd791e|20765209",
            "1.5.0|linux_x86_64|9ae1bcfef088e9aaabeaf6fdc6cce01187dc4936f1564899ee6fa6baec5ad19c|20957558",
            "1.5.0|linux_arm64|7d0bb120dc90dc05011f7a6c7c027f2ac1b13c0d5721b8c935f2f440e539a968|19006668",
            "1.4.7|macos_x86_64|603764c07862bd3a87fce193f8b9823383df22626b254f353c83511635763301|22051376",
            "1.4.7|macos_arm64|4b2ae04467469b923d038e6720ae1f92cb2adaa96b7ab08199c2fffee8b45baa|20612022",
            "1.4.7|linux_x86_64|247c75658065b8691e19455f79969f583029f905a37026489f22c56a8830b8b2|20779728",
            "1.4.7|linux_arm64|5f8a31bbb391b2044e992975290d8fb1bf4f7996c84a40c91ea521b9cb0b5791|18834553",
            "1.4.6|macos_x86_64|5d8332994b86411b049391d31ad1a0785dfb470db8b9c50617de28ddb5d1f25d|22051279",
            "1.4.6|macos_arm64|30a2f87298ff9f299452119bd14afaa8d5b000c572f62fa64baf432e35d9dec1|20613318",
            "1.4.6|linux_x86_64|e079db1a8945e39b1f8ba4e513946b3ab9f32bd5a2bdf19b9b186d22c5a3d53b|20779821",
            "1.4.6|linux_arm64|b38f5db944ac4942f11ceea465a91e365b0636febd9998c110fbbe95d61c3b26|18834675",
            "1.4.5|macos_x86_64|808e54d826737e9a0ca79bbe29330e50d3622bbeeb26066c63b371a291731711|22031074",
            "1.4.5|macos_arm64|7104d9d13632aa61b494a349c589048d21bd550e579404c3a41c4932e4d6aa97|20592841",
            "1.4.5|linux_x86_64|ce10e941cd11554b15a189cd00191c05abc20dff865599d361bdb863c5f406a9|20767621",
            "1.4.5|linux_arm64|ca2c48f518f72fef668255150cc5e63b92545edc62a05939bbff8a350bceb357|18813058",
            "1.4.4|macos_x86_64|0303ed9d7e5a225fc2e6fa9bf76fc6574c0c0359f22d5dfc04bc8b3234444f7c|22032187",
            "1.4.4|macos_arm64|75602d9ec491982ceabea813569579b2991093a4e0d76b7ca86ffd9b7a2a1d1e|20594012",
            "1.4.4|linux_x86_64|67541c1f6631befcc25b764028e5605e59234d4424e60a256518ee1e8dd50593|20767354",
            "1.4.4|linux_arm64|f0b4e092f2aa6de3324e5e4b5b51260ecf5e8c2f5335ff7a2ffdc4fb54a8922d|18814310",
            "1.4.3|macos_x86_64|89bdb242bfacf24167f365ef7a3bf0ad0e443ddd27ebde425fb71d77ce1a2597|22032267",
            "1.4.3|macos_arm64|20b9d484bf99ada6c0de89316176ba33f7c87f64c0738991188465147bba221b|20574247",
            "1.4.3|linux_x86_64|2252ee6ac8437b93db2b2ba341edc87951e2916afaeb50a88b858e80796e9111|20781685",
            "1.4.3|linux_arm64|d3d9464953d390970e7f4f7cbcd94dbf63136da6fe1cbb4955d944a9315bdcdb|18814307",
            "1.4.2|macos_x86_64|c218a6c0ef6692b25af16995c8c7bdf6739e9638fef9235c6aced3cd84afaf66|22030042",
            "1.4.2|macos_arm64|af8ff7576c8fc41496fdf97e9199b00d8d81729a6a0e821eaf4dfd08aa763540|20588400",
            "1.4.2|linux_x86_64|9f3ca33d04f5335472829d1df7785115b60176d610ae6f1583343b0a2221a931|20234129",
            "1.4.2|linux_arm64|39c182670c4e63e918e0a16080b1cc47bb16e158d7da96333d682d6a9cb8eb91|18206088",
            "1.4.1|macos_x86_64|96466364a7e66e3d456ecb6c85a63c83e124c004f8835fb8ea9b7bbb7542a9d0|22077050",
            "1.4.1|macos_arm64|61f76e130b97c8a9017d8aaff15d252af29117e35ea1a0fc30bcaab7ceafce73|20634145",
            "1.4.1|linux_x86_64|9e9f3e6752168dea8ecb3643ea9c18c65d5a52acc06c22453ebc4e3fc2d34421|20276168",
            "1.4.1|linux_arm64|53322cc70b6e50ac1985bf26a78ffa2814789a4704880f071eaf3e67a463d6f6|18248378",
            "1.4.0|macos_x86_64|e897a4217f1c3bfe37c694570dcc6371336fbda698790bb6b0547ec8daf1ffb3|21935694",
            "1.4.0|macos_arm64|d4a1e564714c6acf848e86dc020ff182477b49f932e3f550a5d9c8f5da7636fb|20508091",
            "1.4.0|linux_x86_64|5da60da508d6d1941ffa8b9216147456a16bbff6db7622ae9ad01d314cbdd188|20144407",
            "1.4.0|linux_arm64|33e0f4f0b75f507fc19012111de008308df343153cd6a3992507f4566c0bb723|18130960",
            "1.3.10|macos_x86_64|e5cf68ef9b259503abf515a1716fcfe21d46af22e24b8ebbbe7849fbfafb428c|21195636",
            "1.3.10|macos_arm64|39cf7882108034f78c0d9144153271efb11ba99924170828eda9b0196f3da6fd|19794701",
            "1.3.10|linux_x86_64|2e3931c3db6999cdd4c7e55227cb877c6946d1f52923d7d057036d2827311402|19989918",
            "1.3.10|linux_arm64|26dbff9a7d5de4ae0b3972fd62ff4784af6d5887833a91a88a013255c9069117|18094292",
            "1.3.9|macos_x86_64|a73326ea8fb06f6976597e005f8047cbd55ac76ed1e517303d8f6395db6c7805|21194871",
            "1.3.9|macos_arm64|d8a59a794a7f99b484a07a0ed2aa6520921d146ac5a7f4b1b806dcf5c4af0525|19793371",
            "1.3.9|linux_x86_64|53048fa573effdd8f2a59b726234c6f450491fe0ded6931e9f4c6e3df6eece56|19477757",
            "1.3.9|linux_arm64|da571087268c5faf884912c4239c6b9c8e1ed8e8401ab1dcb45712df70f42f1b|17513770",
            "1.3.8|macos_x86_64|1a27a6fac31ecb05de610daf61a29fe83d304d7c519d773afbf56c11c3b6276b|21189878",
            "1.3.8|macos_arm64|873b05ac81645cd7289d6ccfd3e73d4735af1a453f2cd19da0650bdabf7d2eb6|19780134",
            "1.3.8|linux_x86_64|9d9e7d6a9b41cef8b837af688441d4fbbd84b503d24061d078ad662441c70240|19479266",
            "1.3.8|linux_arm64|a42bf3c7d6327f45d2b212b692ab4229285fb44dbb8adb7c39e18be2b26167c8|17507360",
            "1.3.7|macos_x86_64|eeae48adcd55212b34148ed203dd5843e9b2a84a852a9877f3386fadb0514980|21185288",
            "1.3.7|macos_arm64|01d553db5f7b4cf0729b725e4402643efde5884b1dabf5eb80af328ce5e447cf|19774151",
            "1.3.7|linux_x86_64|b8cf184dee15dfa89713fe56085313ab23db22e17284a9a27c0999c67ce3021e|19464102",
            "1.3.7|linux_arm64|5b491c555ea8a62dda551675fd9f27d369f5cdbe87608d2a7367d3da2d38ea38|17499971",
            "1.3.6|macos_x86_64|13881fe0100238577394243a90c0631783aad21b77a9a7ee830404f86c0d37bb|21183111",
            "1.3.6|macos_arm64|dbff0aeeaeee877c254f5414bef5c9d186e159aa0019223aac678abad9442c53|19779986",
            "1.3.6|linux_x86_64|bb44a4c2b0a832d49253b9034d8ccbd34f9feeb26eda71c665f6e7fa0861f49b|19466755",
            "1.3.6|linux_arm64|f4b1af29094290f1b3935c29033c4e5291664ee2c015ca251a020dd425c847c3|17501845",
            "1.3.5|macos_x86_64|e6c9836188265b20c2588e9c9d6b1727094b324a379337e68ba58a6d26be8b51|21182319",
            "1.3.5|macos_arm64|fcec1cbff229fbe59b03257ba2451d5ad1f5129714f08ccf6372b2737647c063|19780547",
            "1.3.5|linux_x86_64|ac28037216c3bc41de2c22724e863d883320a770056969b8d211ca8af3d477cf|19469337",
            "1.3.5|linux_arm64|ba5b1761046b899197bbfce3ad9b448d14550106d2cc37c52a60fc6822b584ed|17502759",
            "1.3.4|macos_x86_64|2a75c69ec5ed8506658b266a40075256b62a7d245ff6297df7e48fa72af23879|21181585",
            "1.3.4|macos_arm64|a1f740f92afac6db84421a3ec07d9061c34a32f88b4b0b47d243de16c961169f|19773343",
            "1.3.4|linux_x86_64|b24210f28191fa2a08efe69f54e3db2e87a63369ac4f5dcaf9f34dc9318eb1a8|19462529",
            "1.3.4|linux_arm64|65381c6b61b2d1a98892199f649a5764ff5a772080a73d70f8663245e6402c39|17494667",
            "1.3.3|macos_x86_64|2b3cf653cd106becdea562b6c8d3f8939641e5626c5278729cbef81678fa9f42|21163874",
            "1.3.3|macos_arm64|51e94ecf88059e8a53c363a048b658230f560574f99b0d8396ebacead894d159|19755200",
            "1.3.3|linux_x86_64|fa5cbf4274c67f2937cabf1a6544529d35d0b8b729ce814b40d0611fd26193c1|19451941",
            "1.3.3|linux_arm64|b940a080c698564df5e6a2f1c4e1b51b2c70a5115358d2361e3697d3985ecbfe|17488660",
            "1.3.2|macos_x86_64|3639461bbc712dc130913bbe632afb449fce8c0df692429d311e7cb808601901|21163990",
            "1.3.2|macos_arm64|80480acbfee2e2d0b094f721f7568a40b790603080d6612e19b797a16b8ba82d|19757201",
            "1.3.2|linux_x86_64|6372e02a7f04bef9dac4a7a12f4580a0ad96a37b5997e80738e070be330cb11c|19451510",
            "1.3.2|linux_arm64|ce1a8770aaf27736a3352c5c31e95fb10d0944729b9d81013bf6848f8657da5f|17485206",
            "1.3.1|macos_x86_64|4282ebe6d1d72ace0d93e8a4bcf9a6f3aceac107966216355bb516b1c49cc203|21161667",
            "1.3.1|macos_arm64|f0514f29b08da2f39ba4fff0d7eb40093915c9c69ddc700b6f39b78275207d96|19756039",
            "1.3.1|linux_x86_64|0847b14917536600ba743a759401c45196bf89937b51dd863152137f32791899|19450765",
            "1.3.1|linux_arm64|7ebb3d1ff94017fbef8acd0193e0bd29dec1a8925e2b573c05a92fdb743d1d5b|17486534",
            "1.3.0|macos_x86_64|80e55182d4495da867c93c25dc6ae29be83ece39d3225e6adedecd55b72d6bbf|21163947",
            "1.3.0|macos_arm64|df703317b5c7f80dc7c61e46de4697c9f440e650a893623351ab5e184995b404|19741011",
            "1.3.0|linux_x86_64|380ca822883176af928c80e5771d1c0ac9d69b13c6d746e6202482aedde7d457|19450952",
            "1.3.0|linux_arm64|0a15de6f934cf2217e5055412e7600d342b4f7dcc133564690776fece6213a9a|17488551",
            "1.2.9|macos_x86_64|84a678ece9929cebc34c7a9a1ba287c8b91820b336f4af8437af7feaa0117b7c|21672810",
            "1.2.9|macos_arm64|bc3b94b53cdf1be3c4988faa61aad343f48e013928c64bfc6ebeb61657f97baa|20280541",
            "1.2.9|linux_x86_64|0e0fc38641addac17103122e1953a9afad764a90e74daf4ff8ceeba4e362f2fb|19906116",
            "1.2.9|linux_arm64|6da7bf01f5a72e61255c2d80eddeba51998e2bb1f50a6d81b0d3b71e70e18531|17946045",
            "1.2.8|macos_x86_64|efd3e21a9bb1cfa68303f8d119ea8970dbb616f5f99caa0fe21d796e0cd70252|21678594",
            "1.2.8|macos_arm64|2c83bfea9e1c202c449e91bee06a804afb45cb8ba64a73da48fb0f61df51b327|20277152",
            "1.2.8|linux_x86_64|3e9c46d6f37338e90d5018c156d89961b0ffb0f355249679593aff99f9abe2a2|19907515",
            "1.2.8|linux_arm64|26c05cadb05cdaa8ac64b90b982b4e9350715ec2e9995a6b03bb964d230de055|17947439",
            "1.2.7|macos_x86_64|74e47b54ea78685be24c84e0e17b22b56220afcdb24ec853514b3863199f01e4|21673162",
            "1.2.7|macos_arm64|ec4e623914b411f8cc93a1e71396a1e7f1fe1e96bb2e532ba3e955d2ca5cc442|20278743",
            "1.2.7|linux_x86_64|dfd7c44a5b6832d62860a01095a15b53616fb3ea4441ab89542f9364e3fca718|19907183",
            "1.2.7|linux_arm64|80d064008d57ba5dc97e189215c87275bf39ca14b1234430eae2f114394ea229|17943724",
            "1.2.6|macos_x86_64|d896d2776af8b06cd4acd695ad75913040ce31234f5948688fd3c3fde53b1f75|21670957",
            "1.2.6|macos_arm64|c88ceb34f343a2bb86960e32925c5ec43b41922ee9ede1019c5cf7d7b4097718|20279669",
            "1.2.6|linux_x86_64|9fd445e7a191317dcfc99d012ab632f2cc01f12af14a44dfbaba82e0f9680365|19905977",
            "1.2.6|linux_arm64|322755d11f0da11169cdb234af74ada5599046c698dccc125859505f85da2a20|17943213",
            "1.2.5|macos_x86_64|2520fde736b43332b0c2648f4f6dde407335f322a3085114dc4f70e6e50eadc0|21659883",
            "1.2.5|macos_arm64|92ad40db4a0930bdf872d6336a7b3a18b17c6fd04d9fc769b554bf51c8add505|20266441",
            "1.2.5|linux_x86_64|281344ed7e2b49b3d6af300b1fe310beed8778c56f3563c4d60e5541c0978f1b|19897064",
            "1.2.5|linux_arm64|0544420eb29b792444014988018ae77a7c8df6b23d84983728695ba73e38f54a|17938208",
            "1.2.4|macos_x86_64|e7d2c66264a3da94854ae6ff692bbb9a1bc11c36bb5658e3ef19841388a07430|21658356",
            "1.2.4|macos_arm64|c31754ff5553707ef9fd2f913b833c779ab05ce192eb14913f51816a077c6798|20263133",
            "1.2.4|linux_x86_64|705ea62a44a0081594dad6b2b093eefefb12d54fa5a20a66562f9e082b00414c|19895510",
            "1.2.4|linux_arm64|11cfa2233dc708b51b16d5b923379db67e35c22b1b988773e5b31a7c2e251471|17936883",
            "1.2.3|macos_x86_64|bdc22658463237530dc120dadb0221762d9fb9116e7a6e0dc063d8ae649c431e|21658937",
            "1.2.3|macos_arm64|6f06debac2ac54951464bf490e1606f973ab53ad8ba5decea76646e8f9309512|20256836",
            "1.2.3|linux_x86_64|728b6fbcb288ad1b7b6590585410a98d3b7e05efe4601ef776c37e15e9a83a96|19891436",
            "1.2.3|linux_arm64|a48991e938a25bfe5d257f4b6cbbdc73d920cc34bbc8f0e685e28b9610ad75fe|17933271",
            "1.2.2|macos_x86_64|1d22663c1ab22ecea774ae63aee21eecfee0bbc23b953206d889a5ba3c08525a|21656824",
            "1.2.2|macos_arm64|b87716b55a3b10cced60db5285bae57aee9cc0f81c555dccdc4f54f62c2a3b60|20254768",
            "1.2.2|linux_x86_64|2934a0e8824925beb956b2edb5fef212a6141c089d29d8568150a43f95b3a626|19889133",
            "1.2.2|linux_arm64|9c6202237d7477412054dcd36fdc269da9ee66ecbc45bb07d0d63b7d36af7b21|17932829",
            "1.2.1|macos_x86_64|31c0fd4deb7c6a77c08d2fdf59c37950e6df7165088c004e1dd7f5e09fbf6307|21645582",
            "1.2.1|macos_arm64|70159b3e3eb49ee71193815943d9217c59203fd4ee8c6960aeded744094a2250|20253448",
            "1.2.1|linux_x86_64|8cf8eb7ed2d95a4213fbfd0459ab303f890e79220196d1c4aae9ecf22547302e|19881618",
            "1.2.1|linux_arm64|972ea512dac822274791dedceb6e7f8b9ac2ed36bd7759269b6806d0ab049128|17922073",
            "1.2.0|macos_x86_64|1b102ba3bf0c60ff6cbee74f721bf8105793c1107a1c6d03dcab98d7079f0c77|21645732",
            "1.2.0|macos_arm64|f5e46cabe5889b60597f0e9c365cbc663e4c952c90a16c10489897c2075ae4f0|20253335",
            "1.2.0|linux_x86_64|b87de03adbdfdff3c2552c8c8377552d0eecd787154465100cf4e29de4a7be1f|19880608",
            "1.2.0|linux_arm64|ee80b8635d8fdbaed57beffe281cf87b8b1fd1ddb29c08d20e25a152d9f0f871|17920355",
            "1.1.9|macos_x86_64|685258b525eae94fb0b406faf661aa056d31666256bf28e625365a251cb89fdc|20850638",
            "1.1.9|macos_arm64|39fac4be74462be86b2290dd09fe1092f73dfb48e2df92406af0e199cfa6a16c|20093184",
            "1.1.9|linux_x86_64|9d2d8a89f5cc8bc1c06cb6f34ce76ec4b99184b07eb776f8b39183b513d7798a|19262029",
            "1.1.9|linux_arm64|e8a09d1fe5a68ed75e5fabe26c609ad12a7e459002dea6543f1084993b87a266|17521011",
            "1.1.8|macos_x86_64|48f1f1e04d0aa8f5f1a661de95e3c2b8fd8ab16b3d44015372aff7693d36c2cf|20354970",
            "1.1.8|macos_arm64|943e1948c4eae82cf8b490bb274939fe666252bbc146f098e7da65b23416264a|19631574",
            "1.1.8|linux_x86_64|fbd37c1ec3d163f493075aa0fa85147e7e3f88dd98760ee7af7499783454f4c5|18796132",
            "1.1.8|linux_arm64|10b2c063dcff91329ee44bce9d71872825566b713308b3da1e5768c6998fb84f|17107405",
            "1.1.7|macos_x86_64|6e56eea328683541f6de0d5f449251a974d173e6d8161530956a20d9c239731a|20351873",
            "1.1.7|macos_arm64|8919ceee34f6bfb16a6e9ff61c95f4043c35c6d70b21de27e5a153c19c7eba9c|19625836",
            "1.1.7|linux_x86_64|e4add092a54ff6febd3325d1e0c109c9e590dc6c38f8bb7f9632e4e6bcca99d4|18795309",
            "1.1.7|linux_arm64|2f72982008c52d2d57294ea50794d7c6ae45d2948e08598bfec3e492bce8d96e|17109768",
            "1.1.6|macos_x86_64|7a499c1f08d89548ae4c0e829eea43845fa1bd7b464e7df46102b35e6081fe44|20303856",
            "1.1.6|macos_arm64|f06a14fdb610ec5a7f18bdbb2f67187230eb418329756732d970b6ca3dae12c3|19577273",
            "1.1.6|linux_x86_64|3e330ce4c8c0434cdd79fe04ed6f6e28e72db44c47ae50d01c342c8a2b05d331|18751464",
            "1.1.6|linux_arm64|a53fb63625af3572f7252b9fb61d787ab153132a8984b12f4bb84b8ee408ec53|17069580",
            "1.1.5|macos_x86_64|dcf7133ebf61d195e432ddcb70e604bf45056163d960e991881efbecdbd7892b|20300006",
            "1.1.5|macos_arm64|6e5a8d22343722dc8bfcf1d2fd7b742f5b46287f87171e8143fc9b87db32c3d4|19581167",
            "1.1.5|linux_x86_64|30942d5055c7151f051c8ea75481ff1dc95b2c4409dbb50196419c21168d6467|18748879",
            "1.1.5|linux_arm64|2fb6324c24c14523ae63cedcbc94a8e6c1c317987eced0abfca2f6218d217ca5|17069683",
            "1.1.4|macos_x86_64|4f3bc78fedd4aa17f67acc0db4eafdb6d70ba72392aaba65fe72855520f11f3d|20242050",
            "1.1.4|macos_arm64|5642b46e9c7fb692f05eba998cd4065fb2e48aa8b0aac9d2a116472fbabe34a1|19498408",
            "1.1.4|linux_x86_64|fca028d622f82788fdc35c1349e78d69ff07c7bb68c27d12f8b48c420e3ecdfb|18695508",
            "1.1.4|linux_arm64|3c1982cf0d16276c82960db60c998d79ba19e413af4fa2c7f6f86e4994379437|16996040",
            "1.1.3|macos_x86_64|016bab760c96d4e64d2140a5f25c614ccc13c3fe9b3889e70c564bd02099259f|20241648",
            "1.1.3|macos_arm64|02ba769bb0a8d4bc50ff60989b0f201ce54fd2afac2fb3544a0791aca5d3f6d5|19493636",
            "1.1.3|linux_x86_64|b215de2a18947fff41803716b1829a3c462c4f009b687c2cbdb52ceb51157c2f|18692580",
            "1.1.3|linux_arm64|ad5a1f2c132bedc5105e3f9900e4fe46858d582c0f2a2d74355da718bbcef65d|16996972",
            "1.1.2|macos_x86_64|78faa76db5dc0ecfe4bf7c6368dbf5cca019a806f9d203580a24a4e0f8cd8353|20240584",
            "1.1.2|macos_arm64|cc3bd03b72db6247c9105edfeb9c8f674cf603e08259075143ffad66f5c25a07|19486800",
            "1.1.2|linux_x86_64|734efa82e2d0d3df8f239ce17f7370dabd38e535d21e64d35c73e45f35dfa95c|18687805",
            "1.1.2|linux_arm64|088e2226d1ddb7f68a4f65c704022a1cfdbf20fe40f02e0c3646942f211fd746|16994702",
            "1.1.1|macos_x86_64|d125dd2e92b9245f2202199b52f234035f36bdcbcd9a06f08e647e14a9d9067a|20237718",
            "1.1.1|macos_arm64|4cb6e5eb4f6036924caf934c509a1dfd61cd2c651bb3ee8fbfe2e2914dd9ed17|19488315",
            "1.1.1|linux_x86_64|07b8dc444540918597a60db9351af861335c3941f28ea8774e168db97dd74557|18687006",
            "1.1.1|linux_arm64|d6fd14da47af9ec5fa3ad5962eaef8eed6ff2f8a5041671f9c90ec5f4f8bb554|16995635",
            "1.1.0|macos_x86_64|6e0ba9afb8795a544e70dc0459f0095fea7df15e38f5d88a7dd3f620d50f8bfe|20226329",
            "1.1.0|macos_arm64|7955e173c7eadb87123fc0633c3ee67d5ba3b7d6c7f485fe803efed9f99dce54|19491369",
            "1.1.0|linux_x86_64|763378aa75500ce5ba67d0cba8aa605670cd28bf8bafc709333a30908441acb5|18683106",
            "1.1.0|linux_arm64|6697e9a263e264310373f3c91bf83f4cbfeb67b13994d2a8f7bcc492b554552e|16987201",
            "1.0.11|macos_x86_64|551a16b612edaae1037925d0e2dba30d16504ff4bd66606955172c2ed8d76131|19422757",
            "1.0.11|macos_arm64|737e1765afbadb3d76e1929d4b4af8da55010839aa08e9e730d46791eb8ea5a6|18467868",
            "1.0.11|linux_x86_64|eeb46091a42dc303c3a3c300640c7774ab25cbee5083dafa5fd83b54c8aca664|18082446",
            "1.0.11|linux_arm64|30c650f4bc218659d43e07d911c00f08e420664a3d12c812228e66f666758645|16148492",
            "1.0.10|macos_x86_64|077479e98701bc9be88db21abeec684286fd85a3463ce437d7739d2a4e372f18|33140832",
            "1.0.10|macos_arm64|776f2e144039ece66ae326ebda0884254848a2e11f0590757d02e3a74f058c81|32013985",
            "1.0.10|linux_x86_64|a221682fcc9cbd7fde22f305ead99b3ad49d8303f152e118edda086a2807716d|32674953",
            "1.0.10|linux_arm64|b091dbe5c00785ae8b5cb64149d697d61adea75e495d9e3d910f61d8c9967226|30505040",
            "1.0.9|macos_x86_64|be122ff7fb925643c5ebf4e5704b18426e18d3ca49ab59ae33d208c908cb6d5a|33140006",
            "1.0.9|macos_arm64|89b2b4fd1a0c57fabc08ad3180ad148b1f7c1c0492ed865408f75f12e11a083b|32010657",
            "1.0.9|linux_x86_64|f06ac64c6a14ed6a923d255788e4a5daefa2b50e35f32d7a3b5a2f9a5a91e255|32674820",
            "1.0.9|linux_arm64|457ac590301126e7b151ea08c5b9586a882c60039a0605fb1e44b8d23d2624fd|30510941",
            "1.0.8|macos_x86_64|909781ee76250cf7445f3b7d2b82c701688725fa1db3fb5543dfeed8c47b59de|33140123",
            "1.0.8|macos_arm64|92fa31b93d736fab6f3d105beb502a9da908445ed942a3d46952eae88907c53e|32011344",
            "1.0.8|linux_x86_64|a73459d406067ce40a46f026dce610740d368c3b4a3d96591b10c7a577984c2e|32681118",
            "1.0.8|linux_arm64|01aaef769f4791f9b28530e750aadbc983a8eabd0d55909e26392b333a1a26e4|30515501",
            "1.0.7|macos_x86_64|23b85d914465882b027d3819cc05cd114a1aaf39b550de742e81a99daa998183|33140742",
            "1.0.7|macos_arm64|d9062959f28ba0f934bfe2b6e0b021e0c01a48fa065102554ca103b8274e8e0c|32012708",
            "1.0.7|linux_x86_64|bc79e47649e2529049a356f9e60e06b47462bf6743534a10a4c16594f443be7b|32671441",
            "1.0.7|linux_arm64|4e71a9e759578020750be41e945c086e387affb58568db6d259d80d123ac80d3|30529105",
            "1.0.6|macos_x86_64|5ac4f41d5e28f31817927f2c5766c5d9b98b68d7b342e25b22d053f9ecd5a9f1|33141677",
            "1.0.6|macos_arm64|613020f90a6a5d0b98ebeb4e7cdc4b392aa06ce738fbb700159a465cd27dcbfa|32024047",
            "1.0.6|linux_x86_64|6a454323d252d34e928785a3b7c52bfaff1192f82685dfee4da1279bb700b733|32677516",
            "1.0.6|linux_arm64|2047f8afc7d0d7b645a0422181ba3fe47b3547c4fe658f95eebeb872752ec129|30514636",
        ]

    extra_env_vars = StrListOption(
        help=softwrap(
            """
            Additional environment variables that would be made available to all Terraform processes.
            """
        ),
        advanced=True,
    )
    args = ArgsListOption(
        example="-auto-approve",
        passthrough=True,
        extra_help=softwrap(
            """
            Additional arguments to pass to the Terraform command line.
            """
        ),
    )

    platforms = StrListOption(
        help=softwrap(
            """
            Platforms to generate lockfiles for. See the [documentation for the providers lock command](https://developer.hashicorp.com/terraform/cli/commands/providers/lock#platform-os_arch).
            For example, `["windows_amd64", "darwin_amd64", "linux_amd64"]`
            """
        ),
        advanced=True,
    )

    tailor = BoolOption(
        default=True,
        help="If true, add `terraform_module` targets with the `tailor` goal.",
        advanced=True,
    )

    @property
    def plugin_cache_dir(self) -> str:
        return "__terraform_filesystem_mirror"

    @property
    def append_only_caches(self) -> dict[str, str]:
        return {"terraform_plugins": self.plugin_cache_dir}


@dataclass(frozen=True)
class TerraformProcess:
    """A request to invoke Terraform."""

    args: tuple[str, ...]
    description: str
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()
    output_directories: tuple[str, ...] = ()
    chdir: str = "."  # directory for terraform's `-chdir` argument


@rule
async def setup_terraform_process(
    request: TerraformProcess,
    terraform: TerraformTool,
    getent_binary: GetentBinary,
    platform: Platform,
) -> Process:
    downloaded_terraform = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        terraform.get_request(platform),
    )
    env = await Get(EnvironmentVars, EnvironmentVarsRequest(terraform.extra_env_vars))

    extra_bins = await Get(
        BinaryShims,
        BinaryShimsRequest,
        BinaryShimsRequest.for_paths(getent_binary, rationale="download terraform providers"),
    )

    path = []
    user_path = env.get("PATH")
    if user_path:
        path.append(user_path)
    path.append(extra_bins.path_component)

    env = EnvironmentVars(
        {
            **env,
            "PATH": ":".join(path),
            "TF_PLUGIN_CACHE_DIR": (os.path.join("{chroot}", terraform.plugin_cache_dir)),
        }
    )

    immutable_input_digests = {
        "__terraform": downloaded_terraform.digest,
        **extra_bins.immutable_input_digests,
    }

    def prepend_paths(paths: Tuple[str, ...]) -> Tuple[str, ...]:
        return tuple((Path(request.chdir) / path).as_posix() for path in paths)

    return Process(
        argv=("__terraform/terraform", f"-chdir={shlex.quote(request.chdir)}") + request.args,
        input_digest=request.input_digest,
        immutable_input_digests=immutable_input_digests,
        output_files=prepend_paths(request.output_files),
        output_directories=prepend_paths(request.output_directories),
        append_only_caches=terraform.append_only_caches,
        env=env,
        description=request.description,
        level=LogLevel.DEBUG,
    )


def rules():
    return [*collect_rules(), *external_tool.rules()]
