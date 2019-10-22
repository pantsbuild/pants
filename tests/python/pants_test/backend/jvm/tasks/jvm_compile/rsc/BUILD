# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='rsc_compile_integration_base',
  sources=['rsc_compile_integration_base.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
    'tests/python/pants_test:test_base',
<<<<<<< 220a130e3688165583f0f1019fc81818a4d52737
    'contrib/node:examples_directory',
=======
  ],
)

python_tests(
  name='rsc_compile_integration',
  sources=['test_rsc_compile_integration.py'],
  dependencies=[
    ':rsc_compile_integration_base',
>>>>>>> Separate RscCompileIntegration tests into rsc and youtline workflows
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:javadepsonscalatransitive_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:javasources_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:mutual_directory',
  ],
  timeout = 600,
  tags = {'integration'},
)

python_tests(
  name='rsc_compile_integration_youtline',
  sources=['test_rsc_compile_integration_youtline.py'],
  dependencies=[
    ':rsc_compile_integration_base',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:mutual_directory',
  ],
  timeout = 600,
  tags = {'integration'},
)


python_tests(
  name = 'rsc_compile',
  sources = ['test_rsc_compile.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile',
    'src/python/pants/backend/jvm/tasks/jvm_compile/rsc',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
  ],
)
