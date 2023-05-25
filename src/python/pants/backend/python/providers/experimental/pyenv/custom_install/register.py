# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.providers.pyenv.custom_install.rules import rules as custom_install_rules
from pants.backend.python.providers.pyenv.custom_install.target_types import PyenvInstall


def target_types():
    return [PyenvInstall]


def rules():
    return custom_install_rules()
