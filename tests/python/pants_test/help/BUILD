# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='build_dictionary_info_extracter',
  sources=['test_build_dictionary_info_extracter.py'],
  coverage=['pants.help.build_dictionary_info_extracter'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/help',
    'src/python/pants/util:objects',
  ],
)

python_tests(
  name='help_formatter',
  sources=['test_help_formatter.py'],
  coverage=['pants.help.help_formatter'],
  dependencies = [
    'src/python/pants/help',
  ],
)

python_tests(
  name='help_info_extracter',
  sources=['test_help_info_extracter.py'],
  coverage=['pants.help.help_info_extracter'],
  dependencies = [
    'src/python/pants/help',
    'src/python/pants/option',
  ],
)

python_tests(
  name='scope_info_iterator',
  sources=['test_scope_info_iterator.py'],
  coverage=['pants.help.scope_info_iterator'],
  dependencies = [
    'src/python/pants/help',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/task',
  ],
)


python_tests(
  name='help_integration',
  sources=[
    'test_help_integration.py',
  ],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)
