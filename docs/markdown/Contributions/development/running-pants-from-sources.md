---
title: "Running Pants from sources"
slug: "running-pants-from-sources"
hidden: false
createdAt: "2021-08-10T00:24:00.100Z"
---
Running Pants from sources in its own repo
------------------------------------------

In most repos, you invoke a pre-built release of Pants, either via the `pants` launcher binary, or a `./pants` runner script in the repo root. However in the Pants repo itself, the [`./pants`](https://github.com/pantsbuild/pants/blob/main/pants) runner script is different - it invokes Pants directly from the sources in that repo. 

This allows you to iterate rapidly when working in the Pants repo: You can edit Rust and Python source files, and immediately run `./pants` to try out your changes. The script will ensure that any Rust changes are compiled and linked, and then run Pants using your modified sources.

Running Pants from sources in other repos
-----------------------------------------

Sometimes you may want to try out your Pants changes on code in some other repo. If you're using the `pants` launcher binary, you can set the env var `PANTS_SOURCE` to point to your local clone of the pantsbuild/pants repo:

```
PANTS_SOURCE=../pants pants test ::
```

Or, if you're using a `./pants` runner script, you can instead use a special `./pants_from_sources` script that you copy into the repo.

This script expects to find a clone of the Pants repo, named `pants`, as a sibling directory of the one you're running in, and it will use the sources in that sibling to run Pants in the other repo, using that repo's config file and so on.

You can find an example of this script [here](https://github.com/pantsbuild/example-python/blob/2.14/pants_from_sources). To copy it into your repo, use

```
curl -L -O https://raw.githubusercontent.com/pantsbuild/example-python/2.14/pants_from_sources && \
  chmod +x pants_from_sources
```
