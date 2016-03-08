# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Integration tests for the jvm_prep_command() target

java_library(name='jvmprepcommand',
  sources=globs('*.java'),
)

prep_command(
  name='test-prep-command',
  prep_executable='touch',
  prep_args=['/tmp/running-prep-in-goal-test.txt'],
)

prep_command(
  name='binary-prep-command',
  goal='binary',
  prep_executable='touch',
  prep_args=['/tmp/running-prep-in-goal-binary.txt'],
)

prep_command(
  name='compile-prep-command',
  goal='compile',
  prep_executable='touch',
  prep_args=['/tmp/running-prep-in-goal-compile.txt'],
)
