# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Iterable, Mapping, Optional

from pkg_resources import Requirement


class PythonRequirements:
    """Translates a pip requirements file into an equivalent set of `python_requirement_library`
    targets.

    If the `requirements.txt` file has lines `foo>=3.14` and `bar>=2.7`,
    then this will translate to:

      python_requirement_library(
        name="foo",
        requirements=[python_requirement("foo>=3.14")],
      )

      python_requirement_library(
        name="bar",
        requirements=[python_requirement("bar>=2.7")],
      )

    Note that some requirements files can't be unambiguously translated due to issues like multiple
    find links. For these files, a ValueError will be raised that points out the issue.

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

        requirements = []
        repository = None

        requirements_path = os.path.join(self._parse_context.rel_path, requirements_relpath)
        with open(requirements_path, "r") as fp:
            for line in fp:
                line = line.strip()
                if line and not line.startswith("#"):
                    if not line.startswith("-"):
                        requirements.append(line)
                    else:
                        # handle flags we know about
                        flag_value = line.split(" ", 1)
                        if len(flag_value) == 2:
                            flag = flag_value[0].strip()
                            value = flag_value[1].strip()
                            if flag in ("-f", "--find-links"):
                                if repository is not None:
                                    raise ValueError(
                                        "Only 1 --find-links url is supported per requirements file"
                                    )
                                repository = value

        requirements_file_target_name = requirements_relpath
        self._parse_context.create_object(
            "_python_requirements_file",
            name=requirements_file_target_name,
            sources=[requirements_relpath],
        )
        requirements_dep = f":{requirements_file_target_name}"

        for req_str in requirements:
            parsed_req = Requirement.parse(req_str)
            python_req_object = self._parse_context.create_object(
                "python_requirement",
                parsed_req,
                repository=repository,
                modules=module_mapping.get(parsed_req.project_name) if module_mapping else None,
            )
            self._parse_context.create_object(
                "python_requirement_library",
                name=parsed_req.project_name,
                requirements=[python_req_object],
                dependencies=[requirements_dep],
            )
