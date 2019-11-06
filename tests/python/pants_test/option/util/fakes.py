# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.testutil.option.fakes import _FakeOptionValues as _FakeOptionValues  # noqa
from pants.testutil.option.fakes import (
  _options_registration_function as _options_registration_function,
)  # noqa
from pants.testutil.option.fakes import create_options as create_options  # noqa
from pants.testutil.option.fakes import (
  create_options_for_optionables as create_options_for_optionables,
)  # noqa


deprecated_module(
  removal_version="1.25.0.dev0",
  hint_message="Import pants.testutil.option.fakes instead."
)
