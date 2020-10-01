# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent
from typing import Any, Match, Optional, Tuple, Type, cast
import re

from pants.backend.python.goals.create_python_binary import (
    AlternateImplementationAck,
    PythonBinaryFieldSet,
    PythonBinaryImplementation,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, TargetRootsToFieldSets, TargetRootsToFieldSetsRequest
from pants.engine.unions import UnionRule, union
from pants.option.subsystem import Subsystem


PYTHON_RUNTIME_REGEX = r"python(?P<major>\d)\.(?P<minor>\d+)"


class AWSLambdaPythonRuntime(Enum):
    python36 = 'python3.6'
    python37 = 'python3.7'
    python38 = 'python3.8'

    def __str__(self) -> str:
        return str(self.value)

    def to_interpreter_version(self) -> Tuple[int, int]:
        """Returns the Python version implied by the runtime, as (major, minor)."""
        mo = cast(Match, re.match(PYTHON_RUNTIME_REGEX, str(self)))
        return int(mo.group("major")), int(mo.group("minor"))


class AWSLambdaSubsystem(Subsystem):
    """Configuration when generating code to upload to an AWS Lambda."""

    options_scope = "awslambda"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register('--python-runtime', type=AWSLambdaPythonRuntime, choices=list(AWSLambdaPythonRuntime),
                 default=None,
                 help='Use this version of the AWS Lambda python environment. '
                      'If set, this option will produce python outputs compatible with AWS.')

    @property
    def python_runtime(self) -> Optional[AWSLambdaPythonRuntime]:
        return cast(Optional[AWSLambdaPythonRuntime], self.options.python_runtime)


@dataclass(frozen=True)
class AWSLambdaPythonRequest(PythonBinaryImplementation):
    field_set: PythonBinaryFieldSet

    @classmethod
    def create(
        cls: Type['AWSLambdaPythonRequest'],
        field_set: PythonBinaryFieldSet,
    ) -> 'AWSLambdaPythonRequest':
        return cls(field_set)


@rule
def whether_to_use_aws_python_lambda(
    _request: AWSLambdaPythonRequest,
    awslambda: AWSLambdaSubsystem,
) -> AlternateImplementationAck:
    if awslambda.python_runtime is None:
        return AlternateImplementationAck.not_applicable
    return AlternateImplementationAck.can_be_used


def rules():
    return [*collect_rules(), UnionRule(PythonBinaryImplementation, AWSLambdaPythonRequest)]
