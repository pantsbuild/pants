# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base',
  sources = ['test_base.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:cmd_line_spec_parser'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/commands:goal'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/backend/core/tasks:console_task'),
    pants('src/python/pants/backend/core/tasks:task'),
    pants('tests/python/pants_test/base:context_utils'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_test_suite(
  name = 'tasks',
  dependencies = [
    pants(':antlr_gen'),
    pants(':binary_create'),
    pants(':builddict'),
    pants(':bundle_create'),
    pants(':cache_manager'),
    pants(':check_exclusives'),
    pants(':check_published_deps'),
    pants(':config'),
    pants(':console_task'),
    pants(':context'),
    pants(':dependees'),
    pants(':dependencies'),
    pants(':depmap'),
    pants(':detect_duplicates'),
    pants(':filemap'),
    pants(':filter'),
    pants(':group_task'),
    pants(':jar_create'),
    pants(':jar_publish'),
    pants(':jar_task'),
    pants(':jaxb_gen'),
    pants(':jvm_task'),
    pants(':jvmdoc_gen'),
    pants(':list_goals'),
    pants(':listtargets'),
    pants(':minimal_cover'),
    pants(':protobuf_gen'),
    pants(':ragel_gen'),
    pants(':roots'),
    pants(':scrooge_gen'),
    pants(':sorttargets'),
    pants(':targets_help'),
    pants(':what_changed'),
    pants('tests/python/pants_test/tasks/jvm_compile')
  ],
)

python_test_suite(
  name = 'integration',
  dependencies = [
    pants(':idea_integration'),
    pants(':jar_publish_integration'),
    pants(':jvm_bundle_integration'),
    pants(':scala_repl_integration'),
    pants(':protobuf_integration'),
  ],
)

python_tests(
  name = 'antlr_gen',
  sources = ['test_antlr_gen.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants(':base'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/codegen/tasks:antlr_gen'),
    pants('tests/python/pants_test/jvm:nailgun_task_test_base'),
  ],
)

python_tests(
  name = 'binary_create',
  sources = ['test_binary_create.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/jvm/tasks:binary_create'),
  ]
)

python_tests(
  name = 'builddict',
  sources = ['test_builddict.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core/tasks:builddictionary'),
  ]
)

python_tests(
  name = 'bundle_create',
  sources = ['test_bundle_create.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/jvm/tasks:bundle_create'),
  ]
)

python_tests(
  name = 'jvm_bundle_integration',
  sources = ['test_jvm_bundle_integration.py'],
  dependencies = [
    pants('tests/python/pants_test:int-test'),
  ],
)

python_tests(
  name = 'scala_repl_integration',
  sources = ['test_scala_repl_integration.py'],
  dependencies = [
    pants('tests/python/pants_test:int-test'),
  ],
)

python_tests(
  name = 'cache_manager',
  sources = ['test_cache_manager.py'],
  dependencies = [
    pants(':base'),
    pants('tests/python/pants_test/testutils'),
    pants('src/python/pants/base:build_invalidator'),
    pants('src/python/pants/base:cache_manager'),
  ]
)

python_tests(
  name = 'check_exclusives',
  sources = ['test_check_exclusives.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/goal:context'),
    pants('src/python/pants/backend/core/tasks:check_exclusives'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_tests(
  name = 'check_published_deps',
  sources = ['test_check_published_deps.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/tasks:check_published_deps'),
    pants('src/python/pants/base:build_file_aliases'),
  ]
)

# XXX Uh shouldn't this be in base?
python_tests(
  name = 'config',
  sources = ['test_config.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/base:config'),
  ]
)

python_tests(
  name = 'console_task',
  sources = ['test_console_task.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core/tasks:console_task'),
  ]
)

# XXX this should be in goal
python_tests(
  name = 'context',
  sources = ['test_context.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/goal:context'),
  ]
)

python_tests(
  name = 'dependees',
  sources = ['test_dependees.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/core/tasks:dependees'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file_aliases'),
  ]
)

python_tests(
  name = 'dependencies',
  sources = ['test_dependencies.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/backend/jvm/tasks:dependencies'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/backend/python:python_requirement'),
    pants('src/python/pants/base:exceptions'),
  ]
)

python_tests(
  name = 'depmap',
  sources = ['test_depmap.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core:plugin'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/jvm:plugin'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/backend/jvm/tasks:depmap'),
    pants('src/python/pants/backend/python:plugin'),
    pants('src/python/pants/base:build_file_aliases'),
  ]
)

python_tests(
  name = 'detect_duplicates',
  sources = ['test_detect_duplicates.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/backend/jvm/tasks:detect_duplicates'),
    pants('src/python/pants/util:dirutil'),
    pants('tests/python/pants_test/base:context_utils'),
  ],
)

python_tests(
  name = 'filemap',
  sources = ['test_filemap.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core/tasks:filemap'),
    pants('src/python/pants/base:source_root'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/base:build_file_aliases'),
  ],
)

python_tests(
  name = 'filter',
  sources = ['test_filter.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/backend/core/tasks:filter'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/base:build_file_aliases'),
  ],
)

python_tests(
  name = 'idea_integration',
  sources = ['test_idea_integration.py'],
  dependencies = [
    pants('tests/python/pants_test:int-test'),
  ],
)

python_tests(
  name = 'jar_create',
  sources = ['test_jar_create.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants(':base'),
    pants('src/python/pants/backend/android/targets:android'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/backend/jvm/tasks:jar_create'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:source_root'),
    pants('src/python/pants/goal:products'),
    pants('src/python/pants/java:jar'),
    pants('src/python/pants/util:dirutil'),
    pants('tests/python/pants_test/base:context_utils'),
    pants('tests/python/pants_test/jvm:jar_task_test_base'),
  ],
)

python_tests(
  name = 'jar_publish',
  sources = ['test_jar_publish.py'],
  dependencies = [
    pants('3rdparty/python:mock'),
    pants(':base'),
    pants('src/python/pants/backend/jvm/tasks:jar_publish'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_tests(
  name = 'jar_publish_integration',
  sources = ['test_jar_publish_integration.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('tests/python/pants_test:int-test'),
  ],
)

python_tests(
  name = 'list_goals',
  sources = ['test_list_goals.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core/tasks:list_goals'),
    pants('src/python/pants/backend/core/tasks:common'),
    pants('src/python/pants/goal'),
  ],
)

python_tests(
  name = 'listtargets',
  sources = ['test_listtargets.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core/tasks:listtargets'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:target'),
  ],
)

python_tests(
  name = 'minimal_cover',
  sources = ['test_minimal_cover.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core/tasks:minimal_cover'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/base:build_file_aliases'),
  ],
)

python_tests(
  name = 'protobuf_gen',
  sources = ['test_protobuf_gen.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/backend/codegen/tasks:protobuf_gen'),
  ],
)

python_tests(
  name = 'protobuf_integration',
  sources = ['test_protobuf_integration.py'],
  dependencies = [
    pants('tests/python/pants_test:int-test'),
  ],
)

python_tests(
  name = 'jaxb_gen',
  sources = ['test_jaxb_gen.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/backend/codegen/tasks:jaxb_gen'),
    pants('src/python/pants/backend/codegen/targets:java'),
  ],
)

python_tests(
  name = 'roots',
  sources = ['test_roots.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/core/tasks:roots'),
  ],
)

python_tests(
  name = 'scrooge_gen',
  sources = ['test_scrooge_gen.py'],
  dependencies = [
    pants('3rdparty/python:mock'),
    pants(':base'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/codegen/tasks:scrooge_gen'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:exceptions'),
  ],
)

python_tests(
  name = 'sorttargets',
  sources = ['test_sorttargets.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/backend/core/tasks:sorttargets'),
    pants('src/python/pants/base:build_file_aliases'),
  ],
)

python_tests(
  name = 'targets_help',
  sources = ['test_targets_help.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/core/tasks:targets_help'),
  ],
)

python_tests(
  name = 'what_changed',
  sources = ['test_what_changed.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/codegen/targets:python'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/core/tasks:what_changed'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:source_root'),
    pants('src/python/pants/base:target'),
  ],
)

python_tests(
  name = 'jar_task',
  sources = ['test_jar_task.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/tasks:jar_task'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:source_root'),
    pants('src/python/pants/util:dirutil'),
    pants('tests/python/pants_test/jvm:jvm_tool_task_test_base'),
  ]
)

python_tests(
  name = 'group_task',
  sources = ['test_group_task.py'],
  dependencies = [
    pants('src/python/pants/backend/core/tasks:check_exclusives'),
    pants('src/python/pants/backend/core/tasks:group_task'),
    pants('src/python/pants/engine:engine'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'jvm_task',
  sources = ['test_jvm_task.py'],
  dependencies = [
    pants('src/python/pants/backend/core/tasks:check_exclusives'),
    pants('src/python/pants/backend/jvm/tasks:jvm_task'),
    pants('src/python/pants/util:dirutil'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'jvmdoc_gen',
  sources = ['test_jvmdoc_gen.py'],
  dependencies = [
    pants('src/python/pants/backend/core/tasks:check_exclusives'),
    pants('src/python/pants/backend/jvm/tasks:jvmdoc_gen'),
    pants('src/python/pants/util:dirutil'),
    pants('tests/python/pants_test:base_test'),
  ]
)


python_tests(
  name = 'ragel_gen',
  sources = ['test_ragel_gen.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python:mock'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/backend/codegen/tasks:ragel_gen'),
    pants('src/python/pants/backend/codegen/targets:java'),
  ],
)
