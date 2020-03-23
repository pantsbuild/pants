# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.backend.jvm.tasks.jvm_compile.zinc.zinc_compile_integration_base import (
    BaseZincCompileIntegrationTest,
)


class ZincCompileIntegration(BaseCompileIT, BaseZincCompileIntegrationTest):
    _EXTRA_TASK_ARGS: List[str] = []
