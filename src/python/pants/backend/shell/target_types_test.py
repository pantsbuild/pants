# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from textwrap import dedent

import pytest

from pants.backend.shell import target_types
from pants.backend.shell.target_types import (
    ShellSourcesGeneratorTarget,
    ShellSourceTarget,
    Shunit2Shell,
    Shunit2TestsGeneratorTarget,
    Shunit2TestTarget,
)
from pants.engine.addresses import Address
from pants.engine.internals.graph import _TargetParametrizations
from pants.engine.target import SingleSourceField, Tags
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.mark.parametrize(
    ["content", "expected"],
    [
        # Direct paths.
        (b"#!/path/to/sh", Shunit2Shell.sh),
        (b"#!/path/to/bash", Shunit2Shell.bash),
        (b"#!/path/to/dash", Shunit2Shell.dash),
        (b"#!/path/to/ksh", Shunit2Shell.ksh),
        (b"#!/path/to/pdksh", Shunit2Shell.pdksh),
        (b"#!/path/to/zsh", Shunit2Shell.zsh),
        # `env $shell`.
        (b"#!/path/to/env sh", Shunit2Shell.sh),
        (b"#!/path/to/env bash", Shunit2Shell.bash),
        (b"#!/path/to/env dash", Shunit2Shell.dash),
        (b"#!/path/to/env ksh", Shunit2Shell.ksh),
        (b"#!/path/to/env pdksh", Shunit2Shell.pdksh),
        (b"#!/path/to/env zsh", Shunit2Shell.zsh),
        # Whitespace is fine.
        (b"#! /path/to/env sh", Shunit2Shell.sh),
        (b"#!/path/to/env   sh", Shunit2Shell.sh),
        (b"#!/path/to/env sh ", Shunit2Shell.sh),
        (b"#!/path/to/sh arg1 arg2 ", Shunit2Shell.sh),
        (b"#!/path/to/env sh\n", Shunit2Shell.sh),
        # Must be absolute path.
        (b"#!/sh", Shunit2Shell.sh),
        (b"#!sh", None),
        # Missing or invalid shebang.
        (b"", None),
        (b"some program", None),
        (b"something #!/path/to/sh", None),
        (b"something #!/path/to/env sh", None),
        (b"\n#!/path/to/sh", None),
    ],
)
def test_shunit2_shell_parse_shebang(content: bytes, expected: Shunit2Shell | None) -> None:
    result = Shunit2Shell.parse_shebang(content)
    if expected is None:
        assert result is None
    else:
        assert result == expected


def test_generate_source_and_test_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_types.rules(),
            QueryRule(_TargetParametrizations, [Address]),
        ],
        target_types=[Shunit2TestsGeneratorTarget, ShellSourcesGeneratorTarget],
    )
    rule_runner.write_files(
        {
            "src/sh/BUILD": dedent(
                """\
                shell_sources(
                    name='lib',
                    sources=['**/*.sh', '!**/*_test.sh'],
                    overrides={'f1.sh': {'tags': ['overridden']}},
                )

                shunit2_tests(
                    name='tests',
                    sources=['**/*_test.sh'],
                    overrides={'f1_test.sh': {'tags': ['overridden']}},
                )
                """
            ),
            "src/sh/f1.sh": "",
            "src/sh/f1_test.sh": "",
            "src/sh/f2.sh": "",
            "src/sh/f2_test.sh": "",
            "src/sh/subdir/f.sh": "",
            "src/sh/subdir/f_test.sh": "",
        }
    )

    def gen_source_tgt(rel_fp: str, tags: list[str] | None = None) -> ShellSourceTarget:
        return ShellSourceTarget(
            {SingleSourceField.alias: rel_fp, Tags.alias: tags},
            Address("src/sh", target_name="lib", relative_file_path=rel_fp),
            residence_dir=os.path.dirname(os.path.join("src/sh", rel_fp)),
        )

    def gen_test_tgt(rel_fp: str, tags: list[str] | None = None) -> Shunit2TestTarget:
        return Shunit2TestTarget(
            {SingleSourceField.alias: rel_fp, Tags.alias: tags},
            Address("src/sh", target_name="tests", relative_file_path=rel_fp),
            residence_dir=os.path.dirname(os.path.join("src/sh", rel_fp)),
        )

    sources_generated = rule_runner.request(
        _TargetParametrizations, [Address("src/sh", target_name="lib")]
    ).parametrizations
    tests_generated = rule_runner.request(
        _TargetParametrizations, [Address("src/sh", target_name="tests")]
    ).parametrizations

    assert set(sources_generated.values()) == {
        gen_source_tgt("f1.sh", tags=["overridden"]),
        gen_source_tgt("f2.sh"),
        gen_source_tgt("subdir/f.sh"),
    }
    assert set(tests_generated.values()) == {
        gen_test_tgt("f1_test.sh", tags=["overridden"]),
        gen_test_tgt("f2_test.sh"),
        gen_test_tgt("subdir/f_test.sh"),
    }
