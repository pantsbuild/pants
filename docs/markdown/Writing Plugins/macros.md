---
title: "Macros"
slug: "macros"
excerpt: "Reducing boilerplate in BUILD files."
hidden: false
createdAt: "2020-05-08T04:15:04.126Z"
updatedAt: "2022-05-12T15:59:18.084Z"
---
[block:api-header]
{
  "title": "When to use a macro"
}
[/block]
Macros are useful to reduce boilerplate in BUILD files. For example, if you keep using the same value for a field, you can use a macro. 

However, also consider that introducing new symbols to BUILD files adds some indirection to your codebase, such as making it harder to follow along with the Pants docs. As with any tool, macros should be used judiciously.

Often, you can instead use the [`parametrize`](doc:targets) mechanism:
[block:code]
{
  "codes": [
    {
      "code": "shell_tests(\n    name=\"tests\",\n    shell=parametrize(\"bash\", \"zsh\"),\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
If you instead want to add support for a new language, or do something more complex than a macro allows, create a new [target type](doc:target-api-new-targets).

If you are already using a target type, but need to store additional metadata for your plugin, [add a new field to the target type](doc:target-api-extending-targets).
[block:api-header]
{
  "title": "How to add a macro"
}
[/block]
Macros are defined in Python files that act like a normal BUILD file. They have access to all the symbols you normally have registered in a BUILD file, such as all of your target types. 

Macros cannot import other modules, just like BUILD files cannot have import statements.

To define a new macro, add a function with `def` and the name of the new symbol. Usually, the last line of the macro will create a new target, like this:
[block:code]
{
  "codes": [
    {
      "code": "def python2_sources(**kwargs):\n    kwargs[\"interpreter_constraints\"] = [\"==2.7.*\"]\n    python_sources(**kwargs)\n\ndef python3_sources(**kwargs):\n    kwargs[\"interpreter_constraints\"] = [\">=3.5\"]\n    python_sources(**kwargs)",
      "language": "python",
      "name": "pants-plugins/macros.py"
    }
  ]
}
[/block]
Then, add this file to the option `[GLOBAL].build_file_prelude_globs`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbuild_file_prelude_globs = [\"pants-plugins/macros.py\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Now, in BUILD files, you can use the new macros:
[block:code]
{
  "codes": [
    {
      "code": "python2_sources(\n    name=\"app_py2\",\n    sources=[\"app_py2.py\"],\n)\n\npython3_sources(\n    name=\"app_py3\",\n    sources=[\"app_py3.py\"],\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]
A macro can create multiple targets—although often it's better to use [`parametrize`](doc:targets):
[block:code]
{
  "codes": [
    {
      "code": "def python23_tests(name, **kwargs):\n    kwargs.pop(\"interpreter_constraints\", None)\n\n    python_tests(\n        name=f\"{name}_py2\",\n        interpreter_constraints=[\"==2.7.*\"],\n        **kwargs,\n    )\n \n    python_tests(\n        name=f\"{name}_py3\",\n        interpreter_constraints=[\">=3.5\"],\n        **kwargs,\n    )\n\n",
      "language": "python",
      "name": "pants-plugins/macros.py"
    }
  ]
}
[/block]
A macro can perform validation:
[block:code]
{
  "codes": [
    {
      "code": "def custom_python_sources(**kwargs):\n    if \"2.7\" in kwargs.get(\"interpreter_constraints\", \"\"):\n        raise ValueError(\"Python 2.7 is banned!\")\n    python_sources(**kwargs)",
      "language": "python",
      "name": "pants-plugins/macros.py"
    }
  ]
}
[/block]
A macro can take new parameters to generate the target dynamically. For example:
[block:code]
{
  "codes": [
    {
      "code": "def custom_python_sources(has_type_hints: bool = True, **kwargs):\n    if has_type_hints:\n        kwargs[\"tags\"] = kwargs.get(\"tags\", []) + [\"type_checked\"]\n    python_sources(**kwargs)",
      "language": "python",
      "name": "pants-plugins/macros.py"
    },
    {
      "code": "custom_python_sources(\n    has_type_hints=False,\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]