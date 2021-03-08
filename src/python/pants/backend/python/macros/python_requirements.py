# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from pathlib import Path
from typing import Iterable, Mapping, Optional

from pants.backend.python.target_types import parse_requirements_file
from pants.base.build_environment import get_buildroot


class PythonRequirements:
    """Translates a pip requirements file into an equivalent set of `python_requirement_library`
    targets.

    If the `requirements.txt` file has lines `foo>=3.14` and `bar>=2.7`,
    then this will translate to:

      python_requirement_library(
        name="foo",
        requirements=["foo>=3.14"],
      )

      python_requirement_library(
        name="bar",
        requirements=["bar>=2.7"],
      )

    See the requirements file spec here:
    https://pip.pypa.io/en/latest/reference/pip_install.html#requirements-file-format

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
        requirements_relpath: str = "requirements.txt",
        *,
        module_mapping: Optional[Mapping[str, Iterable[str]]] = None,
    ) -> None:
        """
        :param requirements_relpath: The relpath from this BUILD file to the requirements file.
            Defaults to a `requirements.txt` file sibling to the BUILD file.
        :param module_mapping: a mapping of requirement names to a list of the modules they provide.
            For example, `{"ansicolors": ["colors"]}`. Any unspecified requirements will use the
            requirement name as the default module, e.g. "Django" will default to
            `modules=["django"]`.
        """
        req_file_tgt = self._parse_context.create_object(
            "_python_requirements_file",
            name=requirements_relpath.replace(os.path.sep, "_"),
            sources=[requirements_relpath],
        )
        requirements_dep = f":{req_file_tgt.name}"

        req_file = Path(get_buildroot(), self._parse_context.rel_path, requirements_relpath)
        requirements = parse_requirements_file(
            req_file.read_text(), rel_path=str(req_file.relative_to(get_buildroot()))
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
