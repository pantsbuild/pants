---
title: "Extending existing targets"
slug: "target-api-extending-targets"
excerpt: "Adding new fields to target types."
hidden: false
createdAt: "2020-05-07T22:38:39.512Z"
---
When to add new fields?
-----------------------

Adding new fields is useful when you are already using a target type, but need to store additional metadata for your plugin.

For example, if you're writing a codegen plugin to convert a `protobuf_source` target into Java source files, you may want to add a `jdk_version` field to `protobuf_source`.

If you are instead adding support for a new language, [create a new target type](doc:target-api-new-targets).

If you want to reduce boilerplate in BUILD files, such as changing default values, use [macros](doc:macros).

How to add new fields
---------------------

First, [define the field](doc:target-api-new-fields). Then, register it by using `OriginalTarget.register_plugin_field(CustomField)`, like this:

```python plugins/register.py
from pants.backend.codegen.protobuf.target_types import ProtobufSourceTarget
from pants.engine.target import IntField


class ProtobufJdkVersionField(IntField):
    alias = "jdk_version"
    default = 11
    help = "Which JDK protobuf should target."


def rules():
    return [ProtobufSourceTarget.register_plugin_field(ProtobufJdkVersionField)]
```

To confirm this worked, run `pants help protobuf_source`.
