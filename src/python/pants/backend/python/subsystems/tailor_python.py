# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import cast

from pants.option.subsystem import Subsystem


class TailorPythonSubsystem(Subsystem):
    options_scope = "tailor-python"
    help = "Options for running tailor on Python code."

    @classmethod
    def register_options(cls, register):
        register(
            "--ignore-solitary-init-files",
            type=bool,
            default=True,
            advanced=True,
            help="Don't create python_library targets for solitary __init__.py files, as "
            "those usually exist as import scaffolding rather than true library code. "
            "Set to False if you commonly have packages containing real code in "
            "__init__.py and there are no other .py files in the package.",
        )

    def ignore_solitary_init_files(self) -> bool:
        return cast(bool, self.options.ignore_solitary_init_files)
