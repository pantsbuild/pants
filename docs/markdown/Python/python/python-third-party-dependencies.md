---
title: "Third-party dependencies"
slug: "python-third-party-dependencies"
excerpt: "How to use third-party Python libraries in your project."
hidden: false
createdAt: "2020-04-30T20:06:43.633Z"
updatedAt: "2022-07-25T15:27:26.087Z"
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

Teaching Pants your "universe"(s) of dependencies
-------------------------------------------------

For Pants to know which dependencies each file uses, it must first know which specific dependencies are in your "universe", i.e. all the third-party dependencies your project directly uses. 

By default, Pants uses a single universe for your whole project, but it's possible to set up multiple. See the header "Multiple resolves" in the "Lockfiles" section.

Each third-party dependency you directly use is modeled by a `python_requirement` target:

```python BUILD
python_requirement(
    name="django",
    requirements=["Django==3.2.1"],
)
```

You do not need a `python_requirement` target for transitive dependencies, i.e. requirements that you do not directly import.

To minimize boilerplate, Pants has target generators to generate `python_requirement` targets for you:

- `python_requirements` for `requirements.txt`.
- `poetry_requirements` for Poetry projects.

### `requirements.txt`

The `python_requirements()` target generator parses a [`requirements.txt`-style file](https://pip.pypa.io/en/stable/user_guide/#requirements-files) to produce a `python_requirement` target for each entry. 

For example:

```text requirements.txt
flask>=1.1.2,<1.3
requests[security]==2.23.0
dataclasses ; python_version<'3.7'
```
```python BUILD
# This will generate three targets:
#
#  - //:reqs#flask
#  - //:reqs#requests
#  - //:reqs#dataclasses
python_requirements(name="reqs")

# The above target generator is spiritually equivalent to this:
python_requirement(
    name="flask",
    requirements=["flask>=1.1.2,<1.3"],
)
python_requirement(
    name="requests",
    requirements=["requests[security]==2.23.0"],
)
python_requirement(
    name="dataclasses",
    requirements=["dataclasses ; python_version<'3.7'"],
)
```

If the file uses a different name than `requirements.txt`, set `source` like this:

```python
python_requirements(source="reqs.txt")
```

> 📘 Where should I put the `requirements.txt`?
> 
> You can name the file whatever you want, and put it wherever makes the most sense for your project.
> 
> In smaller repositories that only use Python, it's often convenient to put the file at the "build root" (top-level), as used on this page.
> 
> For larger repositories or multilingual repositories, it's often useful to have a `3rdparty` or `3rdparty/python` directory. Rather than the target's address being `//:reqs#my_requirement`, its address would be `3rdparty/python:reqs#my_requirement`, for example; or `3rdparty/python#my_requirement` if you leave off the `name` field for `python_requirements`. See [Target Generation](doc:targets#target-generation).

### Poetry

The `poetry_requirements()` target generator parses the [Poetry](https://python-poetry.org/docs/) section in `pyproject.toml` to produce a `python_requirement` target for each entry.

```toml pyproject.toml
[tool.poetry.dependencies]
python = "^3.8"
requests = {extras = ["security"], version = "~1"}
flask = "~1.12"

[tool.poetry.dev-dependencies]
isort = "~5.5"
```
```python BUILD
# This will generate three targets:
#
#  - //:poetry#flask
#  - //:poetry#requests
#  - //:poetry#dataclasses
poetry_requirements(name="poetry")

# The above target generator is spiritually equivalent to this:
python_requirement(
    name="requests",
    requirements=["requests[security]>=1,<2.0"],
)
python_requirement(
    name="flask",
    requirements=["flask>=1.12,<1.13"],
)
python_requirement(
    name="isort",
    requirements=["isort>=5.5,<5.6"],
)
```

Note that Pants does not consume your `poetry.lock` file. Instead, see the [section on lockfiles](#lockfiles) below.

How dependencies are chosen
---------------------------

Once Pants knows about your "universe"(s) of dependencies, it determines which subset should be used through [dependency inference](https://blog.pantsbuild.org/dependency-inference/). Pants will read your import statements, like `import django`, and map it back to the relevant `python_requirement` target. Run [`./pants dependencies path/to/file.py`](doc:project-introspection) or `./pants dependencies path/to:target` to confirm this works.

If dependency inference does not work—such as because it's a runtime dependency you do not import—you can explicitly add the `python_requirement` target to the `dependencies` field, like this:

```python project/BUILD
python_sources(
    name="lib",
    dependencies=[
        # We don't have an import statement for this dep, so inference
        # won't add it automatically. We add it explicitly instead.
        "3rdparty/python#psyscopg2-binary",
    ],
)
```

### Use `modules` and `module_mapping` when the module name is not standard

Some dependencies expose a module different than their project name, such as `beautifulsoup4` exposing `bs4`. Pants assumes that a dependency's module is its normalized name—i.e. `My-distribution` exposes the module `my_distribution`. If that default does not apply to a dependency, it will not be inferred.

Pants already defines a [default module mapping](https://github.com/pantsbuild/pants/blob/main/src/python/pants/backend/python/dependency_inference/default_module_mapping.py) for some common Python requirements, but you may need to augment this by teaching Pants additional mappings:

```python 3rdparty/python/BUILD
# `modules` and `module_mapping` is only needed for requirements where 
# the defaults do not work.

python_requirement(
    name="my_distribution",
    requirements=["my_distribution==4.1"],
    modules=["custom_module"],
)

python_requirements(
    name="reqs",
    module_mapping={"my_distribution": ["custom_module"]},
)

poetry_requirements(
    name="poetry",
    module_mapping={"my_distribution": ["custom_module"]},
)
```

If the dependency is a type stub, and the default does not work, set `type_stub_modules` on the `python_requirement` target, and `type_stubs_module_mapping` on the `python_requirements` and `poetry_requirements` target generators. (The default for type stubs is to strip off `types-`, `-types`, `-stubs`, and `stubs-`. So, `types-requests` gives type stubs for the module `requests`.)

### Warning: multiple versions of the same dependency

It's invalid in Python to have conflicting versions of the same requirement, e.g. `Django==2` and `Django==3`. Instead, Pants supports "multiple resolves" (i.e. multiple lockfiles), as explained in the below section on lockfiles.

When you have multiple targets for the same dependency and they belong to the same resolve ("lockfile"), dependency inference will not work due to ambiguity. If you're using lockfiles—which we strongly recommend—the solution is to set the `resolve` field for problematic `python_requirement` targets so that each resolve has only one requirement and there is no ambiguity.  

This ambiguity is often a problem when you have 2+ `requirements.txt` or `pyproject.toml` files in your project, such as `project1/requirements.txt` and `project2/requirements.txt` both specifying `django`. You may want to set up each `poetry_requirements`/`python_requirements` target generator to use a distinct resolve so that there is no overlap. Alternatively, if the versions are the same, you may want to consolidate the requirements into a common file.

Lockfiles
---------

We strongly recommend using lockfiles because they make your builds [more stable](https://classic.yarnpkg.com/blog/2016/11/24/lockfiles-for-all/) so that new releases of dependencies will not break your project. They also reduce the risk of [supply chain attacks](https://docs.microsoft.com/en-us/windows/security/threat-protection/intelligence/supply-chain-malware).

Pants has two types of lockfiles:

- User lockfiles, for your own code such as packaging binaries and running tests.
- Tool lockfiles, to install tools that Pants runs like Pytest and Flake8.

With both types of lockfiles, Pants can generate the lockfile for you with the `lock` goal.

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

Then, use `./pants lock` to generate the lockfile.

```
❯ ./pants lock
19:00:39.26 [INFO] Completed: Generate lockfile for python-default
19:00:39.29 [INFO] Wrote lockfile for the resolve `python-default` to 3rdparty/python/default.lock
```

> 📘 FYI: user lockfiles improve performance
> 
> As explained at the top of these docs, Pants only uses the subset of the "universe" of your dependencies that is actually needed for a build, such as running tests and packaging a wheel file. This gives fine-grained caching and has other benefits like built packages (e.g. PEX binaries) only including their true dependencies. However, naively, this would mean that you need to resolve dependencies multiple times, which can be slow.
> 
> If you use the default of Pex-generated lockfiles (see below), Pants will only install the
> subset of the lockfile you need for a task. If you instead use Poetry-generated lockfiles,
> Pants will first install the entire lockfile and then it
> will [extract](https://blog.pantsbuild.org/introducing-pants-2-5/) the exact subset needed.
>
> This greatly speeds up performance and improves caching for goals like `test`, `run`, `package`, and `repl`.

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

```python BUILD
python_requirement(
    name="ansicolors",
    requirements=["ansicolors==1.18"],
    resolve="web-app",
)

# Often, you will want to set `resolve` on the 
# `poetry_requirements` and `python_requirements`
# target generators.
poetry_requirements(
    name="poetry",
    resolve="data-science",
    # You can use `overrides` if you only want to change
    # some targets.
    overrides={"requests": {"resolve": "web-app"}},
)
```

If you want the same requirement to show up in multiple resolves, use the [`parametrize`](doc:targets) mechanism.

```python BUILD
# The same requirement in multiple resolves:
python_requirement(
    name="ansicolors_web-app",
    requirements=["ansicolors==1.18"],
    resolve=parametrize("web-app", "data-science")
)

# You can parametrize target generators, including 
# via the `overrides` field:
poetry_requirements(
    name="poetry",
    resolve="data-science",
    overrides={
        "requests": {
            "resolve": parametrize("web-app", "data-science")
        }
    },
)
```

Then, run `./pants lock` to generate the lockfiles. If the results aren't what you'd expect, adjust the prior step.

Finally, update your first-party targets like `python_source` / `python_sources`, `python_test` / `python_tests`, and `pex_binary` to set their `resolve` field. As before, the `resolve` field defaults to `[python].default_resolve`.

```python project/BUILD
python_sources(
    resolve="web-app",
)

python_tests(
    name="tests",
    resolve="web-app",
    # You can use `overrides` to change certain generated targets
    overrides={"test_utils.py": {"resolve": "data-science"}},
)

pex_binary(
    name="main",
    entry_point="main.py",
    resolve="web-app",
)
```

If a first-party target is compatible with multiple resolves—such as some utility code—you can either use the [`parametrize` mechanism](doc:targets) with the `resolve` field or create distinct targets for the same entity.

All transitive dependencies of a target must use the same resolve. Pants's dependency inference already handles this for you by only inferring dependencies on targets that share the same resolve. If you incorrectly add a target from a different resolve to the `dependencies` field, Pants will error with a helpful message when building your code with goals like `test`, `package`, and `run`.

### Tool lockfiles

Pants distributes a lockfile with each tool by default. However, if you change the tool's `version` and `extra_requirements`—or you change its interpreter constraints to not be compatible with our default lockfile—you will need to use a custom lockfile. Set the `lockfile` option in `pants.toml` for that tool, and then run `./pants lock`.

```toml
[flake8]
version = "flake8==3.8.0"
lockfile = "3rdparty/flake8_lockfile.txt"  # This can be any path you'd like.

[pytest]
extra_requirements.add = ["pytest-icdiff"]
lockfile = "3rdparty/pytest_lockfile.txt"
```

```
❯  ./pants lock
19:00:39.26 [INFO] Completed: Generate lockfile for flake8
19:00:39.27 [INFO] Completed: Generate lockfile for pytest
19:00:39.29 [INFO] Wrote lockfile for the resolve `flake8` to 3rdparty/flake8_lockfile.txt
19:00:39.30 [INFO] Wrote lockfile for the resolve `pytest` to 3rdparty/pytest_lockfile.txt
```

You can also run `./pants lock --resolve=tool`, e.g. `--resolve=flake8`, to only generate that tool's lockfile rather than generating all lockfiles.

To disable lockfiles entirely for a tool, set `[tool].lockfile = "<none>"` for that tool. Although we do not recommend this!

### Pex vs. Poetry for lockfile generation

Pants defaults to using [Pex](https://pex.readthedocs.io/) to generate lockfiles, but you can
instead use [Poetry](https://python-poetry.org) by setting `[python].lockfile_generator = "poetry"`
in `pants.toml`.

We generally recommend using the default of Pex, which has several benefits:

1. Supports `[python-repos]` if you have a custom index or repository other than PyPI.
2. Supports `[GLOBAL].ca_certs_path`.
3. Supports VCS (Git) requirements.
4. Faster performance when installing lockfiles. With Pex, Pants will only install the subset of the lockfile needed for a task; with Poetry, Pants will first install the lockfile and then extract the relevant subset.
5. Avoids an issue many users have with problematic environment markers for transitive requirements (see below).

However, it is very plausible there are still issues with Pex lockfiles because the Python ecosystem is so vast. Please open [bug reports](docs:getting-help)! If `lock` fails—or the lockfile errors when installed during goals like `test` and `package`—you may need to temporarily use Poetry. 

Alternatively, you can try to manually generate and manage lockfiles—change to the v2.10 version of these docs to see instructions.

> 📘 Incremental migration from Poetry to Pex
> 
> Pants can understand lockfiles in either Pex's JSON format or Poetry's requirements.txt-style file, regardless of what you set `[python].lockfile_generator` to. This means that you can have some lockfiles using a different format than the others.
> 
> To incrementally migrate, consider writing a script that dynamically sets the option `--python-lockfile-generator`, like this:
> 
> ```
> ./pants --python-lockfile-generator=pex lock --resolve=black --resolve=isort
> ./pants --python-lockfile-generator=poetry lock --resolve=python-default
> ```
> 
> Tip: if you write a script, set `[lock].custom_command` to say how to run your script.

#### Poetry issue with environment markers

One of the issues with Poetry is that sometimes `lock` will work, but then it errors when being installed due to missing transitive dependencies. This is especially common with user lockfiles. For example:

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

```python BUILD
python_requirement(
    name="bad_transitive_dependencies_workaround",
    requirements=[
        "colorama",
        "zipp",
    ],
    # This turns off dependency inference for these 
    # requirements, which you may want to do as they 
    # are transitive dependencies that should not be directly imported.
    modules=[],
    # If you are using multiple resolves, you may need to set the 
    # `resolve` field.
)
```

For tool lockfiles, add the problematic transitive dependencies to `[tool].extra_requirements`. For example:

```toml
[pylint]
version = "pylint>=2.11.0,<2.12"
extra_requirements.add = ["colorama"]
```

Then, regenerate the lock with `lock`.

You can also try manually removing the problematic environment markers, although you will need to remember to do this again whenever re-running `lock`.

Advanced usage
--------------

### Requirements with undeclared dependencies

Sometimes a requirement does not properly declare in its packaging metadata the other dependencies it depends on, so those will not be installed. It's especially common to leave off dependencies on `setuptools`, which results in import errors like this:

```
import pkg_resources
ModuleNotFoundError: No module named 'pkg_resources'
```

To work around this, you can use the `dependencies` field of `python_requirement`, so that anytime you depend on your requirement, you also bring in the undeclared dependency.

```python BUILD
# First, make sure you have a `python_requirement` target for 
# the undeclared dependency.
python_requirement(
    name="setuptools",
    requirements=["setuptools"],
)

python_requirement(
    name="mongomock",
    requirements=["mongomock"],
    dependencies=[":setuptools"],
)
```

If you are using the `python_requirements` and `poetry_requirements` target generators, you can use the `overrides` field to do the same thing:

```python BUILD
python_requirements(
    name="reqs",
    overrides={
        "mongomock": {"dependencies": [":reqs#setuptools"]},
    },
)
```
```text requirements.txt
setuptools
mongomock
```

### Version control and local requirements

You can install requirements from version control using two styles:

- pip's proprietary VCS-style requirements, e.g.
  - `git+https://github.com/django/django.git#egg=Django`
  - `git+https://github.com/django/django.git@stable/2.1.x#egg=Django`
  - `git+https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8#egg=Django`
- direct references from [PEP 440](https://www.python.org/dev/peps/pep-0440/#direct-references), e.g.
  - `Django@ git+https://github.com/django/django.git`
  - `Django@ git+https://github.com/django/django.git@stable/2.1.x`
  - `Django@ git+https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8`

You can also install from local files using [PEP 440 direct references](https://www.python.org/dev/peps/pep-0440/#direct-references). You must use an absolute path to the file, and you should ensure that the file exists on your machine.

```
Django @ file:///Users/pantsbuild/prebuilt_wheels/django-3.1.1-py3-none-any.whl
```

> 🚧 Local file requirements do not yet work with lockfiles
> 
> Pex lockfiles will soon support local file requirements.
> 
> In the meantime, the workaround is to host the files in a private repository / index and load it with `[python-repos]`.

> 📘 Version control via SSH
> 
> When using version controlled direct references hosted on private repositories with SSH access:
> 
> ```
> target@ git+ssh://git@github.com:/myorg/myrepo.git@myhash
> ```
> 
> ...you may see errors like:
> 
> ```
>  Complete output (5 lines):
>   git@github.com: Permission denied (publickey).
>   fatal: Could not read from remote repository.
>   Please make sure you have the correct access rights
>   and the repository exists.
>   ----------------------------------------
> ```
> 
> To fix this, Pants needs to be configured to pass relevant SSH specific environment variables to processes by adding the following to `pants.toml`:
> 
> ```
> [subprocess-environment]
> env_vars.add = [
>   "SSH_AUTH_SOCK",
> ]
> ```

### Custom repositories

There are two mechanisms for setting up custom Python distribution repositories:

#### Simple repositories as defined by PEP 503

If your custom repo is of this type, i.e., "private PyPI", aka "cheese shop", use the option `indexes` in the `[python-repos]` scope.

```toml pants.toml
[python-repos]
indexes.add = ["https://custom-cheeseshop.net/simple"]
```

To exclusively use your custom index—i.e. to not use PyPI—use `indexes = [..]` instead of `indexes.add = [..]`.

#### A Pip findlinks repository

If your custom repo is of this type, use the option `repos` in the `[python-repos]` scope.

```toml
[python-repos]
repos = ["https://your/repo/here"]
```

Indexes are assumed to have a nested structure (like <http://pypi.org/simple>), whereas repos are flat lists of packages.

#### Authenticating to custom repos

To authenticate to custom repos, you may need to provide credentials 
(such as a username and password) in the URL. 

You can use [config file `%(env.ENV_VAR)s` interpolation](doc:options#config-file-interpolation)
to load the values via environment variables. This avoids checking in sensitive information to
version control.

```toml pants.toml
[python-repos]
indexes.add = ["http://%(env.INDEX_USERNAME)s:%(INDEX_PASSWORD)s@my.custom.repo/index"]
```

Alternatively, you can hardcode the value in a private (not checked-in)
[.pants.rc file](doc:options#pantsrc-file) in each user's Pants repo, that sets this config for
the user:

```toml .pants.rc
[python-repos]
indexes.add = ["http://$USERNAME:$PASSWORD@my.custom.repo/index"]
```

Tip: use `./pants export` to create a virtual environment for IDEs
------------------------------------------------------------------

See [Setting up an IDE](doc:setting-up-an-ide) for more information on `./pants export`. This will create a virtual environment for your user code for compatibility with the rest of the Python ecosystem, e.g. IDEs like Pycharm.
