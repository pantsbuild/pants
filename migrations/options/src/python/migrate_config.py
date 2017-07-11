# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from colors import cyan, green, red, yellow

from pants.option import custom_types
from pants.option.config import Config
from pants.option.errors import ParseError


migrations = {
  # E.g.:
  #('backends', 'packages'): ('DEFAULT', 'backend_packages'),
  #('unknown-arguments', 'ignored'): None,

  ('gen', 'thrift'): ('gen', 'thrift-java'),
}


notes = {
  # E.g.:
  #('jvm', 'debug_port'): 'For now must be defined for each JvmTask subtask separately.  Will soon '
  #                       'move to a subsystem, which will fix this requirement.',
}


def check_option(cp, src, dst):
  def has_explicit_option(section, key):
    # David tried to avoid poking into cp's guts in https://rbcommons.com/s/twitter/r/1451/ but
    # that approach fails for the important case of boolean options.  Since this is a ~short term
    # tool and its highly likely its lifetime will be shorter than the time the private
    # ConfigParser_sections API we use here changes, it's worth the risk.
    if section == 'DEFAULT':
      # NB: The 'DEFAULT' section is not tracked via `has_section` or `_sections`, so we use a
      # different API to check for an explicit default.
      return key in cp.defaults()
    else:
      return cp.has_section(section) and (key in cp._sections[section])

  def sect(s):
    return cyan('[{}]'.format(s))

  src_section, src_key = src
  if has_explicit_option(src_section, src_key):
    if dst is not None:
      dst_section, dst_key = dst
      print('Found {src_key} in section {src_section}. Should be {dst_key} in section '
            '{dst_section}.'.format(src_key=green(src_key), src_section=sect(src_section),
                                    dst_key=green(dst_key), dst_section=sect(dst_section)),
            file=sys.stderr)
    elif src not in notes:
      print('Found {src_key} in section {src_section} and there is no automated migration path'
            'for this option.  Please consult the '
            'codebase.'.format(src_key=red(src_key), src_section=red(src_section)))

    if (src_section, src_key) in notes:
      print('  Note for {src_key} in section {src_section}: {note}'
            .format(src_key=green(src_key),
                    src_section=sect(src_section),
                    note=yellow(notes[(src_section, src_key)])))


def check_config_file(path):
  cp = Config._create_parser()
  with open(path, 'r') as ini:
    cp.readfp(ini)

  print('Checking config file at {} for unmigrated keys.'.format(path), file=sys.stderr)

  def section(s):
    return cyan('[{}]'.format(s))

  for src, dst in migrations.items():
    check_option(cp, src, dst)

  # Special-case handling of per-task subsystem options, so we can sweep them up in all
  # sections easily.

  def check_task_subsystem_options(subsystem_sec, options_map, sections=None):
    sections = sections or cp.sections()
    for src_sec in ['DEFAULT'] + sections:
      dst_sec = subsystem_sec if src_sec == 'DEFAULT' else '{}.{}'.format(subsystem_sec, src_sec)
      for src_key, dst_key in options_map.items():
        check_option(cp, (src_sec, src_key), (dst_sec, dst_key))

  artifact_cache_options_map = {
    'read_from_artifact_cache': 'read',
    'write_to_artifact_cache': 'write',
    'overwrite_cache_artifacts': 'overwrite',
    'read_artifact_caches': 'read_from',
    'write_artifact_caches': 'write_to',
    'cache_compression': 'compression_level',
  }
  check_task_subsystem_options('cache', artifact_cache_options_map)

  jvm_options_map = {
    'jvm_options': 'options',
    'args': 'program_args',
    'debug': 'debug',
    'debug_port': 'debug_port',
    'debug_args': 'debug_args',
  }
  jvm_options_sections = [
    'repl.scala', 'test.junit', 'run.jvm', 'bench', 'doc.javadoc', 'doc.scaladoc'
  ]
  check_task_subsystem_options('jvm', jvm_options_map, sections=jvm_options_sections)

  # Check that all values are parseable.
  for sec in ['DEFAULT'] + cp.sections():
    for key, value in cp.items(sec):
      value = value.strip()
      if value.startswith('['):
        try:
          custom_types.list_option(value)
        except ParseError:
          print('Value of {key} in section {section} is not a valid '
                'JSON list.'.format(key=green(key), section=section(sec)))
      elif value.startswith('{'):
        try:
          custom_types.dict_option(value)
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
