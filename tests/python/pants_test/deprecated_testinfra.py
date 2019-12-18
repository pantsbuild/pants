# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect

from pants.base.deprecated import deprecated_module


def deprecated_testinfra_module(instead=None):
  if not instead:
    caller_frame_info = inspect.stack()[1]
    caller_module = inspect.getmodule(caller_frame_info.frame)
    caller_module_name = caller_module.__name__
    assert caller_module_name.startswith('pants_test.'), (
      'The `deprecated_testinfra_module` helper should only be used in `pants_test` code that has '
      'been deprecated in favor of `pants.testutil` equivalent code. Detected use from module '
      f'{caller_module_name}.'
    )
    instead = f'pants.testutil.{caller_module_name.lstrip("pants_test.")}'

  deprecated_module(
    removal_version='1.26.0.dev2',
    hint_message=f'Import {instead} from the pantsbuild.pants.testutil distribution instead.',
    stacklevel=4
  )
