# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

dependencies(
  name = 'common',
  dependencies = [
    'src/python/pants/backend/core/tasks:task',
  ],
)

python_library(
  name = 'all',
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:all',
    ':common',
    ':benchmark_run',
    ':binary_create',
    ':bootstrap_jvm_tools',
    ':bundle_create',
    ':check_published_deps',
    ':checkstyle',
    ':dependencies',
    ':depmap',
    ':detect_duplicates',
    ':eclipse_gen',
    ':filedeps',
    ':ide_gen',
    ':idea_gen',
    ':ivy_imports',
    ':ivy_resolve',
    ':ivy_task_mixin',
    ':jar_create',
    ':jar_publish',
    ':javadoc_gen',
    ':junit_run',
    ':jvm_binary_task',
    ':jvm_run',
    ':jvm_task',
    ':jvm_tool_task_mixin',
    ':jvmdoc_gen',
    ':nailgun_task',
    ':provides',
    ':scala_repl',
    ':scaladoc_gen',
    ':scalastyle',
    ':specs_run',
  ],
)

python_library(
  name = 'benchmark_run',
  sources = ['benchmark_run.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
  ],
)

python_library(
  name = 'binary_create',
  sources = ['binary_create.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_binary_task'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/java:jar'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'bootstrap_jvm_tools',
  sources = ['bootstrap_jvm_tools.py'],
  dependencies = [
    pants('src/python/pants/backend/core/tasks:task'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/backend/jvm/tasks:ivy_task_mixin'),
  ],
)

python_library(
  name = 'bundle_create',
  sources = ['bundle_create.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants(':common'),
    pants(':jvm_binary_task'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/fs'),
    pants('src/python/pants/java:jar'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'check_published_deps',
  sources = ['check_published_deps.py'],
  dependencies = [
    pants(':jar_publish'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/core/tasks:console_task'),
  ],
)

python_library(
  name = 'checkstyle',
  sources = ['checkstyle.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/backend/jvm/tasks:nailgun_task'),
    pants('src/python/pants/process'),
    pants('src/python/pants/util:dirutil'),
  ],
)

# XXX(pl): Not really JVM, but a hairball violator
python_library(
  name = 'dependencies',
  sources = ['dependencies.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/backend/core/tasks:console_task'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/python/targets:python'),
  ],
)

# XXX(pl): Not really JVM, but a hairball violator
python_library(
  name = 'depmap',
  sources = ['depmap.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/backend/core/tasks:console_task'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/base:build_environment'),
  ],
)

python_library(
  name = 'detect_duplicates',
  sources = ['detect_duplicates.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_binary_task'),
    # TODO(pl): Use twitter.common.lang instead, but for the to_bytes helper, twitter.commons
    # needs to be updated so the standard compatibility helpers act like the ones in
    # twitter.common.python
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/java:jar'),
  ],
)

python_library(
  name = 'eclipse_gen',
  sources = ['eclipse_gen.py'],
  resources = globs('templates/eclipse/*.mustache'),
  dependencies = [
    pants(':common'),
    pants(':ide_gen'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:generator'),
    pants('src/python/pants/util:dirutil'),
  ],
)

# XXX(pl): Not really JVM, but a hairball violator
python_library(
  name = 'filedeps',
  sources = ['filedeps.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/backend/core/tasks:console_task'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/core/targets:common'),
  ],
)

python_library(
  name = 'ide_gen',
  sources = ['ide_gen.py'],
  dependencies = [
    pants(':checkstyle'),
    pants(':common'),
    pants(':jvm_binary_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/goal:phase'), # XXX?
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'idea_gen',
  sources = ['idea_gen.py'],
  resources = globs('templates/idea/*.mustache'),
  dependencies = [
    pants(':common'),
    pants(':ide_gen'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:generator'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'ivy_imports',
  sources = ['ivy_imports.py'],
  dependencies = [
    pants('src/python/pants/backend/jvm:ivy_utils'),
    pants(':nailgun_task'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/base:cache_manager'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/backend/jvm/tasks:ivy_task_mixin'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/fs'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'ivy_resolve',
  sources = ['ivy_resolve.py'],
  dependencies = [
    pants('src/python/pants/backend/jvm:ivy_utils'),
    pants(':nailgun_task'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/base:cache_manager'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/backend/jvm/tasks:ivy_task_mixin'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'ivy_task_mixin',
  sources = ['ivy_task_mixin.py'],
  dependencies = [
    pants('src/python/pants/backend/jvm:ivy_utils'),
    pants('src/python/pants/base:cache_manager'),
    pants('src/python/pants/ivy'),
  ],
)

python_library(
  name = 'jar_create',
  sources = ['jar_create.py'],
  dependencies = [
    pants(':common'),
    pants(':javadoc_gen'),
    pants(':jar_task'),
    pants(':scaladoc_gen'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/fs'),
    pants('src/python/pants/java:jar'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'jar_publish',
  sources = ['jar_publish.py'],
  resources = globs('templates/jar_publish/*.mustache') +
              globs('templates/ivy_resolve/*.mustache'),
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.config'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants(':common'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/core/tasks:scm_publish'),
    pants('src/python/pants/backend/core/tasks:task'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/backend/jvm:ivy_utils'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_graph'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:generator'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'jar_task',
  sources = ['jar_task.py'],
  dependencies = [
    pants(':nailgun_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/java:jar'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/util:contextutil'),
  ],
)

python_library(
  name = 'javadoc_gen',
  sources = ['javadoc_gen.py'],
  dependencies = [
    pants(':jvmdoc_gen'),
  ],
)

python_library(
  name = 'junit_run',
  sources = ['junit_run.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'jvm_binary_task',
  sources = ['jvm_binary_task.py'],
  dependencies = [
    pants(':common'),
    pants(':jar_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
  ],
)

python_library(
  name = 'jvm_run',
  sources = ['jvm_run.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/java:executor'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'jvm_task',
  sources = ['jvm_task.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/base:build_environment'),
  ],
)

python_library(
  name = 'jvm_tool_task_mixin',
  sources = ['jvm_tool_task_mixin.py'],
  dependencies = [
    pants('src/python/pants/backend/jvm:jvm_tool_bootstrapper'),
  ],
)

python_library(
  name = 'jvmdoc_gen',
  sources = ['jvmdoc_gen.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'nailgun_task',
  sources = ['nailgun_task.py'],
  dependencies = [
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/java:executor'),
    pants('src/python/pants/java:nailgun_executor'),
    pants('src/python/pants/java:distribution'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/backend/core/tasks:task'),
  ],
)

python_library(
  name = 'provides',
  sources = ['provides.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/backend/jvm:ivy_utils'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/util:contextutil'),
  ],
)

python_library(
  name = 'scala_repl',
  sources = ['scala_repl.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/console:stty_utils'),
    pants('src/python/pants/java:util'),
  ],
)

python_library(
  name = 'scaladoc_gen',
  sources = ['scaladoc_gen.py'],
  dependencies = [
    pants(':jvmdoc_gen'),
  ],
)

python_library(
  name = 'scalastyle',
  sources = ['scalastyle.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/backend/jvm/tasks:nailgun_task'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/process'),
  ],
)

python_library(
  name = 'specs_run',
  sources = ['specs_run.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
  ],
)

