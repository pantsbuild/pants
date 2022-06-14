---
title: "Enabling Python support"
slug: "python-backend"
excerpt: "How to enable Pants's bundled Python backend package."
hidden: false
createdAt: "2020-03-02T22:39:55.355Z"
updatedAt: "2022-05-16T05:07:08.461Z"
---
[block:callout]
{
  "type": "info",
  "title": "Example Python repository",
  "body": "See [here](https://github.com/pantsbuild/example-python) for examples of Pants's Python functionality.\n\nSee [here](https://github.com/pantsbuild/example-django) for Django-specific examples."
}
[/block]
Enable the Python [backend](doc:enabling-backends) like this:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\n...\nbackend_packages = [\n  \"pants.backend.python\"\n]\n",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Pants use [`python_source`](doc:reference-python_source) and [`python_test`](doc:reference-python_test) targets to know which Python files to run on and to set any metadata.

To reduce boilerplate, the [`python_sources`](doc:reference-python_sources) target generates a `python_source` target for each file in its `sources` field, and [`python_tests`](doc:reference-python_tests) generates a `python_test` target for each file in its `sources` field.
[block:code]
{
  "codes": [
    {
      "code": "python_sources(name=\"lib\", sources=[\"dirutil.py\", \"strutil.py\"])\npython_tests(name=\"tests\", sources=[\"strutil_test.py\"])\n\n# Spiritually equivalent to:\npython_source(name=\"dirutil\", source=\"dirutil.py\")\npython_source(name=\"strutil\", source=\"strutil.py\")\npython_test(name=\"strutil_test.py\", source=\"strutil_test.py\")\n\n# Thanks to the default `sources` values, spiritually equivalent to:\npython_sources(name=\"lib\")\npython_tests(name=\"tests\")",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
You can generate these targets by running [`./pants tailor`](doc:create-initial-build-files).

```
Created project/BUILD:
  - Add python_sources target project
  - Add python_tests target tests
```
[block:callout]
{
  "type": "info",
  "title": "Have content in your `__init__.py` files?",
  "body": "Pants automatically uses all relevant `__init__.py` files, even if dependency inference does not include the files and you don't add it to the `dependencies` fields of your targets.\n\nThis works if you have empty `__init__.py` files, like most Python projects do; but if you have actual code in your `__init__.py` files, you should turn on both of these options in your `pants.toml`:\n\n```toml\n[python]\ntailor_ignore_solitary_init_files = false\n\n[python-infer]\ninits = true\n```\n\nThis option will cause Pants to infer \"proper\" dependencies on any ancestor `__init__.py` file. If you run `./pants dependencies project/util/foo.py`, you should see `project/__init__.py` and `project/util/__init__.py` show up. This will ensure that any of the `dependencies` of your `__init__.py` files are included."
}
[/block]

[block:callout]
{
  "type": "warning",
  "title": "macOS users: you may need to change interpreter search paths",
  "body": "By default, Pants will look at both your `$PATH` and—if you use Pyenv—your `$(pyenv root)/versions` folder when discovering Python interpreters. Your `$PATH` likely includes the system Pythons at `/usr/bin/python` and `/usr/bin/python3`, which are known to have many issues like failing to install some dependencies.\n\nPants will prefer new Python versions, like 3.6.10 over 3.6.3. Because macOS system Pythons are usually very old, they will usually be ignored.\n\nHowever, if you run into issues, you can set the `search_paths` option in the `[python-bootstrap]` scope:\n\n```toml\n[python-bootstrap]\nsearch_paths = [\n    # This will use all interpreters in `$(pyenv root)/versions`.\n    \"<PYENV>\",\n     # Brew usually installs Python here. \n    \"/usr/local/bin\",\n]\n```\n\nSee [here](doc:python-interpreter-compatibility#changing-the-interpreter-search-path) for more information."
}
[/block]