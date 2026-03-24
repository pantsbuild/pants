# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from collections.abc import Iterable
from enum import StrEnum

from packaging.version import parse

from pants.backend.python.util_rules import python_sources
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap


class RuffMode(StrEnum):
    FIX = "check --fix"
    FORMAT = "format"
    LINT = "check"
    # "format --check" is automatically covered by builtin linter for RuffFmtRequest.


# --------------------------------------------------------------------------------------
# Subsystem
# --------------------------------------------------------------------------------------


class Ruff(TemplatedExternalTool):
    options_scope = "ruff"
    name = "Ruff"
    help = "The Ruff Python formatter (https://github.com/astral-sh/ruff)."

    default_version = "0.14.14"
    default_known_versions = [
        "0.15.5|linux_arm64 |ae22fb3b6ad85cff59abf147d572d266397f42b73e51e6d55dba56fb3430fe1d|10033873",
        "0.15.5|linux_x86_64|da9b5c8ba7a789fe3bcf6287ea58ccbac9328a711b7674681706106e7580a836|10959476",
        "0.15.5|macos_arm64 |f39400f9504c940fa4eb46b02e2d4889a9f86b81ce4c57bda02ea3568894d094|9727686",
        "0.15.5|macos_x86_64|1e01b0d6354f14dac0f4de7a89488d18e00f8aa37ce3635b55bcaf1357b2a375|10519592",
        "0.15.4|linux_arm64 |f34909dacbebaf3773ececc0d321e0fa0599729e9b4570f1dbcec91b4c435913|10037148",
        "0.15.4|linux_x86_64|e39111195ef761569773562209bbb7f943c834c961f2c1ed28e2126a15c4cd35|10925091",
        "0.15.4|macos_arm64 |2d63cc9fd12c9cc3b524563bbeb50470cf3f68f3194002228a417a53a2a56164|9730759",
        "0.15.4|macos_x86_64|f40e16784c867b60850fbe96a2cccd123589c90d6db71ad8ade62efdeabccc84|10508868",
        "0.15.3|linux_arm64 |dea1c50f06820f27b34a56b3f358522df72b197e3d6d935c0d591562b7d8ceef|10023783",
        "0.15.3|linux_x86_64|c3bbd085bc0a1438fccc912bf3b25a390fcf9f2bb46dbe67491a9589bff618ee|10924268",
        "0.15.3|macos_arm64 |9135019481619b3d2d797784ed422cd8622d91ea14b0dfe5c7ebe177a98fabb6|9724192",
        "0.15.3|macos_x86_64|890958c88c244902171878209bc91d237d87f55518fb5e3f40ab76a5bb36e4bb|10508562",
        "0.15.2|linux_arm64 |b1417ad2977d38c93a40cc77b467b4c68d6b5578031852c38033f9b53b26a543|10034015",
        "0.15.2|linux_x86_64|2b11788c9457ba8350f9b55bc302adf7f440d2f92a1d9660cbc3b20b6abf5e1c|10897947",
        "0.15.2|macos_arm64 |59a3a08a077e81d0fd99566604556687b834edb2da34a69522cfb5168a07123b|9712551",
        "0.15.2|macos_x86_64|78702adcccc2309696f19442f18b5fbe6a4bf4211efa157576c2b5f498a4cc0f|10479080",
        "0.15.1|linux_arm64 |05a41b8b7c068633b27e8f9149c70154ac2090e61d48e5ea9983de769593d29c|10013500",
        "0.15.1|linux_x86_64|c8d04b4f6ce053809d98d1ef99f897c52e6204708bb157551ede7fbab505fea2|10888081",
        "0.15.1|macos_arm64 |196f6d4bd380f4a03f9d2d3bcfe17b991145a110f5fc9f5999521cd5e5335e1c|9689563",
        "0.15.1|macos_x86_64|55fd4437b4b6b0c75793525c980bb1d49d9723044edbdd7dcc962cb595d26d51|10458205",
        "0.15.0|linux_arm64 |b9860c394ea814a9e9560e80bc798c53b8a3a5120ce961a2555fb563cee9f73b|9970266",
        "0.15.0|linux_x86_64|f2bd69f091517ebc49405319a6e7818b1037e250b8d539336aa0b91c44ffa4aa|10865213",
        "0.15.0|macos_arm64 |093d355ac33c6b8e91e80b8497d5581c61b028c0405e265cf38fd88f9a291c5c|9618772",
        "0.15.0|macos_x86_64|09fa6fe0d4172e1bb84cc6d937a0e1f42ff84c90b61163fff4f31c51a9c14879|10427634",
        "0.14.14|linux_arm64 |a4d7302aa201a6f8e71dfa217cd8273fddd4e434a93ee3b4b07047fd7a684ac1|10071345",
        "0.14.14|linux_x86_64|55a1ee65f5ac9416cc40f99c2df62f0d4525d40369fe371caff945c495174d57|10976010",
        "0.14.14|macos_arm64 |76a9b0ebe57d0eee56940dbe0b62462578d1369cca8314ed0d2a6f2102292d4f|9770588",
        "0.14.14|macos_x86_64|749396c675c6f07205be6c4ef89e2e95123d790062d681059a355030e9d7d119|10540822",
        "0.14.13|linux_arm64 |25941b777ff712f4d9473d26c1b875034214a3d5de20ea99b2add939dcd0b367|12691467",
        "0.14.13|linux_x86_64|2fe394f493318551f271277a2228e56b31ca69a4842483e5709af4548f342bc3|13946916",
        "0.14.13|macos_arm64 |067d1a90da8add55614eff91990425883a092d8279d9e503258ff8be0f8e9c18|12367714",
        "0.14.13|macos_x86_64|69e424a42ac3a7c6c7032ad96deb757c35c93c848b6ea329a3f4c605e6d89ef9|13439935",
        "0.14.11|linux_arm64 |4779a99b51812b56d56d180174be46ddb2fed98fecaea7565b450d37cff1b8c6|12613237",
        "0.14.11|linux_x86_64|8e8b7a3f791e0faf3a1728d808133f6f9bd5c1422eccb9956e7e7376ff5404b8|13873894",
        "0.14.11|macos_arm64 |c3fab6bcad9cc2f8a342829dd4ea011c54b9671d023b71baac1cbf2b3526cefd|12271824",
        "0.14.11|macos_x86_64|b301d1c04facba1004d180c8fd9ae36d868b780900682c97ecf324015c75f0b3|13324100",
        "0.14.10|linux_arm64 |0888883f71199ca3af3569052d0cc1aee8b316390ffe75bc19f9a8047ffd0158|12700549",
        "0.14.10|linux_x86_64|e1fac6f2705057f48f3d000694d0f41c95b06e738cf4825315c670f3b9d24933|13946807",
        "0.14.10|macos_arm64 |dd0f3ec914604d802658ae0d271ff9d767c117d1702a44222170dd2ffbad8d2c|12364615",
        "0.14.10|macos_x86_64|7d5af84e84a189b49ac235d7970d35588cbed0d087f4237c96e5ac3c392bc6fb|13408056",
        "0.14.9|linux_arm64 |9bdedf2e8d6398e193c2b2feccb2b4c9f8d37a6dc87cc0b587340a60e87d14e2|12694969",
        "0.14.9|linux_x86_64|3bdbdb32f95bcf2c5bc45502a2050f30706f1c205fa0087ee3d4c688f67854fc|13928932",
        "0.14.9|macos_arm64 |ea132e6d6af23dbcf21c81d7fd8c5a94ccf16b1fb36a8bc60da971e339301f10|12372970",
        "0.14.9|macos_x86_64|ce980eb4b44a84cbf278686f8cf71a21b353888b29472ca269ffe385ce4f2351|13389771",
        "0.14.8|linux_arm64 |0b3464f54fa56f514c29e92bcf05867b914ad6c246e2ddbe4cce5c0700f2a3d9|12604548",
        "0.14.8|linux_x86_64|0f5496a3d2413b3cb85bbf9e4a6f95b5db127ac10989ecb3d8c0c0a0a74a892b|13826546",
        "0.14.8|macos_arm64 |4efc019832a6b9225f650ee256d31b2e875021cae662963d533c78b5cf865f52|12262293",
        "0.14.8|macos_x86_64|c53af0ba3cbc5e9e8f7768d28a7ff2d0795843e39302891093227bc6df343e94|13284305",
        "0.14.7|linux_arm64 |8d429dbc2c308377c33874dc71d4c2388728f0d01c0a5869d2c878d21a6ced87|12592606",
        "0.14.7|linux_x86_64|0f6cd59aa2b266758f1083c73f1b8303e3aedde0d953f0e79777faf174d8104f|13813529",
        "0.14.7|macos_arm64 |24631da81fe9ce5f4112e8caeb71957e81682e752a563f0a50715735f923e3c4|12219111",
        "0.14.7|macos_x86_64|c3035811c5354d923f3d7fd6320cfb23de30600f1eb86aa1518bac27c3d7fffd|13252991",
        "0.14.6|linux_arm64 |4d3c113e59c5fbc31f1def566cebf28732bb45ff6b83df8e142bc1c055b3afa3|12482518",
        "0.14.6|linux_x86_64|7ef1743875c7c469cc1c4bb6da6a9bbff3f3a7b89a75632d6cd2944ede470a5e|13675527",
        "0.14.6|macos_arm64 |b2ace677f51d0f2b91ca27d312ac8b069658502049015f4891c16f8864136282|12135363",
        "0.14.6|macos_x86_64|efe45a6defcf4f1b6de87d56ce94635f53b00f88ddc2fcb8e25e2c4e3a61261c|13143383",
        "0.14.5|linux_arm64 |ebef9d7119119e67b1065a5a35128148898e1581037e7d68c3aa9223983af0a4|12382966",
        "0.14.5|linux_x86_64|69ddecf374a4f53eeda238399614ed6f92c5e75fe04436c604fb78435d5658eb|13572647",
        "0.14.5|macos_arm64 |c07616663ac63792c16269d6798a47fb1f45b29997706178d60e90da698a9970|12032411",
        "0.14.5|macos_x86_64|d7285770c5098be00c9b4ff099d6ef7f8b2a54b4019c9507b628ee9f0d404c06|13030885",
        "0.14.4|linux_arm64 |c77b72e565e9044eddce02e71f9214edea045047b786bb2bc973a6d8f94fb13e|12298984",
        "0.14.4|linux_x86_64|dcb5b42fd364c9e837b6800886564a891d023c8b87c967224351399cb1cda154|13483455",
        "0.14.4|macos_arm64 |ab26cd2b03d5b2ec42dc7ac1886a29055eb2003aa2db14b26c7091c7cd6b4c68|11942656",
        "0.14.4|macos_x86_64|041b9429400bfc3aca8402940fe6fa0ec33f9d79e8f50fbfb3063f70b4327fa3|12941582",
        "0.14.3|linux_arm64 |571058fe7e3381ad54bec8b3d9d127013e332d822b35978b503722147aa3b9cf|12272843",
        "0.14.3|linux_x86_64|58fd05427420df7b7b51bc6bbd5a430f38d2dfd63c74660f27625a4632f12532|13422654",
        "0.14.3|macos_arm64 |fc4c2c153656bc4082fb6c928fbd6867d5eb932240b663b329365f3f1821fc82|11953314",
        "0.14.3|macos_x86_64|076e88da3dcb38d3fef61daccc759bf29b605a490143ae707c0e067ebf8d7050|12848979",
        "0.14.2|linux_arm64 |e323e9716661c9e18152aefe62e3fada497c10c9b3ef3095359c31b4df4f866a|12285246",
        "0.14.2|linux_x86_64|e5e177a829b370376abb6a1dc9edc8c59ac519ebe64b1366b65e2952fa524a8d|13391598",
        "0.14.2|macos_arm64 |33225f67ce61188fce91b801ab50a4028f8b0d66abbf81810841dd7d42371e38|11936503",
        "0.14.2|macos_x86_64|f119057618599e8983bdeed64e949af54f67d7a62464d11de0ba1237619a9990|12877704",
        "0.14.1|linux_arm64 |ddfc9df5c879a1984fef4e29838e46fa8e979adc3fdab5967f096363427e8790|12150527",
        "0.14.1|linux_x86_64|ec5b8eb318ff9e2412988420eb78f965aca02e9f67df34eeea7609e0c5a0fb7f|13233886",
        "0.14.1|macos_arm64 |ee12f441b4c14eff354784a52f8a16767573bd6285627cad2ade04551e8a678b|11791296",
        "0.14.1|macos_x86_64|7fda94bd7fc6114eecb67b858a8c93f1b4aa658aa1f5e887b37a2b95bf6f26a7|12773582",
        "0.14.0|linux_arm64 |34a25398f03e7d32a4ec406c5c841c6e183fa0a96fbdd40b7e7eec1f177b360e|12465179",
        "0.14.0|linux_x86_64|ed6d1b8407a1d228dc332fb19057e86e04a6cd3c2beacdb324ad6ff2a3f9071b|13647531",
        "0.14.0|macos_arm64 |0b7c193d5c45eda02226720eb75239fabeca995d5a0eb3830fd2973caa3030ec|12364514",
        "0.14.0|macos_x86_64|880ae046b435eb306cd557a7481eed6da463b85f283ba1f2c1e2ad7c139ed6c5|13149751",
        "0.13.3|linux_arm64 |4301d51fd2fbce6d4cc55613e5f8f96ee4fcb8dcaec8419023fe555575cf78f6|12440723",
        "0.13.3|linux_x86_64|8d24d74171772c67366d3187b990a3dc706022aa3a631b2a612d12e362f226c7|13639367",
        "0.13.3|macos_arm64 |a170ead9a9f03527dba3d2fb3e9e445f73d9efe3584c3307f3d30c6d5f31c487|12345660",
        "0.13.3|macos_x86_64|1c3a291a595ddd08398eb1e06fba883b7d8d715bd4255af5972f858fec8b4e57|13112788",
        "0.13.2|linux_arm64 |a225f352214340d50882ede447fb8eea6a0a5a77233a2e03cda194aa19e5e514|12359532",
        "0.13.2|linux_x86_64|60755c060181b8d3649d5b568ebc80f76df49dd03249445627f2ceae552c21b6|13537377",
        "0.13.2|macos_arm64 |96738ad0b9decb981f53790949487650255a9da0375524b02dcdd862de9f2efa|12251385",
        "0.13.2|macos_x86_64|ed848ebd0a8d7d96a88686c5fc86e8bb6a4c1b831ace2dfa252777f9c69460c6|13031647",
        "0.13.1|linux_arm64 |3ad26d4a7a736e00373e635f03d7427e20183b0fe99b003a494bd5cdbc3c9c12|12317596",
        "0.13.1|linux_x86_64|917c300e001a86d9a5d9aaa275dc49b20a7438e3f298e071b7b695a4092f1898|13439513",
        "0.13.1|macos_arm64 |1cfb3a7455a83602d474044243b618989edf58c2edda45eb4d3331ab550d52c1|12218926",
        "0.13.1|macos_x86_64|9c4d53f20f5bae4d4e664cc91c26d57c1d0a67fb5fd16af6cffdac0db88474c2|12932947",
        "0.13.0|linux_arm64 |bdee6f1376470b74b1dc5ed48eca52ec9c3e4512bd7f3204e0df100f0bed4741|12137114",
        "0.13.0|linux_x86_64|b56ac90cc6987401bafdcf1b931ef044074c5b9451286afa4606a983f64f4fdd|13437622",
        "0.13.0|macos_arm64 |0d706798534537b6655b79fd95c2955c0a0013d4c54d36679d3306825a6bd6aa|12098971",
        "0.13.0|macos_x86_64|ac47ad1ac90f3070c064d2f5fceef4fe609fec7c073fd29d0814ed126c492e6d|12924617",
        "0.12.5|linux_arm64 |f147ccdbe26d35f2752c6d97d158bc8e3b4d1833d283748fc48f350c698a6f7b|11787954",
        "0.12.5|linux_x86_64|79beb4eac07beaea24774709eeb88a87115f1b53f857dcc1155431e642e01ade|12995071",
        "0.12.5|macos_arm64 |8819b61cff645c1d1671df331bb57c1ab230094b686942bccedde1f888feb522|11719060",
        "0.12.5|macos_x86_64|5af0b2931581a5ed91743c9f669c23cb0db9bb1f0c49f8695ad1443dbc6a9e50|12478716",
        "0.11.13|linux_arm64 |1ff8292d610302bc20791f6ab264de499b6d2fbf89030fef915908c564a78e82|10519905",
        "0.11.13|linux_x86_64|4540e8bc5b2af73c4b79e9e993724b044310eea4aa9003cf05ed4bdee6c25735|11609889",
        "0.11.13|macos_arm64 |7d5e8feea7ee5c3962807996cad557e8a0c4d676c1cba6223bfb0e8b2ca07723|10425890",
        "0.11.13|macos_x86_64|8dcc61306472f75c07af6d0446060e26227d773cee319d21900ac3a1d7bc4955|11085786",
        "0.11.5|linux_arm64 |77c11c7a70d3bf499915bab5a7691e955f4127164c4cfb7ef4e0773892ed2509|10318966",
        "0.11.5|linux_x86_64|067c1c6c4d6033b65fe788f5310075686110b286a102431fb19883c079e2fca1|11413549",
        "0.11.5|macos_arm64 |4a5b1a44412bda817debb67d826a565f11b235744870b509f44102403a3a9e89|10228748",
        "0.11.5|macos_x86_64|c28725c6421d5834b2cd16c7b13c3831b3363d6d558448d7dd3e0aa695551f94|10882726",
        "0.11.0|linux_arm64 |60904d6d51b1a8dd49ab948dd1de33ce439ca872c82faa5dab90fce838539317|10313237",
        "0.11.0|linux_x86_64|3148cd8131ec4f525551b16a57186f5533c705950269cbee7674d484ca6eefe5|11412993",
        "0.11.0|macos_arm64 |09ea313f2aab3844432b46c6c5e3e066b26ae4953f4bac1e545176e5dea22306|10239274",
        "0.11.0|macos_x86_64|a208dee9c1a7a063dace746836fd2d7e5f7694d2142700d3964fccf141ada555|10861900",
        "0.10.0|linux_arm64 |7b9fe2e2cecde897fb35a1a0bb1ccd10dde3395acd81aea7e5e6b0b24824e7c7|10305951",
        "0.10.0|linux_x86_64|5e949f667a1dd76ab4382ba713fed3390ddc6088147ba0eb70fd8aa2ec564751|11399512",
        "0.10.0|macos_arm64 |1da279b8302cd86f50d38fc8ad62cd12f4d07c0c402c13a3bac7dc244c7db138|10224628",
        "0.10.0|macos_x86_64|2388af7881c7e50026388e953fa6eab7c1ae94c868926a6185c3cb38f9f15aa2|10862770",
        "0.9.10|linux_arm64 |c131df77457ed45aa44b617194563ceea2e29e595c42d06804e04155529423b4|10245226",
        "0.9.10|linux_x86_64|15e93ee078beb5ec24d1afb02a1cce2a873ac627d378c987adda4f6ab3b5f886|11373081",
        "0.9.10|macos_arm64 |1fccbd53431eaa596f2322494edbdc444f99db651566188fa0a9820c26bbef77|10147621",
        "0.9.10|macos_x86_64|1e5080489fdf483e7111bb1575f045ec13da2fdbfc6ac5fd58b5d55cf9cd7668|10838186",
        "0.9.6|linux_arm64 |8f64e97deae1c12f659fd13e6e14d78cf15ed876d1548ac76b235f78ab5803e1|11929444",
        "0.9.6|linux_x86_64|c725f57aa11d636f1d7f0f378c604d4db29c4dbb5ff0578f9fbbc578364875df|12568611",
        "0.9.6|macos_arm64 |a3132eb5e3d95f36d378144082276fbed0309789dadb19d8a4c41ec5e80451fb|11124436",
        "0.9.6|macos_x86_64|ec88c095036b25e95391ea202fcc9496d565f4e43152db10785eb9757ea0815d|11663591",
        "0.8.6|linux_arm64 |23c5d1dd7eed23d2bd6d340df05a068030e267db28150892a72e3dc97b175164|10868993",
        "0.8.6|linux_x86_64|a691c78f045f7202b15620939c4b087f301afe884e42d09a19725f61581aa887|11329234",
        "0.8.6|macos_arm64 |d24cfe247de2bfd90d7f0604196247b680e1db5b6c8427cf6e540c38044526f7|10005432",
        "0.8.6|macos_x86_64|3ff48d180472a1aee6385ba43606ba6a5a6ab89f16a3ca8ccb234966fe3698c1|10374010",
        "0.7.4|linux_arm64 |329ddf6bb4f34fbcba273ecb1460280aa2ad92150a94f58110861b3c4453ce35|10703090",
        "0.7.4|linux_x86_64|38ff38639f33764acf2cf3c3252e2a214b7f5fedafa67c50909926297dba9229|11172665",
        "0.7.4|macos_arm64 |af9583bff12afbca5d5670334e0187dd60c4d91bc71317d1b2dde70cb1200ba9|9882883",
        "0.7.4|macos_x86_64|9762afafafacd801eb95a086dcd3359075ab5cc4cd1371b7ff0550c44ac4e47c|10223356",
        "0.7.2|linux_arm64 |f9342fcca6b58143f316ef3e617f39334edb4c3d15fced5220bd939685f6261d|10651691",
        "0.7.2|linux_x86_64|b769e11a3e23a72692cb97ed762ff28e48534972a8ef447fd5b0d3178a56ffd8|11097578",
        "0.7.2|macos_arm64 |1c9f5a4fc815330d01fd8a56a7a70114ff3ed149bd997ff831524313705ba991|9802953",
        "0.7.2|macos_x86_64|5815756947d0a7b1d90805b07ffb2c376c8a9800e9462d545839dc0d79a091d2|10162492",
        "0.6.9|linux_arm64 |73df3729a3381d0918e4640aac4b2653c542f74c7b7843dee8310e2c877e6f2e|10724239",
        "0.6.9|linux_x86_64|39a1cd878962ebc88322b4f6d33cae2292454563028f93a3f1f8ce58e3025b07|11000553",
        "0.6.9|macos_arm64 |b94562393a4bf23f1a48521f5495a8e48de885b7c173bd7ea8206d6d09921633|9697031",
        "0.6.9|macos_x86_64|34aa37643e30dcb81a3c0e011c3a8df552465ea7580ba92ca727a3b7c6de25d1|10018168",
        "0.6.4|linux_arm64 |a9157a0f062d62c1b1582284a8d10629503f38bc9b7126b614cb7569073180ff|10120541",
        "0.6.4|linux_x86_64|3ca04aabf7259c59193e4153a865618cad26f73be930ce5f6109e0e6097d037b|10373921",
        "0.6.4|macos_arm64 |2648dd09984c82db9f3163ce8762c89536e4bf0e198f17e06a01c0e32214273e|9167424",
        "0.6.4|macos_x86_64|4438cbc80c6aa0e839abc3abb2a869a27113631cb40aa26540572fb53752c432|9463378",
        "0.5.7|linux_arm64 |2509d20ef605fb1c8af37af1f46fefc85e1d72add6e87187cb6543420c05dfb1|9991080",
        "0.5.7|linux_x86_64|9a5580536ef9cea7d8e56be8af712ac5cd152c081969ece2fbc3631b30bbb5e8|10263458",
        "0.5.7|macos_arm64 |b78a09f44dc60d8c894aba6cad55abd3b0eccc0992d60a86f74155fc459e227b|8256430",
        "0.5.7|macos_x86_64|1f9a7d307f191781fc895947af21d32f8c810c5a5a4cdff16ac53d88a14acd69|8662539",
        "0.4.10|linux_arm64 |75332c97520233b5f95cb3d40bdef13b40e1aa5e6c82a078623993545771f55f|9851689|https://github.com/astral-sh/ruff/releases/download/v0.4.10/ruff-0.4.10-aarch64-unknown-linux-musl.tar.gz",
        "0.4.10|linux_x86_64|332ba368c6e08afc3c5d1c7f6e4fb7bf238b7cbf007b400e6bdf01a0a36ae656|10130989|https://github.com/astral-sh/ruff/releases/download/v0.4.10/ruff-0.4.10-x86_64-unknown-linux-musl.tar.gz",
        "0.4.10|macos_arm64 |5a4ff81270eee1efa7901566719aca705a3e8d0f1abead96c01caa4678a7762e|8094319|https://github.com/astral-sh/ruff/releases/download/v0.4.10/ruff-0.4.10-aarch64-apple-darwin.tar.gz",
        "0.4.10|macos_x86_64|6e96f288d13b68863e79c9f107a0c51660215829726c9d3dc4879c1801fa3140|8490153|https://github.com/astral-sh/ruff/releases/download/v0.4.10/ruff-0.4.10-x86_64-apple-darwin.tar.gz",
        "0.4.9|linux_arm64 |00c50563f9921a141ddd4ec0371149f3bbfa0369d9d238a143bcc3a932363785|8106747|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-aarch64-unknown-linux-musl.tar.gz",
        "0.4.9|linux_x86_64|5ceba21dad91e3fa05056ca62f278b0178516cfad8dbf08cf2433c6f1eeb92d3|8863118|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-x86_64-unknown-linux-musl.tar.gz",
        "0.4.9|macos_arm64 |5f4506d7ec2ae6ac5a48ba309218a4b825a00d4cad9967b7bbcec1724ef04930|8148128|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-aarch64-apple-darwin.tar.gz",
        "0.4.9|macos_x86_64|e4d745adb0f5a0b08f2c9ca71e57f451a9b8485ae35b5555d9f5d20fc93a6cb6|8510706|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-x86_64-apple-darwin.tar.gz",
        "0.3.7|linux_arm64 |0e79fbefcd813a10fa60250441bbe36978c95d010b64646848fada64b9af61f0|8180808|https://github.com/astral-sh/ruff/releases/download/v0.3.7/ruff-0.3.7-aarch64-unknown-linux-musl.tar.gz",
        "0.3.7|linux_x86_64|3f8348096f7d9c0a9266c4a821dbc7599ef299983e456b61eb0d5290d8615df8|8905370|https://github.com/astral-sh/ruff/releases/download/v0.3.7/ruff-0.3.7-x86_64-unknown-linux-musl.tar.gz",
        "0.3.7|macos_x86_64|b1c961c1bed427e74ab72950c6debcb078c82aba0ee347183cc27a9fc8aaa43b|8615221|https://github.com/astral-sh/ruff/releases/download/v0.3.7/ruff-0.3.7-x86_64-apple-darwin.tar.gz",
        "0.2.2|linux_arm64 |e73a37f41acf4a4f44cdb9b587316f0f9eb83b51c3c134d1401501e3f8d65dee|7247275|https://github.com/astral-sh/ruff/releases/download/v0.2.2/ruff-0.2.2-aarch64-unknown-linux-musl.tar.gz",
        "0.2.2|linux_x86_64|044e4dbd46acc12de78a144c24fd9af86003eaba28e83244546d85076a9c7b04|7881552|https://github.com/astral-sh/ruff/releases/download/v0.2.2/ruff-0.2.2-x86_64-unknown-linux-musl.tar.gz",
        "0.2.2|macos_arm64 |21454a77f0a5ff8ed23a43327f6de9c2f9f6bab1352ebe87fc03866889fa7fae|7262889|https://github.com/astral-sh/ruff/releases/download/v0.2.2/ruff-0.2.2-aarch64-apple-darwin.tar.gz",
        "0.2.2|macos_x86_64|798a2028a783f10f21f11eb59763eabcff9961d4302cdcc37d186ab9f864ca82|7611899|https://github.com/astral-sh/ruff/releases/download/v0.2.2/ruff-0.2.2-x86_64-apple-darwin.tar.gz",
        "0.1.15|linux_arm64 |e9ed3c353c4f2b801ed4d21fee2b6159883ad777e959fbbad0b2d2b22e1974c7|7049764|https://github.com/astral-sh/ruff/releases/download/v0.1.15/ruff-0.1.15-aarch64-unknown-linux-musl.tar.gz",
        "0.1.15|linux_x86_64|d7389b9743b0b909c364d11bba94d13302171d751430b58c13dcdf248e924276|7605249|https://github.com/astral-sh/ruff/releases/download/v0.1.15/ruff-0.1.15-x86_64-unknown-linux-musl.tar.gz",
        "0.1.15|macos_arm64 |373c648d693ddaf4f1936a05d3093aabd08553f585c3c3afbbdba41d16b70032|7025376|https://github.com/astral-sh/ruff/releases/download/v0.1.15/ruff-0.1.15-aarch64-apple-darwin.tar.gz",
        "0.1.15|macos_x86_64|6d006dc427a74cba930717297b0c472856a2be4cfc37cd04309895c11329dc68|7308240|https://github.com/astral-sh/ruff/releases/download/v0.1.15/ruff-0.1.15-x86_64-apple-darwin.tar.gz",
    ]
    version_constraints = ">=0.1.2,<1"

    default_url_template = (
        "https://github.com/astral-sh/ruff/releases/download/{version}/ruff-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        # NB. musl not gnu, for increased compatibility
        "linux_arm64": "aarch64-unknown-linux-musl",
        "linux_x86_64": "x86_64-unknown-linux-musl",
        "macos_arm64": "aarch64-apple-darwin",
        "macos_x86_64": "x86_64-apple-darwin",
    }

    def generate_exe(self, plat: Platform) -> str:
        # Older versions like 0.4.x just have the binary at the top level of the tar.gz, newer
        # versions nest it within a directory with the platform.
        if parse(self.version) < parse("0.5.0"):
            return "./ruff"

        return f"ruff-{self.default_url_platform_mapping[plat.value]}/ruff"

    skip = SkipOption("fmt", "fix", "lint")
    args = ArgsListOption(example="--exclude=foo --ignore=E501")
    config = FileOption(
        default=None,
        advanced=True,
        help=softwrap(
            f"""
            Path to the `pyproject.toml` or `ruff.toml` file to use for configuration
            (https://github.com/astral-sh/ruff#configuration).

            Setting this option will disable `[{options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=softwrap(
            f"""
            If true, Pants will include any relevant config files during
            runs (`pyproject.toml`, and `ruff.toml`).

            Use `[{options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # See https://github.com/astral-sh/ruff#configuration for how ruff discovers
        # config files.
        all_dirs = ("", *dirs)
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[os.path.join(d, "ruff.toml") for d in all_dirs],
            check_content={os.path.join(d, "pyproject.toml"): b"[tool.ruff" for d in all_dirs},
        )


def rules():
    return (
        *collect_rules(),
        *python_sources.rules(),
        UnionRule(ExportableTool, Ruff),
    )
