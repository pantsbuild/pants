# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import textwrap
from dataclasses import dataclass
from typing import Optional, Sequence

from pants.engine.console import Console
from pants.engine.fs import Digest, FileContent, FilesContent, PathGlobs, Snapshot
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.option.global_options import GlobalOptions
from pants.source.source_root import NoSourceRootError, SourceRootConfig, SourceRoots


class BackendsOptions(LineOriented, GoalSubsystem):
    """List all the discoverable backends that you can register, e.g. `pants.backend.python`."""

    name = "backends"


class Backends(Goal):
    subsystem_cls = BackendsOptions


def hackily_get_module_docstring(content: str) -> Optional[str]:
    """Try to get module docstring by looking for \"\"\" with no left indentation.

    We cannot use a more robust mechanism like calling module.__doc__ because we do not want to call
    import() or eval() on the file to convert the raw content into Python symbols.
    """
    lines = content.splitlines()
    module_docstring_start = next(
        (i for i, line in enumerate(lines) if line.startswith('"""')), None
    )
    if module_docstring_start is None:
        return None
    if lines[module_docstring_start].rstrip().endswith('"""'):
        return lines[module_docstring_start].strip().replace('"""', "")
    module_docstring_end_offset = next(
        (
            i
            for i, line in enumerate(lines[module_docstring_start:])
            if line.rstrip().endswith('"""')
        ),
        None,
    )
    if module_docstring_end_offset is None:
        return None
    return (
        " ".join(
            line.strip()
            for line in lines[
                module_docstring_start : module_docstring_start + module_docstring_end_offset + 1
            ]
            if line.strip()
        )
        .replace('"""', "")
        .strip()
    )


@dataclass(frozen=True)
class BackendInfo:
    name: str
    description: Optional[str]
    is_v1: bool
    is_v2: bool
    is_v1_activated: bool
    is_v2_activated: bool

    @classmethod
    def create(
        cls, file_content: FileContent, source_roots: SourceRoots, global_options: GlobalOptions
    ) -> "BackendInfo":
        source_root = source_roots.safe_find_by_path(file_content.path)
        if source_root is None:
            raise NoSourceRootError(f"Could not find a source root for `{file_content.path}`.")
        stripped_path = file_content.path[len(source_root.path) + 1 :]
        module_name = os.path.dirname(stripped_path).replace(os.sep, ".")

        v1_entry_points = ("register_goals", "global_subsystems", "build_file_aliases")
        # NB: We intentionally do not check for `targets2` because even V1 is expected to have
        # Target API bindings.
        v2_entry_points = ("rules", "build_file_aliases2")

        def any_entry_points_registered(entry_points: Sequence[str]) -> bool:
            return any(
                f"def {entry_point}()" in file_content.content.decode()
                for entry_point in entry_points
            )

        activated_v1_backends = {
            "pants.build_graph",
            "pants.core_tasks",
            *global_options.options.backend_packages,
        }
        activated_v2_backends = {"pants.rules.core", *global_options.options.backend_packages2}

        return cls(
            name=module_name,
            description=hackily_get_module_docstring(file_content.content.decode()),
            is_v1=any_entry_points_registered(v1_entry_points),
            is_v2=any_entry_points_registered(v2_entry_points),
            is_v1_activated=module_name in activated_v1_backends,
            is_v2_activated=module_name in activated_v2_backends,
        )

    def format_for_cli(self, console: Console, *, longest_backend: int, is_v2: bool) -> str:
        chars_before_description = longest_backend + 3
        is_activated = self.is_v2_activated if is_v2 else self.is_v1_activated
        activated_icon = "*" if is_activated else " "
        name = console.cyan(f"{self.name}{activated_icon}".ljust(chars_before_description))
        if not self.description:
            description = "<no description>"
        else:
            description_lines = textwrap.wrap(
                self.description, 80 - chars_before_description, break_long_words=False
            )
            if len(description_lines) > 1:
                description_lines = [
                    description_lines[0],
                    *(f"{' ' * chars_before_description} {line}" for line in description_lines[1:]),
                ]
            description = "\n".join(description_lines)
        return f"{name} {description}\n"


def format_section(
    backends: Sequence[BackendInfo], console: Console, *, version_number: int, option_name: str
) -> str:
    longest_backend = max(len(backend.name) for backend in backends)
    title = f"V{version_number} backends"
    formatted_title = console.green(f"{title}\n{'-' * len(title)}")
    instructions = textwrap.dedent(
        f"""\
        To enable V{version_number} backends, add the backend to `{option_name}.add` in your
        `pants.toml`, like this:

            [GLOBAL]
            {option_name}.add = ["pants.backend.python"]

        In the below list, all activated backends end with `*`.\n
        """
    )
    lines = [
        f"\n{formatted_title}\n",
        instructions,
        *(
            backend.format_for_cli(
                console, longest_backend=longest_backend, is_v2=version_number == 2
            )
            for backend in sorted(backends, key=lambda backend: backend.name)
        ),
    ]
    return "\n".join(lines)


@goal_rule
async def list_backends(
    backend_options: BackendsOptions,
    source_roots_config: SourceRootConfig,
    global_options: GlobalOptions,
    console: Console,
) -> Backends:
    source_roots = source_roots_config.get_source_roots()
    discovered_register_pys = await Get[Snapshot](PathGlobs(["**/*/register.py"]))
    register_pys_content = await Get[FilesContent](Digest, discovered_register_pys.directory_digest)

    backend_infos = tuple(
        BackendInfo.create(fc, source_roots, global_options) for fc in register_pys_content
    )
    v1_backends = []
    v2_backends = []
    for backend in backend_infos:
        if backend.is_v1:
            v1_backends.append(backend)
        if backend.is_v2:
            v2_backends.append(backend)

    with backend_options.line_oriented(console) as print_stdout:
        if global_options.options.v1:
            print_stdout(
                format_section(
                    v1_backends, console, version_number=1, option_name="backend_packages"
                )
            )
        if global_options.options.v2:
            print_stdout(
                format_section(
                    v2_backends, console, version_number=2, option_name="backend_packages2"
                )
            )
    return Backends(exit_code=0)


def rules():
    return [list_backends]
