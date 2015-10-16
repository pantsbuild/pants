# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='tasks',
  sources=[
    'stack_build.py',
    'stack_task.py',
  ],
  dependencies=[
    'src/python/pants/backend/core/tasks:common',
    'contrib/haskell/src/python/pants/contrib/haskell/targets:haskell_package',
    'contrib/haskell/src/python/pants/contrib/haskell/targets:hackage',
    'contrib/haskell/src/python/pants/contrib/haskell/targets:cabal',
  ],
)
