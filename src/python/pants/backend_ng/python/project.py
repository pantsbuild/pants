# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import tomllib
from pants.engine.intrinsics import get_file_contents
from pants.engine.rules import collect_rules, rule
from pants.ng.subsystem import ContextualSubsystem, option
from pants.util.strutil import softwrap


class PythonProject(ContextualSubsystem):
    options_scope = "python-project"
    help = "Options for setting up a Python project."

    interpreter_version_help = softwrap(
        """
        The constaints on the interpreter to use, e.g., `==3.12.7`.

        Can also be @path/to/pyproject.toml (or any name ending in .toml), which will use
        the value of `project.required-python` in the given .toml file.
        """
    )

    # Don't call directly - use `await get_interpreter_version()`.
    @option(required=True, help=interpreter_version_help)
    def interpreter_version(self) -> str: ...

    requirements_help = softwrap(
        """
        3rd-party requirements. Each value can have one of the following formats:
        - A requirement string.
        - `@path/to/requirements.txt` (or any name ending in .txt)
        - `@path/to/pyproject.toml` (or any name ending in .toml)
           - will take the contents of the `project.dependencies` list
        - `@path/to/pyproject.toml:dependencies.list.location` (or any name ending in .toml)
        """
    )
    @option(help=requirements_help)
    def requirements(self) -> tuple[str, ...]: ...

    @option(default="pyproject.toml", help="Path to project file")
    def project(self) -> str: ...

    @option(default="uv.lock", help="Path to the lockfile, relative to the build root")
    def lockfile(self) -> str: ...


@rule
async def get_interpreter_version(project: PythonProject) -> str:
    version = project.interpreter_version()
    if version.startswith("@") and version.endswith(".toml"):
        pyproject_toml_path = version[1:]
        contents = (await get_file_contents(pyproject_toml_path)).decode()
        toml = tomllib.loads(contents)
        version = toml.get("project", {}).get("requires-python")
        if not version:
            raise Exception(f"No [project].requires-python value found in {pyproject_toml_path}")
    return version


def rules():
    return [*collect_rules()]
