# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.jvm.repository import Repository
from pants.base.build_file_aliases import BuildFileAliases


public_repo = Repository(name = 'public',
                         url = 'http://maven.twttr.com',
                         push_db_basedir = os.path.join('build-support', 'ivy', 'pushdb'))

testing_repo = Repository(name = 'testing',
                          url = 'http://maven.twttr.com',
                          push_db_basedir = os.path.join('testprojects', 'ivy', 'pushdb'))


def build_file_aliases():
  return BuildFileAliases.create(
    objects={
      'public': public_repo,
      'testing': testing_repo,
    },
  )

