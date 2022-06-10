---
title: "python"
slug: "reference-python"
hidden: false
createdAt: "2022-06-02T21:10:01.435Z"
updatedAt: "2022-06-02T21:10:01.915Z"
---
Options for Pants's Python backend.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[python]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>no_binary</code></h3>
  <code>--python-no-binary=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTHON_NO_BINARY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Do not use binary packages (i.e., wheels) for these 3rdparty projects.

Also accepts `:all:` to disable all binary packages.

Note that some packages are tricky to compile and may fail to install when this option is used on them. See https://pip.pypa.io/en/stable/cli/pip_install/#install-no-binary for details.

Note: Only takes effect if you use Pex lockfiles. Set `[python].lockfile_generator = "pex"` and run the `generate-lockfiles` goal.
</div>
<br>

<div style="color: purple">
  <h3><code>only_binary</code></h3>
  <code>--python-only-binary=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTHON_ONLY_BINARY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Do not use source packages (i.e., sdists) for these 3rdparty projects.

Also accepts `:all:` to disable all source packages.

Packages without binary distributions will fail to install when this option is used on them. See https://pip.pypa.io/en/stable/cli/pip_install/#install-only-binary for details.

Note: Only takes effect if you use Pex lockfiles. Set `[python].lockfile_generator = "pex"` and run the `generate-lockfiles` goal.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>interpreter_constraints</code></h3>
  <code>--python-interpreter-constraints=&quot;[&lt;requirement&gt;, &lt;requirement&gt;, ...]&quot;</code><br>
  <code>PANTS_PYTHON_INTERPRETER_CONSTRAINTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "CPython&gt;=3.7,&lt;4"
]</pre></span>

<br>

The Python interpreters your codebase is compatible with.

These constraints are used as the default value for the `interpreter_constraints` field of Python targets.

Specify with requirement syntax, e.g. 'CPython>=2.7,<3' (A CPython interpreter with version >=2.7 AND version <3) or 'PyPy' (A pypy interpreter of any version). Multiple constraint strings will be ORed together.
</div>
<br>

<div style="color: purple">
  <h3><code>interpreter_versions_universe</code></h3>
  <code>--python-interpreter-versions-universe=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTHON_INTERPRETER_VERSIONS_UNIVERSE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "2.7",
  "3.5",
  "3.6",
  "3.7",
  "3.8",
  "3.9",
  "3.10",
  "3.11"
]</pre></span>

<br>

All known Python major/minor interpreter versions that may be used by either your code or tools used by your code.

This is used by Pants to robustly handle interpreter constraints, such as knowing when generating lockfiles which Python versions to check if your code is using.

This does not control which interpreter your code will use. Instead, to set your interpreter constraints, update `[python].interpreter_constraints`, the `interpreter_constraints` field, and relevant tool options like `[isort].interpreter_constraints` to tell Pants which interpreters your code actually uses. See [Interpreter compatibility](doc:python-interpreter-compatibility).

All elements must be the minor and major Python version, e.g. '2.7' or '3.10'. Do not include the patch version.
</div>
<br>

<div style="color: purple">
  <h3><code>enable_resolves</code></h3>
  <code>--[no-]python-enable-resolves</code><br>
  <code>PANTS_PYTHON_ENABLE_RESOLVES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Set to true to enable lockfiles for user code. See `[python].resolves` for an explanation of this feature.

Warning: the `generate-lockfiles` goal does not yet work if you have local requirements, regardless of using Pex vs. Poetry for the lockfile generator. Support is coming in a future Pants release. In the meantime, the workaround is to host the files in a custom repository with `[python-repos]` ([Third-party dependencies](doc:python-third-party-dependencies)#custom-repositories).

You may also run into issues generating lockfiles when using Poetry as the generator, rather than Pex. See the option `[python].lockfile_generator` for more information.

This option is mutually exclusive with `[python].requirement_constraints`. We strongly recommend using this option because it:

  1. Uses `--hash` to validate that all downloaded files are expected, which reduces the risk of supply chain attacks.
  2. Enforces that all transitive dependencies are in the lockfile, whereas constraints allow you to leave off dependencies. This ensures your build is more stable and reduces the risk of supply chain attacks.
  3. Allows you to have multiple lockfiles in your repository.
</div>
<br>

<div style="color: purple">
  <h3><code>resolves</code></h3>
  <code>--python-resolves=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_PYTHON_RESOLVES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "python-default": "3rdparty/python/default.lock"
}</pre></span>

<br>

A mapping of logical names to lockfile paths used in your project.

Many organizations only need a single resolve for their whole project, which is a good default and often the simplest thing to do. However, you may need multiple resolves, such as if you use two conflicting versions of a requirement in your repository.

If you only need a single resolve, run `./pants generate-lockfiles` to generate the lockfile.

If you need multiple resolves:

  1. Via this option, define multiple resolve names and their lockfile paths. The names should be meaningful to your repository, such as `data-science` or `pants-plugins`.
  2. Set the default with `[python].default_resolve`.
  3. Update your `python_requirement` targets with the `resolve` field to declare which resolve they should be available in. They default to `[python].default_resolve`, so you only need to update targets that you want in non-default resolves. (Often you'll set this via the `python_requirements` or `poetry_requirements` target generators)
  4. Run `./pants generate-lockfiles` to generate the lockfiles. If the results aren't what you'd expect, adjust the prior step.
  5. Update any targets like `python_source` / `python_sources`, `python_test` / `python_tests`, and `pex_binary` which need to set a non-default resolve with the `resolve` field.

If a target can work with multiple resolves, you can either use the `parametrize` mechanism or manually create a distinct target per resolve. See [Targets and BUILD files](doc:targets) for information about `parametrize`.

For example:

    python_sources(
        resolve=parametrize("data-science", "web-app"),
    )

You can name the lockfile paths what you would like; Pants does not expect a certain file extension or location.

Only applies if `[python].enable_resolves` is true.
</div>
<br>

<div style="color: purple">
  <h3><code>default_resolve</code></h3>
  <code>--python-default-resolve=&lt;str&gt;</code><br>
  <code>PANTS_PYTHON_DEFAULT_RESOLVE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>python-default</code></span>

<br>

The default value used for the `resolve` field.

The name must be defined as a resolve in `[python].resolves`.
</div>
<br>

<div style="color: purple">
  <h3><code>resolves_to_interpreter_constraints</code></h3>
  <code>--python-resolves-to-interpreter-constraints=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_PYTHON_RESOLVES_TO_INTERPRETER_CONSTRAINTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

Override the interpreter constraints to use when generating a resolve's lockfile with the `generate-lockfiles` goal.

By default, each resolve from `[python].resolves` will use your global interpreter constraints set in `[python].interpreter_constraints`. With this option, you can override each resolve to use certain interpreter constraints, such as `{'data-science': ['==3.8.*']}`.

Warning: this does NOT impact the interpreter constraints used by targets within the resolve, which is instead set by the option `[python.interpreter_constraints` and the `interpreter_constraints` field. It only impacts how the lockfile is generated.

Pants will validate that the interpreter constraints of your code using a resolve are compatible with that resolve's own constraints. For example, if your code is set to use ['==3.9.*'] via the `interpreter_constraints` field, but it's using a resolve whose interpreter constraints are set to ['==3.7.*'], then Pants will error explaining the incompatibility.

The keys must be defined as resolves in `[python].resolves`.
</div>
<br>

<div style="color: purple">
  <h3><code>invalid_lockfile_behavior</code></h3>
  <code>--python-invalid-lockfile-behavior=&lt;InvalidLockfileBehavior&gt;</code><br>
  <code>PANTS_PYTHON_INVALID_LOCKFILE_BEHAVIOR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, ignore, warn</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>

The behavior when a lockfile has requirements or interpreter constraints that are not compatible with what the current build is using.

We recommend keeping the default of `error` for CI builds.

Note that `warn` will still expect a Pants lockfile header, it only won't error if the lockfile is stale and should be regenerated. Use `ignore` to avoid needing a lockfile header at all, e.g. if you are manually managing lockfiles rather than using the `generate-lockfiles` goal.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile_generator</code></h3>
  <code>--python-lockfile-generator=&lt;LockfileGenerator&gt;</code><br>
  <code>PANTS_PYTHON_LOCKFILE_GENERATOR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>pex, poetry</code></span><br>
<span style="color: green">default: <code>pex</code></span>

<br>

Whether to use Pex or Poetry with the `generate-lockfiles` goal.

Poetry does not support these features:

  1) `[python-repos]` for custom indexes/cheeseshops.
  2) VCS (Git) requirements.
  3) `[GLOBAL].ca_certs_path`.

If you use any of these features, you should use Pex.

Several users have also had issues with how Poetry's lockfile generation handles environment markers for transitive dependencies; certain dependencies end up with nonsensical environment markers which cause the dependency to not be installed, then for Pants/Pex to complain the dependency is missing, even though it's in the lockfile. There is a workaround: for `[python].resolves`, manually create a `python_requirement` target for the problematic transitive dependencies so that they are seen as direct requirements, rather than transitive. For tool lockfiles, add the problematic transitive dependency to `[tool].extra_requirements`, e.g. `[isort].extra_requirements`. Then, regenerate the lockfile(s) with the `generate-lockfiles` goal. Alternatively, use Pex for generation.

Finally, installing from a Poetry-generated lockfile is slower than installing from a Pex lockfile. When using a Pex lockfile, Pants will only install the subset needed for the current task.

However, Pex lockfile generation is a new feature. Given how vast the Python packaging ecosystem is, it is possible you may experience edge cases / bugs we haven't yet covered. Bug reports are appreciated! https://github.com/pantsbuild/pants/issues/new/choose

Note that while Pex generates locks in a proprietary JSON format, you can use the `./pants export` goal for Pants to create a virtual environment for interoperability with tools like IDEs.
</div>
<br>

<div style="color: purple">
  <h3><code>resolves_generate_lockfiles</code></h3>
  <code>--[no-]python-resolves-generate-lockfiles</code><br>
  <code>PANTS_PYTHON_RESOLVES_GENERATE_LOCKFILES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If False, Pants will not attempt to generate lockfiles for `[python].resolves` when running the `generate-lockfiles` goal.

This is intended to allow you to manually generate lockfiles as a workaround for the issues described in the `[python].lockfile_generator` option, if you are not yet ready to use Pex.

If you set this to False, Pants will not attempt to validate the metadata headers for your user lockfiles. This is useful so that you can keep `[python].invalid_lockfile_behavior` to `error` or `warn` if you'd like so that tool lockfiles continue to be validated, while user lockfiles are skipped.
</div>
<br>

<div style="color: purple">
  <h3><code>run_against_entire_lockfile</code></h3>
  <code>--[no-]python-run-against-entire-lockfile</code><br>
  <code>PANTS_PYTHON_RUN_AGAINST_ENTIRE_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

If enabled, when running binaries, tests, and repls, Pants will use the entire lockfile file instead of just the relevant subset.

We generally do not recommend this if `[python].lockfile_generator` is set to `"pex"` thanks to performance enhancements we've made. When using Pex lockfiles, you should get similar performance to using this option but without the downsides mentioned below.

Otherwise, if not using Pex lockfiles, this option can improve performance and reduce cache size. But it has two consequences: 1) All cached test results will be invalidated if any requirement in the lockfile changes, rather than just those that depend on the changed requirement. 2) Requirements unneeded by a test/run/repl will be present on the sys.path, which might in rare cases cause their behavior to change.

This option does not affect packaging deployable artifacts, such as PEX files, wheels and cloud functions, which will still use just the exact subset of requirements needed.
</div>
<br>

<div style="color: purple">
  <h3><code>requirement_constraints</code></h3>
  <code>--python-requirement-constraints=&lt;file_option&gt;</code><br>
  <code>PANTS_PYTHON_REQUIREMENT_CONSTRAINTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

When resolving third-party requirements for your own code (vs. tools you run), use this constraints file to determine which versions to use.

Mutually exclusive with `[python].enable_resolves`, which we generally recommend as an improvement over constraints file.

See https://pip.pypa.io/en/stable/user_guide/#constraints-files for more information on the format of constraint files and how constraints are applied in Pex and pip.

This only applies when resolving user requirements, rather than tools you run like Black and Pytest. To constrain tools, set `[tool].lockfile`, e.g. `[black].lockfile`.
</div>
<br>

<div style="color: purple">
  <h3><code>resolve_all_constraints</code></h3>
  <code>--[no-]python-resolve-all-constraints</code><br>
  <code>PANTS_PYTHON_RESOLVE_ALL_CONSTRAINTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

(Only relevant when using `[python].requirement_constraints.`) If enabled, when resolving requirements, Pants will first resolve your entire constraints file as a single global resolve. Then, if the code uses a subset of your constraints file, Pants will extract the relevant requirements from that global resolve so that only what's actually needed gets used. If disabled, Pants will not use a global resolve and will resolve each subset of your requirements independently.

Usually this option should be enabled because it can result in far fewer resolves.
</div>
<br>

<div style="color: purple">
  <h3><code>resolver_manylinux</code></h3>
  <code>--python-resolver-manylinux=&lt;str&gt;</code><br>
  <code>PANTS_PYTHON_RESOLVER_MANYLINUX</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>manylinux2014</code></span>

<br>

Whether to allow resolution of manylinux wheels when resolving requirements for foreign linux platforms. The value should be a manylinux platform upper bound, e.g.: 'manylinux2010', or else the string 'no' to disallow.
</div>
<br>

<div style="color: purple">
  <h3><code>tailor_ignore_solitary_init_files</code></h3>
  <code>--[no-]python-tailor-ignore-solitary-init-files</code><br>
  <code>PANTS_PYTHON_TAILOR_IGNORE_SOLITARY_INIT_FILES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Don't tailor `python_sources` targets for solitary `__init__.py` files, as those usually exist as import scaffolding rather than true library code.

Set to False if you commonly have packages containing real code in `__init__.py` and there are no other .py files in the package.
</div>
<br>

<div style="color: purple">
  <h3><code>tailor_requirements_targets</code></h3>
  <code>--[no-]python-tailor-requirements-targets</code><br>
  <code>PANTS_PYTHON_TAILOR_REQUIREMENTS_TARGETS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Tailor python_requirements() targets for requirements files.
</div>
<br>

<div style="color: purple">
  <h3><code>tailor_pex_binary_targets</code></h3>
  <code>--[no-]python-tailor-pex-binary-targets</code><br>
  <code>PANTS_PYTHON_TAILOR_PEX_BINARY_TARGETS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Tailor pex_binary() targets for Python entry point files.
</div>
<br>

<div style="color: purple">
  <h3><code>macos_big_sur_compatibility</code></h3>
  <code>--[no-]python-macos-big-sur-compatibility</code><br>
  <code>PANTS_PYTHON_MACOS_BIG_SUR_COMPATIBILITY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

If set, and if running on MacOS Big Sur, use macosx_10_16 as the platform when building wheels. Otherwise, the default of macosx_11_0 will be used. This may be required for pip to be able to install the resulting distribution on Big Sur.
</div>
<br>


## Deprecated options

None