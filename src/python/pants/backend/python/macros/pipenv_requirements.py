# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from pathlib import Path
from typing import Iterable, Mapping, Optional

from pkg_resources import Requirement

from pants.base.build_environment import get_buildroot


# TODO(#10655): add support for PEP 440 direct references (aka VCS style).
# TODO(#10655): differentiate between Pipfile vs. Pipfile.lock.
class PipenvRequirements:
    """Translates a Pipenv.lock file into an equivalent set `python_requirement_library` targets.

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
        requirements_relpath: str = "Pipfile.lock",
        module_mapping: Optional[Mapping[str, Iterable[str]]] = None,
        pipfile_target: Optional[str] = None,
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

        requirements_path = Path(
            get_buildroot(), self._parse_context.rel_path, requirements_relpath
        )
        lock_info = json.loads(requirements_path.read_text())

        if pipfile_target:
            requirements_dep = pipfile_target
        else:
            requirements_file_target_name = requirements_relpath
            self._parse_context.create_object(
                "_python_requirements_file",
                name=requirements_file_target_name,
                sources=[requirements_relpath],
            )
            requirements_dep = f":{requirements_file_target_name}"

        requirements = {**lock_info.get("default", {}), **lock_info.get("develop", {})}
        for req, info in requirements.items():
            extras = [x for x in info.get("extras", [])]
            extras_str = f"[{','.join(extras)}]" if extras else ""
            req_str = f"{req}{extras_str}{info.get('version','')}"
            if info.get("markers"):
                req_str += f";{info['markers']}"

            parsed_req = Requirement.parse(req_str)

            req_module_mapping = (
                {parsed_req.project_name: module_mapping[parsed_req.project_name]}
                if module_mapping and parsed_req.project_name in module_mapping
                else None
            )

            self._parse_context.create_object(
                "python_requirement_library",
                name=parsed_req.project_name,
                requirements=[parsed_req],
                dependencies=[requirements_dep],
                module_mapping=req_module_mapping,
            )
