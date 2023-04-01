---
title: "Plugin helpers"
slug: "plugin-helpers"
excerpt: "Helpers which make writing plugins easier."
hidden: true
createdAt: "2023-01-07T22:23:00.000Z"
---
Pants has helpers to make writing plugins easier.

# Python

## Lockfiles

The lockfiles for most Python tools fit into common categories. Pants has helpers to generate the rules for lockfile generation.

- A single Python package that could be installed with `pip install my_tool`

```python
from pants.backend.python.subsystems.python_tool_base import (
    LockfileRules,
    PythonToolBase,
)

class Isort(PythonToolBase):
    options_scope = "isort"
    ...
    lockfile_rules_type = LockfileRules.SIMPLE
```
