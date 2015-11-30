# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.build_environment import pants_version


def pants_requirement(parse_context, name=None):
  """Exports a `python_requirement_library` pointing at the active pants' corresponding sdist.

  This requirement is useful for custom plugin authors who want to build and test their plugin with
  pants itself.  Using the resulting target as a dependency of their plugin target ensures the
  dependency stays true to the surrounding repo's version of pants.

  NB: The requirement generated is for official pants releases on pypi; so may not be appropriate
  for use in a repo that tracks `pantsbuild/pants` or otherwise uses custom pants sdists.

  :param string name: The name to use for the target, defaults to the parent dir name.
  """
  name = name or os.path.basename(parse_context.rel_path)
  requirement = PythonRequirement(requirement='pantsbuild.pants=={}'.format(pants_version()))
  parse_context.create_object(PythonRequirementLibrary, name=name, requirements=[requirement])
