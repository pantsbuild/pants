python_library(
  name = 'abbreviate_target_ids',
  sources = ['abbreviate_target_ids.py'],
)

python_library(
  name = 'address',
  sources = ['address.py'],
  dependencies = [
    pants('src/python/twitter/common/lang'),
    pants(':build_file'),
  ]
)

python_library(
  name = 'build_environment',
  sources = ['build_environment.py'],
  dependencies = [
    pants('src/python/twitter/common/log'),
    pants('src/python/twitter/pants/version'),
    pants('src/python/twitter/pants/scm:all'),
    pants(':build_root'),
  ]
)

python_library(
  name = 'build_file',
  sources = ['build_file.py'],
  dependencies = [
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/python'),
  ]
)

python_library(
  name = 'build_file_aliases',
  sources = ['build_file_aliases.py'],
  dependencies = [
    pants('src/python/twitter/pants/targets:all'),  # XXX(fixme)
  ]
)

python_library(
  name = 'build_file_context',  # XXX(fixme)
  sources = ['build_file_context.py'],
  dependencies = [
    pants(':build_environment'),
    pants(':build_file_aliases'),
    pants(':build_file_helpers'),
    pants(':config'),
    pants('src/python/twitter/pants/goal'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/tasks:common'),
  ]
)

python_library(
  name = 'build_file_helpers',  # XXX(fixme)
  sources = ['build_file_helpers.py'],
  dependencies = [
    pants('src/python/twitter/pants/targets:all'),  # XXX(fixme)
  ]
)

python_library(
  name = 'build_invalidator',
  sources = ['build_invalidator.py'],
  dependencies = [
    pants(':hash_utils'),
    pants(':target'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
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
    pants('src/python/twitter/common/lang'),
  ],
)

python_library(
  name = 'config',
  sources = ['config.py'],
  dependencies = [
    pants(':build_environment'),
  ]
)

python_library(
  name = 'double_dag',
  sources = ['double_dag.py'],
  dependencies = [
    pants(':abbreviate_target_ids'),
  ]
)

python_library(
  name = 'generator',
  sources = ['generator.py'],
  dependencies = [
    pants(':mustache'),
    pants('src/python/twitter/common/lang'),
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
    pants('3rdparty/python:pystache'),
  ]
)

python_library(
  name = 'parse_context',
  sources = ['parse_context.py'],
  dependencies = [
    pants(':build_environment'),
    pants(':build_file'),
    pants(':build_file_context'),
    pants(':config'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
  ]
)

python_library(
  name = 'rcfile',
  sources = ['rcfile.py'],
  dependencies = [
    pants(':config'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/log'),
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
    pants(':build_environment'),
    pants('src/python/twitter/common/dirutil'),
  ],
)

python_library(
  name = 'target',
  sources = ['target.py'],
  dependencies = [
    pants(':address'),
    pants(':build_manual'),
    pants(':hash_utils'),
    pants(':parse_context'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/lang'),
  ],
)

python_library(
  name = 'timer',
  sources = ['timer.py'],
  dependencies = [
    pants('src/python/twitter/common/lang'),
  ],
)

python_library(
  name = 'worker_pool',
  sources = ['worker_pool.py'],
  dependencies = [
    pants('src/python/twitter/pants/reporting'), # XXX(fixme)
  ],
)

python_library(
  name = 'workunit',
  sources = ['workunit.py'],
  dependencies = [
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/rwbuf'), # XXX(fixme)
  ],
)
