# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import sys

from colors import cyan, green

from pants.base.config import Config
from pants.option import custom_types
from pants.option.errors import ParseError


migrations = {
  ('java-compile', 'partition_size_hint'): ('compile.java', 'partition_size_hint'),
  ('java-compile', 'javac_args'): ('compile.java', 'args'),
  ('java-compile', 'warning_args'): ('compile.java', 'warning_args'),
  ('java-compile', 'no_warning_args'): ('compile.java', 'no_warning_args'),

  ('javadoc-gen', 'include_codegen'): ('gen.javadoc', 'include_codegen'),
  ('scaladoc-gen', 'include_codegen'): ('gen.scaladoc', 'include_codegen'),

  ('nailgun', 'autokill'): ('DEFAULT', 'kill_nailguns'),

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

  ('checkstyle', 'bootstrap-tools'): ('compile.checkstyle', 'bootstrap_tools'),
  ('checkstyle', 'configuration'): ('compile.checkstyle', 'configuration'),
  ('checkstyle', 'properties'): ('compile.checkstyle', 'properties'),

  ('scala-compile', 'scalac-plugins'): ('compile.scala', 'plugins'),
  ('scala-compile', 'scalac-plugin-args'): ('compile.scala', 'plugin_args'),

  ('markdown-to-html', 'extensions'): ('markdown', 'extensions'),
  ('markdown-to-html', 'code-style'): ('markdown', 'code_style'),

  # Note: This assumes that ConfluencePublish is registered as the only task in a
  #       goal called 'confluence'.  Adjust if this is not the case in your pants.ini.
  ('confluence-publish', 'url'): ('confluence', 'url'),
}

notes = {
  ('java-compile', 'javac_args'): 'source and target args should be moved to separate source: and '
                                  'target: options. Other args should be placed in args: and '
                                  'prefixed with -C.',
}


def check_config_file(path):
  config = Config.load(configpaths=[path])

  print('Checking config file at {0} for unmigrated keys.'.format(path), file=sys.stderr)
  def section(s):
    return cyan('[{0}]'.format(s))

  cp = config.configparser

  for (src_section, src_key), (dst_section, dst_key) in migrations.items():
    def has_non_default_option(section, key):
      return cp.has_option(section, key) and cp.get(section, key) != cp.defaults().get(key, None)

    if config.has_section(src_section) and has_non_default_option(src_section, src_key):
      print('Found {src_key} in section {src_section}. Should be {dst_key} in section '
            '{dst_section}.'.format(src_key=green(src_key), src_section=section(src_section),
                                    dst_key=green(dst_key), dst_section=section(dst_section)),
                                    file=sys.stderr)
      if (src_section, src_key) in notes:
        print('  Note: {0}'.format(notes[(src_section, src_key)]))

  # Check that all values are parseable.
  for sec in ['DEFAULT'] + cp.sections():
    for key, value in cp.items(sec):
      value = value.strip()
      if value.startswith('['):
        try:
          custom_types.list_type(value)
        except ParseError:
          print('Value of {key} in section {section} is not a valid '
                'JSON list.'.format(key=green(key), section=section(sec)))
      elif value.startswith('{'):
        try:
          custom_types.dict_type(value)
        except ParseError:
          print('Value of {key} in section {section} is not a valid '
                'JSON object.'.format(key=green(key), section=section(sec)))


if __name__ == '__main__':
  if len(sys.argv) > 2:
    print('Usage: migrate_config.py [path to pants.ini file]', file=sys.stderr)
    sys.exit(1)
  elif len(sys.argv) > 1:
    path = sys.argv[1]
  else:
    path = './pants.ini'
  check_config_file(path)
