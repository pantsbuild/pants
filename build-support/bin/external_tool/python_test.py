# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pathlib import Path
from textwrap import dedent

from external_tool.python import replace_class_variables

CONTENT = """\
from __future__ import annotations

from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.strutil import help_text


class Cue(TemplatedExternalTool):
    options_scope = "cue"
    name = "CUE"
    help = help_text(
        \"\"\"
        CUE is an open-source data validation language and inference engine with its roots in logic
        programming. Although the language is not a general-purpose programming language, it has
        many applications, such as data validation, data templating, configuration, querying, code
        generation and even scripting. The inference engine can be used to validate data in code or
        to include it as part of a code generation pipeline.

        Homepage: https://cuelang.org/
        \"\"\"
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


def rules():
    return (UnionRule(ExportableTool, Cue),)
"""


EXPECTED = """\
from __future__ import annotations

from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.strutil import help_text


class Cue(TemplatedExternalTool):
    options_scope = "cue"
    name = "CUE"
    help = help_text(
        \"\"\"
        CUE is an open-source data validation language and inference engine with its roots in logic
        programming. Although the language is not a general-purpose programming language, it has
        many applications, such as data validation, data templating, configuration, querying, code
        generation and even scripting. The inference engine can be used to validate data in code or
        to include it as part of a code generation pipeline.

        Homepage: https://cuelang.org/
        \"\"\"
    )
    default_version = "v0.12.0"
    default_known_versions = [
        "v0.12.0|linux_x86_64|e55cd5abd98a592c110f87a7da9ef15bc72515200aecfe1bed04bf86311f5ba1|8731479",
        "v0.12.0|linux_arm64|488012bb0e5c080e2a9694ef8765403dd1075a4ec373dda618efa2d37b47f14f|8067539",
        "v0.12.0|macos_arm64|7055a6423f753c8ea763699d48d78d341e8543397399daee281c66ecdc9ec5a5|8400578",
        "v0.12.0|macos_x86_64|8474e522a978ecadef49b06d706ff276cd07629b1aa107b88adfc1284d3f93cc|8902127",
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


def rules():
    return (UnionRule(ExportableTool, Cue),)
"""


def test_replace_class_variables(tmpdir: str):
    file_path = Path(tmpdir) / "subsystem.py"
    file_path.write_text(CONTENT)

    replacements = {
        "default_version": "v0.12.0",
        "default_known_versions": [
            "v0.12.0|linux_x86_64|e55cd5abd98a592c110f87a7da9ef15bc72515200aecfe1bed04bf86311f5ba1|8731479",
            "v0.12.0|linux_arm64|488012bb0e5c080e2a9694ef8765403dd1075a4ec373dda618efa2d37b47f14f|8067539",
            "v0.12.0|macos_arm64|7055a6423f753c8ea763699d48d78d341e8543397399daee281c66ecdc9ec5a5|8400578",
            "v0.12.0|macos_x86_64|8474e522a978ecadef49b06d706ff276cd07629b1aa107b88adfc1284d3f93cc|8902127",
        ],
    }

    replace_class_variables(file_path, "Cue", replacements)

    updated_content = file_path.read_text()
    assert updated_content == EXPECTED


def test_replace_class_variables_adds_trailing_comma(tmpdir: str):
    file_path = Path(tmpdir) / "tool.py"
    file_path.write_text(
        dedent("""\
        class MyTool:
            default_known_versions = [
                "1.0.0|linux_x86_64|abc123|1234",
            ]
        """)
    )

    replace_class_variables(
        file_path,
        "MyTool",
        replacements={
            "default_known_versions": [
                "2.0.0|linux_x86_64|def456|5678",
                "2.0.0|linux_arm64|ghi789|9012",
            ],
        },
    )

    assert file_path.read_text() == dedent("""\
        class MyTool:
            default_known_versions = [
                "2.0.0|linux_x86_64|def456|5678",
                "2.0.0|linux_arm64|ghi789|9012",
            ]
        """)
