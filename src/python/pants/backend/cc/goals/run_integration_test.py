# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_run_binary() -> None:
    sources = {
        "foo.h": dedent(
            """\
                int add(int a, int b);
                """
        ),
        "main.cpp": dedent(
            """\
                #include "foo.h"
                #include <iostream>

                int add(int a, int b) {{
                    return a + b;
                }}

                int main() {{
                    std::cout << "Hello, world!" << std::endl;
                    return 0;
                }}
                """
        ),
        "BUILD": dedent(
            """\
                cc_sources(name="sources")
                cc_binary(name="bin", dependencies=[":sources"])
                """
        ),
    }

    with setup_tmpdir(sources) as tmpdir:
        result = run_pants(
            [
                "--backend-packages=pants.backend.experimental.cc",
                "run",
                f"{tmpdir}:bin",
            ]
        )

    assert result.stdout == "Hello, world!\n"
    assert result.exit_code == 0
