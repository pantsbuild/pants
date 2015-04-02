# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'address',
  sources = ['address.py'],
  dependencies = [
    ':build_file',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name = 'address_lookup_error',
  sources = ['address_lookup_error.py'],
)

python_library(
  name = 'addressable',
  sources = ['addressable.py'],
  dependencies = [
    ':address',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name = 'build_configuration',
  sources = ['build_configuration.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':addressable',
    ':build_file_aliases',
    ':parse_context',
    ':target',
  ],
)

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
  ]
)

python_library(
  name = 'build_file_address_mapper',
  sources = ['build_file_address_mapper.py'],
  dependencies = [
    ':address',
    ':address_lookup_error',
    ':build_file',
    ':build_file_parser',
    ':build_environment',
  ]
)

python_library(
  name = 'build_file_aliases',
  sources = ['build_file_aliases.py'],
)

python_library(
  name = 'build_file_parser',
  sources = ['build_file_parser.py'],
  dependencies = [
    '3rdparty/python:six',
    ':address',
    ':build_environment',
    ':build_file',
    ':build_graph',
  ]
)

python_library(
  name = 'build_graph',
  sources = ['build_graph.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':address',
    ':address_lookup_error',
  ]
)

python_library(
  name = 'build_invalidator',
  sources = ['build_invalidator.py'],
  dependencies = [
    ':hash_utils',
    ':target', # XXX(fixme)
    'src/python/pants/fs',
    'src/python/pants/util:dirutil',
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
  name = 'cache_manager',
  sources = ['cache_manager.py'],
  dependencies = [
    ':build_graph',
    ':build_invalidator',
    ':target',
  ],
)

python_library(
  name = 'config',
  sources = ['config.py'],
  dependencies = [
    '3rdparty/python:six',
    ':build_environment',
    'src/python/pants/util:strutil',
  ]
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
  name = 'extension_loader',
  sources = ['extension_loader.py'],
  dependencies = [
    ':exceptions',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/android:plugin',
    'src/python/pants/backend/authentication:authentication',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/maven_layout:plugin',
    'src/python/pants/backend/project_info:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/base:build_configuration',
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
    '3rdparty/python:six',
  ]
)

python_library(
  name = 'hash_utils',
  sources = ['hash_utils.py'],
)

python_library(
  name = 'lazy_source_mapper',
  sources = ['lazy_source_mapper.py'],
  dependencies = [
    ':build_file',
    ':build_environment',
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
  ],
)

python_library(
  name = 'cmd_line_spec_parser',
  sources = ['cmd_line_spec_parser.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':address',
    ':address_lookup_error',
    ':build_file',
  ],
)

python_library(
  name = 'source_root',
  sources = ['source_root.py'],
  dependencies = [
    ':build_environment',
    ':build_manual',
    ':exceptions',
    ':parse_context',
    '3rdparty/python/twitter/commons:twitter.common.collections',
  ],
)

python_library(
  name = 'target',
  sources = ['target.py'],
  dependencies = [
    '3rdparty/python:six',
    ':address',
    ':build_environment',
    ':exceptions',
    ':fingerprint_strategy',
    ':hash_utils',
    ':lazy_source_mapper',
    ':payload',
    ':payload_field',
    ':source_root',
    ':target_addressable',
    ':validation',
  ],
)

python_library(
  name = 'target_addressable',
  sources = ['target_addressable.py'],
  dependencies = [
    '3rdparty/python:six',
    ':addressable',
    ':exceptions',
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
    'src/python/pants/rwbuf',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name='validation',
  sources=['validation.py'],
  dependencies=[
    '3rdparty/python:six',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
  ],
)
