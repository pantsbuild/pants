# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
from pathlib import Path

from pants.rules.core.generate_pants_ini import GeneratePantsIni
from pants.rules.core.generate_pants_ini import rules as generate_pants_ini_rules
from pants.testutil.goal_rule_test_base import GoalRuleTestBase
from pants.version import VERSION


class GeneratePantsIniTest(GoalRuleTestBase):

  goal_cls = GeneratePantsIni

  @classmethod
  def rules(cls):
    return (*super().rules(), *generate_pants_ini_rules())

  def test_fails_if_file_already_exists(self) -> None:
    Path(self.build_root, "pants.ini").touch()
    self.execute_rule(exit_code=1)

  def _get_generated_config(self, args):
    self.execute_rule(args=args)
    pants_ini = Path(self.build_root, "pants.ini")
    assert pants_ini.exists()
    config = configparser.ConfigParser()
    config.read(pants_ini)
    return config["GLOBAL"]

  def test_generates_v1_file(self) -> None:
    global_config = self._get_generated_config(args=None)
    assert global_config["pants_version"] == VERSION
    assert global_config["v1"] == 'True'
    assert global_config["v2"] == 'False'
    assert global_config["v2_ui"] == 'False'

  def test_generates_v2_file(self) -> None:
    global_config = self._get_generated_config(args=['--v2-only'])
    assert global_config["pants_version"] == VERSION
    assert global_config["v1"] == 'False'
    assert global_config["v2"] == 'True'
    assert global_config["v2_ui"] == 'True'
