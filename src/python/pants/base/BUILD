# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'build_environment',
  sources = ['build_environment.py'],
  dependencies = [
    ':build_root',
    'src/python/pants/scm',
    'src/python/pants:version',
  ],
)

python_library(
  name = 'project_tree',
  sources = ['file_system_project_tree.py', 'project_tree.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    '3rdparty/python:pathspec',
    ':build_environment',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
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
  ],
)

python_library(
  name = 'exception_sink',
  sources = ['exception_sink.py'],
  dependencies = [
    '3rdparty/python:setproctitle',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:osutil',
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
)

python_library(
  name = 'generator',
  sources = ['generator.py'],
  dependencies = [
    ':mustache',
    '3rdparty/python:pystache',
  ],
)

python_library(
  name = 'hash_utils',
  sources = ['hash_utils.py'],
  dependencies = [
    '3rdparty/python:typing-extensions',
    'src/python/pants/util:strutil',
    'src/python/pants/util:ordered_set',
  ],
)

python_library(
  name = 'mustache',
  sources = ['mustache.py'],
  dependencies = [
    '3rdparty/python:pystache',
  ],
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
    ':hash_utils',
    'src/python/pants/util:ordered_set',
  ],
)

python_library(
  name = 'specs',
  sources = ['specs.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/engine:collection',
    'src/python/pants/engine:fs',
    'src/python/pants/option:global_options',
    'src/python/pants/util:collections',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:filtering',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
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
    ':specs',
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
    '3rdparty/python:dataclasses',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:logging',
    'src/python/pants/util:memo',
    'src/python/pants/util:rwbuf',
  ],
)

python_library(
  name='validation',
  sources=['validation.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/util:ordered_set',
  ],
)

python_library(
  name='exiter',
  sources=['exiter.py'],
  dependencies=[
    'src/python/pants/util:fileutil',
    'src/python/pants/util:strutil',
  ],
)

python_tests(
  name='tests',
  dependencies=[
    'src/python/pants/engine/internals:native',
    'src/python/pants/engine/legacy:structs',
    ':specs'
  ],
)
