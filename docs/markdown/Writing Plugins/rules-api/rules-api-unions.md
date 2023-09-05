---
title: "Union rules (advanced)"
slug: "rules-api-unions"
excerpt: "Polymorphism for the engine."
hidden: false
createdAt: "2020-05-08T04:15:07.104Z"
---
Union rules solve the same problem that polymorphism solves in general: how to write generic code that operates on types not known about at the time of writing.

For example, Pants has many generic goals like `lint` and `test`. Those `@goal_rule` definitions cannot know about every concrete linter or test implementation ahead-of-time.

Unions allow a specific linter to be registered with `UnionRule(LintTargetsRequest, ShellcheckRequest)`, and then for `lint.py` to access its type:

```python pants/core/goals/lint.py
from pants.engine.rules import Get, MultiGet, goal_rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership

..

@goal_rule
async def lint(..., targets: Targets, union_membership: UnionMembership) -> Lint:
    lint_request_types = union_membership[LintTargetsRequest]
    concrete_requests = [
        request_type(
            request_type.field_set_type.create(target)
            for target in targets
            if request_type.field_set_type.is_valid(target)
        )
        for request_type in lint_request_types
    ]
    results = await MultiGet(
        Get(LintResults, LintTargetsRequest, concrete_request)
        for concrete_request in concrete_requests
    )
```

```python pants-plugins/bash/shellcheck.py
from pants.core.goals.lint import LintTargetsRequest


class ShellcheckRequest(LintTargetsRequest):
    ...


...


def rules():
    return [*ShellcheckRequest.rules()]
```

This example will find all registered linter implementations by looking up `union_membership[LintTargetsRequest]`, which returns a tuple of all `LintTargetsRequest ` types that were registered with a `UnionRule`, such as `ShellcheckRequest` and `Flake8Request`.

How to create a new Union
-------------------------

To set up a new union, create a class for the union "base". Typically, this should be an [abstract class](https://docs.python.org/3/library/abc.html) that is subclassed by the union members, but it does not need to be. Mark the class with `@union`.

```python
from abc import ABC, abstractmethod

from pants.engine.unions import union

@union
class Vehicle(ABC):
   @abstractmethod
   def num_wheels(self) -> int:
        pass
```

Then, register every implementation of your union with `UnionRule`:

```python
class Truck(Vehicle):
    def num_wheels(self) -> int:
        return 4

def rules():
    return [UnionRule(Vehicle, Truck)]
```

Now, your rules can request `UnionMembership` as a parameter in the `@rule`, and then look up `union_membership[Vehicle]` to get a tuple of all relevant types that are registered via `UnionRule`.
