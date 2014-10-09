# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

class JvmDebugConfig(object):

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
