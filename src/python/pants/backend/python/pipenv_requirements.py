# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from json import load
from typing import Iterable, Mapping, Optional

from pkg_resources import Requirement


class PipenvRequirements:
    """Translates a Pipenv.lock file into an equivalent set `python_requirement_library` targets.

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
        requirements_relpath: str = "Pipfile.lock",
        module_mapping: Optional[Mapping[str, Iterable[str]]] = None,
        pipfile_target: Optional[str] = None,
    ) -> None:
        """
        :param requirements_relpath: The relpath from this BUILD file to the requirements file.
            Defaults to a `requirements.txt` file sibling to the BUILD file.
        :param module_mapping: a mapping of requirement names to a list of the modules they provide.
            For example, `{"ansicolors": ["colors"]}`. Any unspecified requirements will use the
            requirement name as the default module, e.g. "Django" will default to
            `modules=["django"]`.
        :param pipfile_target: a `_python_requirements_file` target to provide for cache invalidation
        if the requirements_relpath value is not in the current rel_path
        """

        repository = None
        lock_info = {}

        requirements_path = os.path.join(self._parse_context.rel_path, requirements_relpath)
        with open(requirements_path, "r") as fp:
            lock_info = load(fp)
            repos = lock_info.get("_meta", {}).get("sources", [])
            if len(repos) > 1:
                raise ValueError("Only one repository source is supported")

            repository = repos[0] if len(repos) == 1 else None

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
            req_str = f"{req}{info.get('version','')}"
            if info.get("markers"):
                req_str += f";{info['markers']}"

            parsed_req = Requirement.parse(req_str)

            index = info.get("index")
            if isinstance(index, dict):
                repo_url = index["url"]
            elif index:
                repo_url = repository.get("url") if repository.get("name") == index else index
            else:
                repo_url = repository.get("url")

            python_req_object = self._parse_context.create_object(
                "python_requirement",
                parsed_req,
                repository=repo_url,
                modules=module_mapping.get(parsed_req.project_name) if module_mapping else None,
            )

            self._parse_context.create_object(
                "python_requirement_library",
                name=parsed_req.project_name,
                requirements=[python_req_object],
                dependencies=[requirements_dep],
            )
