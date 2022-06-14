---
title: "Initial configuration"
slug: "initial-configuration"
excerpt: "Creating the configuration necessary to run Pants."
hidden: false
createdAt: "2020-02-21T17:44:29.297Z"
updatedAt: "2022-05-02T20:58:57.689Z"
---
To get started in a new repository, follow these steps, and then visit one of the language-specific overview pages.

# 1. Create `pants.toml`

Pants configuration lives in a file called `pants.toml` in the root of the repo. This file uses the [TOML](https://github.com/toml-lang/toml) format. 

If you haven't yet, create a `pants.toml` file:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\npants_version = \"$PANTS_VERSION\"",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
where `$PANTS_VERSION` is the version of Pants that you want to pin your repo to.  When you'd like to upgrade Pants, edit `pants_version` and the `./pants` script will self-update on the next run.

# 2. Configure source roots

Many languages organize code in a package hierarchy, so that the relative location of a source file on the filesystem corresponds to a logical package name. The directories that correspond to the roots of the language's package hierarchy are referred to as [source roots](doc:source-roots). These are the filesystem locations from which import paths are computed.

For example, if your Python code lives under `src/python`, then `import myorg.myproject.app` will import the code in `src/python/myorg/myproject/app.py`. 

In simple cases the root of the repository itself might be your only source root. But in many other cases the code is organized so that the source root is nested under some directory such as `src/` or `src/<language name>`. 

To work correctly, Pants needs to know about the source roots in your repo. By default, given a source file path, Pants will treat the longest path prefix that ends in `src`, `src/python`, or `src/py` as its source root, falling back to the repo root itself if no such prefix is found. 

If your project has a different structure, see [Source roots](doc:source-roots) for how to configure them, and for examples of different project structures you can use Pants with.
[block:callout]
{
  "type": "info",
  "title": "Golang projects can skip this step",
  "body": "Golang projects already use `go.mod` to indicate source roots."
}
[/block]
# 3. Enable backends

Most Pants functionality is provided via pluggable [_backends_](doc:enabling-backends), which are activated by adding to the `[GLOBAL].backend_packages` option like this:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\n...\nbackend_packages = [\n  \"pants.backend.go\",\n  \"pants.backend.python\",\n  \"pants.backend.python.lint.black\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
See [here](doc:enabling-backends) for a list of available backends. 

# 4. Update `.gitignore`

If you use Git, we recommend adding these lines to your top-level `.gitignore` file:
[block:code]
{
  "codes": [
    {
      "code": "# Pants workspace files\n/.pants.*\n/dist/\n/.pids",
      "language": "text",
      "name": ".gitignore"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "info",
  "body": "The `pants_ignore` option tells Pants which files to avoid looking at, but it additionally ignores all `.gitignore`d files by default. Occasionally, you will want to ignore something with Git, but still want Pants to work on the file. See [Troubleshooting / common issues](doc:troubleshooting) for how to do this.",
  "title": "FYI: Pants will ignore all files in your `.gitignore` by default"
}
[/block]
# 5. Generate BUILD files

Once you have enabled the backends for the language(s) you'd like to use, run [`./pants tailor`](doc:create-initial-build-files) to generate an initial set of [BUILD](doc:targets) files.

[BUILD](doc:targets) files provide metadata about your code (the timeout of a test, any dependencies which cannot be inferred, etc). BUILD files are typically located in the same directory as the code they describe. Unlike many other systems, Pants BUILD files are usually very succinct, as most metadata is either inferred from static analysis, assumed from sensible defaults, or generated for you. 

In general, you should create (and update) BUILD files by running `./pants tailor`:

```
❯ ./pants tailor
Created scripts/BUILD:
  - Add shell_sources target scripts
Created src/py/project/BUILD:
  - Add python_sources target project
  - Add python_tests target tests
Created src/go/BUILD:
  - Add go_mod target mod
```

Often, this will be all you need for Pants to work, thanks to sensible defaults and inference, like [inferring your dependencies](doc:targets). Sometimes, though, you may need to or want to change certain fields, like setting a longer timeout on a test. 

You may also need to add some targets that Pants cannot generate, like [`resources` and `files`](doc:assets) targets.

To ignore false positives, set `[tailor].ignore_paths` and `[tailor].ignore_adding_targets`. See [tailor](doc:reference-tailor) for more detail.
[block:callout]
{
  "type": "info",
  "body": "We recommend running `./pants tailor --check` in your [continuous integration](doc:doc:using-pants-in-ci) so that you don't forget to add any targets and BUILD files (which might mean that tests aren't run or code isn't validated).\n\n```\n❯ ./pants tailor --check\nWould create scripts/BUILD:\n  - Add shell_sources target scripts\n\nTo fix `tailor` failures, run `./pants tailor`.\n```",
  "title": "Run `./pants tailor --check` in CI"
}
[/block]
# 6. Visit a language specific overview

You're almost ready to go! Next up is visiting one of the language-specific overviews listed below.