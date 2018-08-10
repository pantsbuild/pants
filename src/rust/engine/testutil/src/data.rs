use bazel_protos;
use bytes;
use digest::FixedOutput;
use hashing;
use protobuf::Message;
use sha2::{self, Digest};

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

  pub fn fourty_chars() -> TestData {
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
    bytes::Bytes::from(self.string.as_str())
  }

  pub fn fingerprint(&self) -> hashing::Fingerprint {
    hash(&self.bytes())
  }

  pub fn digest(&self) -> hashing::Digest {
    hashing::Digest(self.fingerprint(), self.string.len())
  }

  pub fn string(&self) -> String {
    self.string.clone()
  }

  pub fn len(&self) -> usize {
    self.string.len()
  }
}

pub struct TestDirectory {
  directory: bazel_protos::remote_execution::Directory,
}

impl TestDirectory {
  pub fn empty() -> TestDirectory {
    TestDirectory {
      directory: bazel_protos::remote_execution::Directory::new(),
    }
  }

  // Directory structure:
  //
  // /roland
  pub fn containing_roland() -> TestDirectory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("roland".to_owned());
      file.set_digest((&TestData::roland().digest()).into());
      file.set_is_executable(false);
      file
    });
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /robin
  pub fn containing_robin() -> TestDirectory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("robin".to_owned());
      file.set_digest((&TestData::robin().digest()).into());
      file.set_is_executable(false);
      file
    });
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /treats
  pub fn containing_treats() -> TestDirectory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("treats".to_owned());
      file.set_digest((&TestData::catnip().digest()).into());
      file.set_is_executable(false);
      file
    });
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /cats/roland
  pub fn nested() -> TestDirectory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_directories().push({
      let mut subdir = bazel_protos::remote_execution::DirectoryNode::new();
      subdir.set_name("cats".to_string());
      subdir.set_digest((&TestDirectory::containing_roland().digest()).into());
      subdir
    });
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /dnalor
  pub fn containing_dnalor() -> TestDirectory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("dnalor".to_owned());
      file.set_digest((&TestData::roland().digest()).into());
      file.set_is_executable(false);
      file
    });
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /roland
  pub fn containing_wrong_roland() -> TestDirectory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("roland".to_owned());
      file.set_digest((&TestData::catnip().digest()).into());
      file.set_is_executable(false);
      file
    });
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /roland
  // /treats
  pub fn containing_roland_and_treats() -> TestDirectory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("roland".to_owned());
      file.set_digest((&TestData::roland().digest()).into());
      file.set_is_executable(false);
      file
    });
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("treats".to_owned());
      file.set_digest((&TestData::catnip().digest()).into());
      file.set_is_executable(false);
      file
    });
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /cats/roland
  // /treats
  pub fn recursive() -> TestDirectory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_directories().push({
      let mut subdir = bazel_protos::remote_execution::DirectoryNode::new();
      subdir.set_name("cats".to_string());
      subdir.set_digest((&TestDirectory::containing_roland().digest()).into());
      subdir
    });
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("treats".to_string());
      file.set_digest((&TestData::catnip().digest()).into());
      file.set_is_executable(false);
      file
    });
    TestDirectory { directory }
  }

  // Directory structure:
  //
  // /feed (executable)
  // /food
  pub fn with_mixed_executable_files() -> TestDirectory {
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("feed".to_string());
      file.set_digest((&TestData::catnip().digest()).into());
      file.set_is_executable(true);
      file
    });
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name("food".to_string());
      file.set_digest((&TestData::catnip().digest()).into());
      file.set_is_executable(false);
      file
    });
    TestDirectory { directory }
  }

  pub fn directory(&self) -> bazel_protos::remote_execution::Directory {
    self.directory.clone()
  }

  pub fn bytes(&self) -> bytes::Bytes {
    bytes::Bytes::from(
      self
        .directory
        .write_to_bytes()
        .expect("Error serializing proto"),
    )
  }

  pub fn fingerprint(&self) -> hashing::Fingerprint {
    hash(&self.bytes())
  }

  pub fn digest(&self) -> hashing::Digest {
    hashing::Digest(self.fingerprint(), self.bytes().len())
  }
}

fn hash(bytes: &bytes::Bytes) -> hashing::Fingerprint {
  let mut hasher = sha2::Sha256::default();
  hasher.input(bytes);
  hashing::Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
}
