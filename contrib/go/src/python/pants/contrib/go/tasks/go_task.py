# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import re
import subprocess
from collections import namedtuple

from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.task.task import Task
from pants.util.memo import memoized_method, memoized_property
from twitter.common.collections.orderedset import OrderedSet

from pants.contrib.go.subsystems.go_distribution import GoDistribution
from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_local_source import GoLocalSource
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.targets.go_target import GoTarget


class GoTask(Task):

  @classmethod
  def global_subsystems(cls):
    return super(GoTask, cls).global_subsystems() + (GoDistribution.Factory,)

  @staticmethod
  def is_binary(target):
    return isinstance(target, GoBinary)

  @staticmethod
  def is_local_lib(target):
    return isinstance(target, GoLibrary)

  @staticmethod
  def is_remote_lib(target):
    return isinstance(target, GoRemoteLibrary)

  @staticmethod
  def is_local_src(target):
    return isinstance(target, GoLocalSource)

  @staticmethod
  def is_go(target):
    return isinstance(target, GoTarget)

  @memoized_property
  def go_dist(self):
    return GoDistribution.Factory.global_instance().create()

  @memoized_property
  def import_oracle(self):
    """Return an import oracle that can help look up and categorize imports.

    :rtype: :class:`ImportOracle`
    """
    return ImportOracle(go_dist=self.go_dist, workunit_factory=self.context.new_workunit)

  @memoized_property
  def goos_goarch(self):
    """Return concatenated $GOOS and $GOARCH environment variables, separated by an underscore.

    Useful for locating where the Go compiler is placing binaries ("$GOPATH/pkg/$GOOS_$GOARCH").

    :rtype: string
    """
    return '{goos}_{goarch}'.format(goos=self._lookup_go_env_var('GOOS'),
                                    goarch=self._lookup_go_env_var('GOARCH'))

  def _lookup_go_env_var(self, var):
    return self.go_dist.create_go_cmd('env', args=[var]).check_output().strip()


class ImportOracle(object):
  """Answers questions about Go imports."""

  class ListDepsError(Exception):
    """Indicates a problem listing import paths for one or more packages."""

  def __init__(self, go_dist, workunit_factory):
    self._go_dist = go_dist
    self._workunit_factory = workunit_factory

  @memoized_property
  def go_stdlib(self):
    """Return the set of all Go standard library import paths.

    :rtype: frozenset of string
    """
    out = self._go_dist.create_go_cmd('list', args=['std']).check_output()
    return frozenset(out.strip().split())

  # This simple regex mirrors the behavior of the relevant go code in practice (see
  # repoRootForImportDynamic and surrounding code in
  # https://github.com/golang/go/blob/7bc40ffb05d8813bf9b41a331b45d37216f9e747/src/cmd/go/vcs.go).
  _remote_import_re = re.compile('[^.]+(?:\.[^.]+)+\/')

  def is_remote_import(self, import_path):
    """Whether the specified import_path denotes a remote import."""
    return self._remote_import_re.match(import_path) is not None

  def is_go_internal_import(self, import_path):
    """Return `True` if the given import path will be satisfied directly by the Go distribution.

    For example, both the go standard library ("archive/tar", "bufio", "fmt", etc.) and "C" imports
    are satisfiable by a Go distribution via linking of internal Go code and external c standard
    library code respectively.

    :rtype: bool
    """
    # The "C" package is a psuedo-package that links through to the c stdlib, see:
    #   http://blog.golang.org/c-go-cgo
    return import_path == 'C' or import_path in self.go_stdlib

  class ImportListing(namedtuple('ImportListing', ['pkg_name',
                                                   'imports',
                                                   'test_imports',
                                                   'x_test_imports'])):
    """Represents all the imports of a given package."""

    @property
    def all_imports(self):
      """Return all imports for this package, including any test imports.

      :rtype: list of string
      """
      return list(OrderedSet(self.imports + self.test_imports + self.x_test_imports))

  @memoized_method
  def list_imports(self, pkg, gopath=None):
    """Return a listing of the dependencies of the given package.

    :param string pkg: The package whose files to list all dependencies of.
    :param string gopath: An optional $GOPATH which points to a Go workspace containing `pkg`.
    :returns: The import listing for `pkg` that represents all its dependencies.
    :rtype: :class:`ImportOracle.ImportListing`
    :raises: :class:`ImportOracle.ListDepsError` if there was a problem listing the dependencies
             of `pkg`.
    """
    go_cmd = self._go_dist.create_go_cmd('list', args=['-json', pkg], gopath=gopath)
    with self._workunit_factory(pkg, cmd=str(go_cmd), labels=[WorkUnitLabel.TOOL]) as workunit:
      # TODO(John Sirois): It would be nice to be able to tee the stdout to the workunit to we have
      # a capture of the json available for inspection in the server console.
      process = go_cmd.spawn(stdout=subprocess.PIPE, stderr=workunit.output('stderr'))
      out, _ = process.communicate()
      returncode = process.returncode
      workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)
      if returncode != 0:
        raise self.ListDepsError('Problem listing imports for {}: {} failed with exit code {}'
                                 .format(pkg, go_cmd, returncode))
      data = json.loads(out)

      # XTestImports are for black box tests.  These test files live inside the package dir but
      # declare a different package and thus can only access the public members of the package's
      # production code.  This style of test necessarily means the test file will import the main
      # package.  For pants, this would lead to a cyclic self-dependency, so we omit the main
      # package as implicitly included as its own dependency.
      x_test_imports = [i for i in data.get('XTestImports', []) if i != pkg]

      return self.ImportListing(pkg_name=data.get('Name'),
                                imports=data.get('Imports', []),
                                test_imports=data.get('TestImports', []),
                                x_test_imports=x_test_imports)
