---
title: "Third-party dependencies"
slug: "python-third-party-dependencies"
excerpt: "How to use third-party Python libraries in your project."
hidden: false
createdAt: "2020-04-30T20:06:43.633Z"
updatedAt: "2022-05-12T15:27:26.087Z"
---
Pants handles dependencies with more precision than traditional Python workflows. Traditionally, you have a single heavyweight [virtual environment](https://docs.python.org/3/tutorial/venv.html) that includes a large set of dependencies, whether or not you actually need them for your current task. 

Instead, Pants understands exactly which dependencies every file in your project needs, and efficiently uses just that subset of dependencies needed for the task.

```
❯ ./pants dependencies src/py/util.py
3rdparty/py#requests

❯ ./pants dependencies --transitive src/py/app.py
3rdparty/py#flask
3rdparty/py#requests
```

Among other benefits, this precise and automatic understanding of your dependencies gives you fine-grained caching. This means, for example, that if none of the dependencies for a particular test file have changed, the cached result can be safely used.
[block:api-header]
{
  "title": "Teaching Pants your \"universe\"(s) of dependencies"
}
[/block]
For Pants to know which dependencies each file uses, it must first know which specific dependencies are in your "universe", i.e. all the third-party dependencies your project directly uses. 

By default, Pants uses a single universe for your whole project, but it's possible to set up multiple. See the header "Multiple resolves" in the "Lockfiles" section.

Each third-party dependency you directly use is modeled by a `python_requirement` target:
[block:code]
{
  "codes": [
    {
      "code": "python_requirement(\n    name=\"django\",\n    requirements=[\"Django==3.2.1\"],\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
You do not need a `python_requirement` target for transitive dependencies, i.e. requirements that you do not directly import.

To minimize boilerplate, Pants has target generators to generate `python_requirement` targets for you:

* `python_requirements` for `requirements.txt`.
* `poetry_requirements` for Poetry projects.

### `requirements.txt`

The `python_requirements()` target generator parses a [`requirements.txt`-style file](https://pip.pypa.io/en/stable/user_guide/#requirements-files) to produce a `python_requirement` target for each entry. 

For example:
[block:code]
{
  "codes": [
    {
      "code": "flask>=1.1.2,<1.3\nrequests[security]==2.23.0\ndataclasses ; python_version<'3.7'",
      "language": "text",
      "name": "requirements.txt"
    },
    {
      "code": "# This will generate three targets:\n#\n#  - //:reqs#flask\n#  - //:reqs#requests\n#  - //:reqs#dataclasses\npython_requirements(name=\"reqs\")\n\n# The above target generator is spiritually equivalent to this:\npython_requirement(\n    name=\"flask\",\n    requirements=[\"flask>=1.1.2,<1.3\"],\n)\npython_requirement(\n    name=\"requests\",\n    requirements=[\"requests[security]==2.23.0\"],\n)\npython_requirement(\n    name=\"dataclasses\",\n    requirements=[\"dataclasses ; python_version<'3.7'\"],\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
If the file uses a different name than `requirements.txt`, set `source` like this:

```python
python_requirements(source="reqs.txt")
```
[block:callout]
{
  "type": "info",
  "title": "Where should I put the `requirements.txt`?",
  "body": "You can name the file whatever you want, and put it wherever makes the most sense for your project.\n\nIn smaller repositories that only use Python, it's often convenient to put the file at the \"build root\" (top-level), as used on this page.\n\nFor larger repositories or multilingual repositories, it's often useful to have a `3rdparty` or `3rdparty/python` directory. Rather than the target's address being `//:reqs#my_requirement`, its address would be `3rdparty/python:reqs#my_requirement`, for example; or `3rdparty/python#my_requirement` if you leave off the `name` field for `python_requirements`. See [Target Generation](doc:targets#target-generation)."
}
[/block]
 ### Poetry

The `poetry_requirements()` target generator parses the [Poetry](https://python-poetry.org/docs/) section in `pyproject.toml` to produce a `python_requirement` target for each entry.
[block:code]
{
  "codes": [
    {
      "code": "[tool.poetry.dependencies]\npython = \"^3.8\"\nrequests = {extras = [\"security\"], version = \"~1\"}\nflask = \"~1.12\"\n\n[tool.poetry.dev-dependencies]\nisort = \"~5.5\"",
      "language": "toml",
      "name": "pyproject.toml"
    },
    {
      "code": "# This will generate three targets:\n#\n#  - //:poetry#flask\n#  - //:poetry#requests\n#  - //:poetry#dataclasses\npoetry_requirements(name=\"poetry\")\n\n# The above target generator is spiritually equivalent to this:\npython_requirement(\n    name=\"requests\",\n    requirements=[\"requests[security]>=1,<2.0\"],\n)\npython_requirement(\n    name=\"flask\",\n    requirements=[\"flask>=1.12,<1.13\"],\n)\npython_requirement(\n    name=\"isort\",\n    requirements=[\"isort>=5.5,<5.6\"],\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
See the section "Lockfiles" below for how you can also hook up `poetry.lock` to Pants.
[block:api-header]
{
  "title": "How dependencies are chosen"
}
[/block]
Once Pants knows about your "universe"(s) of dependencies, it determines which subset should be used through [dependency inference](https://blog.pantsbuild.org/dependency-inference/). Pants will read your import statements, like `import django`, and map it back to the relevant `python_requirement` target. Run [`./pants dependencies path/to/file.py`](doc:project-introspection) or `./pants dependencies path/to:target` to confirm this works.

If dependency inference does not work—such as because it's a runtime dependency you do not import—you can explicitly add the `python_requirement` target to the `dependencies` field, like this:
[block:code]
{
  "codes": [
    {
      "code": "python_sources(\n    name=\"lib\",\n    dependencies=[\n        # We don't have an import statement for this dep, so inference\n        # won't add it automatically. We add it explicitly instead.\n        \"3rdparty/python#psyscopg2-binary\",\n    ],\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]
### Use `modules` and `module_mapping` when the module name is not standard

Some dependencies expose a module different than their project name, such as `beautifulsoup4` exposing `bs4`. Pants assumes that a dependency's module is its normalized name—i.e. `My-distribution` exposes the module `my_distribution`. If that default does not apply to a dependency, it will not be inferred.

Pants already defines a [default module mapping](https://github.com/pantsbuild/pants/blob/main/src/python/pants/backend/python/dependency_inference/default_module_mapping.py) for some common Python requirements, but you may need to augment this by teaching Pants additional mappings:
[block:code]
{
  "codes": [
    {
      "code": "# `modules` and `module_mapping` is only needed for requirements where \n# the defaults do not work.\n\npython_requirement(\n    name=\"my_distribution\",\n    requirements=[\"my_distribution==4.1\"],\n    modules=[\"custom_module\"],\n)\n\npython_requirements(\n    name=\"reqs\",\n    module_mapping={\"my_distribution\": [\"custom_module\"]},\n)\n\npoetry_requirements(\n    name=\"poetry\",\n    module_mapping={\"my_distribution\": [\"custom_module\"]},\n)",
      "language": "python",
      "name": "3rdparty/python/BUILD"
    }
  ]
}
[/block]
If the dependency is a type stub, and the default does not work, set `type_stub_modules` on the `python_requirement` target, and `type_stubs_module_mapping` on the `python_requirements` and `poetry_requirements` target generators. (The default for type stubs is to strip off `types-`, `-types`, `-stubs`, and `stubs-`. So, `types-requests` gives type stubs for the module `requests`.)

### Warning: multiple versions of the same dependency

It's invalid in Python to have conflicting versions of the same requirement, e.g. `Django==2` and `Django==3`. Instead, Pants supports "multiple resolves" (i.e. multiple lockfiles), as explained in the below section on lockfiles.

When you have multiple targets for the same dependency and they belong to the same resolve ("lockfile"), dependency inference will not work due to ambiguity. If you're using lockfiles—which we strongly recommend—the solution is to set the `resolve` field for problematic `python_requirement` targets so that each resolve has only one requirement and there is no ambiguity.  

This ambiguity is often a problem when you have 2+ `requirements.txt` or `pyproject.toml` files in your project, such as `project1/requirements.txt` and `project2/requirements.txt` both specifying `django`. You may want to set up each `poetry_requirements`/`python_requirements` target generator to use a distinct resolve so that there is no overlap. Alternatively, if the versions are the same, you may want to consolidate the requirements into a common file.
[block:api-header]
{
  "title": "Lockfiles"
}
[/block]
We strongly recommend using lockfiles because they make your builds [more stable](https://classic.yarnpkg.com/blog/2016/11/24/lockfiles-for-all/) so that new releases of dependencies will not break your project. They also reduce the risk of [supply chain attacks](https://docs.microsoft.com/en-us/windows/security/threat-protection/intelligence/supply-chain-malware).

Pants has two types of lockfiles:

* User lockfiles, for your own code such as packaging binaries and running tests.
* Tool lockfiles, to install tools that Pants runs like Pytest and Flake8.

With both types of lockfiles, Pants can generate the lockfile for you with the `generate-lockfiles` goal.

### User lockfiles

First, set `[python].enable_resolves` in `pants.toml`:

```toml
[python]
enable_resolves = true
```

By default, Pants will write the lockfile to `3rdparty/python/default.lock`. If you want a different location, change `[python].resolves` like this:

```toml
[python]
enable_resolves = true

[python.resolves]
python-default = "lockfile_path.txt" 
```

Then, use `./pants generate-lockfiles` to generate the lockfile.

```
❯ ./pants generate-lockfiles
19:00:39.26 [INFO] Completed: Generate lockfile for python-default
19:00:39.29 [INFO] Wrote lockfile for the resolve `python-default` to 3rdparty/python/default.lock
```
[block:callout]
{
  "type": "info",
  "title": "FYI: user lockfiles improve performance",
  "body": "As explained at the top of these docs, Pants only uses the subset of the \"universe\" of your dependencies that is actually needed for a build, such as running tests and packaging a wheel file. This gives fine-grained caching and has other benefits like built packages (e.g. PEX binaries) only including their true dependencies. However, naively, this would mean that you need to resolve dependencies multiple times, which can be slow.\n\nIf you use Pex-generated lockfiles (see below), Pants will only install the subset of the lockfile you need for a task. If you use Poetry-generated lockfiles, Pants will first install the entire lockfile and then it will [extract](https://blog.pantsbuild.org/introducing-pants-2-5/) the exact subset needed. \n\nThis greatly speeds up performance and improves caching for goals like `test`, `run`, `package`, and `repl`."
}
[/block]
#### Multiple lockfiles

While it's often desirable to have a single lockfile for the whole repository for simplicity and consistency, sometimes you may need multiple. This is necessary, for example, when you have conflicting versions of requirements, such as one project using Django 2 and other projects using Django 3.

Start by defining multiple "resolves", which are logical names for lockfile paths. For example:

```toml
[python]
enable_resolves = true
default_resolve = "web-app"

[python.resolves]
data-science = "3rdparty/python/data_science_lock.txt"
web-app = "3rdparty/python/web_app_lock.txt"
```

Then, teach Pants which resolves every `python_requirement` target belongs to through the `resolve` field. It will default to `[python].default_resolve`.
[block:code]
{
  "codes": [
    {
      "code": "python_requirement(\n    name=\"ansicolors\",\n    requirements=[\"ansicolors==1.18\"],\n    resolve=\"web-app\",\n)\n\n# Often, you will want to set `resolve` on the \n# `poetry_requirements` and `python_requirements`\n# target generators.\npoetry_requirements(\n    name=\"poetry\",\n    resolve=\"data-science\",\n    # You can use `overrides` if you only want to change\n    # some targets.\n    overrides={\"requests\": {\"resolve\": \"web-app\"}},\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
If you want the same requirement to show up in multiple resolves, use the [`parametrize`](doc:targets) mechanism.
[block:code]
{
  "codes": [
    {
      "code": "# The same requirement in multiple resolves:\npython_requirement(\n    name=\"ansicolors_web-app\",\n    requirements=[\"ansicolors==1.18\"],\n    resolve=parametrize(\"web-app\", \"data-science\")\n)\n\n# You can parametrize target generators, including \n# via the `overrides` field:\npoetry_requirements(\n    name=\"poetry\",\n    resolve=\"data-science\",\n    overrides={\n        \"requests\": {\n            \"resolve\": parametrize(\"web-app\", \"data-science\")\n        }\n    },\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
Then, run `./pants generate-lockfiles` to generate the lockfiles. If the results aren't what you'd expect, adjust the prior step.

Finally, update your first-party targets like `python_source` / `python_sources`, `python_test` / `python_tests`, and `pex_binary` to set their `resolve` field. As before, the `resolve` field defaults to `[python].default_resolve`.
[block:code]
{
  "codes": [
    {
      "code": "python_sources(\n    resolve=\"web-app\",\n)\n\npython_tests(\n    name=\"tests\",\n    resolve=\"web-app\",\n    # You can use `overrides` to change certain generated targets\n    overrides={\"test_utils.py\": {\"resolve\": \"data-science\"}},\n)\n\npex_binary(\n    name=\"main\",\n    entry_point=\"main.py\",\n    resolve=\"web-app\",\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]
If a first-party target is compatible with multiple resolves—such as some utility code—you can either use the [`parametrize` mechanism](doc:targets) with the `resolve` field or create distinct targets for the same entity.

All transitive dependencies of a target must use the same resolve. Pants's dependency inference already handles this for you by only inferring dependencies on targets that share the same resolve. If you incorrectly add a target from a different resolve to the `dependencies` field, Pants will error with a helpful message when building your code with goals like `test`, `package`, and `run`.

### Tool lockfiles

Pants distributes a lockfile with each tool by default. However, if you change the tool's `version` and `extra_requirements`—or you change its interpreter constraints to not be compatible with our default lockfile—you will need to use a custom lockfile. Set the `lockfile` option in `pants.toml` for that tool, and then run `./pants generate-lockfiles`.

```toml
[flake8]
version = "flake8==3.8.0"
lockfile = "3rdparty/flake8_lockfile.txt"  # This can be any path you'd like.

[pytest]
extra_requirements.add = ["pytest-icdiff"]
lockfile = "3rdparty/pytest_lockfile.txt"
```

```
❯  ./pants generate-lockfiles
19:00:39.26 [INFO] Completed: Generate lockfile for flake8
19:00:39.27 [INFO] Completed: Generate lockfile for pytest
19:00:39.29 [INFO] Wrote lockfile for the resolve `flake8` to 3rdparty/flake8_lockfile.txt
19:00:39.30 [INFO] Wrote lockfile for the resolve `pytest` to 3rdparty/pytest_lockfile.txt
```

You can also run `./pants generate-lockfiles --resolve=tool`, e.g. `--resolve=flake8`, to only generate that tool's lockfile rather than generating all lockfiles.

To disable lockfiles entirely for a tool, set `[tool].lockfile = "<none>"` for that tool. Although we do not recommend this!

### Pex vs. Poetry for lockfile generation

You should set `[python].lockfile_generator` to either `"pex"` or `"poetry"` in `pants.toml`. The default of `poetry` will change in Pants 2.12.

We generally recommend using Pex, which has several benefits:

1. Supports `[python-repos]` if you have a custom index or repository other than PyPI.
2. Supports `[GLOBAL].ca_certs_path`.
3. Supports VCS (Git) requirements.
4. Faster performance when installing lockfiles. With Pex, Pants will only install the subset of the lockfile needed for a task; with Poetry, Pants will first install the lockfile and then extract the relevant subset.
5. Avoids an issue many users have with problematic environment markers for transitive requirements (see below).

However, it is very plausible there are still issues with Pex lockfiles because the Python ecosystem is so vast. Please open [bug reports](docs:getting-help)! If `generate-lockfiles` fails—or the lockfile errors when installed during goals like `test` and `package`—you may need to temporarily use Poetry. 

Alternatively, you can try to manually generate and manage lockfiles—change to the v2.10 version of these docs to see instructions.
[block:callout]
{
  "type": "info",
  "title": "Incremental migration from Poetry to Pex",
  "body": "Pants can understand lockfiles in either Pex's JSON format or Poetry's requirements.txt-style file, regardless of what you set `[python].lockfile_generator` to. This means that you can have some lockfiles using a different format than the others.\n\nTo incrementally migrate, consider writing a script that dynamically sets the option `--python-lockfile-generator`, like this:\n\n```\n./pants --python-lockfile-generator=pex generate-lockfiles --resolve=black --resolve=isort\n./pants --python-lockfile-generator=poetry generate-lockfiles --resolve=python-default\n```\n\nTip: if you write a script, set `[generate-lockfiles].custom_command` to say how to run your script."
}
[/block]
#### Poetry issue with environment markers 

One of the issues with Poetry is that sometimes `generate-lockfiles` will work, but then it errors when being installed due to missing transitive dependencies. This is especially common with user lockfiles. For example:

```
Failed to resolve requirements from PEX environment @ /home/pantsbuild/.cache/pants/named_caches/pex_root/unzipped_pexes/42735ba5593c0be585614e50072f765c6a45be15.
Needed manylinux_2_28_x86_64-cp-37-cp37m compatible dependencies for:
 1: colorama<0.5.0,>=0.4.0
    Required by:
      FingerprintedDistribution(distribution=rich 11.0.0 (/home/pantsbuild/.cache/pants/named_caches/pex_root/installed_wheels/4ce6259e437af26bac891ed2867340d4163662b9/rich-11.0.0-py3-none-any.whl), fingerprint='ff22612617b194af3cd95380174413855aad7240')
    But this pex had no 'colorama' distributions.
```

Usually, the transitive dependency is in the lockfile, but it doesn't get installed because it has nonsensical environment markers, like this:

```
colorama==0.4.4; sys_platform == "win32" and python_version >= "3.6" and python_full_version >= "3.6.2" and python_full_version < "4.0.0" and (python_version >= "3.6" and python_full_version < "3.0.0" or python_full_version >= "3.5.0" and python_version >= "3.6") and (python_version >= "3.6" and python_full_version < "3.0.0" and sys_platform == "win32" or sys_platform == "win32" and python_version >= "3.6" and python_full_version >= "3.5.0") and (python_version >= "3.6" and python_full_version < "3.0.0" and platform_system == "Windows" or python_full_version >= "3.5.0" and python_version >= "3.6" and platform_system == "Windows")
```

For user lockfiles, the workaround is to treat the problematic transitive dependencies as direct inputs to the resolve by creating a `python_requirement` target, which usually causes the lockfile generator to handle things correctly. For example:
[block:code]
{
  "codes": [
    {
      "code": "python_requirement(\n    name=\"bad_transitive_dependencies_workaround\",\n    requirements=[\n        \"colorama\",\n        \"zipp\",\n    ],\n    # This turns off dependency inference for these \n    # requirements, which you may want to do as they \n    # are transitive dependencies that should not be directly imported.\n    modules=[],\n    # If you are using multiple resolves, you may need to set the \n    # `resolve` field.\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
For tool lockfiles, add the problematic transitive dependencies to `[tool].extra_requirements`. For example:

```toml
[pylint]
version = "pylint>=2.11.0,<2.12"
extra_requirements.add = ["colorama"]
```

Then, regenerate the lock with `generate-lockfiles`.

You can also try manually removing the problematic environment markers, although you will need to remember to do this again whenever re-running `generate-lockfiles`.
[block:api-header]
{
  "title": "Advanced usage"
}
[/block]
### Requirements with undeclared dependencies

Sometimes a requirement does not properly declare in its packaging metadata the other dependencies it depends on, so those will not be installed. It's especially common to leave off dependencies on `setuptools`, which results in import errors like this:

```
import pkg_resources
ModuleNotFoundError: No module named 'pkg_resources'
```

To work around this, you can use the `dependencies` field of `python_requirement`, so that anytime you depend on your requirement, you also bring in the undeclared dependency.
[block:code]
{
  "codes": [
    {
      "code": "# First, make sure you have a `python_requirement` target for \n# the undeclared dependency.\npython_requirement(\n    name=\"setuptools\",\n    requirements=[\"setuptools\"],\n)\n\npython_requirement(\n    name=\"mongomock\",\n    requirements=[\"mongomock\"],\n    dependencies=[\":setuptools\"],\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
If you are using the `python_requirements` and `poetry_requirements` target generators, you can use the `overrides` field to do the same thing:
[block:code]
{
  "codes": [
    {
      "code": "python_requirements(\n    name=\"reqs\",\n    overrides={\n        \"mongomock\": {\"dependencies\": [\":reqs#setuptools\"]},\n    },\n)",
      "language": "python",
      "name": "BUILD"
    },
    {
      "code": "setuptools\nmongomock",
      "language": "text",
      "name": "requirements.txt"
    }
  ]
}
[/block]
### Version control and local requirements

You might be used to using pip's proprietary VCS-style requirements for this, like `git+https://github.com/django/django.git#egg=django`. However, this proprietary format does not work with Pants.

Instead of pip VCS-style requirements:

```
git+https://github.com/django/django.git#egg=Django
git+https://github.com/django/django.git@stable/2.1.x#egg=Django
git+https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8#egg=Django
```

Use direct references from [PEP 440](https://www.python.org/dev/peps/pep-0440/#direct-references):

```
Django@ git+https://github.com/django/django.git
Django@ git+https://github.com/django/django.git@stable/2.1.x
Django@ git+https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8
```

You can also install from local files using [PEP 440 direct references](https://www.python.org/dev/peps/pep-0440/#direct-references). You must use an absolute path to the file, and you should ensure that the file exists on your machine.

```
Django @ file:///Users/pantsbuild/prebuilt_wheels/django-3.1.1-py3-none-any.whl
```

Pip still works with these PEP 440-compliant formats, so you won't be losing any functionality by switching to using them.
[block:callout]
{
  "type": "warning",
  "title": "Local file requirements do not yet work with lockfiles",
  "body": "Pex lockfiles will soon support local file requirements.\n\nIn the meantime, the workaround is to host the files in a private repository / index and load it with `[python-repos]`."
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Version control via SSH",
  "body": "When using version controlled direct references hosted on private repositories with SSH access:\n```\ntarget@ git+ssh://git@github.com:/myorg/myrepo.git@myhash\n```\n...you may see errors like:\n```\n Complete output (5 lines):\n  git@github.com: Permission denied (publickey).\n  fatal: Could not read from remote repository.\n  Please make sure you have the correct access rights\n  and the repository exists.\n  ----------------------------------------\n```\n\nTo fix this, Pants needs to be configured to pass relevant SSH specific environment variables to processes by adding the following to `pants.toml`:\n\n```\n[subprocess-environment]\nenv_vars.add = [\n  \"SSH_AUTH_SOCK\",\n]\n```"
}
[/block]
### Custom repositories

There are two mechanisms for setting up custom Python distribution repositories:

#### Simple repositories as defined by PEP 503
If your custom repo is of this type, i.e., "private PyPI", aka "cheese shop", use the option `indexes` in the `[python-repos]` scope.
[block:code]
{
  "codes": [
    {
      "code": "[python-repos]\nindexes.add = [\"https://custom-cheeseshop.net/simple\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
To exclusively use your custom index—i.e. to not use PyPI—use `indexes = [..]` instead of `indexes.add = [..]`.

#### A Pip findlinks repository
If your custom repo is of this type, use the option `repos` in the `[python-repos]` scope.
[block:code]
{
  "codes": [
    {
      "code": "[python-repos]\nrepos = [\"https://your/repo/here\"]",
      "language": "toml"
    }
  ]
}
[/block]
Indexes are assumed to have a nested structure (like http://pypi.org/simple), whereas repos are flat lists of packages.

#### Authenticating to custom repos

To authenticate to these custom repos you may need to provide credentials (such as a username and password) in the URL, that you don't want to expose in your checked-in pants.toml file.  Instead you can do one of the following:

Create a private (not checked-in) [.pants.rc file](doc:options#pantsrc-file) in each user's Pants repo, that sets this config for the user:
[block:code]
{
  "codes": [
    {
      "code": "[python-repos]\nindexes.add = [\"http://$USERNAME:$PASSWORD@my.custom.repo/index\"]",
      "language": "toml",
      "name": ".pants.rc"
    }
  ]
}
[/block]
Or, set the `indexes` or `repos` config in an environment variable:
[block:code]
{
  "codes": [
    {
      "code": "$ export PANTS_PYTHON_REPOS_INDEXES='+[\"http://$USERNAME:$PASSWORD@my.custom.repo/index\"]'\n$ ./pants package ::",
      "language": "shell"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Tip: use `./pants export` to create a virtual environment for IDEs"
}
[/block]
See [Setting up an IDE](doc:setting-up-an-ide) for more information on `./pants export`. This will create a virtual environment for your user code for compatibility with the rest of the Python ecosystem, e.g. IDEs like Pycharm.