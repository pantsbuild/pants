# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=['java_thrifty_gen.py', 'java_thrifty_library.py'],
  tags={"partially_type_checked"},
)

contrib_plugin(
  name='plugin',
  dependencies=[
    ':thrifty',
    'src/python/pants/goal:task_registrar',
  ],
  tags = {"partially_type_checked"},
  distribution_name='pantsbuild.pants.contrib.thrifty',
  description='Microsoft Thrifty thrift generator pants plugins.',
  additional_classifiers=[
    'Topic :: Software Development :: Code Generators'
  ],
  register_goals=True,
  build_file_aliases=True,
)
