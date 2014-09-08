# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name='pantsplus',
  entry_point = 'pants.bin.pants_exe:main',
  dependencies=[
    'src/python/pants/bin:pants_exe',
    'src/python/internal_backend/docsite:plugin',
    'src/python/pants/backend/python/commands:pants_old',
    'src/python/pants/commands:pants_new',
  ],
  platforms=[
    'current',
    'linux-x86_64',
    'macosx-10.4-x86_64',
  ],
).with_description('The pants binary target with internal add-ons.')
