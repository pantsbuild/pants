# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='fetchers',
  sources=['archive_retriever.py', 'fetcher.py', 'fetcher_factory.py',
           'go_import_meta_tag_reader.py', 'imported_repo.py'],
  dependencies=[
    '3rdparty/python:requests',
    '3rdparty/python:six',
    'contrib/go/src/python/pants/contrib/go/targets:go_remote_library',
    'src/python/pants/fs',
    'src/python/pants/option',
    'src/python/pants/scm:git',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
  ],
)

python_library(
  name='go_distribution',
  sources=['go_distribution.py'],
  dependencies=[
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/fs',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
  ],
)
