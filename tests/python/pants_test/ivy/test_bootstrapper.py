# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

import pkg_resources

from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.testutil.subsystem.util import init_subsystem


class BootstrapperTest(unittest.TestCase):
    def setUp(self):
        super().setUp()
        pants_ivy_settings = pkg_resources.resource_filename(
            __name__, "../../build-support/ivy/ivysettings.xml"
        )
        # This ivy settings contains the RBE maven mirror that gets around maven blacklisting.
        init_subsystem(IvySubsystem, {"ivy": {"bootstrap_ivy_settings": pants_ivy_settings}})

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
