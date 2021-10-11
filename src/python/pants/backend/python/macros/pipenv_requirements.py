# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

from packaging.utils import canonicalize_name as canonicalize_project_name
from pkg_resources import Requirement

from pants.backend.python.target_types import normalize_module_mapping
from pants.base.build_environment import get_buildroot
from pants.base.deprecated import warn_or_error


# TODO(#10655): add support for PEP 440 direct references (aka VCS style).
# TODO(#10655): differentiate between Pipfile vs. Pipfile.lock.
class PipenvRequirements:
    """Translates a Pipenv.lock file into an equivalent set `python_requirement` targets.

    You may also use the parameter `module_mapping` to teach Pants what modules each of your
    requirements provide. For any requirement unspecified, Pants will default to the name of the
    requirement. This setting is important for Pants to know how to convert your import
    statements back into your dependencies. For example:

        pipenv_requirements(
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
        requirements_relpath: str | None = None,
        *,
        source: str | None = None,
        module_mapping: Mapping[str, Iterable[str]] | None = None,
        type_stubs_module_mapping: Mapping[str, Iterable[str]] | None = None,
        pipfile_target: str | None = None,
    ) -> None:
        """
        :param requirements_relpath: The relpath from this BUILD file to the requirements file.
            Defaults to a `Pipfile.lock` file sibling to the BUILD file.
        :param module_mapping: a mapping of requirement names to a list of the modules they provide.
            For example, `{"ansicolors": ["colors"]}`. Any unspecified requirements will use the
            requirement name as the default module, e.g. "Django" will default to
            `modules=["django"]`.
        :param pipfile_target: a `_python_requirements_file` target to provide for cache invalidation
        if the requirements_relpath value is not in the current rel_path
        """
        if requirements_relpath and source:
            raise ValueError(
                "Specified both `requirements_relpath` and `source` in the `pipenv_requirements` "
                f"macro in the BUILD file at {self._parse_context.rel_path}. Use one, preferably "
                "`source`."
            )
        if requirements_relpath is not None:
            warn_or_error(
                "2.9.0.dev0",
                "the `requirements_relpath` argument for `pipenv_requirements()`",
                (
                    "Use the `source` argument instead of `requirements_relpath` for the "
                    f"`pipenv_requirements` macro in the BUILD file at "
                    f"{self._parse_context.rel_path}. `source` behaves the same."
                ),
            )
            source = requirements_relpath
        if source is None:
            source = "Pipfile.lock"

        requirements_path = Path(get_buildroot(), self._parse_context.rel_path, source)
        lock_info = json.loads(requirements_path.read_text())

        if pipfile_target:
            requirements_dep = pipfile_target
        else:
            requirements_file_target_name = source
            self._parse_context.create_object(
                "_python_requirements_file",
                name=requirements_file_target_name,
                sources=[source],
            )
            requirements_dep = f":{requirements_file_target_name}"

        normalized_module_mapping = normalize_module_mapping(module_mapping)
        normalized_type_stubs_module_mapping = normalize_module_mapping(type_stubs_module_mapping)

        requirements = {**lock_info.get("default", {}), **lock_info.get("develop", {})}
        for req, info in requirements.items():
            extras = [x for x in info.get("extras", [])]
            extras_str = f"[{','.join(extras)}]" if extras else ""
            req_str = f"{req}{extras_str}{info.get('version','')}"
            if info.get("markers"):
                req_str += f";{info['markers']}"

            parsed_req = Requirement.parse(req_str)
            normalized_proj_name = canonicalize_project_name(parsed_req.project_name)
            self._parse_context.create_object(
                "python_requirement",
                name=parsed_req.project_name,
                requirements=[parsed_req],
                dependencies=[requirements_dep],
                modules=normalized_module_mapping.get(normalized_proj_name),
                type_stub_modules=normalized_type_stubs_module_mapping.get(normalized_proj_name),
            )
