# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.backend.jvm.register import build_file_aliases
from pants.backend.jvm.targets.jvm_binary import Duplicate, JarRules, ManifestEntries, Skip
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload_field import FingerprintedField
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.java.jar.exclude import Exclude
from pants.testutil.test_base import TestBase


class JarRulesTest(unittest.TestCase):
    def test_jar_rule(self):
        dup_rule = Duplicate("foo", Duplicate.REPLACE)
        self.assertEqual("Duplicate(apply_pattern=foo, action=REPLACE)", repr(dup_rule))
        skip_rule = Skip("foo")
        self.assertEqual("Skip(apply_pattern=foo)", repr(skip_rule))

    def test_invalid_apply_pattern(self):
        with self.assertRaisesRegex(ValueError, r"The supplied apply_pattern is not a str"):
            Skip(None)
        with self.assertRaisesRegex(ValueError, r"The supplied apply_pattern is not a str"):
            Duplicate(None, Duplicate.SKIP)
        with self.assertRaisesRegex(ValueError, r"The supplied apply_pattern: \) is not a valid"):
            Skip(r")")
        with self.assertRaisesRegex(ValueError, r"The supplied apply_pattern: \) is not a valid"):
            Duplicate(r")", Duplicate.SKIP)

    def test_bad_action(self):
        with self.assertRaisesRegex(ValueError, r"The supplied action must be one of"):
            Duplicate("foo", None)

    def test_duplicate_error(self):
        with self.assertRaisesRegex(Duplicate.Error, r"Duplicate entry encountered for path foo"):
            raise Duplicate.Error("foo")

    def test_default(self):
        jar_rules = JarRules.default()
        self.assertTrue(4, len(jar_rules.rules))
        for rule in jar_rules.rules:
            self.assertTrue(rule.apply_pattern.pattern.startswith(r"^META-INF"))

    def test_set_bad_default(self):
        with self.assertRaisesRegex(ValueError, r"The default rules must be a JarRules"):
            JarRules.set_default(None)


class JvmBinaryTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return build_file_aliases().merge(BuildFileAliases(objects={"duplicate": Duplicate}))

    def test_simple(self):
        self.add_to_build_file(
            "", 'jvm_binary(name = "foo", main = "com.example.Foo", basename = "foo-base")',
        )
        target = self.target(":foo")
        self.assertEqual("com.example.Foo", target.main)
        self.assertEqual("com.example.Foo", target.payload.main)
        self.assertEqual("foo-base", target.basename)
        self.assertEqual("foo-base", target.payload.basename)
        self.assertEqual([], target.deploy_excludes)
        self.assertEqual([], target.payload.deploy_excludes)
        self.assertEqual(JarRules.default(), target.deploy_jar_rules)
        self.assertEqual(JarRules.default(), target.payload.deploy_jar_rules)
        self.assertEqual({}, target.payload.manifest_entries.entries)

    def test_default_base(self):
        self.add_to_build_file("", 'jvm_binary(name = "foo", main = "com.example.Foo")')
        target = self.target(":foo")
        self.assertEqual("foo", target.basename)

    def test_deploy_jar_excludes(self):
        self.add_to_build_file(
            "",
            """jvm_binary(
            name = "foo",
            main = "com.example.Foo",
            deploy_excludes=[exclude(org = "example.com", name = "foo-lib")],
            )""",
        )
        target = self.target(":foo")
        self.assertEqual([Exclude(org="example.com", name="foo-lib")], target.deploy_excludes)

    def test_deploy_jar_rules(self):
        self.add_to_build_file(
            "",
            """jvm_binary(
              name = "foo",
              main = "com.example.Foo",
              deploy_jar_rules = jar_rules(
                [duplicate("foo", duplicate.SKIP)],
                default_dup_action = duplicate.FAIL,
              ),
            )""",
        )
        target = self.target(":foo")
        jar_rules = target.deploy_jar_rules
        self.assertEqual(1, len(jar_rules.rules))
        self.assertEqual("foo", jar_rules.rules[0].apply_pattern.pattern)
        self.assertEqual(
            repr(Duplicate.SKIP), repr(jar_rules.rules[0].action)
        )  # <object object at 0x...>
        self.assertEqual(Duplicate.FAIL, jar_rules.default_dup_action)

    def test_bad_sources_declaration(self):
        self.create_file("foo/foo.py")
        self.create_file("foo/bar.py")
        self.add_to_build_file(
            "foo",
            'jvm_binary(name = "foo", main = "com.example.Foo", sources = ["foo.py", "bar.py"])',
        )
        with self.assertRaisesRegex(
            AddressLookupError, r"Invalid target.*foo.*jvm_binary must have exactly 0 or 1 sources"
        ):
            self.target("foo:foo")

    def test_bad_main_declaration(self):
        self.add_to_build_file("", 'jvm_binary(name = "bar", main = ["com.example.Bar"])')
        with self.assertRaisesRegex(
            TargetDefinitionException, r"Invalid target JvmBinary.*bar.*main must be a fully"
        ):
            self.target(":bar")

    def test_bad_jar_rules(self):
        self.add_to_build_file(
            "", 'jvm_binary(name = "foo", main = "com.example.Foo", deploy_jar_rules="invalid")',
        )
        with self.assertRaisesRegex(
            TargetDefinitionException,
            r"Invalid target JvmBinary.*foo.*"
            r"deploy_jar_rules must be a JarRules specification. "
            r"got (str|unicode)",
        ):
            self.target(":foo")

    def _assert_fingerprints_not_equal(self, fields):
        for field in fields:
            for other_field in fields:
                if field == other_field:
                    continue
                self.assertNotEqual(field.fingerprint(), other_field.fingerprint())

    def test_jar_rules_field(self):
        field1 = FingerprintedField(JarRules(rules=[Duplicate("foo", Duplicate.SKIP)]))
        field1_same = FingerprintedField(JarRules(rules=[Duplicate("foo", Duplicate.SKIP)]))
        field2 = FingerprintedField(JarRules(rules=[Duplicate("foo", Duplicate.CONCAT)]))
        field3 = FingerprintedField(JarRules(rules=[Duplicate("bar", Duplicate.SKIP)]))
        field4 = FingerprintedField(
            JarRules(rules=[Duplicate("foo", Duplicate.SKIP), Duplicate("bar", Duplicate.SKIP)])
        )
        field5 = FingerprintedField(JarRules(rules=[Duplicate("foo", Duplicate.SKIP), Skip("foo")]))
        field6 = FingerprintedField(
            JarRules(rules=[Duplicate("foo", Duplicate.SKIP)], default_dup_action=Duplicate.FAIL)
        )
        field6_same = FingerprintedField(
            JarRules(rules=[Duplicate("foo", Duplicate.SKIP)], default_dup_action=Duplicate.FAIL)
        )
        field7 = FingerprintedField(JarRules(rules=[Skip("foo")]))
        field8 = FingerprintedField(JarRules(rules=[Skip("bar")]))
        field8_same = FingerprintedField(JarRules(rules=[Skip("bar")]))

        self.assertEqual(field1.fingerprint(), field1_same.fingerprint())
        self.assertEqual(field6.fingerprint(), field6_same.fingerprint())
        self.assertEqual(field8.fingerprint(), field8_same.fingerprint())
        self._assert_fingerprints_not_equal(
            [field1, field2, field3, field4, field5, field6, field7]
        )

    def test_manifest_entries(self):
        self.add_to_build_file(
            "",
            """jvm_binary(
              name = "foo",
              main = "com.example.Foo",
              manifest_entries = {"Foo-Field": "foo"},
            )""",
        )
        target = self.target(":foo")
        self.assertTrue(isinstance(target.payload.manifest_entries, ManifestEntries))
        entries = target.payload.manifest_entries.entries
        self.assertEqual({"Foo-Field": "foo"}, entries)

    def test_manifest_not_dict(self):
        self.add_to_build_file(
            "",
            """jvm_binary(
              name = "foo",
              main = "com.example.Foo",
              manifest_entries = "foo",
            )""",
        )
        with self.assertRaisesRegex(
            TargetDefinitionException,
            r"Invalid target JvmBinary.*foo.*: manifest_entries must be a "
            r"dict. got (str|unicode)",
        ):
            self.target(":foo")

    def test_manifest_bad_key(self):
        self.add_to_build_file(
            "",
            """jvm_binary(
              name = "foo",
              main = "com.example.Foo",
              manifest_entries = {jar("bad", "bad", "bad"): "foo"},
            )""",
        )
        with self.assertRaisesRegex(
            TargetDefinitionException,
            r"entries must be dictionary of strings, got key .* " r"type JarDependency",
        ):
            self.target(":foo")

    def test_manifest_entries_fingerprint(self):
        field1 = ManifestEntries()
        field2 = ManifestEntries({"Foo-Field": "foo"})
        field2_same = ManifestEntries({"Foo-Field": "foo"})
        field3 = ManifestEntries({"Foo-Field": "foo", "Bar-Field": "bar"})
        self.assertEqual(field2.fingerprint(), field2_same.fingerprint())
        self._assert_fingerprints_not_equal([field1, field2, field3])
