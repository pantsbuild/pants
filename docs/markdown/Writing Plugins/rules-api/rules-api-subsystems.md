---
title: "Options and subsystems"
slug: "rules-api-subsystems"
excerpt: "How to add options to your plugin."
hidden: false
createdAt: "2020-07-01T04:55:36.180Z"
---
Defining options
----------------

As explained in [Options](doc:options), options are partitioned into named scopes, like `[test]` and `[isort]`. Each of these scopes corresponds to a _subsystem_.

To add new options:

1. Define a subclass of `Subsystem` from `pants.subsystem.subsystem`.
   1. Set the class property `options_scope` with the name of the subsystem.
      - This value will be prepended to all options in the subsystem, e.g. `--skip` will become `--shellcheck-skip`.
   2. Set the class property `help`, which is used by `pants help`.
2. Add new options through `pants.options.option_types` class attributes.
3. Register the `Subsystem` with `Subsystem.rules()` and `register.py`.
   - You don't need `Subsystem.rules()` if the `Subsystem` is used in an `@rule` because `collect_rules()` will recognize it. It doesn't hurt to keep this around, though.

```python pants-plugins/example/shellcheck.py
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem


class ShellcheckSubsystem(Subsystem):
    options_scope = "shellcheck"
    help = "The Shellcheck linter."

    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help="Whether Pants should...",
    )


def rules():
    return [*ShellcheckSubsystem.rules()]
```
```python pants-plugins/example/register.py
from example import shellcheck

def rules():
    return [*shellcheck.rules()]
```

The subsystem should now show up when you run `pants help shellcheck`.

> 📘 `GoalSubsystem`
>
> As explained in [Goal rules](doc:rules-api-goal-rules), goals use a subclass of  `Subsystem`: `GoalSubsystem` from `pants.engine.goal`.
>
> `GoalSubsystem` behaves the same way as a normal subsystem, except that you set the class property `name` rather than `options_scope`. The `name` will auto-populate the `options_scope`.

### Option types

These classes correspond to the option types at [Options](doc:options).

Every option type requires that you set the keyword argument `help`.

Most types require that you set `default`. You can optionally set `advanced=True` with every option
for it to only show up with `help-advanced`.

The option name will default to the class attribute name, e.g. `my_opt = StrOption()` will default to `--my-opt`.
You can instead pass a string positional argument, e.g. `my_opt = StrOption("--different-name")`.

[block:parameters]
{
  "data": {
    "h-0": "Class name",
    "h-1": "Notes",
    "0-0": "`StrOption`",
    "0-1": "Must set `default` to a `str` or `None`.",
    "1-0": "`BoolOption`",
    "1-1": "Must set `default` to a `bool` or `None`. TODO  \n  \nReminder when choosing a flag name: Pants will recognize the command line argument `--no-my-flag-name` as equivalent to `--my-flag-name=false`.",
    "2-0": "`IntOption`",
    "2-1": "Must set `default` to an `int` or `None`.",
    "3-0": "`FloatOption`",
    "3-1": "Must set `default` to a `float` or `None`.",
    "4-0": "`EnumOption`",
    "4-1": "This is like `StrOption`, but with the valid choices constrained to your enum.  \n  \nTo use, define an `enum.Enum`. The values of your enum will be what users can type, e.g. `'kale'` and `'spinach'` below:  \n  \n```python\nclass LeafyGreens(Enum):\n    KALE = \"kale\"\n    SPINACH = \"spinach\"\n```You must either set `default` to a value from your enum or `None`. If you set `default=None`, you must set `enum_type`.",
    "5-0": "List options:  \n  \n- `StrListOption`\n- `BoolListOption`\n- `IntListOption`\n- `FloatListOption`\n- `EnumListOption`",
    "5-1": "Default is `[]` if `default`  is not set.  \n  \nFor `EnumListOption`, you must set the keyword argument `enum_type`.",
    "6-0": "`DictOption`",
    "6-1": "Default is `{}` if `default` is not set.  \n  \nCurrently, Pants does not offer any validation of the dictionary entries, e.g. `dict[str, str]` vs `dict[str, list[str]]`. (Although per TOML specs, the key should always be `str`.) You may want to add eager validation that users are inputting options the correct way.",
    "7-0": "`ArgsListOption`",
    "7-1": "Adds an `--args` option, e.g. `--isort-args`. This type is extra useful because it uses a special `shell_str` that lets users type the arguments as a single string with spaces, which Pants will _shlex_ for them. That is, `--args='arg1 arg2'` gets converted to `['arg1', 'arg2']`.  \n  \nYou must set the keyword argument `example`, e.g. `'--arg1 arg2'`. You must also set `tool_name: str`, e.g. `'Black'`.  \n  \nYou can optionally set `passthrough=True` if the user should be able to use the style `pants my-goal :: -- --arg1`, i.e. arguments after `--`."
  },
  "cols": 2,
  "rows": 8,
  "align": [
    "left",
    "left"
  ]
}
[/block]

Using options in rules
----------------------

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

> 📘 Name clashing
>
> When adding custom options, make sure their name does not start with an existing goal name. For instance, passing a boolean option named `check_foobar` as `--check-foobar` in the command line would fail since Pants would think you are trying to pass the `--foobar` flag in the built-in `check` goal scope.
