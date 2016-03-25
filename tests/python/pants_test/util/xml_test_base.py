# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap
import unittest
from contextlib import contextmanager

from pants.util.contextutil import temporary_file


class XmlTestBase(unittest.TestCase):
  """Base class for tests that parse xml."""

  @contextmanager
  def xml_file(self,
               manifest_element='manifest',
               package_attribute='package',
               package_value='org.pantsbuild.example.hello',
               uses_sdk_element='uses-sdk',
               android_attribute='android:targetSdkVersion',
               activity_element='activity',
               android_name_attribute='android:name',
               application_name_value='org.pantsbuild.example.hello.HelloWorld'):
    """Represent an .xml file (Here an AndroidManifest.xml is used)."""
    with temporary_file() as fp:
      fp.write(textwrap.dedent(
        """<?xml version="1.0" encoding="utf-8"?>
        <{manifest} xmlns:android="http://schemas.android.com/apk/res/android"
                    xmlns:unrelated="http://schemas.android.com/apk/res/android"
            {package}="{package_name}" >
            <{uses_sdk}
                {android}="19" />
            <application >
                <{activity}
                    {android_name}="{application_name}" >
                </{activity}>
            </application>
        </{manifest}>""".format(manifest=manifest_element,
                                package=package_attribute,
                                package_name=package_value,
                                uses_sdk=uses_sdk_element,
                                android=android_attribute,
                                activity=activity_element,
                                android_name=android_name_attribute,
                                application_name=application_name_value)))
      fp.close()
      path = fp.name
      yield path
