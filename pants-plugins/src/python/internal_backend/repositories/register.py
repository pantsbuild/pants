# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.ossrh_publication_metadata import (Developer, License,
                                                          OSSRHPublicationMetadata, Scm)
from pants.backend.jvm.repository import Repository
from pants.base.build_manual import manual
from pants.build_graph.build_file_aliases import BuildFileAliases


public_repo = Repository(name='public',
                         url='https://oss.sonatype.org/#stagingRepositories',
                         push_db_basedir=os.path.join('build-support', 'ivy', 'pushdb'))

testing_repo = Repository(name='testing',
                          url='https://dl.bintray.com/pantsbuild/maven',
                          push_db_basedir=os.path.join('testprojects', 'ivy', 'pushdb'))


def org_pantsbuild_publication_metadata(description):
  return OSSRHPublicationMetadata(
    description=description,
    url='http://pantsbuild.github.io/',
    licenses=[
      License(
        name='Apache License, Version 2.0',
        url='http://www.apache.org/licenses/LICENSE-2.0'
      )
    ],
    developers=[
      Developer(
        name='The pants developers',
        email='pants-devel@googlegroups.com',
        url='https://github.com/pantsbuild/pants'
      )
    ],
    scm=Scm.github(
      user='pantsbuild',
      repo='pants'
    )
  )


# Your repositories don't need this manual.builddict magic.
# It keeps these examples out of http://pantsbuild.github.io/build_dictionary.html
manual.builddict(suppress=True)(public_repo)
manual.builddict(suppress=True)(testing_repo)


def build_file_aliases():
  return BuildFileAliases(
    objects={
      'public': public_repo,  # key 'public' must match name='public' above
      'testing': testing_repo,
      'pants_library': org_pantsbuild_publication_metadata
    },
  )
