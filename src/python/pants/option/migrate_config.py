# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import sys

from colors import cyan, green

from pants.base.config import Config

migrations = {
  ('java-compile', 'partition_size_hint'): ('compile.java', 'partition_size_hint'),

  ('javadoc-gen', 'include_codegen'): ('gen.javadoc', 'include_codegen'),
  ('scaladoc-gen', 'include_codegen'): ('gen.scaladoc', 'include_codegen'),

  ('jvm-run', 'jvm_args'): ('run.jvm', 'jvm_options'),
  ('benchmark-run', 'jvm_args'): ('bench', 'jvm_options'),
  ('specs-run', 'jvm_args'): ('test.specs', 'jvm_options'),
  ('junit-run', 'jvm_args'): ('test.junit', 'jvm_options'),
  ('scala-repl', 'jvm_args'): ('repl.scala', 'jvm_options'),

  ('jvm-run', 'confs'): ('run.jvm', 'confs'),
  ('benchmark-run', 'confs'): ('bench', 'confs'),
  ('specs-run', 'confs'): ('test.specs', 'confs'),
  ('junit-run', 'confs'): ('test.junit', 'confs'),
  ('scala-repl', 'confs'): ('repl.scala', 'confs'),

  ('scala-repl', 'args'): ('repl.scala', 'args'),

  ('scala-compile', 'scalac-plugins'): ('compile.scala', 'plugins'),
  ('scala-compile', 'scalac-plugin-args'): ('compile.scala', 'plugin-args'),
}


def check_config_file(path):
  config = Config.load(configpath=path)

  print('Checking config file at {0} for unmigrated keys.'.format(path), file=sys.stderr)
  def section(s):
    return cyan('[{0}]'.format(s))

  for (src_section, src_key), (dst_section, dst_key) in migrations.items():
    if config.has_section(src_section) and config.has_option(src_section, src_key):
      print('Found {src_key} in section {src_section}. Should be {dst_key} in section '
            '{dst_section}.'.format(src_key=green(src_key), src_section=section(src_section),
                                    dst_key=green(dst_key), dst_section=section(dst_section)),
                                    file=sys.stderr)


if __name__ == '__main__':
  if len(sys.argv) > 2:
    print('Usage: migrate_config.py [path to pants.ini file]', file=sys.stderr)
    sys.exit(1)
  elif len(sys.argv) > 1:
    path = sys.argv[1]
  else:
    path = './pants.ini'
  check_config_file(path)
