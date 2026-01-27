# Qualifier Lexicon

This lexicon defines standard qualifier names that servers
**MAY** support in the `Qualifier` message to facilitate interoperability.

The following standard qualifier `name`s are defined:

* `resource_type`: This describes the type of resource.

  File assests should use an existing [media type](https://www.iana.org/assignments/media-types/media-types.xhtml).

  Git repositories should use `application/x-git`.
  
  Example:
  ```json
  // (FetchDirectoryRequest proto)
  {
    "uris": [
      "https://github.com/bazelbuild/remote-apis.git"
    ],
    "qualifiers": [
      {
        "name": "resource_type",
        "value": "application/x-git"
      }
    ]
  }
  ```   

* `checksum.sri`: The value represents a [Subresource Integrity](https://www.w3.org/TR/SRI/)
  checksum of the content. Multiple checksums may be specified, separated by
  whitespace. The Qualifier is satisfied if the server validates at least one of the
  provided checksums, although it may choose to validate more than one.

  Example:
  ```json
  // (FetchBlobRequest proto)
  {
    "uris": [
      "https://github.com/bazelbuild/remote-apis/archive/v2.0.0.tar.gz"
    ],
    "qualifiers": [
      {
        "name": "checksum.sri",
        "value": "sha384-G9d9sKLNRfeFfGn1mnVXeJzXSbkCsYt11kl5hJnHpdzfVuLIuruIDnrs/lZyB4Gs"
      }
    ]
  }
  ```

* `directory`: This is the relative path of a subdirectory of the resource.  There should
  be no trailing `/`.

  Example:
  ```json
  // (FetchDirectoryRequest proto)
  {
    "uris": [
      "https://github.com/bazelbuild/remote-apis.git"
    ],
    "qualifiers": [
      {
        "name": "directory",
        "value": "build/bazel/remote/execution/v2"
      }
    ]
  }
  ```

* `vcs.branch`: This is the name of the branch under source control management

  Example:
  ```json
  // (FetchDirectoryRequest proto)
  {
    "uris": [
      "https://github.com/bazelbuild/remote-apis.git"
    ],
    "qualifiers": [
      {
        "name": "vcs.branch",
        "value": "master"
      }
    ]
  }
  ```

* `vcs.commit`: The value is the identity of a specific version of the content
  under source control management.  For git this is a commit-ish, for subversion
  this is a revision, for example.

  Example:
  ```json
  // (FetchDirectoryRequest proto)
  {
    "uris": [
      "https://github.com/bazelbuild/remote-apis.git"
    ],
    "qualifiers": [
      {
        "name": "vcs.commit",
        "value": "b5123b1bb2853393c7b9aa43236db924d7e32d61"
      }
    ]
  }
  ```
