# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    # TODO: exclude all inferred Pants dependencies.
    'testprojects/pants-plugins/3rdparty/python/pants',
  ],
  provides=setup_py(
    name='test_pants_plugin',
    description='A test pants plugin',
    version='0.0.1',
    namespace_packages=[
      'test_pants_plugin',
    ],
  )
)
