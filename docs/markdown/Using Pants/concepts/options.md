---
title: "Options"
slug: "options"
excerpt: "A deep dive into how options may be configured."
hidden: false
createdAt: "2020-02-21T17:44:27.231Z"
updatedAt: "2022-03-18T23:55:37.347Z"
---
Option scopes
=============

Options are partitioned into named _scopes_.

Some systemwide options belong in the _global scope_. For example, the `--level` option, which controls the logging level, is in the global scope. 

Other options belong to a _subsystem scope_. A _subsystem_ is simply a collection of related options, in a scope. For example, the `pytest` subsystem contains options related to [Python's test framework pytest](doc:reference-pytest). 

Setting options
===============

Every option can be set in the following ways, in order of precedence:

1. Via a command line flag.
2. In an environment variable.
3. In a config file (`pants.toml`).

If an option isn't set in one of these ways, it will take on a default value.

You can inspect both the current value and the default value by using `./pants help $scope` or `./pants help-advanced $scope`, e.g. `./pants help global`.

Command-line flags
------------------

Global options are set using an unqualified flag:

```bash
./pants --level=debug ...
```

Subsystem options are set by providing the flag, with the name prefixed with the lower-case scope name and a dash. So for the option `--root-patterns` in the scope `source`:

```bash
./pants --source-root-patterns="['^ext']"
```

Environment variables
---------------------

Global options are set using the environment variable `PANTS_{OPTION_NAME}`:

```bash
PANTS_LEVEL=debug ./pants ...
```

Subsystem options are set using the environment variable  
`PANTS_{SCOPE}_{OPTION_NAME}`:

```bash
PANTS_SOURCE_ROOT_PATTERNS="['^ext']" ./pants ...
```

Note that the scope and option name are upper-cased, and any dashes in the option flag name are converted to underscores: `--multiword-name` becomes `MULTIWORD_NAME`.

Config file entries
-------------------

Global options are set in the `GLOBAL` section of the config file:

```toml pants.toml
[GLOBAL]
level = "debug"
```

Subsystem options are set in the section named for their scope:

```toml pants.toml
[source]
root_patterns = ["/src/python"]
```

Note that any dashes in the option flag name are converted to underscores: `--multiword-name` becomes `multiword_name`.

### Config file interpolation

Environment variables can be interpolated by using the syntax `%(env.ENV_VAR)s`, e.g.:

```toml pants.toml
[python-repos]
# This will substitute `%(env.PY_REPO)s` with the value of the environment
# variable PY_REPO
indexes.add = ["http://%(env.PY_REPO)s@my.custom.repo/index
```

Additionally, a few special values are pre-populated with the `%(var)s` syntax:

- `%(buildroot)s`: absolute path to the root of your repository
- `%(homedir)s`: equivalent to `$HOME` or `~`
- `%(user)s`: equivalent to `$USER`
- `%(pants_distdir)s`: absolute path of the global option `--pants-distdir`, which defaults 
   to `{buildroot}/dist/`

Option types
============

Every option has a type, and any values you set must be of that type.

The option types are:

- string
- integer
- bool
- list
- dict

A list-valued option may also declare a specific type for its members (e.g., a list of strings, or a list of integers). 

String and integer values
-------------------------

Standalone string and integer values are written without quotes. Any quotes will be considered part of the value, after shell escaping.

### Command-line flags:

```bash
./pants --scope-intopt=42
./pants --scope-stropt=qux
```

### Environment variables:

```bash
PANTS_SCOPE_INTOPT=42
PANTS_SCOPE_STROPT=qux
```

### Config file entries:

```toml pants.toml
[scope]
intopt = 42
stropt = "qux"
```

Boolean values
--------------

Boolean values can be specified using the special strings `true` and `false`. When specifying them via command-line flags you can also use the `--boolopt/--no-boolopt` syntax.

### Command-line flags:

```bash
./pants --scope-boolopt=true
./pants --scope-boolopt
./pants --no-scope-boolopt
```

### Environment variables:

```bash
PANTS_SCOPE_BOOLOPT=true
```

### Config file entries:

```toml pants.toml
[scope]
boolopt = true
```

List values
-----------

List values are parsed as Python list literals, so you must quote string values, and you may need to apply shell-level quoting and/or escaping, as required.

### Command-line flags:

```bash
./pants --scope-listopt="['foo','bar']"
```

You can also leave off the `[]` to _append_ elements. So we can rewrite the above to:

```bash
./pants --scope-listopt=foo --scope-listopt=bar
```

### Environment variables:

```bash
PANTS_SCOPE_LISTOPT="['foo','bar']"
```

Like with command-line flags, you can leave off the `[]` to _append_ elements:

```bash
PANTS_SCOPE_LISTOPT=foo
```

### Config file entries:

```toml pants.toml
[scope]
listopt = [
  'foo', 
  'bar'
]
```

### Add/remove semantics

List values have some extra semantics:

- A value can be preceded by `+`, which will _append_ the elements to the value obtained from lower-precedence sources. 
- A value can be preceded by `-`, which will _remove_ the elements from the value obtained from lower-precedence sources. 
- Multiple `+` and `-` values can be provided, separated by commas.
- Otherwise, the value _replaces_ the one obtained from lower-precedence sources. 

For example, if the value of `--listopt` in `scope` is set to `[1, 2]` in a config file, then 

```bash
./pants --scope-listopt="+[3,4]"
```

will set the value to `[1, 2, 3, 4]`. 

```bash
./pants --scope-listopt="-[1],+[3,4]"
```

will set the value to `[2, 3, 4]`, and 

```bash
./pants --scope-listopt="[3,4]"
```

will set the value to `[3, 4]`.

> 📘 Add/remove syntax in .toml files
> 
> The +/- syntax works in .toml files, but the entire value must be quoted:
> 
> ```toml pants.toml
> [scope]
> listopt = "+[1,2],-[3,4]"
> ```
> 
> This means that TOML treats the value as a string, instead of a TOML list. 
> 
> Alternatively, you can use this syntactic sugar, which allows the values to be regular TOML lists: 
> 
> ```toml pants.toml
> [scope]
> listopt.add = [1, 2]
> listopt.remove = [3, 4]
> ```
> 
> But note that this only works in Pants's `.toml` config files, not in environment variables or command-line flags.

Dict values
-----------

Dict values are parsed as Python dict literals on the command-line and environment variables, so you must quote string keys and values, and you may need to apply shell-level quoting and/or escaping, as required.

### Command-line flags:

```bash
./pants --scope-dictopt="{'foo':1,'bar':2}"
```

### Environment variables:

```bash
PANTS_SCOPE_DICTOPT="{'foo':1,'bar':2}"
```

### Config file entries:

You can use TOML's [nested table features](https://toml.io/en/v1.0.0#inline-table). These are equivalent:

```toml pants.toml
[scope]
dictopt = { foo = 1, bar = 2}
```

```toml pants.toml
[scope.dictopt]
foo = 1
bar = 2
```

You can also use a string literal. Note the quotes:

```toml pants.toml
[scope]
dictopt = """{
 'foo': 1,
 'bar': 2,
}"""
```

### Add/replace semantics

- A value can be preceded by `+`, which will _update_ the value obtained from lower-precedence sources with the entries.
- Otherwise, the value _replaces_ the one obtained from lower-precendence sources. 

For example, if the value of `--dictopt` in `scope` is set to `{'foo', 1, 'bar': 2}` in a config file, then 

```bash
./pants --scope-dictopt="+{'foo':42,'baz':3}"
```

will set the value to `{'foo': 42, 'bar': 2, 'baz': 3}`, and 

```bash
./pants --scope-dictopt="{'foo':42,'baz':3}"
```

will set the value to `{'foo': 42, 'baz': 3}`.

Reading individual option values from files
===========================================

If an option value is too large or elaborate to use directly, or if you don't want to hard-code 
values directly in `pants.toml`, you can set the value of any option to the string 
`@relative/path/from/repo/root/to/file` (note the leading `@`), and the value will be read 
from that file. 

If the file name ends with `.json` or `.yaml` then the file will be parsed as the relevant
format, which is useful for list- and dict-valued options. 

Otherwise, the file is parsed as a literal as described above for each option type.

Note that you can use this feature on the command-line, in an env var, or in a config file:

```toml pants.toml
[scope]
opt = "@path/to/file.json"
```

```bash
PANTS_SCOPE_OPTION=@path/to/file.json
```

```bash
./pants --scope-option="@path/to/file.json"
```

> 🚧 Gotcha: If you modify the value file, you must manually restart pantsd
> 
> Until we resolve [this issue](https://github.com/pantsbuild/pants/issues/10360), changing
> the value in a file used with the `@` syntax as described above will not invalidate the build.
> For now, if such a file changes you will have to restart the Pants daemon manually. You can 
> do so by `kill`ing it (after using `ps -ef | grep pantsd` to find its pid), or by running 
> Pants once with `--no-pantsd`.


`.pants.rc` file
================

You can set up personal Pants config files, using the same TOML syntax as `pants.toml`. By default, Pants looks for the paths `/etc/pantsrc`, `~/.pants.rc`, and `.pants.rc` in the repository root.

For example:

```toml .pants.rc
[python]
# Even though our repository uses 3.8+, because I have an M1, 
# I must use Python 3.9+.
interpreter_constraints = ["==3.9.*"]
```

If you want to ban this feature, set `[GLOBAL].pantsrc = false` in `pants.toml`.
