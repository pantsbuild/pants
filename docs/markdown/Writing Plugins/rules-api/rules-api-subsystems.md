---
title: "Options and subsystems"
slug: "rules-api-subsystems"
excerpt: "How to add options to your plugin."
hidden: false
createdAt: "2020-07-01T04:55:36.180Z"
updatedAt: "2022-04-26T22:11:07.667Z"
---
[block:api-header]
{
  "title": "Defining options"
}
[/block]
As explained in [Options](doc:options), options are partitioned into named scopes, like `[test]` and `[isort]`. Each of these scopes corresponds to a _subsystem_.

To add new options:

1. Define a subclass of `Subsystem` from `pants.subsystem.subsystem`.
    1. Set the class property `options_scope` with the name of the subsystem.
         * This value will be prepended to all options in the subsystem, e.g. `--skip` will become `--shellcheck-skip`.
    1. Set the class property `help`, which is used by `./pants help`.
2. Add new options through `pants.options.option_types` class attributes.
3. Register the `Subsystem` with `SubsystemRule` and `register.py`.
    - You don't need `SubsystemRule` if the `Subsystem` is used in an `@rule` because `collect_rules()` will recognize it. It doesn't hurt to keep this around, though.
[block:code]
{
  "codes": [
    {
      "code": "from pants.engine.rules import SubsystemRule\nfrom pants.option.option_types import BoolOption\nfrom pants.option.subsystem import Subsystem\n\n\nclass ShellcheckSubsystem(Subsystem):\n    options_scope = \"shellcheck\"\n    help = \"The Shellcheck linter.\"\n    \n    config_discovery = BoolOption(\n        \"--config-discovery\",\n        default=True,\n        advanced=True,\n        help=\"Whether Pants should...\",\n    )\n\n        \ndef rules():\n    return [SubsystemRule(ShellcheckSubsystem)]",
      "language": "python",
      "name": "pants-plugins/example/shellcheck.py"
    },
    {
      "code": "from example import shellcheck\n\ndef rules():\n    return [*shellcheck.rules()]",
      "language": "python",
      "name": "pants-plugins/example/register.py"
    }
  ]
}
[/block]
The subsystem should now show up when you run `./pants help shellcheck`.
[block:callout]
{
  "type": "info",
  "title": "`GoalSubsystem`",
  "body": "As explained in [Goal rules](doc:rules-api-goal-rules), goals use a subclass of  `Subsystem`: `GoalSubsystem` from `pants.engine.goal`.\n\n`GoalSubsystem` behaves the same way as a normal subsystem, except that you set the class property `name` rather than `options_scope`. The `name` will auto-populate the `options_scope`."
}
[/block]
### Option types
These classes correspond to the option types at [Options](doc:options).

Every option type requires that you set the flag name (e.g. `-l` or `--level`) and the keyword argument `help`. Most types require that you set `default`. You can optionally set `advanced=True` with every option for it to only show up with `help-advanced`.
[block:parameters]
{
  "data": {
    "h-0": "Class name",
    "h-1": "Notes",
    "0-0": "`StrOption`",
    "0-1": "Must set `default` to a `str` or `None`.",
    "2-0": "`IntOption`",
    "2-1": "Must set `default` to an `int` or `None`.",
    "5-0": "List options:\n- `StrListOption`\n- `BoolListOption`\n- `IntListOption`\n- `FloatListOption`\n- `EnumListOption`",
    "5-1": "Default is `[]` if `default`  is not set.\n\nFor `EnumListOption`, you must set the keyword argument `enum_type`.",
    "3-0": "`FloatOption`",
    "3-1": "Must set `default` to a `float` or `None`.",
    "1-0": "`BoolOption`",
    "1-1": "Must set `default` to a `bool` or `None`. TODO\n\nReminder when choosing a flag name: Pants will recognize the command line argument `--no-my-flag-name` as equivalent to `--my-flag-name=false`.",
    "6-0": "`DictOption`",
    "6-1": "Default is `{}` if `default` is not set.\n\nCurrently, Pants does not offer any validation of the dictionary entries, e.g. `dict[str, str]` vs `dict[str, list[str]]`. (Although per TOML specs, the key should always be `str`.) You may want to add eager validation that users are inputting options the correct way.",
    "4-0": "`EnumOption`",
    "4-1": "This is like `StrOption`, but with the valid choices constrained to your enum.\n\nTo use, define an `enum.Enum`. The values of your enum will be what users can type, e.g. `'kale'` and `'spinach'` below:\n\n```python\nclass LeafyGreens(Enum):\n    KALE = \"kale\"\n    SPINACH = \"spinach\"\n```\n\nYou must either set `default` to a value from your enum or `None`. If you set `default=None`, you must set `enum_type`.",
    "7-0": "`ArgsListOption`",
    "7-1": "Adds an `--args` option, e.g. `--isort-args`. This type is extra useful because it uses a special `shell_str` that lets users type the arguments as a single string with spaces, which Pants will _shlex_ for them. That is, `--args='arg1 arg2'` gets converted to `['arg1', 'arg2']`.\n\nYou must set the keyword argument `example`, e.g. `'--arg1 arg2'`. You must also set `tool_name: str`, e.g. `'Black'`.\n\nYou can optionally set `passthrough=True` if the user should be able to use the style `./pants my-goal :: -- --arg1`, i.e. arguments after `--`."
  },
  "cols": 2,
  "rows": 8
}
[/block]

[block:api-header]
{
  "title": "Using options in rules"
}
[/block]
To use a `Subsystem` or `GoalSubsystem` in your rule, request it as a parameter. Then, use the class attributes to access the option value.

```python
from pants.engine.rules import rule
...

@rule
async def demo(shellcheck: Shellcheck) -> LintResults:
    if shellcheck.skip:
        return LintResults()
    config_discovery = shellcheck.config_discovery
    ...
```