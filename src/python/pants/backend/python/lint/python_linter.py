# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta
from dataclasses import dataclass

from pants.engine.legacy.structs import (
    PantsPluginAdaptorWithOrigin,
    PythonAppAdaptorWithOrigin,
    PythonBinaryAdaptorWithOrigin,
    PythonTargetAdaptorWithOrigin,
    PythonTestsAdaptorWithOrigin,
    TargetAdaptorWithOrigin,
)
from pants.engine.rules import RootRule
from pants.rules.core.lint import Linter


@dataclass(frozen=True)
class PythonLinter(Linter, metaclass=ABCMeta):
    @staticmethod
    def is_valid_target(adaptor_with_origin: TargetAdaptorWithOrigin) -> bool:
        return isinstance(adaptor_with_origin, PYTHON_TARGET_TYPES)


PYTHON_TARGET_TYPES = (
    PythonAppAdaptorWithOrigin,
    PythonBinaryAdaptorWithOrigin,
    PythonTargetAdaptorWithOrigin,
    PythonTestsAdaptorWithOrigin,
    PantsPluginAdaptorWithOrigin,
)


def rules():
    return [RootRule(target_type) for target_type in PYTHON_TARGET_TYPES]
