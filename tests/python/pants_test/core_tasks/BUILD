# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='bash_completion',
  sources=['test_bash_completion.py'],
  coverage=['pants.core_tasks.bash_completion'],
  dependencies=[
    'src/python/pants/core_tasks',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'deferred_sources_mapper_integration',
  sources = ['test_deferred_sources_mapper_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'prep_command_integration',
  sources = ['test_prep_command_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'run_prep_command',
  sources = ['test_run_prep_command.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/core_tasks',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:task_test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'substitute_target_aliases_integration',
  sources = ['test_substitute_target_aliases_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:aliases_directory'
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 750,
)
