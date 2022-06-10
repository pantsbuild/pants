---
title: "python_distribution"
slug: "reference-python_distribution"
hidden: false
createdAt: "2022-06-02T21:10:45.313Z"
updatedAt: "2022-06-02T21:10:45.726Z"
---
A publishable Python setuptools distribution (e.g. an sdist or wheel).

See [Building distributions](doc:python-distributions).

Backend: <span style="color: purple"><code>pants.backend.python</code></span>

## <code>dependencies</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to other targets that this target depends on, e.g. ['helloworld/subdir:lib', 'helloworld/main.py:lib', '3rdparty:reqs#django'].

This augments any dependencies inferred by Pants, such as by analyzing your imports. Use `./pants dependencies` or `./pants peek` on this target to get the final result.

See [Targets and BUILD files](doc:targets)#target-addresses and [Targets and BUILD files](doc:targets)#target-generation for more about how addresses are formed, including for generated targets. You can also run `./pants list ::` to find all addresses in your project, or `./pants list dir:` to find all addresses defined in that directory.

If the target is in the same BUILD file, you can leave off the BUILD file path, e.g. `:tgt` instead of `helloworld/subdir:tgt`. For generated first-party addresses, use `./` for the file path, e.g. `./main.py:tgt`; for all other generated targets, use `:tgt#generated_name`.

You may exclude dependencies by prefixing with `!`, e.g. `['!helloworld/subdir:lib', '!./sibling.txt']`. Ignores are intended for false positives with dependency inference; otherwise, simply leave off the dependency from the BUILD file.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>entry_points</code>

<span style="color: purple">type: <code>Dict[str, Dict[str, str]] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Any entry points, such as `console_scripts` and `gui_scripts`.

Specify as a nested dictionary, with a dictionary for each type of entry point, e.g. `console_scripts` vs. `gui_scripts`. Each dictionary maps the entry point name to either a setuptools entry point ("path.to.module:func") or a Pants target address to a pex_binary target.

    Example:

        entry_points={
          "console_scripts": {
            "my-script": "project.app:main",
            "another-script": "project/subdir:pex_binary_tgt"
          }
        }

Note that Pants will assume that any value that either starts with `:` or has `/` in it, is a target address to a pex_binary target. Otherwise, it will assume it's a setuptools entry point as defined by https://packaging.python.org/specifications/entry-points/#entry-points-specification. Use `//` as a prefix for target addresses if you need to disambiguate.

Pants will attempt to infer dependencies, which you can confirm by running:

    ./pants dependencies <python_distribution target address>

## <code>generate_setup</code>

<span style="color: purple">type: <code>bool | None</code></span>
<span style="color: green">default: <code>None</code></span>

Whether to generate setup information for this distribution, based on analyzing sources and dependencies. Set to False to use existing setup information, such as existing setup.py, setup.cfg, pyproject.toml files or similar.

## <code>long_description_path</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Path to a file that will be used to fill the long_description field in setup.py.

Path is relative to the build root.

Alternatively, you can set the `long_description` in the `provides` field, but not both.

This field won't automatically set `long_description_content_type` field for you. You have to specify this field yourself in the `provides` field.

## <code>provides</code>

<span style="color: purple">type: <code>PythonArtifact</code></span>
<span style="color: green">required</span>

The setup.py kwargs for the external artifact built from this target.

You must define `name`. You can also set almost any keyword argument accepted by setup.py in the `setup()` function: (https://packaging.python.org/guides/distributing-packages-using-setuptools/#setup-args).

See [Custom `python_artifact()` kwargs](doc:plugins-setup-py) for how to write a plugin to dynamically generate kwargs.

## <code>repositories</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>
backend: <span style="color: green"><code>pants.backend.experimental.python</code></span>

List of URL addresses or Twine repository aliases where to publish the Python package.

Twine is used for publishing Python packages, so the address to any kind of repository that Twine supports may be used here.

Aliases are prefixed with `@` to refer to a config section in your Twine configuration, such as a `.pypirc` file. Use `@pypi` to upload to the public PyPi repository, which is the default when using Twine directly.

## <code>sdist</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>True</code></span>

Whether to build an sdist for the distribution.

## <code>sdist_config_settings</code>

<span style="color: purple">type: <code>Dict[str, Iterable[str]] | None</code></span>
<span style="color: green">default: <code>None</code></span>

PEP-517 config settings to pass to the build backend when building an sdist.

## <code>skip_twine</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.experimental.python</code></span>

If true, don't publish this target's packages using Twine.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>wheel</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>True</code></span>

Whether to build a wheel for the distribution.

## <code>wheel_config_settings</code>

<span style="color: purple">type: <code>Dict[str, Iterable[str]] | None</code></span>
<span style="color: green">default: <code>None</code></span>

PEP-517 config settings to pass to the build backend when building a wheel.