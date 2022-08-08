# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import StringField, StringSequenceField, Target


class TargetField(StringField):
    alias = "target"
    help = "Address of the targets to run match the rule on"
    required = True


class AllowedTargetsField(StringSequenceField):
    alias = "allowed_targets"
    help = "The list of targets allowed for the dependency rule"
    required = True


class DependencyRuleTarget(Target):
    alias = "dependency_rule"
    core_fields = (TargetField, AllowedTargetsField)
    help = "Enforce allowed dependencies for targets"
