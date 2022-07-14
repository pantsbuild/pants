---
title: "Enabling Python support"
slug: "python-backend"
excerpt: "How to enable Pants's bundled Python backend package."
hidden: false
createdAt: "2020-03-02T22:39:55.355Z"
updatedAt: "2022-05-16T05:07:38.169Z"
---
> 📘 Example Python repository
>
> See [here](https://github.com/pantsbuild/example-python) for examples of Pants's Python functionality.
>
> See [here](https://github.com/pantsbuild/example-django) for Django-specific examples.

Enable the Python [backend](doc:enabling-backends) like this:

```toml pants.toml
[GLOBAL]
...
backend_packages = [
  "pants.backend.python"
]

[python]
# This will become the default in Pants 2.15.
tailor_pex_binary_targets = false
```

Pants use [`python_source`](doc:reference-python_source) and [`python_test`](doc:reference-python_test) targets to know which Python files to run on and to set any metadata.

To reduce boilerplate, the [`python_sources`](doc:reference-python_sources) target generates a `python_source` target for each file in its `sources` field, and [`python_tests`](doc:reference-python_tests) generates a `python_test` target for each file in its `sources` field.

```python BUILD
python_sources(name="lib", sources=["dirutil.py", "strutil.py"])
python_tests(name="tests", sources=["strutil_test.py"])

# Spiritually equivalent to:
python_source(name="dirutil", source="dirutil.py")
python_source(name="strutil", source="strutil.py")
python_test(name="strutil_test.py", source="strutil_test.py")

# Thanks to the default `sources` values, spiritually equivalent to:
python_sources(name="lib")
python_tests(name="tests")
```

You can generate these targets by running [`./pants tailor ::`](doc:initial-configuration#5-generate-build-files).

```
❯ ./pants tailor ::
Created project/BUILD:
  - Add python_sources target project
  - Add python_tests target tests
```

> 📘 Have content in your `__init__.py` files?
>
> Pants automatically uses all relevant `__init__.py` files, even if dependency inference does not include the files and you don't add it to the `dependencies` fields of your targets.
>
> This works if you have empty `__init__.py` files, like most Python projects do; but if you have actual code in your `__init__.py` files, you should turn on both of these options in your `pants.toml`:
>
> ```toml
> [python]
> tailor_ignore_solitary_init_files = false
>
> [python-infer]
> inits = true
> ```
>
> This option will cause Pants to infer "proper" dependencies on any ancestor `__init__.py` file. If you run `./pants dependencies project/util/foo.py`, you should see `project/__init__.py` and `project/util/__init__.py` show up. This will ensure that any of the `dependencies` of your `__init__.py` files are included.

> 🚧 macOS users: you may need to change interpreter search paths
>
> By default, Pants will look at both your `$PATH` and—if you use Pyenv—your `$(pyenv root)/versions` folder when discovering Python interpreters. Your `$PATH` likely includes the system Pythons at `/usr/bin/python` and `/usr/bin/python3`, which are known to have many issues like failing to install some dependencies.
>
> Pants will prefer new Python versions, like 3.6.10 over 3.6.3. Because macOS system Pythons are usually very old, they will usually be ignored.
>
> However, if you run into issues, you can set the `search_paths` option in the `[python-bootstrap]` scope:
>
> ```toml
> [python-bootstrap]
> search_paths = [
>     # This will use all interpreters in `$(pyenv root)/versions`.
>     "<PYENV>",
>      # Brew usually installs Python here.
>     "/usr/local/bin",
> ]
> ```
>
> See [here](doc:python-interpreter-compatibility#changing-the-interpreter-search-path) for more information.
