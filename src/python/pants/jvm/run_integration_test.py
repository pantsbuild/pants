# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

EMPTY_RESOLVE = """
# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---
# {{
#   "version": 1,
#   "generated_with_requirements": [
#   ]
# }}
# --- END PANTS LOCKFILE METADATA ---
"""


@pytest.fixture
def scala_stdlib_jvm_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "scala-library-2.13.test.lock",
        ["org.scala-lang:scala-library:2.13.8"],
    )


@pytest.fixture
def scala_stdlib_jvm_lockfile(
    scala_stdlib_jvm_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scala_stdlib_jvm_lockfile_def.load(request)


@pytest.fixture
def antlr_jvm_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "antlr.test.lock",
        ["org.antlr:antlr4:4.11.1"],
    )


@pytest.fixture
def antlr_jvm_lockfile(
    antlr_jvm_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return antlr_jvm_lockfile_def.load(request)


def test_java_by_deploy_jar() -> None:
    sources = {
        "src/org/pantsbuild/test/Hello.java": dedent(
            """\
            package org.pantsbuild.test;

            public class Hello {{
                public static void main(String[] args) {{
                    System.out.println("Hello, World!");
                }}
            }}
            """
        ),
        "src/org/pantsbuild/test/BUILD": dedent(
            """\
            java_sources()
            deploy_jar(
                name="test_deploy_jar",
                main="org.pantsbuild.test.Hello",
                dependencies=[":test"],
            )
            """
        ),
        "lockfile": EMPTY_RESOLVE,
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.experimental.java",
            f"--source-root-patterns=['{tmpdir}/src']",
            "--pants-ignore=__pycache__",
            f'--jvm-resolves={{"empty": "{tmpdir}/lockfile"}}',
            "--jvm-default-resolve=empty",
            "run",
            f"{tmpdir}/src/org/pantsbuild/test:test_deploy_jar",
        ]
        result = run_pants(args)
        assert result.stdout.strip() == "Hello, World!"


def test_java_direct() -> None:
    sources = {
        "src/org/pantsbuild/test/Hello.java": dedent(
            """\
            package org.pantsbuild.test;

            public class Hello {{
                public static void main(String[] args) {{
                    System.out.println("Hello, World!");
                }}
            }}
            """
        ),
        "src/org/pantsbuild/test/BUILD": dedent(
            """\
            java_sources()
            """
        ),
        "lockfile": EMPTY_RESOLVE,
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.experimental.java",
            f"--source-root-patterns=['{tmpdir}/src']",
            "--pants-ignore=__pycache__",
            f'--jvm-resolves={{"empty": "{tmpdir}/lockfile"}}',
            "--jvm-default-resolve=empty",
            "run",
            f"{tmpdir}/src/org/pantsbuild/test/Hello.java",
        ]
        result = run_pants(args)
        assert result.stdout.strip() == "Hello, World!"


def test_java_direct_ambiguous_main() -> None:
    sources = {
        "src/org/pantsbuild/test/Hello.java": dedent(
            """\
            package org.pantsbuild.test;

            public class Hello {{

                public static class Misdirection {{
                    public static void main(String[] args) {{
                        System.out.println("This should not be printed");
                    }}
                }}

                public static void main(String[] args) {{
                    System.out.println("Hello, World!");
                }}
            }}
            """
        ),
        "src/org/pantsbuild/test/BUILD": dedent(
            """\
            java_source(source="Hello.java", main="org.pantsbuild.test.Hello")
            """
        ),
        "lockfile": EMPTY_RESOLVE,
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.experimental.java",
            f"--source-root-patterns=['{tmpdir}/src']",
            "--pants-ignore=__pycache__",
            f'--jvm-resolves={{"empty": "{tmpdir}/lockfile"}}',
            "--jvm-default-resolve=empty",
            "run",
            f"{tmpdir}/src/org/pantsbuild/test/Hello.java",
        ]
        result = run_pants(args)
        assert result.stdout.strip() == "Hello, World!"


def test_scala_by_deploy_jar(scala_stdlib_jvm_lockfile: JVMLockfileFixture) -> None:
    sources = {
        "src/org/pantsbuild/test/Hello.scala": dedent(
            """\
            package org.pantsbuild.test;

            object Hello {{
                def main(args: Array[String]): Unit = {{
                    println("Hello, World!")
                }}
            }}

            """
        ),
        "src/org/pantsbuild/test/BUILD": dedent(
            """\
            scala_sources()
            deploy_jar(
                name="test_deploy_jar",
                main="org.pantsbuild.test.Hello",
                dependencies=[":test"],
            )
            """
        ),
        "BUILD": scala_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
        "lockfile": scala_stdlib_jvm_lockfile.serialized_lockfile.replace("{", "{{").replace(
            "}", "}}"
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.experimental.scala",
            f"--source-root-patterns=['{tmpdir}/src']",
            "--pants-ignore=__pycache__",
            f'--jvm-resolves={{"jvm-default": "{tmpdir}/lockfile"}}',
            "--jvm-default-resolve=jvm-default",
            "--scala-version-for-resolve={'jvm-default': '2.13.8'}",
            "run",
            f"{tmpdir}/src/org/pantsbuild/test:test_deploy_jar",
        ]
        result = run_pants(args)
        assert result.stdout.strip() == "Hello, World!"


def test_scala_direct(scala_stdlib_jvm_lockfile: JVMLockfileFixture) -> None:
    sources = {
        "src/org/pantsbuild/test/Hello.scala": dedent(
            """\
            package org.pantsbuild.test;

            object Hello {{
                def main(args: Array[String]): Unit = {{
                    println("Hello, World!")
                }}
            }}

            """
        ),
        "src/org/pantsbuild/test/BUILD": dedent(
            """\
            scala_sources()
            """
        ),
        "BUILD": scala_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
        "lockfile": scala_stdlib_jvm_lockfile.serialized_lockfile.replace("{", "{{").replace(
            "}", "}}"
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.experimental.scala",
            f"--source-root-patterns=['{tmpdir}/src']",
            "--pants-ignore=__pycache__",
            f'--jvm-resolves={{"jvm-default": "{tmpdir}/lockfile"}}',
            "--jvm-default-resolve=jvm-default",
            "--scala-version-for-resolve={'jvm-default': '2.13.8'}",
            "run",
            f"{tmpdir}/src/org/pantsbuild/test/Hello.scala",
        ]
        result = run_pants(args)
        assert result.stdout.strip() == "Hello, World!"


def test_jvm_artifact(antlr_jvm_lockfile: JVMLockfileFixture) -> None:
    sources = {
        "BUILD": antlr_jvm_lockfile.requirements_as_jvm_artifact_targets(),
        "lockfile": antlr_jvm_lockfile.serialized_lockfile.replace("{", "{{").replace("}", "}}"),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.experimental.java",
            f'--jvm-resolves={{"jvm-default": "{tmpdir}/lockfile"}}',
            "--jvm-default-resolve=jvm-default",
            "run",
            f"{tmpdir}:org.antlr_antlr4",
        ]
        result = run_pants(args)
        assert result.stdout.splitlines()[0].strip() == "ANTLR Parser Generator  Version 4.11.1"
