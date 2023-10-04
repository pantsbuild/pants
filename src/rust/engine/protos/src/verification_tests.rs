// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use hashing::EMPTY_DIGEST;

use crate::gen::build::bazel::remote::execution::v2::{Digest, Directory, DirectoryNode, FileNode};
use crate::verify_directory_canonical;

const HASH: &str = "693d8db7b05e99c6b7a7c0616456039d89c555029026936248085193559a0b5d";
const FILE_SIZE: i64 = 16;
const DIRECTORY_HASH: &str = "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16";
const DIRECTORY_SIZE: i64 = 80;
const OTHER_DIRECTORY_HASH: &str = "e3b0c44298fc1c149afbf4c8996fb924\
                                    27ae41e4649b934ca495991b7852b855";
const OTHER_DIRECTORY_SIZE: i64 = 0;

#[test]
fn empty_directory() {
  assert_eq!(
    Ok(()),
    verify_directory_canonical(EMPTY_DIGEST, &Directory::default())
  );
}

#[test]
fn canonical_directory() {
  let directory = Directory {
    files: vec![
      FileNode {
        name: "roland".to_owned(),
        digest: Some(Digest {
          hash: HASH.to_owned(),
          size_bytes: FILE_SIZE,
        }),
        ..FileNode::default()
      },
      FileNode {
        name: "simba".to_owned(),
        digest: Some(Digest {
          hash: HASH.to_owned(),
          size_bytes: FILE_SIZE,
        }),
        ..FileNode::default()
      },
    ],
    directories: vec![
      DirectoryNode {
        name: "cats".to_owned(),
        digest: Some(Digest {
          hash: DIRECTORY_HASH.to_owned(),
          size_bytes: DIRECTORY_SIZE,
        }),
      },
      DirectoryNode {
        name: "dogs".to_owned(),
        digest: Some(Digest {
          hash: OTHER_DIRECTORY_HASH.to_owned(),
          size_bytes: OTHER_DIRECTORY_SIZE,
        }),
      },
    ],
    ..Directory::default()
  };

  assert_eq!(Ok(()), verify_directory_canonical(EMPTY_DIGEST, &directory));
}

#[test]
fn empty_child_name() {
  let directory = Directory {
    directories: vec![DirectoryNode {
      name: "".to_owned(),
      digest: Some(Digest {
        hash: DIRECTORY_HASH.to_owned(),
        size_bytes: DIRECTORY_SIZE,
      }),
    }],
    ..Directory::default()
  };

  let error = verify_directory_canonical(EMPTY_DIGEST, &directory).expect_err("Want error");
  assert!(
    error.contains("A child name must not be empty"),
    "Bad error message: {error}"
  );
}

#[test]
fn multiple_path_segments_in_directory() {
  let directory = Directory {
    directories: vec![DirectoryNode {
      name: "pets/cats".to_owned(),
      digest: Some(Digest {
        hash: DIRECTORY_HASH.to_owned(),
        size_bytes: DIRECTORY_SIZE,
      }),
    }],
    ..Directory::default()
  };

  let error = verify_directory_canonical(EMPTY_DIGEST, &directory).expect_err("Want error");
  assert!(error.contains("pets/cats"), "Bad error message: {error}");
}

#[test]
fn multiple_path_segments_in_file() {
  let directory = Directory {
    files: vec![FileNode {
      name: "cats/roland".to_owned(),
      digest: Some(Digest {
        hash: HASH.to_owned(),
        size_bytes: FILE_SIZE,
      }),
      ..FileNode::default()
    }],
    ..Directory::default()
  };

  let error = verify_directory_canonical(EMPTY_DIGEST, &directory).expect_err("Want error");
  assert!(error.contains("cats/roland"), "Bad error message: {error}");
}

#[test]
fn duplicate_path_in_directory() {
  let directory = Directory {
    directories: vec![
      DirectoryNode {
        name: "cats".to_owned(),
        digest: Some(Digest {
          hash: DIRECTORY_HASH.to_owned(),
          size_bytes: DIRECTORY_SIZE,
        }),
      },
      DirectoryNode {
        name: "cats".to_owned(),
        digest: Some(Digest {
          hash: DIRECTORY_HASH.to_owned(),
          size_bytes: DIRECTORY_SIZE,
        }),
      },
    ],
    ..Directory::default()
  };

  let error = verify_directory_canonical(EMPTY_DIGEST, &directory).expect_err("Want error");
  assert!(error.contains("cats"), "Bad error message: {error}");
}

#[test]
fn duplicate_path_in_file() {
  let directory = Directory {
    files: vec![
      FileNode {
        name: "roland".to_owned(),
        digest: Some(Digest {
          hash: HASH.to_owned(),
          size_bytes: FILE_SIZE,
        }),
        ..FileNode::default()
      },
      FileNode {
        name: "roland".to_owned(),
        digest: Some(Digest {
          hash: HASH.to_owned(),
          size_bytes: FILE_SIZE,
        }),
        ..FileNode::default()
      },
    ],
    ..Directory::default()
  };

  let error = verify_directory_canonical(EMPTY_DIGEST, &directory).expect_err("Want error");
  assert!(error.contains("roland"), "Bad error message: {error}");
}

#[test]
fn duplicate_path_in_file_and_directory() {
  let directory = Directory {
    files: vec![FileNode {
      name: "roland".to_owned(),
      digest: Some(Digest {
        hash: HASH.to_owned(),
        size_bytes: FILE_SIZE,
      }),
      ..FileNode::default()
    }],
    directories: vec![DirectoryNode {
      name: "roland".to_owned(),
      digest: Some(Digest {
        hash: DIRECTORY_HASH.to_owned(),
        size_bytes: DIRECTORY_SIZE,
      }),
    }],
    ..Directory::default()
  };

  verify_directory_canonical(EMPTY_DIGEST, &directory).expect_err("Want error");
}
