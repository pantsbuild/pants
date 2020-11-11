# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules import archive, external_tool
from pants.testutil.test_base import TestBase


class ExternalToolTestBase(TestBase):
    """A baseclass useful for tests that use an ExternalTool.

    :API: public
    """

    @classmethod
    def rules(cls):
        return [*super().rules(), *archive.rules(), *external_tool.rules()]
