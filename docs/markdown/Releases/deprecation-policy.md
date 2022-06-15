---
title: "Deprecation policy"
slug: "deprecation-policy"
excerpt: "How we try to provide you a stable experience."
hidden: false
createdAt: "2020-05-16T22:36:48.260Z"
updatedAt: "2022-02-08T21:05:17.456Z"
---
Deprecations must live at least one minor release, meaning that if something is deprecated in 2.1.x, for example, it cannot be removed until 2.2.x.

Every deprecation message will include a description of how to respond to the change, such as renaming a value in your `pants.toml` config file. When possible, we will automate the deprecation via the `update-build-files` goal.
[block:api-header]
{
  "title": "Prohibited changes"
}
[/block]
* Removing options without a deprecation.
   * Deprecated options must behave the same as before.
* Changing default option values without a deprecation.
* Removing features without a deprecation.
* Substantial performance regressions (slowdown of >= 10%).
    * If a new feature results in this slowdown, it should be put behind a flag that is disabled by default.
[block:api-header]
{
  "title": "Allowed changes"
}
[/block]
* Adding new options.
* Adding new functionality.
* Fixing bugs.
* Changes that are required by law.
[block:api-header]
{
  "title": "Plugin API deprecation policy"
}
[/block]
When [writing plugins](doc:plugin-overview), Pants is used as a _library_, rather than a _binary_. That is, you import Pants code to write plugins. We try to make this API stable for your plugins.

### What is public?

A module, variable, method, function, or class is part of the public API if at least one of the following is true:

* Its definition's docstring is marked with `:API: public`.
* Its enclosing scope is marked with `:API: public` and the name does not start with an underscore.
* It is abstract and any inheriting class published by Pants is marked `:API: public`.

All other code defaults to being a private API and does not need to follow this deprecation policy.

Examples:
[block:code]
{
  "codes": [
    {
      "code": "\"\"\"An example public module.\n\nThis means that everything in this module is public, except for \nvalues prefixed with `_`.\n\n:API: public\n\"\"\"\n\ndef demo_function(x: int) -> None:\n    \"\"\"An example public top-level function.\n  \n    :API: public\n    \"\"\"\n    print(x)\n\n\nclass Demo:\n    \"\"\"An example public class.\n    \n    All methods and class properties are public, except for values \n    prefixed with `_`.\n    \n    :API: public\n    \"\"\"\n    \n    def demo_method(self, x: int) -> None:\n        \"\"\"An example public method.\n        \n        :API: public\n        \"\"\"\n        print(x)\n\n",
      "language": "python",
      "name": "deprecation_example.py"
    }
  ]
}
[/block]
### Prohibited API changes
These changes all require a deprecation.

* Removing a public API.
* Moving a public API to a new module.
* Removing the parameters of a public function.
* Changing the default values of a public function.
* Changing a public function to require keyword arguments through the `*` operator.
* Moving the order of the parameters of a public function.
    * This is only allowed if we are already enforcing keyword arguments with the `*` operator.
* Changing the behavior of a public API.
    * Instead, the API would need a new parameter that toggles the change in behavior.

### Allowed API changes

* Adding a new module.
* Adding new functionality to a module, e.g. new classes or functions.
* Adding new parameters to a function _if and only if_ they have a default value.
* Adding type hints.
* Fixing bugs.
* Upgrading Pants to use new versions of third-party libraries.
* Changes that are required by law.

[block:callout]
{
  "type": "warning",
  "body": "These two APIs do not yet follow this deprecation policy because we are actively shaping the API. \n\nWe do try, however, to limit changes and may choose to respect the deprecation policy on a case-by-case basis.",
  "title": "The Rules and Target APIs are still experimental"
}
[/block]