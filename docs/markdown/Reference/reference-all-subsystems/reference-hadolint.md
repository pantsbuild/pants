---
title: "hadolint"
slug: "reference-hadolint"
hidden: false
createdAt: "2022-06-02T21:09:46.325Z"
updatedAt: "2022-06-02T21:09:46.811Z"
---
A linter for Dockerfiles.

Backend: <span style="color: purple"><code>pants.backend.docker.lint.hadolint</code></span>
Config section: <span style="color: purple"><code>[hadolint]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>skip</code></h3>
  <code>--[no-]hadolint-skip</code><br>
  <code>PANTS_HADOLINT_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use Hadolint when running `./pants lint`.
</div>
<br>

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--hadolint-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_HADOLINT_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to Hadolint, e.g. `--hadolint-args='--format json'`.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--hadolint-version=&lt;str&gt;</code><br>
  <code>PANTS_HADOLINT_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>v2.8.0</code></span>

<br>

Use this version of Hadolint.
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--hadolint-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_HADOLINT_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "v2.8.0|macos&lowbar;x86&lowbar;64|27985f257a216ecab06a16e643e8cb0123e7145b5d526cfcb4ce7a31fe99f357|2428944",
  "v2.8.0|macos&lowbar;arm64 |27985f257a216ecab06a16e643e8cb0123e7145b5d526cfcb4ce7a31fe99f357|2428944",
  "v2.8.0|linux&lowbar;x86&lowbar;64|9dfc155139a1e1e9b3b28f3de9907736b9dfe7cead1c3a0ae7ff0158f3191674|5895708"
]</pre></span>

<br>


Known versions to verify downloads against.

Each element is a pipe-separated string of `version|platform|sha256|length`, where:

    - `version` is the version string
    - `platform` is one of [linux_arm64,linux_x86_64,macos_arm64,macos_x86_64],
    - `sha256` is the 64-character hex representation of the expected sha256
    digest of the download file, as emitted by `shasum -a 256`
    - `length` is the expected length of the download file in bytes, as emitted by
    `wc -c`

E.g., `3.1.2|macos_x86_64|6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813`.

Values are space-stripped, so pipes can be indented for readability if necessary.

</div>
<br>

<div style="color: purple">
  <h3><code>use_unsupported_version</code></h3>
  <code>--hadolint-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_HADOLINT_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of Hadolint is not supported.

Supported Hadolint versions: unspecified

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--hadolint-url-template=&lt;str&gt;</code><br>
  <code>PANTS_HADOLINT_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://github.com/hadolint/hadolint/releases/download/{version}/hadolint-{platform}</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--hadolint-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_HADOLINT_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "linux&lowbar;x86&lowbar;64": "Linux-x86&lowbar;64",
  "macos&lowbar;arm64": "Darwin-x86&lowbar;64",
  "macos&lowbar;x86&lowbar;64": "Darwin-x86&lowbar;64"
}</pre></span>

<br>

A dictionary mapping platforms to strings to be used when generating the URL to download the tool.

In --url-template, anytime the `{platform}` string is used, Pants will determine the current platform, and substitute `{platform}` with the respective value from your dictionary.

For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`, and run Pants on Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with unknown-linux.
</div>
<br>

<div style="color: purple">
  <h3><code>config</code></h3>
  <code>--hadolint-config=&lt;file_option&gt;</code><br>
  <code>PANTS_HADOLINT_CONFIG</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Path to an YAML config file understood by Hadolint (https://github.com/hadolint/hadolint#configure).

Setting this option will disable `[hadolint].config_discovery`. Use this option if the config is located in a non-standard location.
</div>
<br>

<div style="color: purple">
  <h3><code>config_discovery</code></h3>
  <code>--[no-]hadolint-config-discovery</code><br>
  <code>PANTS_HADOLINT_CONFIG_DISCOVERY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If true, Pants will include all relevant config files during runs (`.hadolint.yaml` and `.hadolint.yml`).

Use `[hadolint].config` instead if your config is in a non-standard location.
</div>
<br>


## Deprecated options

None