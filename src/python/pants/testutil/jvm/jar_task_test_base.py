# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.jvm.nailgun_task_test_base import NailgunTaskTestBase


class JarTaskTestBase(NailgunTaskTestBase):
    """Prepares an ephemeral test build root that supports jar tasks.

    :API: public
    """
