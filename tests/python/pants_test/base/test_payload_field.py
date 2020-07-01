# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha1

from pants.base.payload_field import (
    FingerprintedField,
    FingerprintedMixin,
    PrimitiveField,
    PrimitivesSetField,
    PythonRequirementsField,
)
from pants.python.python_requirement import PythonRequirement
from pants.testutil.test_base import TestBase
from pants.util.strutil import ensure_binary


class PayloadTest(TestBase):
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
