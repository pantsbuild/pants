# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.exceptions import TargetDefinitionException

class BuildTypeMixin(object):
  """Mixin class to validate and normalize build type input for keystores and android targets."""

  def get_build_type(self, build_type):
    if build_type is None:
      raise TargetDefinitionException(self, "Target must define a 'build_type' attribute as either "
                                            "debug or release")
    if build_type.lower() not in ('release', 'debug'):
      raise TargetDefinitionException(self, "The 'build_type' attribute must be 'debug' "
                                            "or 'release' instead of: {0}".format(build_type))
    return build_type