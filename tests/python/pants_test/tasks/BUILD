# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base',
  sources = ['test_base.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/core/tasks:console_task',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:config',
    'src/python/pants/base:target',
    'src/python/pants/goal:context',
    'src/python/pants/goal',
    'tests/python/pants_test/base:context_utils',
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
    ':filter',
    ':group_task',
    ':ivy_utils',
    ':jar_create',
    ':jar_publish',
    ':jar_task',
    ':jvm_run',
    ':jvm_task',
    ':jvmdoc_gen',
    ':list_goals',
    ':listtargets',
    ':markdown_to_html',
    ':minimal_cover',
    ':reflect',
    ':roots',
    ':sorttargets',
    ':targets_help',
    ':what_changed',
    'tests/python/pants_test/tasks/jvm_compile/scala'
  ],
)

target(
  name = 'integration',
  dependencies = [
    ':antlr_integration',
    ':depmap_integration',
    ':eclipse_integration',
    ':ensime_integration',
    ':idea_integration',
    ':ivy_resolve_integration',
    ':jar_publish_integration',
    ':junit_tests_integration',
    ':jvm_bundle_integration',
    ':jvm_run_integration',
    ':markdown_to_html_integration',
    ':protobuf_integration',
    ':scala_repl_integration',
    ':wire_integration',
    'tests/python/pants_test/tasks/jvm_compile/java:integration',
  ],
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
    ':base',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/core/tasks:builddictionary',
    'src/python/pants/backend/core/tasks:reflect',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
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
  name = 'reflect',
  sources = ['test_reflect.py'],
  dependencies = [
    ':base',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/core/tasks:reflect',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
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
    ':base',
    'tests/python/pants_test/testutils',
    'src/python/pants/base:build_invalidator',
    'src/python/pants/base:cache_manager',
  ]
)

python_tests(
  name = 'check_published_deps',
  sources = ['test_check_published_deps.py'],
  dependencies = [
    ':base',
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
    ':base',
    'src/python/pants/backend/core/tasks:console_task',
  ]
)

python_tests(
  name = 'dependees',
  sources = ['test_dependees.py'],
  dependencies = [
    ':base',
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
  name = 'depmap_integration',
  sources = ['test_depmap_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/base:config',
    'src/python/pants/ivy:ivy',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'detect_duplicates',
  sources = ['test_detect_duplicates.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/backend/jvm/tasks:detect_duplicates',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:task_test_base',
  ],
)

python_tests(
  name = 'filemap',
  sources = ['test_filemap.py'],
  dependencies = [
    ':base',
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
    ':base',
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
  name = 'ivy_utils',
  sources = ['test_ivy_utils.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm:ivy_utils',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
    'tests/python/pants_test/base:context_utils',
  ]
)

python_tests(
  name = 'jar_create',
  sources = ['test_jar_create.py'],
  dependencies = [
    ':base',
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
    'src/python/pants/java:jar',
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
    ':base',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_publish',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:source_root',
    'src/python/pants/scm:scm',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name = 'jar_publish_integration',
  sources = ['test_jar_publish_integration.py'],
  dependencies = [
    ':base',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name = 'list_goals',
  sources = ['test_list_goals.py'],
  dependencies = [
    ':base',
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
    ':base',
    'src/python/pants/backend/core/tasks:listtargets',
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:target',
  ],
)

python_tests(
  name = 'markdown_to_html',
  sources = ['test_markdown_to_html.py'],
  dependencies = [
    ':base',
    'src/python/pants/backend/core/tasks:markdown_to_html',
  ]
)

python_tests(
  name='markdown_to_html_integration',
  sources=['test_markdown_to_html_integration.py'],
  dependencies=[
    'src/python/pants/backend/core/tasks:markdown_to_html',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
  ],
  coverage=[
    'pants.backend.core.tasks.markdown_to_html',
  ]
)

python_tests(
  name = 'minimal_cover',
  sources = ['test_minimal_cover.py'],
  dependencies = [
    ':base',
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
    ':base',
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
    ':base',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/core/tasks:sorttargets',
    'src/python/pants/base:build_file_aliases',
  ],
)

python_tests(
  name = 'targets_help',
  sources = ['test_targets_help.py'],
  dependencies = [
    ':base',
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
    ':base',
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
    ':base',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_run',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'jvm_task',
  sources = ['test_jvm_task.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:jvm_task',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:task_test_base',
  ]
)

python_tests(
  name = 'jvmdoc_gen',
  sources = ['test_jvmdoc_gen.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:jvmdoc_gen',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:task_test_base',
  ]
)

