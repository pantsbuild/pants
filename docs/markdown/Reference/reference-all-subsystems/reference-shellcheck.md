---
title: "shellcheck"
slug: "reference-shellcheck"
hidden: false
createdAt: "2022-06-02T21:10:14.562Z"
updatedAt: "2022-06-02T21:10:15.076Z"
---
A linter for shell scripts.

Backend: <span style="color: purple"><code>pants.backend.shell</code></span>
Config section: <span style="color: purple"><code>[shellcheck]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>skip</code></h3>
  <code>--[no-]shellcheck-skip</code><br>
  <code>PANTS_SHELLCHECK_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use Shellcheck when running `./pants lint`.
</div>
<br>

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--shellcheck-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_SHELLCHECK_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to Shellcheck, e.g. `--shellcheck-args='-e SC20529'`.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--shellcheck-version=&lt;str&gt;</code><br>
  <code>PANTS_SHELLCHECK_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>v0.8.0</code></span>

<br>

Use this version of Shellcheck.
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--shellcheck-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SHELLCHECK_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "v0.8.0|macos&lowbar;arm64 |e065d4afb2620cc8c1d420a9b3e6243c84ff1a693c1ff0e38f279c8f31e86634|4049756",
  "v0.8.0|macos&lowbar;x86&lowbar;64|e065d4afb2620cc8c1d420a9b3e6243c84ff1a693c1ff0e38f279c8f31e86634|4049756",
  "v0.8.0|linux&lowbar;arm64 |9f47bbff5624babfa712eb9d64ece14c6c46327122d0c54983f627ae3a30a4ac|2996468",
  "v0.8.0|linux&lowbar;x86&lowbar;64|ab6ee1b178f014d1b86d1e24da20d1139656c8b0ed34d2867fbb834dad02bf0a|1403852"
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
  <code>--shellcheck-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_SHELLCHECK_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of Shellcheck is not supported.

Supported Shellcheck versions: unspecified

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--shellcheck-url-template=&lt;str&gt;</code><br>
  <code>PANTS_SHELLCHECK_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://github.com/koalaman/shellcheck/releases/download/{version}/shellcheck-{version}.{platform}.tar.xz</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--shellcheck-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_SHELLCHECK_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "linux&lowbar;arm64": "linux.aarch64",
  "linux&lowbar;x86&lowbar;64": "linux.x86&lowbar;64",
  "macos&lowbar;arm64": "darwin.x86&lowbar;64",
  "macos&lowbar;x86&lowbar;64": "darwin.x86&lowbar;64"
}</pre></span>

<br>

A dictionary mapping platforms to strings to be used when generating the URL to download the tool.

In --url-template, anytime the `{platform}` string is used, Pants will determine the current platform, and substitute `{platform}` with the respective value from your dictionary.

For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`, and run Pants on Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with unknown-linux.
</div>
<br>

<div style="color: purple">
  <h3><code>config_discovery</code></h3>
  <code>--[no-]shellcheck-config-discovery</code><br>
  <code>PANTS_SHELLCHECK_CONFIG_DISCOVERY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If true, Pants will include all relevant `.shellcheckrc` and `shellcheckrc` files during runs. See https://www.mankier.com/1/shellcheck#RC_Files for where these can be located.
</div>
<br>


## Deprecated options

None