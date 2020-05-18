# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest.mock
from hashlib import sha1
from pathlib import Path

from pants.base.exceptions import TargetDefinitionException
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.payload import Payload
from pants.base.payload_field import PrimitivesSetField
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.build_graph.target_scopes import Scopes
from pants.source.wrapped_globs import Globs
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase


class ImplicitSourcesTestingTarget(Target):
    default_sources_globs = "*.foo"


class ImplicitSourcesTestingTargetMulti(Target):
    default_sources_globs = ("*.foo", "*.bar")
    default_sources_exclude_globs = ("*.baz", "*.qux")


class SourcesTarget(Target):
    def __init__(self, sources, address=None, exports=None, **kwargs):
        payload = Payload()
        payload.add_field(
            "sources",
            self.create_sources_field(
                sources, sources_rel_path=address.spec_path, key_arg="sources"
            ),
        )
        payload.add_field("exports", PrimitivesSetField(exports or []))
        super().__init__(address=address, payload=payload, **kwargs)

    @property
    def export_specs(self):
        return self.payload.exports


class TargetTest(TestBase):
    def test_derived_from_chain(self):
        # add concrete target
        concrete = self.make_target("y:concrete", Target)

        # add synthetic targets
        syn_one = self.make_target("y:syn_one", Target, derived_from=concrete)
        syn_two = self.make_target("y:syn_two", Target, derived_from=syn_one)

        # validate
        self.assertEqual(list(syn_two.derived_from_chain), [syn_one, concrete])
        self.assertEqual(list(syn_one.derived_from_chain), [concrete])
        self.assertEqual(list(concrete.derived_from_chain), [])

    def test_is_synthetic(self):
        # add concrete target
        concrete = self.make_target("y:concrete", Target)

        # add synthetic targets
        syn_one = self.make_target("y:syn_one", Target, derived_from=concrete)
        syn_two = self.make_target("y:syn_two", Target, derived_from=syn_one)
        syn_three = self.make_target("y:syn_three", Target, synthetic=True)

        self.assertFalse(concrete.is_synthetic)
        self.assertTrue(syn_one.is_synthetic)
        self.assertTrue(syn_two.is_synthetic)
        self.assertTrue(syn_three.is_synthetic)

    def test_empty_traversable_properties(self):
        target = self.make_target(":foo", Target)
        self.assertSequenceEqual(
            [], list(target.compute_dependency_address_specs(payload=target.payload))
        )

    def test_validate_target_representation_args_invalid_exactly_one(self):
        with self.assertRaises(AssertionError):
            Target._validate_target_representation_args(None, None)

        with self.assertRaises(AssertionError):
            Target._validate_target_representation_args({}, Payload())

    def test_validate_target_representation_args_invalid_type(self):
        with self.assertRaises(AssertionError):
            Target._validate_target_representation_args(kwargs=Payload(), payload=None)

        with self.assertRaises(AssertionError):
            Target._validate_target_representation_args(kwargs=None, payload={})

    def test_validate_target_representation_args_valid(self):
        Target._validate_target_representation_args(kwargs={}, payload=None)
        Target._validate_target_representation_args(kwargs=None, payload=Payload())

    def test_illegal_kwargs(self):
        init_subsystem(Target.Arguments)
        with self.assertRaises(Target.Arguments.UnknownArgumentError) as cm:
            self.make_target("foo:bar", Target, foobar="barfoo")
        self.assertTrue("foobar = barfoo" in str(cm.exception))
        self.assertTrue("foo:bar" in str(cm.exception))

    def test_unknown_kwargs(self):
        options = {Target.Arguments.options_scope: {"ignored": {"Target": ["foobar"]}}}
        init_subsystem(Target.Arguments, options)
        target = self.make_target("foo:bar", Target, foobar="barfoo")
        self.assertFalse(hasattr(target, "foobar"))

    def test_tags_applied_from_configured_dict(self):
        options = {
            Target.TagAssignments.options_scope: {
                "tag_targets_mappings": {
                    "special_tag": ["foo:bar", "path/to/target:foo", "path/to/target"],
                    "special_tag2": ["path/to/target:target", "//base:foo"],
                    "nonexistent_target_tag": ["i/dont/exist"],
                }
            }
        }

        init_subsystem(Target.TagAssignments, options)
        target1 = self.make_target("foo:bar", Target, tags=["tag1", "tag2"])
        target2 = self.make_target("path/to/target:foo", Target, tags=["tag1"])
        target3 = self.make_target("path/to/target", Target, tags=["tag2"])
        target4 = self.make_target("//base:foo", Target, tags=["tag3"])
        target5 = self.make_target("baz:qux", Target, tags=["tag3"])

        self.assertEqual({"tag1", "tag2", "special_tag"}, target1.tags)
        self.assertEqual({"tag1", "special_tag"}, target2.tags)
        self.assertEqual({"tag2", "special_tag", "special_tag2"}, target3.tags)
        self.assertEqual({"tag3", "special_tag2"}, target4.tags)
        self.assertEqual({"tag3"}, target5.tags)

    def test_target_id_long(self):
        long_path = "dummy"
        for i in range(1, 30):
            long_path = Path(long_path, f"dummy{i}")
        long_target = self.make_target(f"{long_path}:foo", Target)
        long_id = long_target.id
        self.assertEqual(len(long_id), 100)
        self.assertTrue(long_id.startswith("dummy.dummy1."))
        self.assertTrue(long_id.endswith(".dummy28.dummy29.foo"))

    def test_target_id_short(self):
        short_path = "dummy"
        for i in range(1, 10):
            short_path = Path(short_path, f"dummy{i}")
        short_target = self.make_target(f"{short_path}:foo", Target)
        short_id = short_target.id
        self.assertEqual(
            short_id, "dummy.dummy1.dummy2.dummy3.dummy4.dummy5.dummy6.dummy7.dummy8.dummy9.foo"
        )

    def test_create_sources_field_with_string_fails(self):
        target = self.make_target(":a-target", Target)

        # No key_arg.
        with self.assertRaises(TargetDefinitionException) as cm:
            target.create_sources_field(sources="a-string", sources_rel_path="")
        self.assertIn(
            "Expected a glob, an address or a list, but was <class 'str'>", str(cm.exception)
        )

        # With key_arg.
        with self.assertRaises(TargetDefinitionException) as cm:
            target.create_sources_field(
                sources="a-string", sources_rel_path="", key_arg="my_cool_field"
            )
        self.assertIn(
            "Expected 'my_cool_field' to be a glob, an address or a list, but was <class 'str'>",
            str(cm.exception),
        )
        # could also test address case, but looks like nothing really uses it.

    def test_max_recursion(self):
        target_a = self.make_target("a", Target)
        target_b = self.make_target("b", Target, dependencies=[target_a])
        self.make_target("c", Target, dependencies=[target_b])
        target_a.inject_dependency(Address.parse("c"))
        with self.assertRaises(Target.RecursiveDepthError):
            target_a.transitive_invalidation_hash()

    def test_transitive_invalidation_hash(self):
        target_a = self.make_target("a", Target)
        target_b = self.make_target("b", Target, dependencies=[target_a])
        target_c = self.make_target("c", Target, dependencies=[target_b])

        hasher = sha1()
        dep_hash = hasher.hexdigest()[:12]
        target_hash = target_a.invalidation_hash()
        hash_value = f"{target_hash}.{dep_hash}"
        self.assertEqual(hash_value, target_a.transitive_invalidation_hash())

        hasher = sha1()
        hasher.update(hash_value.encode())
        dep_hash = hasher.hexdigest()[:12]
        target_hash = target_b.invalidation_hash()
        hash_value = f"{target_hash}.{dep_hash}"
        self.assertEqual(hash_value, target_b.transitive_invalidation_hash())

        hasher = sha1()
        hasher.update(hash_value.encode())
        dep_hash = hasher.hexdigest()[:12]
        target_hash = target_c.invalidation_hash()
        hash_value = f"{target_hash}.{dep_hash}"
        self.assertEqual(hash_value, target_c.transitive_invalidation_hash())

        # Check direct invalidation.
        class TestFingerprintStrategy(DefaultFingerprintStrategy):
            def direct(self, target):
                return True

        fingerprint_strategy = TestFingerprintStrategy()
        hasher = sha1()
        hasher.update(
            target_b.invalidation_hash(fingerprint_strategy=fingerprint_strategy).encode()
        )
        dep_hash = hasher.hexdigest()[:12]
        target_hash = target_c.invalidation_hash(fingerprint_strategy=fingerprint_strategy)
        hash_value = f"{target_hash}.{dep_hash}"
        self.assertEqual(
            hash_value,
            target_c.transitive_invalidation_hash(fingerprint_strategy=fingerprint_strategy),
        )

    def test_has_sources(self):
        def sources(rel_path, *args):
            return Globs.create_fileset_with_spec(rel_path, *args)

        self.create_file("foo/bar/a.txt", "a_contents")

        txt_sources = self.make_target(
            "foo/bar:txt", SourcesTarget, sources=sources("foo/bar", "*.txt")
        )
        self.assertTrue(txt_sources.has_sources())
        self.assertTrue(txt_sources.has_sources(".txt"))
        self.assertFalse(txt_sources.has_sources(".rs"))

        no_sources = self.make_target(
            "foo/bar:none", SourcesTarget, sources=sources("foo/bar", "*.rs")
        )
        self.assertFalse(no_sources.has_sources())
        self.assertFalse(no_sources.has_sources(".txt"))
        self.assertFalse(no_sources.has_sources(".rs"))

    def _generate_strict_dependencies(self):
        init_subsystem(Target.Arguments)
        self.lib_aa = self.make_target(
            "com/foo:AA", target_type=SourcesTarget, sources=["com/foo/AA.scala"],
        )

        self.lib_a = self.make_target(
            "com/foo:A", target_type=SourcesTarget, sources=["com/foo/A.scala"],
        )

        self.lib_b = self.make_target(
            "com/foo:B",
            target_type=SourcesTarget,
            sources=["com/foo/B.scala"],
            dependencies=[self.lib_a, self.lib_aa],
            exports=[":A"],
        )

        self.lib_c = self.make_target(
            "com/foo:C",
            target_type=SourcesTarget,
            sources=["com/foo/C.scala"],
            dependencies=[self.lib_b],
            exports=[":B"],
        )

        self.lib_c_alias = self.make_target("com/foo:C_alias", dependencies=[self.lib_c],)

        self.lib_d = self.make_target(
            "com/foo:D",
            target_type=SourcesTarget,
            sources=["com/foo/D.scala"],
            dependencies=[self.lib_c_alias],
            exports=[":C_alias"],
        )

        self.lib_f = self.make_target(
            "com/foo:F",
            target_type=SourcesTarget,
            sources=["com/foo/E.scala"],
            scope=Scopes.RUNTIME,
        )

        self.lib_e = self.make_target(
            "com/foo:E",
            target_type=SourcesTarget,
            sources=["com/foo/E.scala"],
            dependencies=[self.lib_d, self.lib_f],
        )

    def test_strict_dependencies(self):
        self._generate_strict_dependencies()
        dep_context = unittest.mock.Mock()
        dep_context.types_with_closure = ()
        dep_context.codegen_types = ()
        dep_context.alias_types = (Target,)
        dep_context.target_closure_kwargs = {"include_scopes": Scopes.JVM_COMPILE_SCOPES}
        self.assertEqual(
            set(self.lib_b.strict_dependencies(dep_context)), {self.lib_a, self.lib_aa}
        )
        self.assertEqual(set(self.lib_c.strict_dependencies(dep_context)), {self.lib_b, self.lib_a})
        self.assertEqual(
            set(self.lib_c_alias.strict_dependencies(dep_context)),
            {self.lib_c, self.lib_b, self.lib_a},
        )
        self.assertEqual(
            set(self.lib_d.strict_dependencies(dep_context)), {self.lib_c, self.lib_b, self.lib_a}
        )
        self.assertEqual(
            set(self.lib_e.strict_dependencies(dep_context)),
            {self.lib_d, self.lib_c, self.lib_b, self.lib_a},
        )
