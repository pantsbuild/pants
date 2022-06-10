---
title: "setup-py-generation"
slug: "reference-setup-py-generation"
hidden: false
createdAt: "2022-06-02T21:10:12.237Z"
updatedAt: "2022-06-02T21:10:12.704Z"
---
Options to control how setup.py is generated from a `python_distribution` target.

Backend: <span style="color: purple"><code>pants.backend.python</code></span>
Config section: <span style="color: purple"><code>[setup-py-generation]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>generate_setup_default</code></h3>
  <code>--[no-]setup-py-generation-generate-setup-default</code><br>
  <code>PANTS_SETUP_PY_GENERATION_GENERATE_SETUP_DEFAULT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

The default value for the `generate_setup` field on `python_distribution` targets. Can be overridden per-target by setting that field explicitly. Set this to False if you mostly rely on handwritten setup files (setup.py, setup.cfg and similar). Leave as True if you mostly rely on Pants generating setup files for you.
</div>
<br>

<div style="color: purple">
  <h3><code>first_party_dependency_version_scheme</code></h3>
  <code>--setup-py-generation-first-party-dependency-version-scheme=&lt;FirstPartyDependencyVersionScheme&gt;</code><br>
  <code>PANTS_SETUP_PY_GENERATION_FIRST_PARTY_DEPENDENCY_VERSION_SCHEME</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>exact, compatible, any</code></span><br>
<span style="color: green">default: <code>exact</code></span>

<br>

What version to set in `install_requires` when a `python_distribution` depends on other `python_distribution`s. If `exact`, will use `==`. If `compatible`, will use `~=`. If `any`, will leave off the version. See https://www.python.org/dev/peps/pep-0440/#version-specifiers.
</div>
<br>


## Advanced options

None

## Deprecated options

None