# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os


def python_requirements(parse_context, requirements_relpath='requirements.txt'):
  """Translates a pip requirements file into an equivalent set of PythonRequirement targets.

  NB that there are some requirements files that can't be unambiguously translated; ie: multiple
  find links.  For these files a ValueError will be raised that points out the issue.

  See the requirements file spec here: http://www.pip-installer.org/en/1.1/requirements.html

  :param string requirements_relpath: The relative path from the parent dir of the BUILD file using
      this function to the requirements file.  By default a `requirements.txt` file sibling to the
      BUILD file is assumed.
  """
  requirements = []
  repository = None

  requirements_path = os.path.join(parse_context.rel_path, requirements_relpath)
  with open(requirements_path) as fp:
    for line in fp:
      line = line.strip()
      if line and not line.startswith('#'):
        if not line.startswith('-'):
          requirements.append(line)
        else:
          # handle flags we know about
          flag_value = line.split(' ', 1)
          if len(flag_value) == 2:
            flag = flag_value[0].strip()
            value = flag_value[1].strip()
            if flag in ('-f', '--find-links'):
              if repository is not None:
                raise ValueError('Only 1 --find-links url is supported per requirements file')
              repository = value

  for requirement in requirements:
    req = parse_context.create_object('python_requirement', requirement, repository=repository)
    parse_context.create_object('python_requirement_library',
                                name=req.project_name,
                                requirements=[req])
