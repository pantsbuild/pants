# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os


class PythonRequirements(object):
  """Translates a pip requirements file into an equivalent set of python_requirements

  If the ``requirements.txt`` file has lines ``foo>=3.14`` and ``bar>=2.7``,
  then this is roughly like::

    python_requirement_library(name="foo", requirements=[
      python_requirement("foo>=3.14"),
    ])
    python_requirement_library(name="bar", requirements=[
      python_requirement("bar>=2.7"),
    ])

  NB some requirements files can't be unambiguously translated; ie: multiple
  find links.  For these files a ValueError will be raised that points out the issue.

  See the requirements file spec here:
  https://pip.pypa.io/en/latest/reference/pip_install.html#requirements-file-format
  """

  def __init__(self, parse_context):
    self._parse_context = parse_context

  def __call__(self, requirements_relpath='requirements.txt'):
    """
    :param string requirements_relpath: The relpath from this BUILD file to the requirements file.
    Defaults to a `requirements.txt` file sibling to the BUILD file.
    """

    requirements = []
    repository = None

    requirements_path = os.path.join(self._parse_context.rel_path, requirements_relpath)
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
      req = self._parse_context.create_object('python_requirement', requirement,
                                              repository=repository)
      self._parse_context.create_object('python_requirement_library',
                                        name=req.project_name,
                                        requirements=[req])
