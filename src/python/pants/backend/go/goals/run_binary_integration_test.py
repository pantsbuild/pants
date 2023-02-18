# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import zipfile
from textwrap import dedent
from typing import Iterable

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
    # Implements hashing algorithm from https://cs.opensource.google/go/x/mod/+/refs/tags/v0.5.0:sumdb/dirhash/hash.go.
    def _compute_module_hash(files: Iterable[tuple[str, str]]) -> str:
        sorted_files = sorted(files, key=lambda x: x[0])
        summary = ""
        for name, content in sorted_files:
            h = hashlib.sha256(content.encode())
            summary += f"{h.hexdigest()}  {name}\n"

        h = hashlib.sha256(summary.encode())
        summary_digest = base64.standard_b64encode(h.digest()).decode()
        return f"h1:{summary_digest}"

    import_path = "pantsbuild.org/go-embed-sample-for-test"
    version = "v0.0.1"
    go_mod_content = dedent(
        f"""\
        module {import_path}
        go 1.16
        """
    )
    go_mod_sum = _compute_module_hash([("go.mod", go_mod_content)])

    prefix = f"{import_path}@{version}"
    files_in_zip = (
        (f"{prefix}/go.mod", go_mod_content),
        (
            f"{prefix}/pkg/hello/hello.go",
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
            f"{prefix}/cmd/hello/main.go",
            dedent(
                """\
        package main
        import "pantsbuild.org/go-embed-sample-for-test/pkg/hello"


        func main() {
            hello.Hello()
        }
        """
            ),
        ),
    )

    mod_zip_bytes = io.BytesIO()
    with zipfile.ZipFile(mod_zip_bytes, "w") as mod_zip:
        for name, content in files_in_zip:
            mod_zip.writestr(name, content)

    mod_zip_sum = _compute_module_hash(files_in_zip)

    sources = {
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
        "go.sum": dedent(
            f"""\
                {import_path} {version} {mod_zip_sum}
                {import_path} {version}/go.mod {go_mod_sum}
                """
        ),
        # Setup the third-party dependency as a custom Go module proxy site.
        # See https://go.dev/ref/mod#goproxy-protocol for details.
        f"go-mod-proxy/{import_path}/@v/list": f"{version}\n",
        f"go-mod-proxy/{import_path}/@v/{version}.info": f"""{{{json.dumps(
            {
                "Version": version,
                "Time": "2022-01-01T01:00:00Z",
            }
        )}}}""",
        f"go-mod-proxy/{import_path}/@v/{version}.mod": go_mod_content,
    }

    raw_files = {
        f"go-mod-proxy/{import_path}/@v/{version}.zip": mod_zip_bytes.getvalue(),
    }

    with setup_tmpdir(sources, raw_files) as tmpdir:
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
