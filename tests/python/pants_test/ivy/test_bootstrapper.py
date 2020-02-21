# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.testutil.subsystem.util import init_subsystem


class BootstrapperTest(unittest.TestCase):
    def setUp(self):
        super().setUp()
        init_subsystem(IvySubsystem)

    def test_simple(self):
        ivy_subsystem = IvySubsystem.global_instance()
        bootstrapper = Bootstrapper(ivy_subsystem=ivy_subsystem)
        ivy = bootstrapper.ivy()
        self.assertIsNotNone(ivy.ivy_resolution_cache_dir)
        self.assertIsNone(ivy.ivy_settings)

    def test_reset(self):
        bootstrapper1 = Bootstrapper.instance()
        Bootstrapper.reset_instance()
        bootstrapper2 = Bootstrapper.instance()
        self.assertIsNot(bootstrapper1, bootstrapper2)

    def test_default_ivy(self):
        ivy = Bootstrapper.default_ivy()
        self.assertIsNotNone(ivy.ivy_resolution_cache_dir)
        self.assertIsNone(ivy.ivy_settings)
