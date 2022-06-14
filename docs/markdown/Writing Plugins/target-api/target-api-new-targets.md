---
title: "Creating new targets"
slug: "target-api-new-targets"
excerpt: "How to add a custom target type."
hidden: false
createdAt: "2020-05-07T22:38:40.570Z"
updatedAt: "2021-11-16T03:24:52.165Z"
---
[block:api-header]
{
  "title": "When to create a new target type?"
}
[/block]
Adding new target types is most helpful when you are adding support for a new language.

If you instead want to reduce boilerplate in BUILD files, such as changing default values, use [macros](doc:macros) .

If you are already using a target type, but need to store additional metadata for your plugin, [add a new field to the target type](doc:target-api-extending-targets).
[block:api-header]
{
  "title": "Step 1: Define the target type"
}
[/block]
To define a new target:

1. Subclass `pants.engine.target.Target`.
2. Define the class property `alias`. This is the symbol that people use in BUILD files.
3. Define the class property `core_fields`.
4. Define the class property `help`. This is used by `./pants help`.

For `core_fields`, we recommend including `COMMON_TARGET_FIELDS`  to add the useful `tags` and `description` fields. You will also often want to add `Dependencies`, and either `SingleSourceField` or `MultipleSourcesField`.
[block:code]
{
  "codes": [
    {
      "code": "from pants.engine.target import (\n    COMMON_TARGET_FIELDS,\n    Dependencies,\n    SingleSourceField,\n    StringField,\n    Target,\n)\n\n\nclass CustomField(StringField):\n    alias = \"custom_field\"\n    help = \"A custom field.\"\n\n\nclass CustomTarget(Target):\n    alias = \"custom_target\"\n    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, SingleSourceField, CustomField)\n    help = (\n      \"A custom target to demo the Target API.\\n\\n\"\n      \"This docstring will be used in the output of \"\n      \"`./pants help $target_type`.\"\n    )",
      "language": "python",
      "name": "plugins/target_types.py"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Tip: subclass `SingleSourceField` or `MultipleSourcesField`",
  "body": "Use `SingleSourceField` for `source: str` and `MultipleSourcesField` for `sources: Iterable[str]`.\n\nYou will often want to subclass either of these fields to give custom functionality:\n\n* set the `default`\n* set `expected_file_extensions`, e.g. to `(\".json\", \".txt\")`\n* set `expected_num_files`, e.g. to `1` or `range(0, 5)` (i.e. 0 to 4 files)"
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Using the fields of an existing target type",
  "body": "Sometimes, you may want to create a new target type that behaves similarly to one that already exists, except for some small changes. \n\nFor example, you might like how `pex_binary` behaves in general, but you have a Django application and keep writing `entry_point=\"manage.py\"`. Normally, you should write a [macro](doc:macros) to set this default value; but, here, you also want to add new Django-specific fields, so you decide to create a new target type.\n\nRather than subclassing the original target type, use this pattern:\n\n```python\nfrom pants.backend.python.target_types import PexBinaryTarget, PexEntryPointField\nfrom pants.engine.target import Target\nfrom pants.util.ordered_set import FrozenOrderedSet\n\nclass DjangoEntryPointField(PexEntryPointField):\n   default = \"manage.py\"\n\n\nclass DjangoManagePyTarget(Target):\n   alias = \"django_manage_py\"\n   core_fields = (\n       *(FrozenOrderedSet(PexBinaryTarget.core_fields) - {PexEntryPoint}),\n       DjangoEntryPointField,\n   )\n```\n\nIn this example, we register all of the fields of `PexBinaryTarget`, except for the field `PexEntryPoint `. We instead register our custom field `DjangoEntryPointField `."
}
[/block]

[block:api-header]
{
  "title": "Step 2: Register the target type in `register.py`"
}
[/block]
Now, in your [`register.py`](doc:plugins-overview), add the target type to the `def target_types()` entry point.
[block:code]
{
  "codes": [
    {
      "code": "from plugins.target_types import CustomTarget\n\ndef target_types():\n    return [CustomTarget]",
      "language": "python",
      "name": "plugins/register.py"
    }
  ]
}
[/block]
You can confirm this works by running `./pants help custom_target`.