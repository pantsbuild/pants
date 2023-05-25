# Docs process

Pants currently hosts documentation at Readme.com, and we use a combination of their `rdme` tool to sync handwritten markdown docs, and a custom `generate-docs` script to update Pants' reference documentation.

Currently the rdme process is manual, until we bed down the process, at which point we'll add it to CI.

The motivation for in-repo docs is covered [on this Google doc](https://docs.google.com/document/d/1bZE8PlF9oRzcPQz4-JUFr5vfD0LFHH4V3Nj2k221CFM/view)

## Versions

Readme expects every version of the docs to correspond to a semver release. Our convention is as follows:

* A version on readme.com corresponds to a pants release (e.g. pants `v2.11` has docs `v2.11`)
* The current development (`main` branch) docs are kept in a readme.com version that will reflect the next version of Pants (e.g. if the most recent release branch is `v2.97`, then `main`'s docs should be synced to `v2.98`).


# Using `rdme` (general notes)

## Setup

### Install `node`

```
brew install node
```

### Install `rdme`

From the `docs` directory,

```
npm install rdme
```

### Log in.

```
npx rdme login --project pants
```

(`rdme` will prompt for two-factor-authentication codes if necessary)

## When cutting a new release branch

Create a fork of the most recent docs branch, and mark it as `beta`, for example:

```
npx rdme versions:create --version=v2.98 --fork="v2.97" --main=false --beta=true --isPublic=true
```

will create a new docs version, `2.98` based on a copy of the docs from version `2.97`.

## Sync docs changes up to `readme.com`

Docs markdown files are stored in the `markdown` directory. `rdme` does not do bidirectional sync, so any changes made on readme.com itself _will be deleted_. Make sure you apply any changes from readme.com locally before syncing up.

From the root of the repository:

```
npx rdme docs docs/markdown --version v2.98
```
