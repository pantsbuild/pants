# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.base.scm_project_tree import ScmProjectTree
from pants.util.memo import memoized


@memoized
def get_project_tree(options):
  """Creates the project tree for build files for use in a given pants run."""
  pants_ignore = options.pants_ignore or []
  if options.build_file_rev:
    return ScmProjectTree(get_buildroot(), get_scm(), options.build_file_rev, pants_ignore)
  else:
    return FileSystemProjectTree(get_buildroot(), pants_ignore)
