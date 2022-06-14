---
title: "Extending existing targets"
slug: "target-api-extending-targets"
excerpt: "Adding new fields to target types."
hidden: false
createdAt: "2020-05-07T22:38:39.512Z"
updatedAt: "2022-02-24T02:54:42.625Z"
---
[block:api-header]
{
  "title": "When to add new fields?"
}
[/block]
Adding new fields is useful when you are already using a target type, but need to store additional metadata for your plugin.

For example, if you're writing a codegen plugin to convert a `protobuf_source` target into Java source files, you may want to add a `jdk_version` field to `protobuf_source`.

If you are instead adding support for a new language, [create a new target type](doc:target-api-new-targets).

If you want to reduce boilerplate in BUILD files, such as changing default values, use [macros](doc:macros).
[block:api-header]
{
  "title": "How to add new fields"
}
[/block]
First, [define the field](doc:target-api-new-fields). Then, register it by using `OriginalTarget.register_plugin_field(CustomField)`, like this:
[block:code]
{
  "codes": [
    {
      "code": "from pants.backend.codegen.protobuf.target_types import ProtobufSourceTarget\nfrom pants.engine.target import IntField\n\n\nclass ProtobufJdkVersionField(IntField):\n    alias = \"jdk_version\"\n    default = 11\n    help = \"Which JDK protobuf should target.\"\n\n\ndef rules():\n    return [ProtobufSourceTarget.register_plugin_field(ProtobufJdkVersionField)]",
      "language": "python",
      "name": "plugins/register.py"
    }
  ]
}
[/block]
To confirm this worked, run `./pants help protobuf_source`.