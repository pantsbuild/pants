# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha1

from pants.base.payload_field import (
    ExcludesField,
    FingerprintedField,
    FingerprintedMixin,
    JarsField,
    PrimitiveField,
    PrimitivesSetField,
    PythonRequirementsField,
)
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependency
from pants.python.python_requirement import PythonRequirement
from pants.testutil.test_base import TestBase
from pants.util.strutil import ensure_binary


class PayloadTest(TestBase):
    def test_excludes_field(self):
        empty = ExcludesField()
        empty_fp = empty.fingerprint()
        self.assertEqual(empty_fp, empty.fingerprint())
        normal = ExcludesField([Exclude("com", "foozle"), Exclude("org")])
        normal_fp = normal.fingerprint()
        self.assertEqual(normal_fp, normal.fingerprint())
        normal_dup = ExcludesField([Exclude("com", "foozle"), Exclude("org")])
        self.assertEqual(normal_fp, normal_dup.fingerprint())
        self.assertNotEqual(empty_fp, normal_fp)

    def test_jars_field_order(self):
        jar1 = JarDependency("com", "foo", "1.0.0")
        jar2 = JarDependency("org", "baz")

        self.assertNotEqual(
            JarsField([jar1, jar2]).fingerprint(), JarsField([jar2, jar1]).fingerprint(),
        )

    def test_jars_field_apidocs(self):
        """apidocs are not properly rolled into the cache key right now; is this intentional?"""

        jar1 = JarDependency("com", "foo", "1.0.0", apidocs="pantsbuild.github.io")
        jar2 = JarDependency("com", "foo", "1.0.0", apidocs="someother.pantsbuild.github.io")

        self.assertEqual(
            JarsField([jar1]).fingerprint(), JarsField([jar2]).fingerprint(),
        )

    def test_python_requirements_field(self):
        req1 = PythonRequirement("foo==1.0")
        req2 = PythonRequirement("bar==1.0")

        self.assertNotEqual(
            PythonRequirementsField([req1]).fingerprint(),
            PythonRequirementsField([req2]).fingerprint(),
        )

    def test_primitive_field(self):
        self.assertEqual(
            PrimitiveField({"foo": "bar"}).fingerprint(),
            PrimitiveField({"foo": "bar"}).fingerprint(),
        )
        self.assertEqual(
            PrimitiveField(["foo", "bar"]).fingerprint(),
            PrimitiveField(("foo", "bar")).fingerprint(),
        )
        self.assertEqual(
            PrimitiveField(["foo", "bar"]).fingerprint(),
            PrimitiveField(("foo", "bar")).fingerprint(),
        )
        self.assertEqual(
            PrimitiveField("foo").fingerprint(), PrimitiveField("foo").fingerprint(),
        )
        self.assertNotEqual(
            PrimitiveField("foo").fingerprint(), PrimitiveField("bar").fingerprint(),
        )

    def test_excludes_field_again(self):
        self.assertEqual(
            ExcludesField([Exclude("com", "foo")]).fingerprint(),
            ExcludesField([Exclude("com", "foo")]).fingerprint(),
        )
        self.assertEqual(
            ExcludesField([]).fingerprint(), ExcludesField().fingerprint(),
        )
        self.assertNotEqual(
            ExcludesField([Exclude("com", "foo")]).fingerprint(),
            ExcludesField([Exclude("com")]).fingerprint(),
        )
        self.assertNotEqual(
            ExcludesField([Exclude("com", "foo"), Exclude("org", "bar")]).fingerprint(),
            ExcludesField([Exclude("org", "bar"), Exclude("com", "foo")]).fingerprint(),
        )

    def test_fingerprinted_field(self):
        class TestValue(FingerprintedMixin):
            def __init__(self, test_value):
                self.test_value = test_value

            def fingerprint(self):
                hasher = sha1()
                self.test_value = ensure_binary(self.test_value)
                hasher.update(self.test_value)
                return hasher.hexdigest()

        field1 = TestValue("field1")
        field1_same = TestValue("field1")
        field2 = TestValue("field2")
        self.assertEqual(field1.fingerprint(), field1_same.fingerprint())
        self.assertNotEqual(field1.fingerprint(), field2.fingerprint())

        fingerprinted_field1 = FingerprintedField(field1)
        fingerprinted_field1_same = FingerprintedField(field1_same)
        fingerprinted_field2 = FingerprintedField(field2)
        self.assertEqual(
            fingerprinted_field1.fingerprint(), fingerprinted_field1_same.fingerprint()
        )
        self.assertNotEqual(fingerprinted_field1.fingerprint(), fingerprinted_field2.fingerprint())

    def test_set_of_primitives_field(self):
        # Should preserve `None` values.
        self.assertEqual(PrimitivesSetField(None).value, None)

        def sopf(underlying):
            return PrimitivesSetField(underlying).fingerprint()

        self.assertEqual(
            sopf({"one", "two"}), sopf({"two", "one"}),
        )
        self.assertEqual(
            sopf(["one", "two"]), sopf(["two", "one"]),
        )
        self.assertEqual(
            sopf(None), sopf(None),
        )
        self.assertNotEqual(
            sopf(None), sopf(["one"]),
        )
        self.assertNotEqual(
            sopf(None), sopf([]),
        )

    def test_unimplemented_fingerprinted_field(self):
        class TestUnimplementedValue(FingerprintedMixin):
            pass

        with self.assertRaises(NotImplementedError):
            FingerprintedField(TestUnimplementedValue()).fingerprint()
