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
    default_version = "1.4.6"
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
