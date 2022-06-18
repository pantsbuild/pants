---
title: "Concepts"
slug: "target-api-concepts"
excerpt: "The core concepts of Targets and Fields."
hidden: false
createdAt: "2020-05-07T22:38:43.975Z"
updatedAt: "2021-11-16T02:52:06.072Z"
---
The Target API defines how you interact with targets in your plugin. For example, you would use the Target API to read the `source` / `sources` field of a target to know which files to run on.

The Target API can also be used to add new target types—such as adding support for a new language. Additionally, the Target API can be used to extend existing target types.

Targets and Fields - the core building blocks
---------------------------------------------

### Definition of _target_

As described in [Targets and BUILD files](doc:targets), a _target_ is an _addressable_ set of metadata describing some of your code.

For example, this BUILD file defines a `PythonTestTarget` target with `Address("project", target_name="app_test")`.

```python project/BUILD
python_test(
    name="app_test",
    source="app_test.py",
    timeout=120,
)
```

### Definition of _field_

A _field_ is a single value of metadata belonging to a target, such as `source` and `timeout` above. (`name` is a special thing used to create the `Address`.)

Each field has a Python class that defines its BUILD file alias, data type, and optional settings like default values. For example:

```python example_fields.py
from pants.engine.target import IntField
    
class PythonTestTimeoutField(IntField):
    alias = "timeout"
    default = 60
```

### Target == alias + combination of fields

Alternatively, you can think of a target as simply an alias and a combination of fields:

```python plugin_target_types.py
from pants.engine.target import Dependencies, SingleSourceField, Target, Tags

class CustomTarget(Target):
    alias = "custom_target"
    core_fields = (SingleSourceField, Dependencies, Tags)
```

A target's fields should make sense together. For example, it does not make sense for a `python_source` target to have a `haskell_version` field.

Any unrecognized fields will cause an exception when used in a BUILD file.

### Fields may be reused

Because fields are stand-alone Python classes, the same field definition may be reused across multiple different target types.

For example, many target types have the `source` field.

```python BUILD
resource(
    name="logo",
    source="logo.png",
)

dockerfile(
    name="docker",
    source="Dockerfile",
)
```

This gives you reuse of code ([DRY](https://en.wikipedia.org/wiki/Don't_repeat_yourself)) and is important for your plugin to work with multiple different target types, as explained below.

A Field-Driven API
------------------

Idiomatic Pants plugins do not care about specific target types; they only care that the target type has the right combination of field types that the plugin needs to operate.

For example, the Python formatter Black does not actually care whether you have a `python_source`, `python_test`, or `custom_target` target; all that it cares about is that your target type has the field `PythonSourceField`. 

Targets are only [used by the Rules API](doc:rules-api-and-target-api) to get access to the underlying fields through the methods `.has_field()` and `.get()`:

```python
if target.has_field(PythonSourceField):
    print("My plugin can work on this target.")

timeout_field = target.get(PythonTestTimeoutField)
print(timeout_field.value)
```

This means that when creating new target types, the fields you choose for your target will determine the functionality it has.

Customizing fields through subclassing
--------------------------------------

Often, you may like how a field behaves, but want to make some tweaks. For example, you may want to give a default value to the `SingleSourceField` field.

To modify an existing field, simply subclass it.

```python
from pants.engine.target import SingleSourceField

class DockerSourceField(SingleSourceField):
    default = "Dockerfile"
```

The `Target` methods `.has_field()` and `.get()` understand this subclass relationship, as follows:

```python
>>> docker_tgt.has_field(DockerSourceField)
True
>>> docker_tgt.has_field(SingleSourceField)
True
>>> python_test_tgt.has_field(DockerSourceField)
False
>>> python_test_tgt.has_field(SingleSourceField)
True
```

This subclass mechanism is key to how the Target API behaves:

- You can use subclasses of fields—along with `Target.has_field()`— to filter out irrelevant targets. For example, the Black formatter doesn't work with any plain `SourcesField` field; it needs `PythonSourceField`. The Python test runner is even more specific: it needs `PythonTestSourceField`.
- You can create custom fields and custom target types that still work with pre-existing functionality. For example, you can subclass `PythonSourceField` to create `DjangoSourceField`, and the Black formatter will still be able to operate on your target.
