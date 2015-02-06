# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


# TOOD(Eric Ayers): There is no task or goal named 'jvm' as used in the config section where these parameters are located.
# We might need to rename these whem merging together the config and the new options system.
class JvmDebugConfig(object):
  """A utility class to consolodate fetching JVM flags needed for debugging from the configuration."""

  @staticmethod
  def debug_args(config):
    return config.getlist('jvm', 'debug_args', default=[
      '-Xdebug',
      '-Xrunjdwp:transport=dt_socket,server=y,suspend=y,address={debug_port}'
      .format(debug_port=JvmDebugConfig.debug_port(config)),
    ])

  @staticmethod
  def debug_port(config):
    return config.getint('jvm', 'debug_port', default=5005)
