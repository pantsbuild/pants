# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import unittest

from pants.testutil.subsystem.util import init_subsystem

from pants.contrib.python.checks.checker.common import CheckstylePlugin
from pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base import (
    PluginSubsystemBase,
    default_subsystem_for_plugin,
)


class Plugin(CheckstylePlugin):
    @classmethod
    def name(cls):
        return "test-plugin"


class PluginSubsystem(PluginSubsystemBase):
    options_scope = "pycheck-test-plugin"

    @classmethod
    def plugin_type(cls):
        return Plugin

    @classmethod
    def register_plugin_options(cls, register):
        register("--bob")
        register("-j", "--jake", dest="jane")


class PluginSubsystemBaseTest(unittest.TestCase):
    def assert_options(self, subsystem_type, **input_opts):
        expected = {"skip": True}
        expected.update(**input_opts)

        unexpected = {
            ("random", "global", "option", "non", "string", "key"): 42,
            "another_unneeded": 137,
        }

        opts = expected.copy()
        opts.update(unexpected)

        init_subsystem(subsystem_type, options={subsystem_type.options_scope: opts})

        subsystem_instance = subsystem_type.global_instance()
        self.assertTrue(subsystem_instance.get_options().skip)
        self.assertEqual(expected, json.loads(subsystem_instance.options_blob()))

    def test_default_subsystem_for_plugin(self):
        subsystem_type = default_subsystem_for_plugin(Plugin)
        self.assertEqual("pycheck-test-plugin", subsystem_type.options_scope)

        self.assert_options(subsystem_type)

    def test_default_subsystem_for_plugin_bad_plugin(self):
        with self.assertRaises(ValueError):
            default_subsystem_for_plugin(object)

    def test_options_blob(self):
        self.assert_options(PluginSubsystem, bob=42, jane=True)
