# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'build_environment',
  sources = ['build_environment.py'],
  dependencies = [
    ':build_root',
    'src/python/pants/scm',
    'src/python/pants/scm:git',
    'src/python/pants:version',
  ]
)

python_library(
  name = 'project_tree',
  sources = ['file_system_project_tree.py', 'project_tree.py', 'project_tree_factory.py'],
  dependencies = [
    '3rdparty/python:pathspec',
    ':build_environment',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:objects',
  ]
)

python_library(
  name = 'build_file',
  sources = ['build_file.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:pathspec',
    'src/python/pants/util:dirutil',
    ':project_tree',
  ]
)

python_library(
  name = 'build_file_target_factory',
  sources = ['build_file_target_factory.py'],
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
    ':revision',
    'src/python/pants:version',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name = 'exception_sink',
  sources = ['exception_sink.py'],
  dependencies = [
    '3rdparty/python:setproctitle',
    'src/python/pants/util:dirutil',
    ':build_environment',
    ':exiter',
  ],
)

python_library(
  name = 'exceptions',
  sources = ['exceptions.py'],
  dependencies = [
    ':exiter',
  ],
)

python_library(
  name = 'fingerprint_strategy',
  sources = ['fingerprint_strategy.py'],
  dependencies = [
    ':deprecated',
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
  dependencies = [
    '3rdparty/python:typing-extensions',
    ':deprecated',
    'src/python/pants/util:objects',
  ]
)

python_library(
  name = 'mustache',
  sources = ['mustache.py'],
  dependencies = [
    '3rdparty/python:pystache',
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
    ':deprecated',
    ':hash_utils',
  ]
)

python_library(
  name = 'specs',
  sources = ['specs.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/util:collections',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:filtering',
    'src/python/pants/util:memo',
    'src/python/pants/util:objects',
  ],
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
    ':specs',
    'src/python/pants/build_graph',
  ],
)

python_library(
  name = 'target_roots',
  sources = ['target_roots.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
  ],
)

python_library(
  name = 'worker_pool',
  sources = ['worker_pool.py'],
  dependencies = [
    ':workunit',
    'src/python/pants/reporting:report', # TODO(pl): Bust this out
  ],
)

python_library(
  name = 'workunit',
  sources = ['workunit.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:rwbuf',
  ],
)

python_library(
  name='validation',
  sources=['validation.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
  ],
)

python_library(
  name='exiter',
  sources=['exiter.py'],
  dependencies=[
    'src/python/pants/util:fileutil',
    'src/python/pants/util:strutil',
  ]
)

python_tests(
  name='tests',
  dependencies=[
    ':specs'
  ]
)
