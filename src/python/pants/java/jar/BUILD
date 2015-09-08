# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='manifest',
  sources=['manifest.py'],
  dependencies=[
    '3rdparty/python:six',
  ]
)

python_library(
  name='shader',
  sources=['shader.py'],
  dependencies=[
    # TODO(John Sirois): This is a bad dependency; either Shader should move to the jvm backend
    # or JarDependency should move here.  Keep in mind the Shader should process JvmBinary targets
    # directly, which suggests the Shader -> jvm backend move.
    # See: https://github.com/pantsbuild/pants/issues/2154
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',

    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
  ]
)
