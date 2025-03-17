# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from collections.abc import Iterable
from enum import Enum

from packaging.version import parse

from pants.backend.python.util_rules import python_sources
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    FileOption,
    SkipOption,
    StrListOption,
    StrOption,
)
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap


class RuffMode(str, Enum):
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

    default_version = "0.9.10"
    default_known_versions = [
        "0.9.10|macos_x86_64|1e5080489fdf483e7111bb1575f045ec13da2fdbfc6ac5fd58b5d55cf9cd7668|10838186",
        "0.9.10|macos_arm64|1fccbd53431eaa596f2322494edbdc444f99db651566188fa0a9820c26bbef77|10147621",
        "0.9.10|linux_x86_64|15e93ee078beb5ec24d1afb02a1cce2a873ac627d378c987adda4f6ab3b5f886|11373081",
        "0.9.10|linux_arm64|c131df77457ed45aa44b617194563ceea2e29e595c42d06804e04155529423b4|10245226",
        "0.9.6|macos_x86_64|ec88c095036b25e95391ea202fcc9496d565f4e43152db10785eb9757ea0815d|11663591",
        "0.9.6|macos_arm64|a3132eb5e3d95f36d378144082276fbed0309789dadb19d8a4c41ec5e80451fb|11124436",
        "0.9.6|linux_x86_64|c725f57aa11d636f1d7f0f378c604d4db29c4dbb5ff0578f9fbbc578364875df|12568611",
        "0.9.6|linux_arm64|8f64e97deae1c12f659fd13e6e14d78cf15ed876d1548ac76b235f78ab5803e1|11929444",
        "0.7.2|macos_x86_64|5815756947d0a7b1d90805b07ffb2c376c8a9800e9462d545839dc0d79a091d2|10162492",
        "0.7.2|macos_arm64|1c9f5a4fc815330d01fd8a56a7a70114ff3ed149bd997ff831524313705ba991|9802953",
        "0.7.2|linux_x86_64|b769e11a3e23a72692cb97ed762ff28e48534972a8ef447fd5b0d3178a56ffd8|11097578",
        "0.7.2|linux_arm64|f9342fcca6b58143f316ef3e617f39334edb4c3d15fced5220bd939685f6261d|10651691",
        "0.6.9|macos_x86_64|34aa37643e30dcb81a3c0e011c3a8df552465ea7580ba92ca727a3b7c6de25d1|10018168",
        "0.6.9|macos_arm64|b94562393a4bf23f1a48521f5495a8e48de885b7c173bd7ea8206d6d09921633|9697031",
        "0.6.9|linux_x86_64|39a1cd878962ebc88322b4f6d33cae2292454563028f93a3f1f8ce58e3025b07|11000553",
        "0.6.9|linux_arm64|73df3729a3381d0918e4640aac4b2653c542f74c7b7843dee8310e2c877e6f2e|10724239",
        "0.6.4|macos_x86_64|4438cbc80c6aa0e839abc3abb2a869a27113631cb40aa26540572fb53752c432|9463378",
        "0.6.4|macos_arm64|2648dd09984c82db9f3163ce8762c89536e4bf0e198f17e06a01c0e32214273e|9167424",
        "0.6.4|linux_x86_64|3ca04aabf7259c59193e4153a865618cad26f73be930ce5f6109e0e6097d037b|10373921",
        "0.6.4|linux_arm64|a9157a0f062d62c1b1582284a8d10629503f38bc9b7126b614cb7569073180ff|10120541",
        "0.5.7|macos_x86_64|1f9a7d307f191781fc895947af21d32f8c810c5a5a4cdff16ac53d88a14acd69|8662539",
        "0.5.7|macos_arm64|b78a09f44dc60d8c894aba6cad55abd3b0eccc0992d60a86f74155fc459e227b|8256430",
        "0.5.7|linux_x86_64|9a5580536ef9cea7d8e56be8af712ac5cd152c081969ece2fbc3631b30bbb5e8|10263458",
        "0.5.7|linux_arm64|2509d20ef605fb1c8af37af1f46fefc85e1d72add6e87187cb6543420c05dfb1|9991080",
        "0.4.10|macos_x86_64|6e96f288d13b68863e79c9f107a0c51660215829726c9d3dc4879c1801fa3140|8490153|https://github.com/astral-sh/ruff/releases/download/v0.4.10/ruff-0.4.10-x86_64-apple-darwin.tar.gz",
        "0.4.10|macos_arm64|5a4ff81270eee1efa7901566719aca705a3e8d0f1abead96c01caa4678a7762e|8094319|https://github.com/astral-sh/ruff/releases/download/v0.4.10/ruff-0.4.10-aarch64-apple-darwin.tar.gz",
        "0.4.10|linux_x86_64|332ba368c6e08afc3c5d1c7f6e4fb7bf238b7cbf007b400e6bdf01a0a36ae656|10130989|https://github.com/astral-sh/ruff/releases/download/v0.4.10/ruff-0.4.10-x86_64-unknown-linux-musl.tar.gz",
        "0.4.10|linux_arm64|75332c97520233b5f95cb3d40bdef13b40e1aa5e6c82a078623993545771f55f|9851689|https://github.com/astral-sh/ruff/releases/download/v0.4.10/ruff-0.4.10-aarch64-unknown-linux-musl.tar.gz",
        "0.4.9|macos_x86_64|e4d745adb0f5a0b08f2c9ca71e57f451a9b8485ae35b5555d9f5d20fc93a6cb6|8510706|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-x86_64-apple-darwin.tar.gz",
        "0.4.9|macos_arm64|5f4506d7ec2ae6ac5a48ba309218a4b825a00d4cad9967b7bbcec1724ef04930|8148128|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-aarch64-apple-darwin.tar.gz",
        "0.4.9|linux_x86_64|5ceba21dad91e3fa05056ca62f278b0178516cfad8dbf08cf2433c6f1eeb92d3|8863118|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-x86_64-unknown-linux-musl.tar.gz",
        "0.4.9|linux_arm64|00c50563f9921a141ddd4ec0371149f3bbfa0369d9d238a143bcc3a932363785|8106747|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-aarch64-unknown-linux-musl.tar.gz",
        "0.3.7|macos_x86_64|b1c961c1bed427e74ab72950c6debcb078c82aba0ee347183cc27a9fc8aaa43b|8615221|https://github.com/astral-sh/ruff/releases/download/v0.3.7/ruff-0.3.7-x86_64-apple-darwin.tar.gz",
        "0.3.7|linux_x86_64|3f8348096f7d9c0a9266c4a821dbc7599ef299983e456b61eb0d5290d8615df8|8905370|https://github.com/astral-sh/ruff/releases/download/v0.3.7/ruff-0.3.7-x86_64-unknown-linux-musl.tar.gz",
        "0.3.7|linux_arm64|0e79fbefcd813a10fa60250441bbe36978c95d010b64646848fada64b9af61f0|8180808|https://github.com/astral-sh/ruff/releases/download/v0.3.7/ruff-0.3.7-aarch64-unknown-linux-musl.tar.gz",
        "0.2.2|macos_x86_64|798a2028a783f10f21f11eb59763eabcff9961d4302cdcc37d186ab9f864ca82|7611899|https://github.com/astral-sh/ruff/releases/download/v0.2.2/ruff-0.2.2-x86_64-apple-darwin.tar.gz",
        "0.2.2|macos_arm64|21454a77f0a5ff8ed23a43327f6de9c2f9f6bab1352ebe87fc03866889fa7fae|7262889|https://github.com/astral-sh/ruff/releases/download/v0.2.2/ruff-0.2.2-aarch64-apple-darwin.tar.gz",
        "0.2.2|linux_x86_64|044e4dbd46acc12de78a144c24fd9af86003eaba28e83244546d85076a9c7b04|7881552|https://github.com/astral-sh/ruff/releases/download/v0.2.2/ruff-0.2.2-x86_64-unknown-linux-musl.tar.gz",
        "0.2.2|linux_arm64|e73a37f41acf4a4f44cdb9b587316f0f9eb83b51c3c134d1401501e3f8d65dee|7247275|https://github.com/astral-sh/ruff/releases/download/v0.2.2/ruff-0.2.2-aarch64-unknown-linux-musl.tar.gz",
        "0.1.15|macos_x86_64|6d006dc427a74cba930717297b0c472856a2be4cfc37cd04309895c11329dc68|7308240|https://github.com/astral-sh/ruff/releases/download/v0.1.15/ruff-0.1.15-x86_64-apple-darwin.tar.gz",
        "0.1.15|macos_arm64|373c648d693ddaf4f1936a05d3093aabd08553f585c3c3afbbdba41d16b70032|7025376|https://github.com/astral-sh/ruff/releases/download/v0.1.15/ruff-0.1.15-aarch64-apple-darwin.tar.gz",
        "0.1.15|linux_x86_64|d7389b9743b0b909c364d11bba94d13302171d751430b58c13dcdf248e924276|7605249|https://github.com/astral-sh/ruff/releases/download/v0.1.15/ruff-0.1.15-x86_64-unknown-linux-musl.tar.gz",
        "0.1.15|linux_arm64|e9ed3c353c4f2b801ed4d21fee2b6159883ad777e959fbbad0b2d2b22e1974c7|7049764|https://github.com/astral-sh/ruff/releases/download/v0.1.15/ruff-0.1.15-aarch64-unknown-linux-musl.tar.gz",
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

    _removal_hint = f"NOW IGNORED: use `version` and `known_versions` options to customise the version of ruff, replacing this option; consider deleting the resolve and `python_requirement` if no longer used. See {doc_url('reference/subsystems/ruff')}"

    # Options that only exist to ease the upgrade from Ruff as a Python tool to Ruff as an external
    # downloaded one
    install_from_resolve = StrOption(
        advanced=True,
        default=None,
        removal_version="2.27.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )

    requirements = StrListOption(
        advanced=True,
        default=None,
        removal_version="2.27.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )
    interpreter_constraints = StrListOption(
        advanced=True,
        default=None,
        removal_version="2.27.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )
    console_script = StrOption(
        advanced=True,
        default=None,
        removal_version="2.27.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )
    entry_point = StrOption(
        advanced=True,
        default=None,
        removal_version="2.27.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )


def rules():
    return (
        *collect_rules(),
        *python_sources.rules(),
        UnionRule(ExportableTool, Ruff),
    )
