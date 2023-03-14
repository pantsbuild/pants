# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.providers.pyenv.rules import rules as pyenv_rules
from pants.backend.python.providers.pyenv.target_types import PyenvInstall


def target_types():
    return [PyenvInstall]


def rules():
    return pyenv_rules()
