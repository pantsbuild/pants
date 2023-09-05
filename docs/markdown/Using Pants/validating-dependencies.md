---
title: "Validating dependencies"
slug: "validating-dependencies"
excerpt: "Validating your code's dependencies."
hidden: false
createdAt: "2022-12-12T09:10:16.427Z"
---

Visibility rules are the mechanism by which to control who may depend on whom. It is an implementation of Pants's dependency rules API. With these rules a dependency between two files (or targets) may be set for entire directory trees down to single files. A target may be selected not only by its file path but also by target type, name, and tags.

To jump right in, start with [enabling the backend](doc:validating-dependencies#enable-visibility-backend) and add some rules to your BUILD files.


Example visibility rules
------------------------

This example gives a quick introduction to what it looks like, and in the rest of this chapter we will be breaking down and looking at each part of the example going over what it does and how it works.

```python
# example/BUILD

__dependencies_rules__(
  (
    {"type": python_sources},
    "src/a/**",
    "src/b/lib.py",
    "!*",
  ),

  ("*", "*"),
)

__dependents_rules__(
  (
    (
      {"type": "python_*", "tags":["any-python"]},
      {"type": "*", "tags":["libs"]},
      {"path": "special-cased.py"}
    ),
    (
      (
        "!tests/**",
        "!src/*/*/**",
      ),
      (
        "*",
      ),
    ),
  ),

  ("*", "*"),
)
```

First things first, it is a good idea to get familiar with the terminology used here for [dependencies and dependents](doc:validating-dependencies#dependencies-and-dependents). The syntax for `__dependencies_rules__` and `__dependents_rules__` is the same for both directives. They accept any number of input [Rule sets](doc:validating-dependencies#rule-sets). In the above example there are two _rule sets_ in each directive both have the generic "all everything" rule set of `("*", "*")`.

The dependencies rules above reads: All `python_sources` targets may depend on everything from the subtree rooted in `src/a/` the source file `src/b/lib.py` and nothing else. For all other targets everything is allowed.

The dependents rules above reads: Any of all targets beginning with `python_` that has the tag `any-python`, OR any target that has the tag `libs`, OR the source file `special-cased.py`, may _not_ be used by anything from the subtrees rooted in `tests/` nor `src/*/*/` anything else is allowed. For everything else anything is allowed.

Note that when there are both dependencies rules _and_ dependents rules in play for a dependency, both have to allow the dependency for it to be valid.


Enable visibility backend
-------------------------

To use the visibility feature, enable the `pants.backend.experimental.visibility` backend by adding it to the list of `backend_packages` in the `[GLOBAL]` section of your `pants.toml` file.

```toml
[GLOBAL]
backend_packages.add = [
  ...
  "pants.backend.experimental.visibility",
]

```

> 📘 The visibility implementation is marked "experimental"
>
> This does not mean you should not use it, only that it is in "preview" mode meaning that things may change between releases without following our deprecation policy as we work on stabilizing this feature. See [the stabilization ticket](https://github.com/pantsbuild/pants/issues/17634) for what remains to be done for the visibility backend to graduate out of preview.


Dependencies and dependents
===========================

The visibility rules operates on the dependency link between two targets. Dependencies are directional, so if target `A` depends on another target `B` the dependency goes from the "origin" target `A` -> `B`, we say that `B` is the __dependency__ of `A`, while `A` is the __dependent__ of `B`.


> 📘 The Direction of Dependency, `A` -> `B`.
>
> Target `A` may have zero or more dependencies. For each of those dependencies `A` is their dependent.
>
> Target `B` may be the dependency of zero or more dependents. For each of those dependents `B` is their dependency.

Dependency rules are configured in the BUILD files along with targets and any other BUILD file configuration. Rules may be provided on either end of a dependency link between two targets. There are two different keywords to use, one for each side of this link. As discussed above, any target may have both dependencies and dependents and these keywords map onto that:

* `__dependencies_rules__` declares the rules that applies to a targets dependencies.
* `__dependents_rules__` declares the rules that applies to a targets dependents.


    `A` `__dependencies_rules__` -> `__dependents_rules__` `B` `__dependencies_rules__` -> ...


It may help to think about these terms in context of a sentence. For `__dependencies_rules__` it is "this X may only import from <...>", and for `__dependents_rules__` it is "this X may only be imported from <...>".

For each dependency there may be up to 2 sets of rules consulted to determine if it should be `allowed` or `denied` (or just `warn`, see [Rule Actions](doc:targets#rule-actions)), one for each end of the dependency link. The rules themselves are merely [path globs](doc:targets#glob-syntax) applied in order until a matching rule is found. It is an error for there to not be any matching rule, if any rules are defined. That is, you may have a dependency without any rules and that will be allowed, but as soon as there are rules in play there must exist at least one that is a match for the dependency link that dictates the outcome. It is valid to declare either dependency rules or dependent rules you don't have to have both when using visibility rules.


> 🚧 There are no default rules
>
> When you setup a set of rules, it must be comprehensive or Pants will throw an error when it fails to find a matching rule for a dependency/dependent.
>
> Without explicit rules defined, Pants allows all dependencies. This allows you to incrementally start to introduce rules.
>
> **Warning: Rule sets propagate to their subtrees, unless you override them with new rule sets in a corresponding BUILD file.**

Lets look at another dependency example, where we have the following BUILD files for the two source files `src/a/main.py` and `src/b/lib.py`:

```python
# src/a/BUILD
python_sources(dependencies=["src/b/lib.py"], tags=["apps"])

# src/b/BUILD
python_sources(tags=["libs"])
```

The dependency `src/a/main.py` -> `src/b/lib.py` would consult the `__dependencies_rules__` in `src/a/BUILD` for a rule that matches `src/b/lib.py` and the `__dependents_rules__` in `src/b/BUILD` for a rule that matches `src/a/main.py`. See [rule sets](doc:targets#rule-sets) for more details on how this works.

When declaring your rules, you not only provide the rules for the current directory, but also set the default rules for all the subdirectories as well. When overriding such default rules in a child BUILD file, there is a `extend=True` kwarg you may use if you want the default rules to still apply after the ones declared in the current BUILD file.

```python
# src/BUILD
# given some parent rules:
__dependencies_rules__(
  <ruleset-top-1>,
  <ruleset-top-2>,
)

# src/subdir/BUILD

# The following rules:
__dependencies_rules__(
  <ruleset-nested-1>,
  <ruleset-nested-2>,
  extend=True,
)

# are equivalent to:
__dependencies_rules__(
  <ruleset-nested-1>,
  <ruleset-nested-2>,
  <ruleset-top-1>,
  <ruleset-top-2>,
)

# Due to the `extend=True` flag, which inherits the parent rules after those just declared.
```

> 📘 Any rule globs using the declaration path anchoring mode that is inherited using `extend=True` will be anchored to the path of the current BUILD file, not the original one where the rule was extended from.
>
> See [glob syntax](doc:targets#glob-syntax) for details on anchoring modes.

For example:
```python
# src/BUILD
__dependencies_rules__(
  (files,
    "/relative/to/BUILD/file/**",
    "!*",
  ),
)

# src/subdir/BUILD
__dependencies_rules__(
  (resources,
    "/relative/to/BUILD/file/**",
    "!*",
  ),
  extend=True,
)
```

The above rules when applied to `resources` _as well as_ `files` targets in `src/subdir` will allow dependencies only to other targets in the subtree of `src/subdir/relative/to/BUILD/file/` despite the inherited rule declared in `src/BUILD`. For `files` targets in other directories in the `src/` subtree (e.g. `src/another/dir`) dependencies will be allowed only to other targets in the subtree of `src/relative/to/BUILD/file/`.

Keep in mind that visibility rules only operate on direct dependencies - they do not validate dependencies transitively. This is because it would otherwise make it impossible to use private modules. For instance, imagine you have an application stored in `src.app.main`. It needs to access the public modules in the shared library `src.library`. The methods in the public module `src.library.public` make calls to the private modules in that shared library, which means that `src.library.public` depends on `src.library._private`. So when we declare that `src.app.main` may not depend on `src.library._private`, we only forbid the application accessing the private modules directly, since it still needs to access the functionality they provide transitively (but only via the public interface).

If your codebase has a very complex dependency graph, you may need to make sure a given module never reaches some other modules (transitively). For instance, you may need to declare that modules in component `C1` may depend on any module in component `C2` as long as these modules (in `C2`) do not depend (transitively) on any module in component `C3`. This could be necessary if components are deployed separately, for instance, you may package a deployable artifact with components `C1` (full) and `C2` (partial) and another one with components `C2` (partial) and `C3` (full).

In this scenario, you may need to look into alternative solutions to codify these constraints. For example, to check for violations, you could query the dependencies of component `C1` (transitively) using the `dependencies` goal with the `--transitive` option to confirm none of the modules from component `C3` are listed. If there are some, you may find the `paths` goal helpful as it would show you exactly why a certain module from component `C1` depends on a given module in component `C3` if it is unclear. 

Rule sets
---------

As there may be many targets and files with dependencies, odds are that they won't all share the same set of rules. The rules keywords accepts multiple sets of rules, or "rule sets", along with "selector rules" that is used to select which set to use for each target.

The overall structure is (example with 2 rule sets):

```python
# BUILD

__dependencies_rules__(

  # Rule set 1
  (<selectors>, <rule a>, <rule b>, ...),

  # Rule set 2
  (<selectors>, <rules>, ...),

  ...
)
```

The selector and rule share a common syntax (refered to as a __target rule spec__), that is a dictionary value with properties describing what targets it applies to. Together, this pair of selector(s) and rules is called a __rule set__. A rule set may have multiple selectors wrapped in a list/tuple and the rules may be spread out or grouped in any fashion. Grouping rules like this makes it easier to re-use/insert rules from macros or similar.

> 📘 An empty selector (`{}` or `""`) will never match anything and is as such pointless and will result in an error.
>
> For every dependency link, only a single set of rules will ever be applied. The first rule set
> with a matching selector will be the only one used and any remaining rule sets are never
> consulted.

The __target rule spec__ has four properties: `type`, `name`, `tags`, and `path`. From the above example, when determining which rule set to apply for the dependencies of `src/a/main.py` Pants will look for the first selector for `src/a/BUILD` that satisifies the properties `type=python_sources`, `tags=["apps"]`, and `path=src/a/main.py`. The selection is based on exclusion so only when there is a property value and it doesn't match the target's property it will move on to the next selector; the lack of a property will be considered to match anything. Consequently an empty target spec would match all targets, but this is disallowed and will raise an error if used because it is conceptually not very clear when reading the rules.

The values of a __target rule spec__ supports wildcard patterns (or globs) in order to have a single selector match multiple different targets, as described in [glob syntax](doc:targets#glob-syntax). When listing multiple values for the `tags` property, the target must have all of them in order to match. Spread the tags over multiple selectors in order to switch from _AND_ to _OR_ as required. The target `type` to match against will be that of the type used in the BUILD file, as the path (and target address) may refer to a generated target it is the target generators type that will be used during the selector matching process.

The selectors are matched against the target in the order they are defined in the BUILD file, and the first rule set with a selector that is a match will be selected. The rules from the selected rule set is then matched in order against the path of the **target on the other end** of the dependency link. This is worth reading again; Using the above example, the rules defined in `src/a/BUILD` will be matched against `src/b/lib.py` while the `path` selector will be matched against `src/a/main.py`.

Providing some example rule sets for the above example (see [rule actions](doc:targets#rule-actions) on how to mark a rule as "allow" or "deny"):

```python
# src/a/BUILD  (continued from previous example)
__dependencies_rules__(
  (
    {"type": python_sources},  # We can use the target type unquoted when we don't need glob syntax
    "src/a/**",  # May depend on anything from src/a/
    "src/b/lib.py",  # May depend on specific file
    "!*",  # May not depend on anything else. This is our "catch all" rule, ensuring there will never be any fall-through, which would've been an error
  ),

  # We need another rule set, in case we have non-python sources in here, to avoid fall-through.
  # Sticking in a generic catch-all allow-all rule.
  ("*", "*"),
)


# src/b/BUILD  (continued from previous example)
__dependents_rules__(
  (
    (  # Using multiple selectors
      {"type": "python_*", "tags":["any-python"]},
      {"type": "*", "tags":["libs"]},
      {"path": "special-cased.py"},
      {"name": "my-target-name"},
      {"path": "//src/**", "name": "named-*"},
    ),
    (  # Grouping rules for readability
      (  # Deny rules
        "!tests/**",  # No tests
        "!src/*/*/**", # Nothing deeply nested
      ),
      (  # Allow rules
        "*",  # Allow everything else
      ),
    )
  ),

  # We need another rule set, in case we have non-python sources in here, to avoid fall-through.
  # Sticking in a generic catch-all allow-all rule.
  ("*", "*"),
)
```

There is some syntactic sugar for __target rule specs__ so they may be declared in a more concise text form rather than as a dictionary (we have used this text form for the rules already--this is also the form in which they are presented in messages from Pants, when possible). The syntax is `<type>[path:name](tags, ...)`. Empty parts are optional and can be left out, and if only `path` (and/or `name`) is provided the enclosing square brackets are optional. For reference, the string form of the selectors in the previous example code block would look like this:

```python
python_sources            # {"type": python_sources}  -- target types works as strings when used bare
"<python_sources>"        # {"type": "python_sources"}
"<python_*>(any-python)"  # {"type": "python_*", "tags":["any-python"]}
"<*>(libs)"               # {"type": "*", "tags":["libs"]}
"[special-cased.py]"      # {"path": "special-cased.py"}
# May omit square brackets when only providing a path and/or name:
"special-cased.py"        # {"path": "special-cased.py"}
":my-target-name"         # {"name": "my-target-name"}
"//src/**:named-*"        # {"path": "//src/**", "name": "named-*"}
```

The previous example, using this alternative syntax for the selectors, would look like:

```python
  (
    (  # Using multiple selectors
      "<python_*>(any-python)",
      "<*>(libs)",
      "special-cased.py",
      ":my-target-name",
      "//src/**:named-*",
    ),
    ...
  )
```


Glob syntax
-----------

The visibility rules are all about matching globs. There are two wildcards: the `*` matches anything except `/`, and the `**` matches anything including `/`. (For paths that is non-recursive and recursive globbing respectively.)

A glob is matched until the end of the value it is being applied to, so if there is no trailing wildcard (`*` or `**`) on the end of the path glob, it will match to the end of the value. An example where this is useful is for matching on file names regardless of where in the project tree they are:

```
.py
my_source.py
my_*.py
```

Any leading wildcards may be used to emphasize this if desired, but will function the same, so the above is equvalent to (non-exhaustive list of alternatives):
```
*.py
*/my_source.py
**/my_*.py
```

When providing a file name, like `my_source.py` it will be assumed that it will be the full name, so `another_my_source.py` will _not_ be considered a match in that case.

To match any file in a particular directory:
```
some/directory/*
```

So far the rule globs have been matched from anywhere in the matched to path up to the end. To ensure the path begins with a certain pattern we'd have to provide full paths in our rules, like `src/python/proj/lib/file.py` if we want to make sure that our `file.py` is from the `src/` tree. To avoid lengthy and rigid rule globs hurting refactorings etc, there's a concept of "anchoring" the rule. That will apply the rule glob from a fixed point in the matched to path, and there are three such points: project root, rule declaration path and rule invocation path. The difference between declaration and invocation is explained below.

#### Anchoring mode for path globs

The glob prefix specifies which "anchoring mode" to use, and are:

- `//` - Anchor the glob to the project root.
  Example: `//src/python/**` will match all files from the `src/python/` tree.

- `/` - Anchor the glob to the declaration path.
  This is the path of the BUILD file where the rule is declared or extended to, using one of the rules keywords (i.e. `__dependencies_rules__` or `__dependents_rules__`)
  Example: in `src/python/BUILD` there is a rule `/proj/**` which will match all files from the `src/python/proj/` tree.

  Note: When a rule is extended (using `extend=True` in a rules keyword), it is treated as declared in that new BUILD with the `extend=True` argument.

- `.` - Anchor the glob to the invocation path.
  This is the file path of the target for which the rule will apply for. Relative paths are supported, so `../../cousin/path` is valid.
  Example: there is a rule `./lib/*` when applied for the file `src/python/proj/main.py` it would match `src/python/proj/lib/*`.

- Any other value will be left "floating" as described at the top of this glob syntax chapter.

> 🚧 Regardless of anchoring mode, all rules are always anchored to the end of the matched path.

#### Targeting non-source files

So far most examples have been about providing rules that match source files. This will likely be the most common scenario, but other targets may just as well need to be considered. For the general case, non-source file targets will be matched using the directory where it has been declared (the path containing the BUILD file in most cases). 

Generated targets such as the `python_requirement` target that has been generated from a `python_requirements` target is a bit special, and borrows some syntax from its address.

```python
# example/BUILD

python_requirements(name="reqs", ...)

# Limit who may depend on a certain library using dependents rules
__dependents_rules__(
  (
    (
      # List libraries this rule set applies to,
      # here using various anchor modes and patterns for illustration purposes.
      "//example/reqs#click",
      "/reqs#ansicolors",
      "#requests",
      "setuptools",
      ...
    ),
    "src/cli/**",
    "src/net/**",
    "!*",
  ),
  ("*", "*"),
)
```

From the other end, to limit which libraries may be used for some sources:
```python
# example/BUILD

# Limit which libraries may be depended upon
__dependencies_rules__(
  (
    "*",  # These rules applies to all targets
    # May only import setuptools and ansicolors, but no other libraries from the example/reqs target
    "//example/reqs#setuptools",
    "reqs#ansicolors",
    "!//example/reqs#*",

    # Any other dependency allowed
    "*",
  ),
)
```


Rule actions
------------

When a matching rule is found for a path, the path is either allowed or denied based on the rule's action. The dependency link as a whole is only allowed if both ends of the dependency allow it. By default a rule's action is `ALLOW`, but may be changed to `DENY` or `WARN`. The `WARN` action logs a warning message rather than raising an error, but will otherwise allow the dependency.

The rule action is specified as a prefix on the rule glob:

- `!` - Sets the rule's action to `DENY`.
- `?` - Sets the rule's action to `WARN`.
- Any other value is part of the [rule glob](doc:targets#glob-syntax).
