# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

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
    sources = {
        "go.mod": dedent(
            """\
                module foo.example.com
                go 1.17

                require github.com/tgolsson/example-pants-third-party v0.0.0-20221101220057-1a7167a87ec5 // indirect
                """
        ),
        "BUILD": dedent(
            """\
                go_mod(name='mod')
                go_binary(name='bin', main=":mod#github.com/tgolsson/example-pants-third-party/cmd/hello")
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

    assert result.stdout == "Hello world!\n"
    assert result.exit_code == 0
