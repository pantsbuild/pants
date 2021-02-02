use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use grpc_util::prost::MessageExt;

#[derive(Clone)]
pub struct TestData {
  string: String,
}

impl TestData {
  pub fn empty() -> TestData {
    TestData::new("")
  }

  pub fn roland() -> TestData {
    TestData::new("European Burmese")
  }

  pub fn catnip() -> TestData {
    TestData::new("catnip")
  }

  pub fn robin() -> TestData {
    TestData::new("Pug")
  }

  pub fn forty_chars() -> TestData {
    TestData::new(
      "0123456789012345678901234567890123456789\
       0123456789012345678901234567890123456789",
    )
  }

  pub fn new(s: &str) -> TestData {
    TestData {
      string: s.to_owned(),
    }
  }

  pub fn bytes(&self) -> bytes::Bytes {
    bytes::Bytes::copy_from_slice(self.string.as_str().as_bytes())
  }

  pub fn fingerprint(&self) -> hashing::Fingerprint {
    self.digest().hash
  }

  pub fn digest(&self) -> hashing::Digest {
    hashing::Digest::of_bytes(&self.bytes())
  }

  pub fn string(&self) -> String {
    self.string.clone()
  }

  pub fn len(&self) -> usize {
    self.string.len()
  }
}

pub struct TestDirectory {
  pub directory: remexec::Directory,
}

impl TestDirectory {
  pub fn empty() -> TestDirectory {
    TestDirectory {
      directory: remexec::Directory::default(),
    }
  }

  // Directory structure:
  //
  // /falcons/
  pub fn containing_falcons_dir() -> TestDirectory {
    let directory = remexec::Directory {
      directories: vec![remexec::DirectoryNode {
        name: "falcons".to_string(),
        digest: Some((&TestDirectory::empty().digest()).into()),
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // birds/falcons/
  // cats/roland
  pub fn nested_dir_and_file() -> TestDirectory {
    let directory = remexec::Directory {
      directories: vec![
        remexec::DirectoryNode {
          name: "birds".to_string(),
          digest: Some(TestDirectory::containing_falcons_dir().digest().into()),
        },
        remexec::DirectoryNode {
          name: "cats".to_string(),
          digest: Some((TestDirectory::containing_roland().digest()).into()),
        },
      ],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // animals/birds/falcons/
  // animals/cats/roland
  pub fn double_nested_dir_and_file() -> TestDirectory {
    let directory = remexec::Directory {
      directories: vec![remexec::DirectoryNode {
        name: "animals".to_string(),
        digest: Some((&TestDirectory::nested_dir_and_file().digest()).into()),
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /roland
  pub fn containing_roland() -> TestDirectory {
    let directory = remexec::Directory {
      files: vec![remexec::FileNode {
        name: "roland".to_owned(),
        digest: Some((&TestData::roland().digest()).into()),
        is_executable: false,
        ..remexec::FileNode::default()
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /robin
  pub fn containing_robin() -> TestDirectory {
    let directory = remexec::Directory {
      files: vec![remexec::FileNode {
        name: "robin".to_owned(),
        digest: Some((&TestData::robin().digest()).into()),
        is_executable: false,
        ..remexec::FileNode::default()
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /treats
  pub fn containing_treats() -> TestDirectory {
    let directory = remexec::Directory {
      files: vec![remexec::FileNode {
        name: "treats".to_owned(),
        digest: Some((&TestData::catnip().digest()).into()),
        is_executable: false,
        ..remexec::FileNode::default()
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /cats/roland
  pub fn nested() -> TestDirectory {
    let directory = remexec::Directory {
      directories: vec![remexec::DirectoryNode {
        name: "cats".to_owned(),
        digest: Some((&TestDirectory::containing_roland().digest()).into()),
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /pets/cats/roland
  pub fn double_nested() -> TestDirectory {
    let directory = remexec::Directory {
      directories: vec![remexec::DirectoryNode {
        name: "pets".to_owned(),
        digest: Some((&TestDirectory::nested().digest()).into()),
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /dnalor
  pub fn containing_dnalor() -> TestDirectory {
    let directory = remexec::Directory {
      files: vec![remexec::FileNode {
        name: "dnalor".to_owned(),
        digest: Some((&TestData::roland().digest()).into()),
        is_executable: false,
        ..remexec::FileNode::default()
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /roland
  pub fn containing_wrong_roland() -> TestDirectory {
    let directory = remexec::Directory {
      files: vec![remexec::FileNode {
        name: "roland".to_owned(),
        digest: Some((&TestData::catnip().digest()).into()),
        is_executable: false,
        ..remexec::FileNode::default()
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /roland
  // /treats
  pub fn containing_roland_and_treats() -> TestDirectory {
    let directory = remexec::Directory {
      files: vec![
        remexec::FileNode {
          name: "roland".to_owned(),
          digest: Some((&TestData::roland().digest()).into()),
          is_executable: false,
          ..remexec::FileNode::default()
        },
        remexec::FileNode {
          name: "treats".to_owned(),
          digest: Some((&TestData::catnip().digest()).into()),
          is_executable: false,
          ..remexec::FileNode::default()
        },
      ],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /cats/roland
  // /treats
  pub fn recursive() -> TestDirectory {
    let directory = remexec::Directory {
      directories: vec![remexec::DirectoryNode {
        name: "cats".to_owned(),
        digest: Some((&TestDirectory::containing_roland().digest()).into()),
      }],
      files: vec![remexec::FileNode {
        name: "treats".to_owned(),
        digest: Some((&TestData::catnip().digest()).into()),
        ..remexec::FileNode::default()
      }],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /feed (executable)
  // /food
  pub fn with_mixed_executable_files() -> TestDirectory {
    let directory = remexec::Directory {
      files: vec![
        remexec::FileNode {
          name: "feed".to_owned(),
          digest: Some((&TestData::catnip().digest()).into()),
          is_executable: true,
          ..remexec::FileNode::default()
        },
        remexec::FileNode {
          name: "food".to_owned(),
          digest: Some((&TestData::catnip().digest()).into()),
          is_executable: false,
          ..remexec::FileNode::default()
        },
      ],
      ..remexec::Directory::default()
    };
    TestDirectory { directory }
  }

  pub fn directory(&self) -> remexec::Directory {
    self.directory.clone()
  }

  pub fn bytes(&self) -> bytes::Bytes {
    self.directory.to_bytes()
  }

  pub fn fingerprint(&self) -> hashing::Fingerprint {
    self.digest().hash
  }

  pub fn digest(&self) -> hashing::Digest {
    hashing::Digest::of_bytes(&self.bytes())
  }
}

pub struct TestTree {
  pub tree: remexec::Tree,
}

impl TestTree {
  pub fn roland_at_root() -> TestTree {
    TestDirectory::containing_roland().into()
  }

  pub fn robin_at_root() -> TestTree {
    TestDirectory::containing_robin().into()
  }
}

impl TestTree {
  pub fn bytes(&self) -> bytes::Bytes {
    self.tree.to_bytes()
  }

  pub fn fingerprint(&self) -> hashing::Fingerprint {
    self.digest().hash
  }

  pub fn digest(&self) -> hashing::Digest {
    hashing::Digest::of_bytes(&self.bytes())
  }
}

impl From<TestDirectory> for TestTree {
  fn from(dir: TestDirectory) -> Self {
    let tree = remexec::Tree {
      root: Some(dir.directory),
      ..remexec::Tree::default()
    };
    TestTree { tree }
  }
}
