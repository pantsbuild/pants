# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.wire.java.java_wire_library import JavaWireLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.testutil.test_base import TestBase


class JavaWireLibraryTest(TestBase):
    def setUp(self):
        super().setUp()

    def test_fields(self):
        target = self.make_target(
            "//:foo",
            JavaWireLibrary,
            registry_class="com.squareup.Registry",
            roots=["foo", "bar"],
            enum_options=["one", "two", "three"],
            service_writer="com.squareup.wire.RetrofitServiceWriter",
        )
        self.assertEqual("com.squareup.Registry", target.payload.get_field_value("registry_class"))
        self.assertEqual(["foo", "bar"], target.payload.get_field_value("roots"))
        self.assertEqual(["one", "two", "three"], target.payload.get_field_value("enum_options"))
        self.assertFalse(target.payload.get_field_value("no_options"))
        self.assertEqual(
            "com.squareup.wire.RetrofitServiceWriter",
            target.payload.get_field_value("service_writer"),
        )
        self.assertEqual([], target.payload.get_field_value("service_writer_options"))

    def test_wire_service_options(self):
        target = self.make_target(
            "//:wire_service_options",
            JavaWireLibrary,
            service_writer="com.squareup.wire.RetrofitServiceWriter",
            service_writer_options=["foo", "bar", "baz"],
        )
        self.assertEqual(["foo", "bar", "baz"], target.payload.service_writer_options)

    def test_invalid_service_writer_opts(self):
        with self.assertRaisesRegex(
            TargetDefinitionException, r"service_writer_options requires setting service_writer"
        ):
            self.make_target(
                "invalid:service_writer_opts",
                JavaWireLibrary,
                service_writer_options=["one", "two"],
            )
