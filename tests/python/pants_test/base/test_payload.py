# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.payload import Payload, PayloadFieldAlreadyDefinedError, PayloadFrozenError
from pants.base.payload_field import PrimitiveField
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.testutil.test_base import TestBase


class PayloadTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            targets={
                # TODO: Use a dummy task type here, instead of depending on the jvm backend.
                "java_library": JavaLibrary,
            },
        )

    def test_freeze(self):
        payload = Payload()
        payload.add_field("foo", PrimitiveField())
        payload.freeze()
        with self.assertRaises(PayloadFrozenError):
            payload.add_field("bar", PrimitiveField())

    def test_field_duplication(self):
        payload = Payload()
        payload.add_field("foo", PrimitiveField())
        payload.freeze()
        with self.assertRaises(PayloadFieldAlreadyDefinedError):
            payload.add_field("foo", PrimitiveField())

    def test_fingerprint(self):
        payload = Payload()
        payload.add_field("foo", PrimitiveField())
        fingerprint1 = payload.fingerprint()
        self.assertEqual(fingerprint1, payload.fingerprint())
        payload.add_field("bar", PrimitiveField())
        fingerprint2 = payload.fingerprint()
        self.assertNotEqual(fingerprint1, fingerprint2)
        self.assertEqual(fingerprint2, payload.fingerprint())
        payload.freeze()
        self.assertEqual(fingerprint2, payload.fingerprint())

    def test_partial_fingerprint(self):
        payload = Payload()
        payload.add_field("foo", PrimitiveField())
        fingerprint1 = payload.fingerprint()
        self.assertEqual(fingerprint1, payload.fingerprint(field_keys=("foo",)))
        payload.add_field("bar", PrimitiveField())
        fingerprint2 = payload.fingerprint()
        self.assertEqual(fingerprint1, payload.fingerprint(field_keys=("foo",)))
        self.assertNotEqual(fingerprint2, payload.fingerprint(field_keys=("foo",)))
        self.assertNotEqual(fingerprint2, payload.fingerprint(field_keys=("bar",)))
        self.assertEqual(fingerprint2, payload.fingerprint(field_keys=("bar", "foo")))

    def test_none(self):
        payload = Payload()
        payload.add_field("foo", None)
        payload2 = Payload()
        payload2.add_field("foo", PrimitiveField(None))
        self.assertNotEqual(payload.fingerprint(), payload2.fingerprint())

    def test_globs(self):
        self.add_to_build_file("y/BUILD", 'java_library(name="y", sources=["*"])')
        self.context().scan()

    def test_single_source(self):
        self.create_file("y/Source.scala")
        self.add_to_build_file("y/BUILD", 'java_library(name="y", sources=["Source.scala"])')
        self.context().scan()

    def test_missing_payload_field(self):
        payload = Payload()
        payload.add_field("foo", PrimitiveField("test-value"))
        payload.add_field("bar", PrimitiveField(None))
        self.assertEqual("test-value", payload.foo)
        self.assertEqual("test-value", payload.get_field("foo").value)
        self.assertEqual("test-value", payload.get_field_value("foo"))
        self.assertEqual(None, payload.bar)
        self.assertEqual(None, payload.get_field("bar").value)
        self.assertEqual(None, payload.get_field_value("bar"))
        self.assertEqual(None, payload.get_field("bar", default="nothing").value)
        self.assertEqual(None, payload.get_field_value("bar", default="nothing"))
        with self.assertRaises(AttributeError):
            self.assertEqual(None, payload.field_doesnt_exist)
        self.assertEqual(None, payload.get_field("field_doesnt_exist"))
        self.assertEqual(None, payload.get_field_value("field_doesnt_exist"))
        self.assertEqual("nothing", payload.get_field("field_doesnt_exist", default="nothing"))
        self.assertEqual(
            "nothing", payload.get_field_value("field_doesnt_exist", default="nothing")
        )
