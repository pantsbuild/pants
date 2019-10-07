# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_binary import PythonBinary
from pants.build_graph.app_base import AppBase


class PythonApp(AppBase):
    """A deployable Python application.

    Invoking the ``bundle`` goal on one of these targets creates a
    self-contained artifact suitable for deployment on some other machine.
    The artifact contains the executable pex, its dependencies, and
    extra files like config files, startup scripts, etc.

    :API: public
    """

    @classmethod
    def alias(cls):
        return "python_app"

    @classmethod
    def binary_target_type(cls):
        return PythonBinary

    @staticmethod
    def is_python_app(target):
        return isinstance(target, PythonApp)
