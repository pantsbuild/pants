#!/usr/bin/env python
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import os.path
import shutil
from string import Template


TEMPLATE = Template('\n'.join([
  ':mod:`$name` Module',
  '-----------------------------------------------',
  '',
  '.. automodule:: pants.$otype.$name',
  '   :members:',
  '', '',
]))

def gen_targets_reference(targets_rst, targets_dir_list):
  lines = [
    'Targets Reference',
    '=================',
    '',
    'This page documents targets available as part of the pants build system.',
    '', '',
  ]

  for targets_dir in targets_dir_list:
    for filename in sorted([filename for filename in os.listdir(targets_dir) if filename.endswith('.py')]):
      if filename == '__init__.py':
        continue # Skip because renaming targets causes duplicates.
      root, _ = os.path.splitext(filename)
      lines.append(TEMPLATE.substitute(otype='targets', name=root))

  with open(targets_rst, 'w') as fh:
    print("Writing to file '%s'" % targets_rst)
    fh.write('\n'.join(lines))

def gen_base_reference(rst_filename, dirname):
  lines = [
    'Base Reference',
    '==============',
    '',
    'This page documents base classes of the pants build system.',
    '', '',
  ]

  for filename in sorted([filename for filename in os.listdir(dirname) if filename.endswith('.py')]):
    if filename == '__init__.py':
      continue # Skip because renaming targets causes duplicates.
    root, _ = os.path.splitext(filename)
    lines.append(TEMPLATE.substitute(otype='base', name=root))

  with open(rst_filename, 'w') as fh:
    print("Writing to file '%s'" % rst_filename)
    fh.write('\n'.join(lines))

def copy_builddict(docs_dir):
  for filename in ['build_dictionary.rst', 'goals_reference.rst', 'pants_ini_reference.rst']:
    filepath = os.path.abspath(os.path.join(docs_dir,
        '../../../../dist/builddict', filename))
    try:
      print("Copying '%s' to '%s'" % (filepath, docs_dir))
      shutil.copy(filepath, docs_dir)
    except IOError as e:
      raise IOError("Forgot to `./pants goal builddict` first? \n\n%s" % e)

def main():
  docs_dir = os.path.dirname(os.path.abspath(__file__))
  pants_src_dir = os.path.dirname(docs_dir)
  backends = ['codegen', 'core', 'jvm', 'python']
  tasks_dirs = [os.path.join(pants_src_dir, 'backend', b, 'tasks') for b in backends]

  copy_builddict(docs_dir)

  with open(os.path.join(docs_dir, 'tasks.rst'), 'w') as tasks_rst:
    tasks_rst.write('\n'.join([
      'Tasks Reference',
      '===============',
      '',
      'This page documents tasks available as part of the pants build system.',
      '', '',
    ]))
    for tasks_dir in tasks_dirs:
      for filename in sorted([filename for filename in os.listdir(tasks_dir) if filename.endswith('.py')]):
        root, _ = os.path.splitext(filename)
        tasks_rst.write(TEMPLATE.substitute(otype='tasks', name=root))

  targets_rst = os.path.join(docs_dir, 'targets.rst')
  targets_dirs = [os.path.join(pants_src_dir, 'backend', b, 'targets') for b in backends]
  gen_targets_reference(targets_rst, targets_dirs)

  gen_base_reference(os.path.join(docs_dir, 'base.rst'), os.path.join(pants_src_dir, 'base'))

if __name__ == '__main__':
  main()
