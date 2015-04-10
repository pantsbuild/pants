# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import tempfile
import textwrap

from twitter.common.dirutil.chroot import RelativeChroot

from pants.backend.python.sdist_builder import SdistBuilder


class CodeGenerator(object):
  class Error(Exception): pass
  class CodeGenerationException(Error): pass

  def __init__(self, target, root_dir, options, target_suffix=None):
    self.target = target
    self.options = options
    self.suffix = target_suffix or ''
    self.root = root_dir
    self.chroot = RelativeChroot(root_dir, options.for_global_scope().pants_distdir, target.name)
    codegen_root = tempfile.mkdtemp(dir=self.chroot.path(), prefix='codegen.')
    self.codegen_root = os.path.relpath(codegen_root, self.chroot.path())
    self.created_packages = set()
    self.created_namespace_packages = set()

  def __del__(self):
    self.cleanup()

  def cleanup(self):
    shutil.rmtree(self.chroot.path())

  @staticmethod
  def path_to_module(path):
    return path.replace(os.path.sep, '.')

  def package_name(self):
    return '{}{}'.format(self.target.id, self.suffix)

  def requirement_string(self):
    return '{}==0.0.0'.format(self.package_name())

  @property
  def package_dir(self):
    """Return the code generation root."""
    return '.'

  @property
  def install_requires(self):
    return []

  def generate(self):
    """Generate code for this target, updating the sets .created_packages and
       .created_namespace_packages."""
    raise NotImplementedError

  def dump_setup_py(self):
    boilerplate = textwrap.dedent("""
      from setuptools import setup

      setup(name        = "{package_name}",
            version     = "0.0.0",
            description = "autogenerated code for {target_name}",
            install_requires = {install_requires!r},
            package_dir = {{ "": {package_dir!r} }},
            packages    = {packages},
            namespace_packages = {namespace_packages})
    """)
    boilerplate = boilerplate.format(
      package_name=self.package_name().encode('utf-8'),
      package_dir=self.package_dir.encode('utf-8'),
      target_name=self.target.name.encode('utf-8'),
      install_requires=[x.encode('utf-8') for x in self.install_requires],
      packages=repr([x.encode('utf-8') for x in self.created_packages]),
      namespace_packages=repr([x.encode('utf-8') for x in self.created_namespace_packages])
    )
    self.chroot.write(boilerplate.encode('utf8'), os.path.join(self.codegen_root, 'setup.py'))
    self.chroot.write('include *.py'.encode('utf8'), os.path.join(self.codegen_root, 'MANIFEST.in'))

  @property
  def sdist_root(self):
    return os.path.join(self.chroot.path(), self.codegen_root)

  @property
  def package_root(self):
    return os.path.join(self.sdist_root, self.package_dir)

  def build(self, interpreter=None):
    self.generate()
    self.dump_setup_py()
    return SdistBuilder.build(self.sdist_root, self.target, interpreter=interpreter)
