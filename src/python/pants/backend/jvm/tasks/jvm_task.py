# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.task import Task
from pants.option.options import Options
from pants.util.strutil import safe_shlex_split


class JvmTask(Task):

  @classmethod
  def _legacy_dest_prefix(cls):
    return cls.options_scope.replace('.', '_')

  @classmethod
  def register_options(cls, register):
    super(JvmTask, cls).register_options(register)
    register('--jvm-options', action='append', metavar='<option>...',
             help='Run the JVM with these extra jvm options.')
    register('--args', action='append', metavar='<arg>...',
             help='Run the JVM with these extra program args.')
    register('--debug', action='store_true',
             help='Run the JVM with remote debugging.')
    register('--debug-port', advanced=True, type=int, default=5005,
             help='The JVM will listen for a debugger on this port.')
    register('--debug-args', advanced=True, type=Options.list,
             default=[
               '-Xdebug',
               '-Xrunjdwp:transport=dt_socket,server=y,suspend=y,address={debug_port}'
             ],
             help='The JVM remote-debugging arguments. {debug_port} will be replaced with '
                  'the value of the --debug-port option.')
    register('--confs', action='append', default=['default'],
             help='Use only these Ivy configurations of external deps.')

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('compile_classpath')

  def __init__(self, *args, **kwargs):
    super(JvmTask, self).__init__(*args, **kwargs)

    self.jvm_options = []
    for jvm_option in self.get_options().jvm_options:
      self.jvm_options.extend(safe_shlex_split(jvm_option))

    if self.get_options().debug:
      debug_port = self.get_options().debug_port
      self.jvm_options.extend(
        [arg.format(debug_port=debug_port) for arg in self.get_options().debug_args])

    self.args = []
    for arg in self.get_options().args:
      self.args.extend(safe_shlex_split(arg))

    self.confs = self.get_options().confs

  def classpath(self, targets, cp=None):
    classpath = list(cp) if cp else []
    compile_classpaths = self.context.products.get_data('compile_classpath')
    compile_classpath = compile_classpaths.get_for_targets(targets)

    def conf_needed(conf):
      return not self.confs or conf in self.confs

    classpath.extend(path for conf, path in compile_classpath if conf_needed(conf))
    return classpath
