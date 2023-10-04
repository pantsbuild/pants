---
title: "1.30.x"
slug: "release-notes-1-30"
hidden: true
createdAt: "2020-06-09T00:14:07.234Z"
---
Some highlights:

- The Pants daemon (pantsd) is now enabled by default for improved performance.
- Added experimental support for Python dependency inference. See below.
- Pants now logs when certain steps of your build are done. This improves, in particular, the experience when you have `--no-dynamic-ui` enabled, such as in CI.

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/1.30.x.rst) for a detailed change log.
[block:api-header]
{
  "title": "Experimental dependency inference feature"
}
[/block]
Pants can now read your Python source files to infer the `dependencies` field for your Python targets, meaning that you can now leave off the `dependencies` field for most of your BUILD files.

### How to activate
Add `dependency_inference = true` to your `pants.toml`, like this:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\ndependency_inference = true",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
To test that it is working, find a sample target, then delete the `dependencies` field from its BUILD file and run `./pants dependencies path/to:target`.

### Teach Pants about your third party dependencies (recommended)
Pants will assume that each of your dependencies exposes a module with the same name; for example, the requirement `Django>=2.0` would expose the module `"django"`. However, sometimes the module is different, like `setuptools` exposing `pkg_resources`.

If you are using a `requirements.txt` and `python_requirements()` target, teach Pants about any unusual modules like this:
[block:code]
{
  "codes": [
    {
      "code": "python_library(\n  module_mapping={\n    \"ansicolors\": [\"colors\"],\n    \"beautifulsoup4\": [\"bs4\"],\n    \"setuptools\": [\"pkg_resources\"],\n  },\n)",
      "language": "python",
      "name": "3rdparty/BUILD"
    }
  ]
}
[/block]
For inline `python_requirement_library` targets, configure like this:
[block:code]
{
  "codes": [
    {
      "code": "python_requirement_library(\n  name='setuptools',\n  requirements=[\n    python_requirement('setuptools', modules=['pkg_resources']),\n  ],\n)\n",
      "language": "python",
      "name": "3rdparty/BUILD"
    }
  ]
}
[/block]
### Known limitations
#### Does not work with the v1 engine
You must be solely using the v2 engine for dependency inference to work. Otherwise, when you run v1 tasks, Pants will not know what your dependencies are.

#### Performance tuning

We have not yet closely tuned the performance. The performance should be acceptable—and the results will be cached through the Pants daemon (pantsd)—but dependency inference will result in a slowdown compared to explicit targets.  

#### May find cycles in your code

Dependency inference sometimes reveals cycles between your targets that you did not know about. Run `./pants dependencies --transitive ::` to see if you have any.

If you have cycles, you will need to manually fix these cycles by either creating new targets or moving around code

#### No way to exclude inferred dependencies
Sometimes, dependency inference may infer something that you do not like. Currently, there is not a way to ignore the inference.

We are working on a feature to ignore a dependency by prefixing the value with `!`, like `!helloworld/project:util`.