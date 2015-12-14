# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'build_environment',
  sources = ['build_environment.py'],
  dependencies = [
    'src/python/pants:version',
    'src/python/pants/scm:all',
    ':build_root',
  ]
)

python_library(
  name = 'build_file',
  sources = ['build_file.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name = 'scm_build_file',
  sources = ['scm_build_file.py'],
  dependencies = [
    ':build_file',
  ]
)

python_library(
  name = 'build_file_target_factory',
  sources = ['build_file_target_factory.py'],
  dependencies = [
    'src/python/pants/util:meta',
  ]
)

python_library(
  name = 'build_manual',
  sources = ['build_manual.py'],
)

python_library(
  name = 'build_root',
  sources = ['build_root.py'],
  dependencies = [
    'src/python/pants/util:meta',
  ],
)

python_library(
  name = 'deprecated',
  sources = ['deprecated.py'],
  dependencies = [
    '3rdparty/python:six',
    ':revision',
    'src/python/pants:version',
  ]
)

python_library(
  name = 'exceptions',
  sources = ['exceptions.py'],
)

python_library(
  name = 'fingerprint_strategy',
  sources = ['fingerprint_strategy.py'],
  dependencies = [
    'src/python/pants/util:meta',
  ]
)

python_library(
  name = 'generator',
  sources = ['generator.py'],
  dependencies = [
    ':mustache',
    '3rdparty/python:pystache',
  ]
)

python_library(
  name = 'hash_utils',
  sources = ['hash_utils.py'],
)

python_library(
  name = 'mustache',
  sources = ['mustache.py'],
  dependencies = [
    '3rdparty/python:pystache',
    '3rdparty/python:six',
  ]
)

python_library(
  name = 'parse_context',
  sources = ['parse_context.py'],
)

python_library(
  name = 'payload',
  sources = ['payload.py'],
)

python_library(
  name = 'payload_field',
  sources = ['payload_field.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':build_environment',
    ':validation',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name = 'revision',
  sources = ['revision.py'],
)

python_library(
  name = 'run_info',
  sources = ['run_info.py'],
  dependencies = [
    ':build_environment',
    'src/python/pants/util:dirutil',
    'src/python/pants:version',
  ],
)

python_library(
  name = 'cmd_line_spec_parser',
  sources = ['cmd_line_spec_parser.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':build_file',
    'src/python/pants/build_graph',
  ],
)

python_library(
  name = 'source_root',
  sources = ['source_root.py'],
  dependencies = [
    ':build_environment',
    ':build_file_target_factory',
    ':build_manual',
    ':deprecated',
    ':exceptions',
    ':parse_context',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    # TEMPORARY dep during migration to new source roots mechanism.
    # I've verified that this does not introduce a circular dep.
    'src/python/pants/source',
  ],
)

python_library(
  name = 'worker_pool',
  sources = ['worker_pool.py'],
  dependencies = [
    'src/python/pants/reporting:report', # TODO(pl): Bust this out
  ],
)

python_library(
  name = 'workunit',
  sources = ['workunit.py'],
  dependencies = [
    '3rdparty/python:six',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:rwbuf',
  ],
)

python_library(
  name='validation',
  sources=['validation.py'],
  dependencies=[
    '3rdparty/python:six',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/backend/core:wrapped_globs',
  ],
)
