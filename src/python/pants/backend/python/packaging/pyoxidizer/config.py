# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from string import Template
from textwrap import indent
from typing import Optional

DEFAULT_TEMPLATE = """
def make_exe():
    dist = default_python_distribution()
    policy = dist.make_python_packaging_policy()

    # Note: Adding this for pydanic and libs that have the "unable to load from memory" error
    # https://github.com/indygreg/PyOxidizer/issues/438
    policy.resources_location_fallback = "filesystem-relative:lib"

    python_config = dist.make_python_interpreter_config()
    $ENTRY_POINT

    exe = dist.to_python_executable(
        name="$NAME",
        packaging_policy=policy,
        config=python_config,
    )

    # pip_download requires that wheels are available for each dep
    # exe.add_python_resources(exe.pip_download($WHEELS))
    exe.add_python_resources(exe.pip_install($WHEELS))
    $UNCLASSIFIED_RESOURCE_INSTALLATION

    return exe

def make_embedded_resources(exe):
    return exe.to_embedded_resources()

def make_install(exe):
    # Create an object that represents our installed application file layout.
    files = FileManifest()
    # Add the generated executable to our install layout in the root directory.
    files.add_python_resource(".", exe)
    return files

register_target("exe", make_exe)
register_target("resources", make_embedded_resources, depends=["exe"], default_build_script=True)
register_target("install", make_install, depends=["exe"], default=True)
resolve_targets()
"""

UNCLASSIFIED_RESOURCES_TEMPLATE = """
for resource in exe.pip_install($UNCLASSIFIED_RESOURCES):
    resource.add_location = "filesystem-relative:lib"
    exe.add_python_resource(resource)
"""


class PyOxidizerConfig:
    def __init__(
        self,
        executable_name: str,
        wheels: list[str],
        entry_point: Optional[str] = None,
        template: Optional[str] = None,
        unclassified_resources: Optional[list[str]] = None,
    ):
        self.executable_name = executable_name
        self.wheels = wheels
        self.entry_point = (
            f"python_config.run_module = '{entry_point}'"
            if entry_point is not None
            else ""
        )
        self.template = template
        self.unclassified_resources = unclassified_resources

    def output(self) -> str:
        unclassified_resource_snippet = ""
        if self.unclassified_resources is not None:
            unclassified_resource_snippet = Template(
                UNCLASSIFIED_RESOURCES_TEMPLATE
            ).safe_substitute(UNCLASSIFIED_RESOURCES=self.unclassified_resources)

            unclassified_resource_snippet = indent(
                unclassified_resource_snippet, "    "
            )

        template = Template(self.template or DEFAULT_TEMPLATE)
        return template.safe_substitute(
            NAME=self.executable_name,
            WHEELS=self.wheels,
            ENTRY_POINT=self.entry_point,
            UNCLASSIFIED_RESOURCE_INSTALLATION=unclassified_resource_snippet,
        )
