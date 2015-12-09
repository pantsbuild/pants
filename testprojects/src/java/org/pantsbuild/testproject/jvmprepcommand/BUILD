# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Integration tests for the jvm_prep_command() target

java_library(name='jvmprepcommand',
  sources=globs('*.java'),
)

jvm_prep_command(
  name='test-prep-command',
  mainclass='org.pantsbuild.testproject.jvmprepcommand.ExampleJvmPrepCommand',
  args=['/tmp/running-in-goal-test', 'foo'],
  jvm_options=['-Dorg.pantsbuild.jvm_prep_command=WORKS-IN-TEST'],
  dependencies=[':jvmprepcommand']
)

jvm_prep_command(
  name='binary-prep-command',
  goal='binary',
  mainclass='org.pantsbuild.testproject.jvmprepcommand.ExampleJvmPrepCommand',
  args=['/tmp/running-in-goal-binary', 'bar'],
  jvm_options=['-Dorg.pantsbuild.jvm_prep_command=WORKS-IN-BINARY'],
  dependencies=[':jvmprepcommand']
)

# NB(Eric Ayers), a jvm_prep_command running from the compile step can only depend on published
# jar_library() targets, not code compiled within the repo.
jvm_prep_command(
  name='compile-prep-command',
  goal='compile',
  mainclass='org.pantsbuild.tools.jar.Main',
  args=['/tmp/running-in-goal-compile.jar',
    '-files=testprojects/src/java/org/pantsbuild/testproject/jvmprepcommand'],
  dependencies=[
    ':jar-tool',
  ],
)

jar_library(name='jar-tool',
  jars=[
    # NB(Eric Ayers): this can be any version of jar-tool, does not need to stay in sync with the
    # rest of pants' use of jar-tool.
    jar(org='org.pantsbuild', name='jar-tool', rev='0.0.8'),
  ],
)
