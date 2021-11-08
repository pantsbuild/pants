# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from itertools import groupby
from pathlib import Path
from typing import Iterable, Mapping

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.macros.caof_utils import (
    OVERRIDES_TYPE,
    flatten_overrides_to_dependency_field,
)
from pants.backend.python.target_types import normalize_module_mapping, parse_requirements_file
from pants.base.build_environment import get_buildroot


class PythonRequirementsCAOF:
    """Translates a pip requirements file into an equivalent set of `python_requirement` targets.

    If the `requirements.txt` file has lines `foo>=3.14` and `bar>=2.7`,
    then this will translate to:

      python_requirement(
        name="foo",
        requirements=["foo>=3.14"],
      )

      python_requirement(
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
        *,
        source: str = "requirements.txt",
        module_mapping: Mapping[str, Iterable[str]] | None = None,
        type_stubs_module_mapping: Mapping[str, Iterable[str]] | None = None,
        overrides: OVERRIDES_TYPE = None,
    ) -> None:
        """
        :param module_mapping: a mapping of requirement names to a list of the modules they provide.
            For example, `{"ansicolors": ["colors"]}`. Any unspecified requirements will use the
            requirement name as the default module, e.g. "Django" will default to
            `modules=["django"]`.
        """
        req_file_tgt = self._parse_context.create_object(
            "_python_requirements_file",
            name=source.replace(os.path.sep, "_"),
            sources=[source],
        )
        requirements_dep = f":{req_file_tgt.name}"

        normalized_module_mapping = normalize_module_mapping(module_mapping)
        normalized_type_stubs_module_mapping = normalize_module_mapping(type_stubs_module_mapping)

        req_file = Path(get_buildroot(), self._parse_context.rel_path, source)
        requirements = parse_requirements_file(
            req_file.read_text(), rel_path=str(req_file.relative_to(get_buildroot()))
        )

        dependencies_overrides = flatten_overrides_to_dependency_field(
            overrides, macro_name="python_requirements", build_file_dir=self._parse_context.rel_path
        )
        grouped_requirements = groupby(requirements, lambda parsed_req: parsed_req.project_name)

        for project_name, parsed_reqs_ in grouped_requirements:
            normalized_proj_name = canonicalize_project_name(project_name)
            self._parse_context.create_object(
                "python_requirement",
                name=project_name,
                requirements=list(parsed_reqs_),
                modules=normalized_module_mapping.get(normalized_proj_name),
                type_stub_modules=normalized_type_stubs_module_mapping.get(normalized_proj_name),
                dependencies=[
                    requirements_dep,
                    *dependencies_overrides.get(normalized_proj_name, []),
                ],
            )
