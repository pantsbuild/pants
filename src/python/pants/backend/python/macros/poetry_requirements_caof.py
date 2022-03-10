# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable, Mapping

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.macros.caof_utils import (
    OVERRIDES_TYPE,
    flatten_overrides_to_dependency_field,
)
from pants.backend.python.macros.poetry_requirements import PyProjectToml, parse_pyproject_toml
from pants.backend.python.target_types import normalize_module_mapping
from pants.core.target_types import TargetGeneratorSourcesHelperTarget


class PoetryRequirementsCAOF:
    """Translates dependencies specified in a  pyproject.toml Poetry file to a set of
    "python_requirements_library" targets.

    For example, if pyproject.toml contains the following entries under
    poetry.tool.dependencies: `foo = ">1"` and `bar = ">2.4"`,

        python_requirement(
          name="foo",
          requirements=["foo>1"],
        )

        python_requirement(
          name="bar",
          requirements=["bar>2.4"],
        )

    See Poetry documentation for correct specification of pyproject.toml:
    https://python-poetry.org/docs/pyproject/

    You may also use the parameter `module_mapping` to teach Pants what modules each of your
    requirements provide. For any requirement unspecified, Pants will default to the name of the
    requirement. This setting is important for Pants to know how to convert your import
    statements back into your dependencies. For example:

        poetry_requirements(
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
        source: str = "pyproject.toml",
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
            TargetGeneratorSourcesHelperTarget.alias,
            name=source.replace(os.path.sep, "_"),
            sources=[source],
        )
        requirements_dep = f":{req_file_tgt.name}"

        normalized_module_mapping = normalize_module_mapping(module_mapping)
        normalized_type_stubs_module_mapping = normalize_module_mapping(type_stubs_module_mapping)

        dependencies_overrides = flatten_overrides_to_dependency_field(
            overrides, macro_name="python_requirements", build_file_dir=self._parse_context.rel_path
        )

        requirements = parse_pyproject_toml(
            PyProjectToml.deprecated_macro_create(self._parse_context, source)
        )
        for parsed_req in requirements:
            normalized_proj_name = canonicalize_project_name(parsed_req.project_name)
            self._parse_context.create_object(
                "python_requirement",
                name=parsed_req.project_name,
                requirements=[parsed_req],
                modules=normalized_module_mapping.get(normalized_proj_name),
                type_stub_modules=normalized_type_stubs_module_mapping.get(normalized_proj_name),
                dependencies=[
                    requirements_dep,
                    *dependencies_overrides.get(normalized_proj_name, []),
                ],
            )
