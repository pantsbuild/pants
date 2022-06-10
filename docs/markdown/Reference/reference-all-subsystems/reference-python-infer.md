---
title: "python-infer"
slug: "reference-python-infer"
hidden: false
createdAt: "2022-06-02T21:10:02.764Z"
updatedAt: "2022-06-02T21:10:03.189Z"
---
Options controlling which dependencies will be inferred for Python targets.

Backend: <span style="color: purple"><code>pants.backend.python</code></span>
Config section: <span style="color: purple"><code>[python-infer]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>imports</code></h3>
  <code>--[no-]python-infer-imports</code><br>
  <code>PANTS_PYTHON_INFER_IMPORTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer a target's imported dependencies by parsing import statements from sources.

To ignore a false positive, you can either put `# pants: no-infer-dep` on the line of the import or put `!{bad_address}` in the `dependencies` field of your target.
</div>
<br>

<div style="color: purple">
  <h3><code>string_imports</code></h3>
  <code>--[no-]python-infer-string-imports</code><br>
  <code>PANTS_PYTHON_INFER_STRING_IMPORTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Infer a target's dependencies based on strings that look like dynamic dependencies, such as Django settings files expressing dependencies as strings.

To ignore any false positives, put `!{bad_address}` in the `dependencies` field of your target.
</div>
<br>

<div style="color: purple">
  <h3><code>string_imports_min_dots</code></h3>
  <code>--python-infer-string-imports-min-dots=&lt;int&gt;</code><br>
  <code>PANTS_PYTHON_INFER_STRING_IMPORTS_MIN_DOTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>2</code></span>

<br>

If --string-imports is True, treat valid-looking strings with at least this many dots in them as potential dynamic dependencies. E.g., `'foo.bar.Baz'` will be treated as a potential dependency if this option is set to 2 but not if set to 3.
</div>
<br>

<div style="color: purple">
  <h3><code>assets</code></h3>
  <code>--[no-]python-infer-assets</code><br>
  <code>PANTS_PYTHON_INFER_ASSETS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Infer a target's asset dependencies based on strings that look like Posix filepaths, such as those given to `open` or `pkgutil.get_data`. To ignore any false positives, put `!{bad_address}` in the `dependencies` field of your target.
</div>
<br>

<div style="color: purple">
  <h3><code>assets_min_slashes</code></h3>
  <code>--python-infer-assets-min-slashes=&lt;int&gt;</code><br>
  <code>PANTS_PYTHON_INFER_ASSETS_MIN_SLASHES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1</code></span>

<br>

If --assets is True, treat valid-looking strings with at least this many forward slash characters as potential assets. E.g. `'data/databases/prod.db'` will be treated as a potential candidate if this option is set to 2 but not to 3.
</div>
<br>

<div style="color: purple">
  <h3><code>inits</code></h3>
  <code>--[no-]python-infer-inits</code><br>
  <code>PANTS_PYTHON_INFER_INITS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Infer a target's dependencies on any `__init__.py` files in the packages it is located in (recursively upward in the directory structure).

Even if this is disabled, Pants will still include any ancestor `__init__.py` files, only they will not be 'proper' dependencies, e.g. they will not show up in `./pants dependencies` and their own dependencies will not be used.

If you have empty `__init__.py` files, it's safe to leave this option off; otherwise, you should enable this option.
</div>
<br>

<div style="color: purple">
  <h3><code>conftests</code></h3>
  <code>--[no-]python-infer-conftests</code><br>
  <code>PANTS_PYTHON_INFER_CONFTESTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer a test target's dependencies on any conftest.py files in the current directory and ancestor directories.
</div>
<br>

<div style="color: purple">
  <h3><code>entry_points</code></h3>
  <code>--[no-]python-infer-entry-points</code><br>
  <code>PANTS_PYTHON_INFER_ENTRY_POINTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer dependencies on targets' entry points, e.g. `pex_binary`'s `entry_point` field, `python_awslambda`'s `handler` field and `python_distribution`'s `entry_points` field.
</div>
<br>

<div style="color: purple">
  <h3><code>unowned_dependency_behavior</code></h3>
  <code>--python-infer-unowned-dependency-behavior=&lt;UnownedDependencyUsage&gt;</code><br>
  <code>PANTS_PYTHON_INFER_UNOWNED_DEPENDENCY_BEHAVIOR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning, ignore</code></span><br>
<span style="color: green">default: <code>ignore</code></span>

<br>

How to handle imports that don't have an inferrable owner.

Usually when an import cannot be inferred, it represents an issue like Pants not being properly configured, e.g. targets not set up. Often, missing dependencies will result in confusing runtime errors like `ModuleNotFoundError`, so this option can be helpful to error more eagerly.

To ignore any false positives, either add `# pants: no-infer-dep` to the line of the import or put the import inside a `try: except ImportError:` block.
</div>
<br>


## Advanced options

None

## Deprecated options

None