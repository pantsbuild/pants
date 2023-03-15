---
title: "Creating new targets"
slug: "target-api-new-targets"
excerpt: "How to add a custom target type."
hidden: false
createdAt: "2020-05-07T22:38:40.570Z"
---
When to create a new target type?
---------------------------------

Adding new target types is most helpful when you are adding support for a new language.

If you instead want to reduce boilerplate in BUILD files, such as changing default values, use [macros](doc:macros) .

If you are already using a target type, but need to store additional metadata for your plugin, [add a new field to the target type](doc:target-api-extending-targets).

Step 1: Define the target type
------------------------------

To define a new target:

1. Subclass `pants.engine.target.Target`.
2. Define the class property `alias`. This is the symbol that people use in BUILD files.
3. Define the class property `core_fields`.
4. Define the class property `help`. This is used by `pants help`.

For `core_fields`, we recommend including `COMMON_TARGET_FIELDS`  to add the useful `tags` and `description` fields. You will also often want to add `Dependencies`, and either `SingleSourceField` or `MultipleSourcesField`.

```python plugins/target_types.py
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    SingleSourceField,
    StringField,
    Target,
)


class CustomField(StringField):
    alias = "custom_field"
    help = "A custom field."


class CustomTarget(Target):
    alias = "custom_target"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, SingleSourceField, CustomField)
    help = (
      "A custom target to demo the Target API.\n\n"
      "This docstring will be used in the output of "
      "`pants help $target_type`."
    )
```

> 📘 Tip: subclass `SingleSourceField` or `MultipleSourcesField`
> 
> Use `SingleSourceField` for `source: str` and `MultipleSourcesField` for `sources: Iterable[str]`.
> 
> You will often want to subclass either of these fields to give custom functionality:
> 
> - set the `default`
> - set `expected_file_extensions`, e.g. to `(".json", ".txt")`
> - set `expected_num_files`, e.g. to `1` or `range(0, 5)` (i.e. 0 to 4 files)

> 📘 Using the fields of an existing target type
> 
> Sometimes, you may want to create a new target type that behaves similarly to one that already exists, except for some small changes. 
> 
> For example, you might like how `pex_binary` behaves in general, but you have a Django application and keep writing `entry_point="manage.py"`. Normally, you should write a [macro](doc:macros) to set this default value; but, here, you also want to add new Django-specific fields, so you decide to create a new target type.
> 
> Rather than subclassing the original target type, use this pattern:
> 
> ```python
> from pants.backend.python.target_types import PexBinaryTarget, PexEntryPointField
> from pants.engine.target import Target
> from pants.util.ordered_set import FrozenOrderedSet
> 
> class DjangoEntryPointField(PexEntryPointField):
>    default = "manage.py"
> 
> 
> class DjangoManagePyTarget(Target):
>    alias = "django_manage_py"
>    core_fields = (
>        *(FrozenOrderedSet(PexBinaryTarget.core_fields) - {PexEntryPoint}),
>        DjangoEntryPointField,
>    )
> ```
> 
> In this example, we register all of the fields of `PexBinaryTarget`, except for the field `PexEntryPoint `. We instead register our custom field `DjangoEntryPointField `.

Step 2: Register the target type in `register.py`
-------------------------------------------------

Now, in your [`register.py`](doc:plugins-overview), add the target type to the `def target_types()` entry point.

```python plugins/register.py
from plugins.target_types import CustomTarget

def target_types():
    return [CustomTarget]
```

You can confirm this works by running `pants help custom_target`.
