---
title: "Add a typechecker"
slug: "plugins-typecheck-goal"
excerpt: "How to add a new typechecker to the `check` goal."
hidden: false
createdAt: "2020-08-19T21:55:10.667Z"
updatedAt: "2022-02-14T23:39:46.585Z"
---
Adding a typechecker is almost identical to [adding a linter](doc:plugins-lint-goal), except for these differences:

1. Subclass `CheckRequest` from `pants.core.goals.check`, rather than `LintTargetsRequest`. Register a `UnionRule(CheckRequest, CustomCheckRequest)`.
2. Return `CheckResults` in your rule—which is a collection of `CheckResult` objects—rather than returning `LintResults`. Both types are defined in `pants.core.goals.check`.

The rule will look like this:

```python
from dataclasses import dataclass

from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.target import FieldSet
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class MyPyFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField


class MyPyRequest(CheckRequest):
    field_set_type = MyPyFieldSet
    name = "mypy"


@rule(desc="Typecheck using MyPy", level=LogLevel.DEBUG)
async def mypy_typecheck(request: MyPyRequest, mypy: MyPy) -> CheckResults:
    if mypy.skip:
        return CheckResults([], checker_name=request.name)
    ...
    return CheckResults(
        [CheckResult.from_fallible_process_result(result)], checker_name=request.name
    )

def rules():
    return [*collect_rules(), UnionRule(CheckRequest, MyPyRequest)]
```

Refer to [Add a linter](doc:plugins-lint-goal). See [`pants/backend/python/typecheck/mypy/rules.py`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/python/typecheck/mypy/rules.py) for an example of MyPy.