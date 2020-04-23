# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Create AWS Lambdas from Python code."""

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.awslambda.python.target_types import PythonAWSLambda
from pants.contrib.awslambda.python.targets.python_awslambda import (
    PythonAWSLambda as PythonAWSLambdaV1,
)
from pants.contrib.awslambda.python.tasks.lambdex_prep import LambdexPrep
from pants.contrib.awslambda.python.tasks.lambdex_run import LambdexRun


def build_file_aliases():
    return BuildFileAliases(targets={"python_awslambda": PythonAWSLambdaV1})


def register_goals():
    task(name="lambdex-prep", action=LambdexPrep).install("bundle")
    task(name="lambdex-run", action=LambdexRun).install("bundle")


def target_types():
    return [PythonAWSLambda]
