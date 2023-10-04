# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.strutil import help_text


class Cue(TemplatedExternalTool):
    options_scope = "cue"
    name = "CUE"
    help = help_text(
        """
        CUE is an open-source data validation language and inference engine with its roots in logic
        programming. Although the language is not a general-purpose programming language, it has
        many applications, such as data validation, data templating, configuration, querying, code
        generation and even scripting. The inference engine can be used to validate data in code or
        to include it as part of a code generation pipeline.

        Homepage: https://cuelang.org/
        """
    )
    default_version = "v0.4.3"
    default_known_versions = [
        "v0.4.3|macos_x86_64|1161254cf38b928b87a7ac1552dc2e12e6c5da298f9ce370d80e5518ddb6513d|6240316",
        "v0.4.3|macos_arm64 |3d84b85a7288f94301a4726dcf95b2d92c8ff796c4d45c4733fbdcc04ceaf21d|5996085",
        "v0.4.3|linux_x86_64|5e7ecb614b5926acfc36eb1258800391ab7c6e6e026fa7cacbfe92006bac895c|6037013",
        "v0.4.3|linux_arm64 |a8c3f4140d18c324cc69f5de4df0566e529e1636cff340095a42475799bf3fed|5548404",
    ]
    default_url_template = "https://github.com/cue-lang/cue/releases/download/{version}/cue_{version}_{platform}.tar.gz"
    default_url_platform_mapping = {
        "macos_arm64": "darwin_arm64",
        "macos_x86_64": "darwin_amd64",
        "linux_arm64": "linux_arm64",
        "linux_x86_64": "linux_amd64",
    }
    skip = SkipOption("fmt", "fix", "lint")
    args = ArgsListOption(example="--all-errors")

    def generate_exe(self, plat: Platform) -> str:
        return "cue"
