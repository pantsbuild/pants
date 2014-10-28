# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# The greet library doesn't do much, but we should still test it

python_tests(name='greet',
  dependencies=[
    'examples/src/python/example/hello/greet:greet',
    ':prep',
  ],
  sources=globs('*.py'),
)

# Prepare for the 'greet' test. Realistically, you wouldn't set up a
# prep_command just to create an emtpy temp file. This is meant as a
# simple example.
prep_command(name='prep',
  prep_executable='touch',
  prep_args=['/tmp/prep_command_result']
)
