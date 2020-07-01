# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Optional

from pants.base.build_environment import pants_version
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.python.python_requirement import PythonRequirement
from pants.util.meta import classproperty


class PantsRequirement:
    """Exports a `python_requirement_library` pointing at the active Pants's corresponding sdist.

    This requirement is useful for custom plugin authors who want to build and test their plugin with
    Pants itself. Using the resulting target as a dependency of their plugin target ensures the
    dependency stays true to the surrounding repo's version of Pants.

    NB: The requirement generated is for official Pants releases on PyPI; so may not be appropriate
    for use in a repo that tracks `pantsbuild/pants` or otherwise uses custom pants sdists.

    :API: public
    """

    @classproperty
    def alias(self):
        return "pants_requirement"

    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(
        self, name: Optional[str] = None, dist: Optional[str] = None,
    ):
        """
        :param name: The name to use for the target, defaults to the dist name if specified and
                     otherwise the parent dir name.
        :param dist: The Pants dist to create a requirement for. This must be a 'pantsbuild.pants*'
                     distribution; eg: 'pantsbuild.pants.testutil'.
        """
        name = name or dist or os.path.basename(self._parse_context.rel_path)
        dist = dist or "pantsbuild.pants"
        if not (dist == "pantsbuild.pants" or dist.startswith("pantsbuild.pants.")):
            target = Address(spec_path=self._parse_context.rel_path, target_name=name)
            raise TargetDefinitionException(
                target=target,
                msg=(
                    f"The {self.alias} target only works for pantsbuild.pants distributions, but "
                    f"given {dist}"
                ),
            )

        module_name = dist.replace("pantsbuild.", "")
        requirement = PythonRequirement(
            requirement=f"{dist}=={pants_version()}", modules=[module_name]
        )
        self._parse_context.create_object(
            "python_requirement_library", name=name, requirements=[requirement]
        )
