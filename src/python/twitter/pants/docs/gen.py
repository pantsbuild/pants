#!/usr/bin/env python2.7

import os
import os.path
import shutil

from string import Template


TEMPLATE = Template('\n'.join([
  ':mod:`$name` Module',
  '-----------------------------------------------',
  '',
  '.. automodule:: twitter.pants.$otype.$name',
  '   :members:',
  '', '',
]))

def gen_targets_reference(targets_rst, targets_dir):
  lines = [
    'Targets Reference',
    '=================',
    '',
    'This page documents targets available as part of the pants build system.',
    '', '',
  ]

  for filename in sorted([filename for filename in os.listdir(targets_dir) if filename.endswith('.py')]):
    if filename == '__init__.py':
      continue # Skip because renaming targets causes duplicates.
    root, _ = os.path.splitext(filename)
    lines.append(TEMPLATE.substitute(otype='targets', name=root))

  with open(targets_rst, 'w') as fh:
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
    fh.write('\n'.join(lines))

def main():
  docs_dir = os.path.dirname(os.path.abspath(__file__))
  pants_src_dir = os.path.dirname(docs_dir)
  tasks_dir = os.path.join(pants_src_dir, 'tasks')

  for filename in ['build_dictionary.rst', 'goals_reference.rst']:
    filepath = os.path.abspath(os.path.join(pants_src_dir,
        '../../../../dist/builddict', filename))
    try:
      shutil.copy(filepath, docs_dir)
    except IOError as e:
      raise IOError("Forgot to `./pants goal builddict` first? \n\n%s" % e)

  with open(os.path.join(docs_dir, 'tasks.rst'), 'w') as tasks_rst:
    tasks_rst.write('\n'.join([
      'Tasks Reference',
      '===============',
      '',
      'This page documents tasks available as part of the pants build system.',
      '', '',
    ]))
    for filename in sorted([filename for filename in os.listdir(tasks_dir) if filename.endswith('.py')]):
      root, _ = os.path.splitext(filename)
      tasks_rst.write(TEMPLATE.substitute(otype='tasks', name=root))

  targets_rst = os.path.join(docs_dir, 'targets.rst')
  gen_targets_reference(targets_rst, os.path.join(pants_src_dir, 'targets'))

  gen_base_reference(os.path.join(docs_dir, 'base.rst'), os.path.join(pants_src_dir, 'base'))

if __name__ == '__main__':
  main()
