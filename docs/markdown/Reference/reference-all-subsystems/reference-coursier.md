---
title: "coursier"
slug: "reference-coursier"
hidden: false
createdAt: "2022-06-02T21:09:37.616Z"
updatedAt: "2022-06-02T21:09:37.946Z"
---
A dependency resolver for the Maven ecosystem. (https://get-coursier.io/)

Backend: <span style="color: purple"><code>pants.backend.experimental.java</code></span>
Config section: <span style="color: purple"><code>[coursier]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>repos</code></h3>
  <code>--coursier-repos=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_COURSIER_REPOS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "https://maven-central.storage-download.googleapis.com/maven2",
  "https://repo1.maven.org/maven2"
]</pre></span>

<br>

Maven style repositories to resolve artifacts from.

Coursier will resolve these repositories in the order in which they are specifed, and re-ordering repositories will cause artifacts to be re-downloaded. This can result in artifacts in lockfiles becoming invalid.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--coursier-version=&lt;str&gt;</code><br>
  <code>PANTS_COURSIER_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>v2.1.0-M5-18-gfebf9838c</code></span>

<br>

Use this version of coursier.
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--coursier-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_COURSIER_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "v2.1.0-M5-18-gfebf9838c|linux&lowbar;arm64 |d4ad15ba711228041ad8a46d848c83c8fbc421d7b01c415d8022074dd609760f|19264005",
  "v2.1.0-M5-18-gfebf9838c|linux&lowbar;x86&lowbar;64|3e1a1ad1010d5582e9e43c5a26b273b0147baee5ebd27d3ac1ab61964041c90b|19551533",
  "v2.1.0-M5-18-gfebf9838c|macos&lowbar;arm64 |d13812c5a5ef4c9b3e25cc046d18addd09bacd149f95b20a14e4d2a73e358ecf|18826510",
  "v2.1.0-M5-18-gfebf9838c|macos&lowbar;x86&lowbar;64|d13812c5a5ef4c9b3e25cc046d18addd09bacd149f95b20a14e4d2a73e358ecf|18826510",
  "v2.0.16-169-g194ebc55c|linux&lowbar;arm64 |da38c97d55967505b8454c20a90370c518044829398b9bce8b637d194d79abb3|18114472",
  "v2.0.16-169-g194ebc55c|linux&lowbar;x86&lowbar;64|4c61a634c4bd2773b4543fe0fc32210afd343692891121cddb447204b48672e8|18486946",
  "v2.0.16-169-g194ebc55c|macos&lowbar;arm64 |15bce235d223ef1d022da30b67b4c64e9228d236b876c834b64e029bbe824c6f|17957182",
  "v2.0.16-169-g194ebc55c|macos&lowbar;x86&lowbar;64|15bce235d223ef1d022da30b67b4c64e9228d236b876c834b64e029bbe824c6f|17957182"
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
  <code>--coursier-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_COURSIER_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of coursier is not supported.

Supported coursier versions: unspecified

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--coursier-url-template=&lt;str&gt;</code><br>
  <code>PANTS_COURSIER_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://github.com/coursier/coursier/releases/download/{version}/cs-{platform}.gz</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--coursier-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_COURSIER_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "linux&lowbar;arm64": "aarch64-pc-linux",
  "linux&lowbar;x86&lowbar;64": "x86&lowbar;64-pc-linux",
  "macos&lowbar;arm64": "x86&lowbar;64-apple-darwin",
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