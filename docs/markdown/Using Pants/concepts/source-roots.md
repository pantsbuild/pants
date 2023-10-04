---
title: "Source roots"
slug: "source-roots"
excerpt: "Configuring Pants to understand your imports."
hidden: false
createdAt: "2020-02-21T17:44:27.655Z"
---
> 📘 Go and Shell can skip this page
> 
> Go does have a notion of source roots: where your `go.mod` is located. However, that is handled automatically by Pants without you needing to follow this page.
> 
> Shell does not have any notion of source roots.

What are source roots?
======================

Some project layouts use top-level folders for namespace purposes, but have the code live underneath. However, the code's imports will ignore these top-level folders, thanks to mechanisms like the `$PYTHONPATH` and the JVM classpath. _Source roots_ are a generic equivalent of these concepts.

For example, given this Python project:

```
src
└── python
    └── project
        ├── __init__.py
        ├── app.py
        ├── config
        │   ├── __init__.py
        │   └── prod.json
        └── util
            ├── __init__.py
            └── math.py
```

You would likely set `PYTHONPATH=src/python` and use imports like this:

```python
from project.app import App
from project.util.math import add_two

pkgutil.get_data("project.config", "prod.json")
```

In the example above, `src/python` is a source root. So, when some code says `from project.app import App`, Pants can know that this corresponds to the code in `src/python/project/app.py`.

Configuring source roots
========================

There are two ways to configure source roots:

- Using patterns
- Using marker files

You can mix and match between both styles. Run `pants roots` to see what Pants is using:

```
pants roots
src/assets
src/python
src/rust
```

Configuring source roots using patterns
---------------------------------------

You can provide a set of patterns that match your source roots:

```toml pants.toml
[source]
root_patterns = [
  '/src/python',
  '/test/python',
]
```

The `/` prefix means that the source root is located at the build root, so it will match `src/python`, but not `project1/src/python`.

You can leave off the `/` prefix to match any directory whose suffix matches a pattern. For example, `root_patterns = ["src/python"]` would consider all of these to be source roots, if they exist:

- `src/python`
- `project1/src/python`

You can use `*` as a glob. For example, `root_patterns = ["/src/*"]` would consider all of these to be source roots:

- `src/python`
- `src/java`
- `src/assets`

### Configuring no source roots

Many projects do not have any top-level folders used for namespacing.

For example, given this Python project:

```
project
├── __init__.py
├── app.py
├── config
│   ├── __init__.py
│   └── prod.json
└── util
    ├── __init__.py
    └── math.py
```

You would likely _not_ set `PYTHONPATH` and would still use imports like this:

```python
from project.app import App
from project.util.math import add_two

pkgutil.get_data("project.config", "prod.json")
```

If you have no source roots, use this config:

```toml pants.toml
[source]
root_patterns = ["/"]
```

> 📘 Default source roots
> 
> The default value of the `root_patterns` config key is `["/", "src", "src/python", "src/py", "src/java", "src/scala", "src/thrift", "src/protos", "src/protobuf"]`. 
> 
> These capture a range of common cases, including a source root at the root of the repository. If your source roots match these patterns, you don't need to explicitly configure them.

Configuring source roots using marker files
-------------------------------------------

You can also denote your source roots using specially-named marker files. To do so, first pick a name (or multiple names) to use:

```toml pants.toml
[source]
marker_filenames = ["SOURCE_ROOT"]
```

Then, place a file of that name in each of the source roots. The contents of those files don't matter. They can be empty.

For example, given this Python repo, where we have a `setup.py` for each distinct project:

```
.
├── server
│   ├── server
│   │   ├── __init__.py
│   │   └── app.py
│   └── setup.py
└── utils
    ├── setup.py
    └── utils
        ├── __init__.py
        ├── math.py
        └── strutil.py
```

We could use this config:

```toml pants.toml
[source]
marker_filenames = ["setup.py"]
```

We can then run `pants roots` to find these source roots used:

```
pants roots
server
utils
```

This means that Pants would work with these imports:

```python
import server.app
from utils.strutil import capitalize
```

Whereas these imports are invalid:

```python
import server.server.app
from utils.utils.strutil import capitalize
```

Examples
========

These project structures are all valid; Pants does not expect you to reorganize your codebase to use the tool. 

`src/<lang>` setup
------------------

This setup is common in "polyglot" repositories: i.e. repos with multiple languages.

### Project:

```
.
├── 3rdparty
│   ├── java
│   │   └── ivy.xml
│   └── python
│       └── requirements.txt
├── src
│   ├── java
│   │   └── org
│   │       └── pantsbuild
│   │           └── project
│   │               ├── App.java
│   │               └── util
│   │                   └── Math.java
│   └── python
│       └── project
│           ├── __init__.py
│           ├── app.py
│           ├── config
│           │   ├── __init__.py
│           │   └── prod.json
│           └── util
│               ├── __init__.py
│               └── math.py
└── test
    └── python
        └── project
            ├── __init__.py
            └── util
                ├── __init__.py
                └── test_math.py
```

While we have tests in a separate source root here, it's also valid to have tests colocated with their src files.

### Example imports:

```python
# Python
from project.app import App
from project.util.test_math import test_add_2
```

```java
// Java
import org.pantsbuild.project.App
import org.pantsbuild.project.util.Math
```

### Config:

```toml pants.toml
[source]
root_patterns = [
    "/src/java",
    "/src/python",
    "/test/python",
]
```

Note that we organized our 3rdparty requirements in the top-level folders `3rdparty/python` and `3rdparty/java`, but we do not need to include them as source roots because we do not have any first-party code there.

Multiple top-level projects
---------------------------

### Project:

This layout has lots of nesting; this is only one possible way to organize the repository.

```
.
├── ads
│   └── py
│       └── ads
│           ├── __init__.py
│           ├── billing
│           │   ├── __init__.py
│           │   └── calculate_bill.py
│           └── targeting
│               ├── __init__.py
│               └── validation.py
├── base
│   └── py
│       └── base
│           ├── __init__.py
│           ├── models
│           │   ├── __init__.py
│           │   ├── org.py
│           │   └── user.py
│           └── util
│               ├── __init__.py
│               └── math.py
└── news
    └── js
        └── spa.js
```

### Example imports:

```python
import ads.billing.calculate_bill
from base.models.user import User
from base.util.math import add_two
```

Note that even though the projects live in different top-level folders, you are still able to import from other projects. If you would like to limit this, you can use `pants dependents` or `pants dependencies` in CI to track where imports are being used. See [Project introspection](doc:project-introspection).

### Config:

Either of these are valid and they have the same result:

```toml pants.toml
[source]
root_patterns = [
  "/ads/py",
  "/base/py",
  "/new/js",
]
```

```toml pants.toml
[source]
root_patterns = [
  "py",
  "js",
]
```

No source root
--------------

Warning: while this project structure is valid, it often does not scale as well as your codebase grows, such as adding new languages.

### Project:

```
.
├── project
│   ├── __init__.py
│   ├── app.py
│   ├── config
│   │   ├── __init__.py
│   │   └── prod.json
│   └── util
│       ├── __init__.py
│       └── math.py
└── pyproject.toml
```

### Example imports:

```python
from project.app import App
from project.util.math import add_two

pkgutil.get_data("project.config", "prod.json")
```

### Config:

Either of these are valid and they have the same result:

```toml pants.toml
[source]
root_patterns = ["/"]
```

```toml
[source]
marker_filenames = ["pyproject.toml"]
```
