# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from pathlib import Path
from typing import Iterable, Mapping, Optional

from pants.backend.python.macros.poetry_project import parse_pyproject_toml

# from pants.backend.python.target_types import parse_requirements_file
from pants.base.build_environment import get_buildroot


class PoetryRequirements:
    """Translates dependencies specified in a  pyproject.toml Poetry file to a set of
    "python_requirements_library" targets.

    For example, if pyproject.toml contains the following entries under
    poetry.tool.dependencies: `foo = ">1"` and `bar = ">2.4"`,

    python_requirement_library(
        name="foo",
        requirements=["foo>1"],
      )

      python_requirement_library(
        name="bar",
        requirements=["bar>2.4"],
      )

    See Poetry documentation for correct specification of pyproject.toml:
    https://python-poetry.org/docs/pyproject/

    You may also use the parameter `module_mapping` to teach Pants what modules each of your
    requirements provide. For any requirement unspecified, Pants will default to the name of the
    requirement. This setting is important for Pants to know how to convert your import
    statements back into your dependencies. For example:

        python_requirements(
          module_mapping={
            "ansicolors": ["colors"],
            "setuptools": ["pkg_resources"],
          }
        )
    """

    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(
        self,
        pyproject_toml_relpath: str = "pyproject.toml",
        *,
        module_mapping: Optional[Mapping[str, Iterable[str]]] = None,
    ) -> None:
        """
        :param pyproject_toml_relpath: The relpath from this BUILD file to the requirements file.
            Defaults to a `requirements.txt` file sibling to the BUILD file.
        :param module_mapping: a mapping of requirement names to a list of the modules they provide.
            For example, `{"ansicolors": ["colors"]}`. Any unspecified requirements will use the
            requirement name as the default module, e.g. "Django" will default to
            `modules=["django"]`.
        """
        req_file_tgt = self._parse_context.create_object(
            "_python_requirements_file",
            name=pyproject_toml_relpath.replace(os.path.sep, "_"),
            sources=[pyproject_toml_relpath],
        )
        requirements_dep = f":{req_file_tgt.name}"

        req_file = Path(get_buildroot(), self._parse_context.rel_path, pyproject_toml_relpath)
        requirements = parse_pyproject_toml(
            req_file.read_text(), str(req_file.relative_to(get_buildroot()))
        )
        for parsed_req in requirements:
            req_module_mapping = (
                {parsed_req.project_name: module_mapping[parsed_req.project_name]}
                if module_mapping and parsed_req.project_name in module_mapping
                else None
            )
            self._parse_context.create_object(
                "python_requirement_library",
                name=parsed_req.project_name,
                requirements=[parsed_req],
                module_mapping=req_module_mapping,
                dependencies=[requirements_dep],
            )
