---
title: "Plugins overview"
slug: "plugins-overview"
excerpt: "An intro to the Pants engine's core concepts."
hidden: false
createdAt: "2020-05-07T22:38:39.922Z"
updatedAt: "2022-05-16T19:56:56.104Z"
---
Pants is designed for extensibility: you can extend Pants by writing custom _plugins_, using a standard Plugin API. In fact, all of Pants's built-in functionality uses the same API!

Some of the ways you can extend Pants:

* Add support for new languages.
* Add new goals, like a `publish` goal or `docker` goal.
* Add new linters, formatters, and type-checkers.
* Add new codegen implementations.
* Define new target types that still work with core Pants.
* Add new forms of dependency inference
* Define macros to reduce boilerplate in BUILD files.

Thanks to Pants's execution engine, your plugins will automatically bring you the same benefits you get from using core Pants, including:

- Fine-grained caching.
- Concurrent execution.
- Remote execution.
[block:callout]
{
  "type": "danger",
  "title": "The Plugin API is not yet stable",
  "body": "While we'll try our best to limit changes, the Plugin API does not yet follow the [Deprecation Policy](doc:deprecation-policy). Components of the API may change between minor versions—e.g. 2.7 to 2.8—without a deprecation.\n\nWe will document changes at [Plugin upgrade guide](doc:plugin-upgrade-guide)."
}
[/block]

[block:api-header]
{
  "title": "Core concepts"
}
[/block]
The plugin API is split into two main interfaces:

1. [The Target API](doc:target-api-concepts): a declarative interface for creating new target types and extending existing targets.
2. [The Rules API](doc:rules-api-concepts): where you define your logic and model each step of your build.

Plugins are written in typed Python 3 code. You write your logic in Python, and then Pants will run your plugin in the Rust engine.
[block:api-header]
{
  "title": "Locating Plugin code"
}
[/block]
Plugins can be consumed in either of two ways:

- From a published package in a repository such as [PyPI](https://pypi.org/).
- Directly from in-repo sources. 

It's often convenient to use in-repo plugins, particularly when the plugin is only relevant to a single repo and you want to iterate on it rapidly. In other cases, you may want to publish the plugin, so it can be reused across multiple repos.

### Published plugins

You consume published plugins by adding them to the `plugins` option:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nplugins = [\"my.plugin==2.3.4\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
### In-repo plugins

Conventionally, in-repo plugins live in a folder called `pants-plugins`, although they may be placed anywhere.

You must specify the path to your plugin's top-level folder using the `pythonpath` option:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\npythonpath = [\"%(buildroot)s/pants-plugins\"]\n",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "warning",
  "title": "In-repo dependencies",
  "body": "In-repo plugin code should not depend on other in-repo code outside of the `pants-plugins` folder.  The `pants-plugins` folder helps isolate plugins from regular code, which is necessary due to how Pants's startup sequence works."
}
[/block]
You can depend on third-party dependencies in your in-repo plugin by adding them to the `plugins` option:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nplugins = [\"ansicolors==1.18.0\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
However, be careful adding third-party dependencies that perform side-effects like reading from the filesystem or making network requests, as they will not work properly with the engine's caching model.
[block:api-header]
{
  "title": "Enabling Plugins with `register.py`"
}
[/block]
A Pants [_backend_](doc:enabling-backends) is a Python package that implements some required functionality and uses hooks to register itself with Pants.  

A plugin will contain one or more backends, with the hooks for each one defined in a file called `register.py`.  To enable a custom plugin you add its backends to your `backend_packages` configuration:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\npythonpath = [\"%(buildroot)s/pants-plugins\"]\nbackend_packages.add = [\n  # This will activate `pants-plugins/plugin1/register.py`.\n  \"plugin1\",\n  # This will activate `pants-plugins/subdir/plugin2/register.py`.\n  \"subdir.plugin2\",\n]",
      "language": "toml",
      "name": "pants.toml"
    },
    {
      "code": "from plugin1.lib import CustomTargetType, rule1, rule2\n\n\ndef rules():\n    return [rule1, rule2]\n\n\ndef target_types():\n    return [CustomTargetType]",
      "language": "python",
      "name": "pants-plugins/plugin1/register.py"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Building in-repo plugins with Pants"
}
[/block]
Because plugin code is written in Python, you can optionally use Pants's [Python backend](doc:python-backend) to build your plugin code. For example, you can use Pants to lint, format, and test your plugin code. This is not required, but it's usually a good idea to improve the quality of your plugin.

To do so, activate the [Python backend](doc:python) and `plugin_development` backend, which adds the `pants_requirements` target type. Also add your `pants-plugins` directory as a source root:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages = [\n  \"pants.backend.python\",\n  \"pants.backend.plugin_development\",\n]\n\n[source]\nroot_patterns = [\n  ..,\n  \"pants-plugins\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Then, add the `pants_requirements` target generator.
[block:code]
{
  "codes": [
    {
      "code": "pants_requirements(name=\"pants\")",
      "language": "python",
      "name": "pants-plugins/BUILD"
    }
  ]
}
[/block]
This will generate [`python_requirement` targets](doc:python-third-party-dependencies) for the `pantsbuild.pants` and `pantsbuild.pants.testutil` distributions, so that when you build your code—like running MyPy or Pytest on your plugin—the dependency on Pants itself is properly resolved. This isn't used for your plugin to work, only for Pants goals like `test` and `check` to understand how to resolve the dependency.

The target generator dynamically sets the version downloaded to match your current `pants_version` set in `pants.toml`. Pants's [dependency inference](doc:targets) understands imports of the `pants` module and will automatically add dependencies on the generated `python_requirement` targets where relevant.

If you do not want your plugin requirements to mix with your normal requirements, it's often a good idea to set up a dedicated "resolve" (lockfile) for your plugins. See [Third-party dependencies](doc:python-third-party-dependencies) for more information. For example:
[block:code]
{
  "codes": [
    {
      "code": "[python]\nenable_resolves = true\n# The repository's own constraints.\ninterpreter_constraints = [\"==3.9.*\"]\n\n[python.resolves]\npants-plugins = \"pants-plugins/lock.txt\"\npython-default = \"3rdparty/python/default_lock.txt\"\n\n[python.resolves_to_interpreter_constraints]\n# Pants can run with 3.7-3.9, so this lets us \n# use different interpreter constraints when \n# generating the lockfile than the rest of our project. \n#\n# Warning: it's still necessary to set the `interpreter_constraints` \n# field on each `python_sources` and `python_tests` target in \n# our plugin! This only impacts how the lockfile is generated.\npants-plugins = [\">=3.7,<3.10\"]",
      "language": "python",
      "name": "pants.toml"
    }
  ]
}
[/block]
Then, update your `pants_requirements` target generator with `resolve="pants-plugins"`, and run `./pants generate-lockfiles`. You will also need to update the relevant `python_source` / `python_sources` and `python_test` / `python_tests` targets to set `resolve="pants-plugins"` (along with possibly the `interpreter_constraints` field).
[block:api-header]
{
  "title": "Publishing a plugin"
}
[/block]
Pants plugins can be published to PyPI and consumed by other Pants users.

As mentioned above: the plugin API is still unstable, and so supporting multiple versions of Pants with a single plugin version may be challenging. Give careful consideration to who you expect to consume the plugin, and what types of maintenance guarantees you hope to provide.

### Thirdparty dependencies

When publishing a plugin, ensure that any [`python_requirement` targets](doc:python-third-party-dependencies) that the plugin depends on either:
1. Do not overlap with [the requirements of Pants itself](https://github.com/pantsbuild/pants/blob/aa0932a54e8c1b6ed6f3be8e084a11b2f6c808e5/3rdparty/python/requirements.txt), or
2. Use range requirements that are compatible with Pants' own requirements.

For example: if a particular version of Pants depends on `requests>=2.25.1` and your plugin must also depend on `requests`, then the safest approach is to specify exactly that range in the plugins' requirements.

### Adapting to changed plugin APIs

If a `@rule` API has been added or removed in versions of Pants that you'd like to support with your plugin, you can use conditional imports to register different `@rules` based on the version:

```python
from pants.version import PANTS_SEMVER

if PANTS_SEMVER < Version("2.10.0"):
  import my.plugin.pants_pre_210 as plugin
else:
  import my.plugin.pants_default as plugin

def rules():
  return plugin.rules()
```