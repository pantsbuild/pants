# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import zipfile

from pants.backend.python.rules.resolve_requirements import (ResolvedRequirementsPex,
                                                             ResolveRequirementsRequest,
                                                             resolve_requirements)
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.fs import Snapshot
from pants.engine.rules import RootRule
from pants.util.collections import assert_single_element
from pants_test.test_base import TestBase


class TestResolveRequirements(TestBase):

  @classmethod
  def rules(cls):
    return super(TestResolveRequirements, cls).rules() + [
      resolve_requirements,
      RootRule(PythonSetup),
      RootRule(PexBuildEnvironment),
      RootRule(ResolveRequirementsRequest),
    ]

  def create_pex_and_get_pex_info(
    self, requirements=None, entry_point=None, interpreter_constraints=None
  ):
    def hashify_optional_collection(iterable):
      return tuple(sorted(iterable)) if iterable is not None else tuple()

    request = ResolveRequirementsRequest(
      requirements=hashify_optional_collection(requirements),
      output_filename="test.pex",
      entry_point=entry_point,
      interpreter_constraints=hashify_optional_collection(interpreter_constraints),
    )
    requirements_pex = assert_single_element(
      self.scheduler.product_request(ResolvedRequirementsPex, [request])
    )
    snapshot = assert_single_element(
      self.scheduler.product_request(Snapshot, [requirements_pex.directory_digest])
    )
    with zipfile.ZipFile(snapshot.files[0], "r") as pex:
      with pex.open("PEX-INFO", "r") as pex_info:
        pex_info_content = pex_info.readline().decode("utf-8")
    return json.loads(pex_info_content)

  def test_resolves_dependencies(self):
    requirements = {"", "", ""}
    pex_info = self.create_pex_and_get_pex_info(requirements=requirements)
    self.assertEqual(set(pex_info[""]), requirements)

  def test_entry_point(self):
    entry_point = ""
    pex_info = self.create_pex_and_get_pex_info(entry_point=entry_point)
    self.assertEqual(pex_info["entry_point"], entry_point)

  def test_interpreter_constraints(self):
    constraints = {"CPython>=2.7,<3", "CPython>=3.6,<4"}
    pex_info = self.create_pex_and_get_pex_info(interpreter_constraints=constraints)
    self.assertEqual(set(pex_info["interpreter_constraints"]), constraints)
