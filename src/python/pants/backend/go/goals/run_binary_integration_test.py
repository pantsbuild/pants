# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from textwrap import dedent
from typing import cast

from pants.backend.go.testutil import gen_module_gomodproxy
from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_run_binary() -> None:
    sources = {
        "go.mod": dedent(
            """\
                module foo.example.com
                go 1.17
                """
        ),
        "main.go": dedent(
            """\
                package main

                import (
                    "fmt"
                    "os"
                )

                func main() {{
                    fmt.Println("Hello world!")
                    fmt.Fprintln(os.Stderr, "Hola mundo!")
                    os.Exit(23)
                }}
                """
        ),
        "BUILD": dedent(
            """\
                go_mod(name='mod')
                go_package(name='pkg')
                go_binary(name='bin')
                """
        ),
    }

    with setup_tmpdir(sources) as tmpdir:
        result = run_pants(
            [
                "--backend-packages=pants.backend.experimental.go",
                "--pants-ignore=__pycache__",
                "run",
                f"{tmpdir}:bin",
            ]
        )

    assert "Hola mundo!\n" in result.stderr
    assert result.stdout == "Hello world!\n"
    assert result.exit_code == 23


def test_run_binary_third_party() -> None:
    import_path = "pantsbuild.org/go-sample-for-test"
    version = "v0.0.1"

    fake_gomod = gen_module_gomodproxy(
        version,
        import_path,
        (
            (
                "pkg/hello/hello.go",
                dedent(
                    """\
        package hello
        import "fmt"


        func Hello() {
            fmt.Println("Hello world!")
        }
        """
                ),
            ),
            (
                "cmd/hello/main.go",
                dedent(
                    """\
        package main
        import "pantsbuild.org/go-sample-for-test/pkg/hello"


        func main() {
            hello.Hello()
        }
        """
                ),
            ),
        ),
    )

    fake_gomod.update(
        {
            "BUILD": dedent(
                f"""\
                go_mod(name='mod')
                go_binary(name="bin", main=':mod#{import_path}/cmd/hello')
                """
            ),
            "go.mod": dedent(
                f"""\
                module go.example.com/foo
                go 1.16

                require (
                \t{import_path} {version}
                )
                """
            ),
        }
    )

    raw_files = {
        f"go-mod-proxy/{import_path}/@v/{version}.zip": fake_gomod.pop(
            f"go-mod-proxy/{import_path}/@v/{version}.zip"
        ),
        f"go-mod-proxy/{import_path}/@v/{version}.info": cast(
            str, fake_gomod.pop(f"go-mod-proxy/{import_path}/@v/{version}.info")
        ).encode("utf-8"),
    }

    with setup_tmpdir(
        cast("dict[str, str]", fake_gomod), cast("dict[str, bytes]", raw_files)
    ) as tmpdir:
        # required for GOPROXY to work correctly when the go-mod-proxy
        # is in a subdir of the cwd.
        abspath = os.path.abspath(tmpdir)
        result = run_pants(
            [
                "--backend-packages=pants.backend.experimental.go",
                "--pants-ignore=__pycache__",
                "--golang-subprocess-env-vars=GOSUMDB=off",
                f"--golang-subprocess-env-vars=GOPROXY=file://{abspath}/go-mod-proxy",
                "run",
                f"//{tmpdir}:bin",
            ]
        )

    assert result.stdout == "Hello world!\n"
    assert result.exit_code == 0
