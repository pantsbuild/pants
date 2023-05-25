# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import Field, Target


class PyenvInstallSentinelField(Field):
    none_is_valid_value = True
    alias = "_sentinel"
    help = "<internal>"
    default = False


class PyenvInstall(Target):
    alias = "_pyenv_install"
    help = "<internal target>"
    core_fields = (PyenvInstallSentinelField,)
