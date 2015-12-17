# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot, pants_version
from pants.base.source_root import SourceRoot
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.from_target import FromTarget
from pants.build_graph.prep_command import PrepCommand
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.source.wrapped_globs import Globs, RGlobs, ZGlobs


"""Register the elementary BUILD file constructs."""


class BuildFilePath(object):
  def __init__(self, parse_context):
    self.rel_path = parse_context.rel_path

  def __call__(self):
    """
    :returns: The absolute path of this BUILD file.
    """
    return os.path.join(get_buildroot(), self.rel_path)


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'prep_command': PrepCommand,
      'resources': Resources,
      'target': Target,
    },
    objects={
      'get_buildroot': get_buildroot,
      'pants_version': pants_version,
    },
    context_aware_object_factories={
      'buildfile_path': BuildFilePath,
      'globs': Globs.factory,
      'from_target': FromTarget,
      'rglobs': RGlobs.factory,
      'source_root': SourceRoot.factory,
      'zglobs': ZGlobs.factory,
    }
  )
