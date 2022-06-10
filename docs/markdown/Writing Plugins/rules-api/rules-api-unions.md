---
title: "Union rules (advanced)"
slug: "rules-api-unions"
excerpt: "Polymorphism for the engine."
hidden: false
createdAt: "2020-05-08T04:15:07.104Z"
updatedAt: "2022-04-26T22:37:59.286Z"
---
Union rules solve the same problem that polymorphism solves in general: how to write generic code that operates on types not known about at the time of writing.

For example, Pants has many generic goals like `lint` and `test`. Those `@goal_rule` definitions cannot know about every concrete linter or test implementation ahead-of-time.

Unions allow a specific linter to be registered with `UnionRule(LintTargetsRequest, ShellcheckRequest)`, and then for `lint.py` to access its type:
[block:code]
{
  "codes": [
    {
      "code": "from pants.engine.rules import Get, MultiGet, goal_rule\nfrom pants.engine.target import Targets\nfrom pants.engine.unions import UnionMembership\n\n..\n\n@goal_rule\nasync def lint(..., targets: Targets, union_membership: UnionMembership) -> Lint:\n    lint_request_types = union_membership[LintTargetsRequest]\n    concrete_requests = [\n        request_type(\n            request_type.field_set_type.create(target)\n            for target in targets\n            if request_type.field_set_type.is_valid(target)\n        )\n        for request_type in lint_request_types\n    ]\n    results = await MultiGet(\n        Get(LintResults, LintTargetsRequest, concrete_request)\n        for concrete_request in concrete_requests\n    )",
      "language": "python",
      "name": "pants/core/goals/lint.py"
    },
    {
      "code": "from pants.core.goals.lint import LintRequest\n\nclass ShellcheckRequest(LintRequest):\n    ...\n\n...\n  \ndef rules():\n    return [UnionRule(LintRequest, ShellcheckRequest)",
      "language": "python",
      "name": "pants-plugins/bash/shellcheck.py"
    }
  ]
}
[/block]
This example will find all registered linter implementations by looking up `union_membership[LintTargetsRequest]`, which returns a tuple of all `LintTargetsRequest ` types that were registered with a `UnionRule`, such as `ShellcheckRequest` and `Flake8Request`.
[block:api-header]
{
  "title": "How to create a new Union"
}
[/block]
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