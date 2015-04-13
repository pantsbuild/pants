# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.repository import Repository
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.build_manual import manual


public_repo = Repository(name='public',
                         url='https://oss.sonatype.org/#stagingRepositories',
                         push_db_basedir=os.path.join('build-support', 'ivy', 'pushdb'))

testing_repo = Repository(name='testing',
                          url='https://dl.bintray.com/pantsbuild/maven',
                          push_db_basedir=os.path.join('testprojects', 'ivy', 'pushdb'))


# Your repositories don't need this manual.builddict magic.
# It keeps these examples out of http://pantsbuild.github.io/build_dictionary.html
manual.builddict(suppress=True)(public_repo)
manual.builddict(suppress=True)(testing_repo)


def build_file_aliases():
  return BuildFileAliases.create(
    objects={
      'public': public_repo,  # key 'public' must match name='public' above
      'testing': testing_repo,
    },
  )
