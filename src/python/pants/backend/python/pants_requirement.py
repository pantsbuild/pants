# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.build_environment import pants_version
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.python.python_requirement import PythonRequirement
from pants.util.meta import classproperty


class PantsRequirement:
    """Exports a `python_requirement_library` pointing at the active pants' corresponding sdist.

    This requirement is useful for custom plugin authors who want to build and test their plugin with
    pants itself.  Using the resulting target as a dependency of their plugin target ensures the
    dependency stays true to the surrounding repo's version of pants.

    NB: The requirement generated is for official pants releases on pypi; so may not be appropriate
    for use in a repo that tracks `pantsbuild/pants` or otherwise uses custom pants sdists.

    :API: public
    """

    @classproperty
    def alias(self):
        return "pants_requirement"

    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(self, name=None, dist=None):
        """
        :param string name: The name to use for the target, defaults to the dist name if specified and
                            otherwise the parent dir name.
        :param string dist: The pants dist to create a requirement for. This must be a
                            'pantsbuild.pants*' distribution; eg:
                            'pantsbuild.pants.contrib.python.checks'.
        """
        name = name or dist or os.path.basename(self._parse_context.rel_path)
        dist = dist or "pantsbuild.pants"
        if not (dist == "pantsbuild.pants" or dist.startswith("pantsbuild.pants.")):
            target = Address(spec_path=self._parse_context.rel_path, target_name=name)
            raise TargetDefinitionException(
                target=target,
                msg="The {} target only works for pantsbuild.pants "
                "distributions, given {}".format(self.alias, dist),
            )

        requirement = PythonRequirement(
            requirement="{key}=={version}".format(key=dist, version=pants_version())
        )

        self._parse_context.create_object(
            "python_requirement_library", name=name, requirements=[requirement]
        )
