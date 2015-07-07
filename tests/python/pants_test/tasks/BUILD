  # Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'task_test_base',
  sources = ['task_test_base.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/core/tasks:console_task',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:target',
    'src/python/pants/goal:context',
    'src/python/pants/goal',
    'src/python/pants/ivy',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:base_test',
  ]
)

target(
  name = 'tasks',
  dependencies = [
    ':builddict',
    ':cache_manager',
    ':check_published_deps',
    ':console_task',
    ':dependees',
    ':detect_duplicates',
    ':execution_graph',
    ':filter',
    ':group_task',
    ':jar_create',
    ':jar_publish',
    ':jar_task',
    ':jvm_run',
    ':jvm_task',
    ':jvmdoc_gen',
    ':list_goals',
    ':listtargets',
    ':minimal_cover',
    ':reflect',
    ':roots',
    ':sorttargets',
    ':targets_help',
    ':what_changed',
  ],
)

target(
  name = 'integration',
  dependencies = [
    ':antlr_integration',
    ':bootstrap_jvm_tools_integration',
    ':checkstyle_integration',
    ':eclipse_integration',
    ':ensime_integration',
    ':idea_integration',
    ':ivy_resolve_integration',
    ':jar_publish_integration',
    ':junit_tests_integration',
    ':jvm_bundle_integration',
    ':jvm_run_integration',
    ':protobuf_integration',
    ':scala_repl_integration',
    ':wire_integration',
  ],
)

python_tests(
  name = 'scalastyle_integration',
  sources = ['test_scalastyle_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'antlr_integration',
  sources = ['test_antlr_integration.py'],
  dependencies = [
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
    ]
)

python_tests(
  name = 'builddict',
  sources = ['test_builddict.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/core/tasks:builddictionary',
    'src/python/pants/backend/core/tasks:reflect',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'changed_target_integration',
  sources = ['test_changed_target_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'checkstyle_integration',
  sources = ['test_checkstyle_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'junit_tests_integration',
  sources = ['test_junit_tests_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'jvm_bundle_integration',
  sources = ['test_jvm_bundle_integration.py'],
  dependencies = [
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'jvm_run_integration',
  sources = ['test_jvm_run_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'bootstrap_jvm_tools_integration',
  sources = ['test_bootstrap_jvm_tools_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'reflect',
  sources = ['test_reflect.py'],
  dependencies = [
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/core/tasks:reflect',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'scala_repl_integration',
  sources = ['test_scala_repl_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'cache_manager',
  sources = ['test_cache_manager.py'],
  dependencies = [
    ':task_test_base',
    'tests/python/pants_test/testutils',
    'src/python/pants/base:build_invalidator',
    'src/python/pants/base:cache_manager',
  ]
)

python_tests(
  name = 'check_published_deps',
  sources = ['test_check_published_deps.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm:repository',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:check_published_deps',
    'src/python/pants/base:build_file_aliases',
  ]
)

python_tests(
  name = 'console_task',
  sources = ['test_console_task.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/core/tasks:console_task',
  ]
)

python_tests(
  name = 'dependees',
  sources = ['test_dependees.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/core/tasks:dependees',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_aliases',
  ]
)

python_tests(
  name = 'detect_duplicates',
  sources = ['test_detect_duplicates.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/base:exceptions',
    'src/python/pants/backend/jvm/tasks:detect_duplicates',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name = 'execution_graph',
  sources = ['test_execution_graph.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:execution_graph',
    ]
)

python_tests(
  name = 'filemap',
  sources = ['test_filemap.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/core/tasks:filemap',
    'src/python/pants/base:source_root',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_file_aliases',
  ],
)

python_tests(
  name = 'filter',
  sources = ['test_filter.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/core/tasks:filter',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/base:build_file_aliases',
  ],
)

python_tests(
  name = 'idea_integration',
  sources = ['test_idea_integration.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'eclipse_integration',
  sources = ['test_eclipse_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'ensime_integration',
  sources = ['test_ensime_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'ivy_resolve_integration',
  sources = ['test_ivy_resolve_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'jar_create',
  sources = ['test_jar_create.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:jar_create',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:source_root',
    'src/python/pants/java/jar:manifest',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/base:context_utils',
    'tests/python/pants_test/jvm:jar_task_test_base',
  ],
)

python_tests(
  name = 'jar_publish',
  sources = ['test_jar_publish.py'],
  dependencies = [
    '3rdparty/python:mock',
    ':task_test_base',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_publish',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:generator',
    'src/python/pants/base:source_root',
    'src/python/pants/scm:scm',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/testutils',
  ],
)

python_tests(
  name = 'jar_publish_integration',
  sources = ['test_jar_publish_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'list_goals',
  sources = ['test_list_goals.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/core/tasks:list_goals',
    'src/python/pants/backend/core/tasks:common',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
  ],
)

python_tests(
  name = 'listtargets',
  sources = ['test_listtargets.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/core/tasks:listtargets',
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:target',
  ],
)

python_tests(
  name = 'minimal_cover',
  sources = ['test_minimal_cover.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/core/tasks:minimal_cover',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_file_aliases',
  ],
)

python_tests(
  name = 'protobuf_integration',
  sources = ['test_protobuf_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'wire_integration',
  sources = ['test_wire_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'roots',
  sources = ['test_roots.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:target',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/core/tasks:roots',
  ],
)

python_tests(
  name = 'sorttargets',
  sources = ['test_sorttargets.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/core/tasks:sorttargets',
    'src/python/pants/base:build_file_aliases',
  ],
)

python_tests(
  name = 'targets_help',
  sources = ['test_targets_help.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:target',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/core/tasks:targets_help',
  ],
)

python_tests(
  name = 'what_changed',
  sources = ['test_what_changed.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/targets:python',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/core/tasks:what_changed',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:source_root',
    'src/python/pants/base:target',
  ],
)

python_tests(
  name = 'jar_task',
  sources = ['test_jar_task.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:six',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_task',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:source_root',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ]
)

python_tests(
  name = 'group_task',
  sources = ['test_group_task.py'],
  dependencies = [
    'src/python/pants/backend/core/tasks:group_task',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:target',
    'src/python/pants/engine:engine',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'jvm_run',
  sources = ['test_jvm_run.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_run',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'jvm_task',
  sources = ['test_jvm_task.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/jvm/tasks:jvm_task',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'jvmdoc_gen',
  sources = ['test_jvmdoc_gen.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/jvm/tasks:jvmdoc_gen',
    'src/python/pants/util:dirutil',
  ]
)

