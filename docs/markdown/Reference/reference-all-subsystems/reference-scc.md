---
title: "scc"
slug: "reference-scc"
hidden: false
createdAt: "2022-06-02T21:10:11.605Z"
updatedAt: "2022-06-02T21:10:12.028Z"
---
The Succinct Code Counter, aka `scc` (https://github.com/boyter/scc).

Backend: <span style="color: purple"><code>pants.backend.project_info</code></span>
Config section: <span style="color: purple"><code>[scc]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--scc-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;, ... -- [&lt;shell_str&gt; [&lt;shell_str&gt; [...]]]</code><br>
  <code>PANTS_SCC_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to SCC, e.g. `--scc-args='--no-cocomo'`.

Refer to to https://github.com/boyter/scc.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--scc-version=&lt;str&gt;</code><br>
  <code>PANTS_SCC_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>3.0.0</code></span>

<br>

Use this version of SCC.
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--scc-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SCC_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "3.0.0|macos&lowbar;arm64 |846cb1b25025a0794d455719bc17cfb3f588576a58af1d95036f6c654e294f98|2006145",
  "3.0.0|macos&lowbar;x86&lowbar;64|9c3064e477ab36e16204ad34f649372034bca4df669615eff5de4aa05b2ddf1a|2048134",
  "3.0.0|linux&lowbar;arm64 |04f9e797b70a678833e49df5e744f95080dfb7f963c0cd34f5b5d4712d290f33|1768037",
  "3.0.0|linux&lowbar;x86&lowbar;64|13ca47ce00b5bd032f97f3af7aa8eb3c717b8972b404b155a378b09110e4aa0c|1948341"
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
  <code>--scc-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_SCC_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of SCC is not supported.

Supported SCC versions: unspecified

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--scc-url-template=&lt;str&gt;</code><br>
  <code>PANTS_SCC_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://github.com/boyter/scc/releases/download/v{version}/scc-{version}-{platform}.zip</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--scc-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_SCC_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "linux&lowbar;arm64": "arm64-unknown-linux",
  "linux&lowbar;x86&lowbar;64": "x86&lowbar;64-unknown-linux",
  "macos&lowbar;arm64": "arm64-apple-darwin",
  "macos&lowbar;x86&lowbar;64": "x86&lowbar;64-apple-darwin"
}</pre></span>

<br>

A dictionary mapping platforms to strings to be used when generating the URL to download the tool.

In --url-template, anytime the `{platform}` string is used, Pants will determine the current platform, and substitute `{platform}` with the respective value from your dictionary.

For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`, and run Pants on Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with unknown-linux.
</div>
<br>


## Deprecated options

None