# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


import os
import pytest
import unittest

from twitter.common.contextutil import temporary_file

from pants.backend.android.tasks.aapt_gen import AaptGen



class AaptGenCalculateGenfilesTestBase(unittest.TestCase):
  def assert_files(self, rel_path, package, expected_file):
    self.assertEqual(expected_file, AaptGen._calculate_genfile(os.path.join(rel_path, 'bin'),
                                                                       package))


class AaptGenCalculateJavaTest(AaptGenCalculateGenfilesTestBase):

  def assert_java_files(self, rel_path, contents, *expected_files):
    self.assert_files( rel_path, contents, *expected_files)

  def test_plain(self):
    self.assert_java_files(
      'out',
      'com.pants.examples.hello',
      'out/bin/com/pants/examples/hello')


#
# class AaptGenTestBase(unittest.TestCase):
#   """Basically copied from test_protobuf_gen.py.
#
#   Contains helper method to check generated temp files.
#   """
#   def assert_files(self, package, contents, *expected_files):
#     with temporary_file() as fp:
#       fp.write(contents)
#       fp.close()
#       self.assertEqual(set(expected_files), set(AaptGen._calculate_genfile(fp.name, package)))
#
#   def create_manifest(self, name):
#      return (
#        '''<?xml version="1.0" encoding="utf-8"?>
#           <manifest xmlns:android="http://schemas.android.com/apk/res/android"
#             package="com.pants.examples.{name}"
#             <uses-sdk
#               android:minSdkVersion="8"
#               android:targetSdkVersion="19" />
#           </manifest>'''.format(name=name)
#      )
#
# class AaptGenJavaTest(AaptGenTestBase):
#   """Test the java code generation.
#
#   Mostly just tests that code would be put in the proper package, since that's the easiest point of
#   failure.
#   """
#
#   def test_plain(self):
#     self.assert_files(
#       'com.pants.example',
#       self.create_manifest('hello'),
#       'bin/com/pants/examples/hello'
#     )
  #
  # def test_slashes(self):
  #   self.assert_files(
  #     'com/actual/package',
  #     self.create_manifest('ComplicatedVegetable', 'Orange', 'Apple', 'Aardvark'),
  #     'com/actual/package/ObjectFactory.java',
  #     'com/actual/package/ComplicatedVegetable.java',
  #     'com/actual/package/Orange.java',
  #     'com/actual/package/Aardvark.java',
  #     'com/actual/package/Apple.java'
  #   )
  #
  # def test_leadtail(self):
  #   self.assert_files(
  #     '/com/actual/package/',
  #     self.create_manifest('ComplicatedVegetable', 'Orange', 'Apple', 'Aardvark'),
  #     'com/actual/package/ObjectFactory.java',
  #     'com/actual/package/ComplicatedVegetable.java',
  #     'com/actual/package/Orange.java',
  #     'com/actual/package/Aardvark.java',
  #     'com/actual/package/Apple.java'
  #   )
# import os
# import pytest
# from textwrap import dedent
# import unittest2
#
# from twitter.common.contextutil import temporary_file
# from twitter.common.dirutil import safe_mkdir
#
# from pants.backend.android.targets.android_resources import AndroidResources
# from pants.backend.android.tasks.aapt_gen import AaptGen
# from pants.base.build_file_aliases import BuildFileAliases
# from pants_test.base_test import BaseTest
#
#
# class AaptGenCalculateGenfilesTestBase(BaseTest):
  # def assert_files(self, contents, expected_name):
  #   with temporary_file() as fp:
  #     fp.write(contents)
  #     fp.close()
  #     self.assertEqual(expected_name, AaptGen.package_path(package))
  #
  # def create_xml(self, name):
  #   return (
  #     '''<?xml version="1.0" encoding="utf-8"?>
  #        <manifest xmlns:android="http://schemas.android.com/apk/res/android"
  #          package="com.pants.examples.{name}"
  #          <uses-sdk
  #            android:minSdkVersion="8"
  #            android:targetSdkVersion="19" />
  #        </manifest>'''.format(name=name)
  #   )
  #

  #
  #
  # @property
  # def alias_groups(self):
  #   return BuildFileAliases.create(targets={'android_resources': AndroidResources})
  #
  # def test_validate(self):
  #
  #   self.add_to_build_file('test_validate', dedent('''
  #       android_resources(name='one',
  #         sources=[],
  #         dependencies=[],
  #       )
  #     '''))
  #
  #   self.add_to_build_file('test_validate', dedent('''
  #       android_resources(name='two',
  #         sources=[],
  #         dependencies=[':one'],
  #       )
  #     '''))
  #
  #   self.add_to_build_file('test_validate', dedent('''
  #       android_resources(name='three',
  #         sources=[],
  #         dependencies=[':red'],
  #       )
#   #     '''))
# from contextlib import contextmanager
# from mock import Mock
# import pytest
# import os
# from textwrap import dedent
#
# from twitter.common.contextutil import temporary_dir, temporary_file
# #from pants.base.exceptions import TaskError
#
# from pants_test.base_test import BaseTest
# from pants_test.tasks.test_base import prepare_task
# from pants.backend.android.distribution import AndroidDistribution
# from pants.backend.android.tasks.aapt_gen import AaptGen
# from pants.backend.android.targets.android_resources import AndroidResources
# from pants.base.build_file_aliases import BuildFileAliases
#
# class AaptGenTest(BaseTest):
#   @property
#   def alias_groups(self):
#     return BuildFileAliases.create(targets={'android_resources': AndroidResources})
#
#   @contextmanager
#   def mock_manifest(self, contents):
#     with temporary_file() as fd:
#      fd.write(contents)
#      fd.close()
#      yield fd.name
#
#   contents = dedent('''
#         <?xml version="1.0" encoding="utf-8"?>
#            <manifest xmlns:android="http://schemas.android.com/apk/res/android"
#             package="com.pants.examples.{name}"
#               <uses-sdk
#               android:minSdkVersion="8"
#               android:targetSdkVersion="19" />
#           </manifest>
#   ''')
#
#   def test_smoke_aapt(self):
#
#     contents = dedent('''
#         <?xml version="1.0" encoding="utf-8"?>
#            <manifest xmlns:android="http://schemas.android.com/apk/res/android"
#             package="com.pants.examples.{name}"
#               <uses-sdk
#               android:minSdkVersion="8"
#               android:targetSdkVersion="19" />
#           </manifest>
#     ''')
#
#     # mock_manifest = os.path.join('test_smoke/AndroidManifest.xml')
#     # self.create_file(relpath=mock_manifest, contents = contents)
#     # self.assertEquals(True, os.path.isfile(mock_manifest))
#     # self.add_to_build_file('test_smoke', dedent('''
#     #   android_resources(name='aapt_test',
#     #      manifest="{0!r},
#     #   )
#     # ''').format(mock_manifest))
#     # task = prepare_task(AaptGen,
#     #                     targets=[self.target('test_smoke:aapt_test')],
#     #                     build_graph=self.build_graph,
#     #                     build_file_parser=self.build_file_parser)
#     # #task.execute()
#     self.create_file(relpath='test_smoke/AndroidManifest.xml', contents=contents)
#     self.add_to_build_file('test_smoke', dedent('''
#       android_resources(name='a',
#       manifest='AndroidManifest.xml'
#       )
#     '''))
#     task_outdir = os.path.join(self.build_root, '.pants.d')
#     task = prepare_task(AaptGen,
#                         build_graph=self.build_graph,
#                         targets=[self.target('test_smoke:a')],
#                         build_file_parser=self.build_file_parser)


  def test_package_path(self):
     self.assertEqual(os.path.join('com', 'pants', 'example', 'tests'),
                      AaptGen.package_path('com.pants.example.tests'))
