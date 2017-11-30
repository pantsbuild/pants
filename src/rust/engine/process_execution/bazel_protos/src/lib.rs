extern crate futures;
extern crate grpcio;
extern crate protobuf;

pub mod code;
pub mod empty;
pub mod operations;
pub mod operations_grpc;
pub mod remote_execution;
pub mod remote_execution_grpc;
pub mod status;

use std::collections::HashSet;

pub fn verify_directory_canonical(directory: &remote_execution::Directory) -> Result<(), String> {
  verify_no_unknown_fields(directory)?;
  verify_names_good(directory.get_files())?;
  verify_names_good(directory.get_directories())?;
  let file_names: HashSet<&str> = directory
    .get_files()
    .iter()
    .map(|file| file.get_name())
    .chain(directory.get_directories().iter().map(|dir| dir.get_name()))
    .collect();
  if file_names.len() != directory.get_files().len() + directory.get_directories().len() {
    return Err(format!(
      "Children must be unique, but a path was both a file and a directory: {:?}",
      directory
    ));
  }
  Ok(())
}

fn verify_names_good<T: HasNameAndDigest>(things: &[T]) -> Result<(), String> {
  let mut prev: Option<&T> = None;
  for thing in things {
    verify_no_unknown_fields(thing)?;
    verify_no_unknown_fields(thing.get_digest())?;
    if thing.get_name().contains("/") {
      return Err(format!(
        "All children must have one path segment, but found {}",
        thing.get_name()
      ));
    }
    match prev {
      Some(p) => {
        if thing.get_name() <= p.get_name() {
          return Err(format!(
            "Children must be sorted and unique, but {} was before {}",
            p.get_name(),
            thing.get_name()
          ));
        }
      }
      None => {}
    }
    prev = Some(thing);
  }
  Ok(())
}

fn verify_no_unknown_fields(message: &protobuf::Message) -> Result<(), String> {
  if message.get_unknown_fields().fields.is_some() {
    return Err(format!(
      "Found unknown fields: {:?}",
      message.get_unknown_fields()
    ));
  }
  return Ok(());
}

trait HasNameAndDigest: protobuf::Message {
  fn get_digest(&self) -> &remote_execution::Digest;
  fn get_name(&self) -> &str;
}

impl HasNameAndDigest for remote_execution::DirectoryNode {
  fn get_digest(&self) -> &remote_execution::Digest {
    self.get_digest()
  }

  fn get_name(&self) -> &str {
    self.get_name()
  }
}

impl HasNameAndDigest for remote_execution::FileNode {
  fn get_digest(&self) -> &remote_execution::Digest {
    self.get_digest()
  }

  fn get_name(&self) -> &str {
    self.get_name()
  }
}

#[cfg(test)]
mod canonical_directory_tests {
  use super::remote_execution::{Digest, Directory, DirectoryNode, FileNode};
  use super::verify_directory_canonical;
  use protobuf::Message;

  const HASH: &str = "693d8db7b05e99c6b7a7c0616456039d89c555029026936248085193559a0b5d";
  const FILE_SIZE: i64 = 16;
  const DIRECTORY_HASH: &str = "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16";
  const DIRECTORY_SIZE: i64 = 80;
  const OTHER_DIRECTORY_HASH: &str = "e3b0c44298fc1c149afbf4c8996fb924\
27ae41e4649b934ca495991b7852b855";
  const OTHER_DIRECTORY_SIZE: i64 = 0;

  #[test]
  fn empty_directory() {
    assert_eq!(Ok(()), verify_directory_canonical(&Directory::new()));
  }

  #[test]
  fn canonical_directory() {
    let mut directory = Directory::new();
    directory.mut_files().push({
      let mut file = FileNode::new();
      file.set_name("roland".to_owned());
      file.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(FILE_SIZE);
        digest.set_hash(HASH.to_owned());
        digest
      });
      file
    });
    directory.mut_files().push({
      let mut file = FileNode::new();
      file.set_name("simba".to_owned());
      file.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(FILE_SIZE);
        digest.set_hash(HASH.to_owned());
        digest
      });
      file
    });
    directory.mut_directories().push({
      let mut dir = DirectoryNode::new();
      dir.set_name("cats".to_owned());
      dir.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(DIRECTORY_SIZE);
        digest.set_hash(DIRECTORY_HASH.to_owned());
        digest
      });
      dir
    });
    directory.mut_directories().push({
      let mut dir = DirectoryNode::new();
      dir.set_name("dogs".to_owned());
      dir.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(OTHER_DIRECTORY_SIZE);
        digest.set_hash(OTHER_DIRECTORY_HASH.to_owned());
        digest
      });
      dir
    });
    assert_eq!(Ok(()), verify_directory_canonical(&directory));
  }

  #[test]
  fn unknown_field() {
    let mut directory = Directory::new();
    directory.mut_unknown_fields().add_fixed32(42, 42);
    let error = verify_directory_canonical(&directory).expect_err("Want error");
    assert!(
      error.contains("unknown"),
      format!("Bad error message: {}", error)
    );
  }

  #[test]
  fn unknown_field_in_file_node() {
    let mut directory = Directory::new();

    directory.mut_files().push({
      let mut file = FileNode::new();
      file.set_name("roland".to_owned());
      file.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(FILE_SIZE);
        digest.set_hash(HASH.to_owned());
        digest
      });
      file.mut_unknown_fields().add_fixed32(42, 42);
      file
    });

    let error = verify_directory_canonical(&directory).expect_err("Want error");
    assert!(
      error.contains("unknown"),
      format!("Bad error message: {}", error)
    );
  }

  #[test]
  fn multiple_path_segments_in_directory() {
    let mut directory = Directory::new();
    directory.mut_directories().push({
      let mut dir = DirectoryNode::new();
      dir.set_name("pets/cats".to_owned());
      dir.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(DIRECTORY_SIZE);
        digest.set_hash(DIRECTORY_HASH.to_owned());
        digest
      });
      dir
    });

    let error = verify_directory_canonical(&directory).expect_err("Want error");
    assert!(
      error.contains("pets/cats"),
      format!("Bad error message: {}", error)
    );
  }

  #[test]
  fn multiple_path_segments_in_file() {
    let mut directory = Directory::new();
    directory.mut_files().push({
      let mut file = FileNode::new();
      file.set_name("cats/roland".to_owned());
      file.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(FILE_SIZE);
        digest.set_hash(HASH.to_owned());
        digest
      });
      file
    });

    let error = verify_directory_canonical(&directory).expect_err("Want error");
    assert!(
      error.contains("cats/roland"),
      format!("Bad error message: {}", error)
    );
  }

  #[test]
  fn duplicate_path_in_directory() {
    let mut directory = Directory::new();
    directory.mut_directories().push({
      let mut dir = DirectoryNode::new();
      dir.set_name("cats".to_owned());
      dir.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(DIRECTORY_SIZE);
        digest.set_hash(DIRECTORY_HASH.to_owned());
        digest
      });
      dir
    });
    directory.mut_directories().push({
      let mut dir = DirectoryNode::new();
      dir.set_name("cats".to_owned());
      dir.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(DIRECTORY_SIZE);
        digest.set_hash(DIRECTORY_HASH.to_owned());
        digest
      });
      dir
    });

    let error = verify_directory_canonical(&directory).expect_err("Want error");
    assert!(
      error.contains("cats"),
      format!("Bad error message: {}", error)
    );
  }

  #[test]
  fn duplicate_path_in_file() {
    let mut directory = Directory::new();
    directory.mut_files().push({
      let mut file = FileNode::new();
      file.set_name("roland".to_owned());
      file.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(FILE_SIZE);
        digest.set_hash(HASH.to_owned());
        digest
      });
      file
    });
    directory.mut_files().push({
      let mut file = FileNode::new();
      file.set_name("roland".to_owned());
      file.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(FILE_SIZE);
        digest.set_hash(HASH.to_owned());
        digest
      });
      file
    });

    let error = verify_directory_canonical(&directory).expect_err("Want error");
    assert!(
      error.contains("roland"),
      format!("Bad error message: {}", error)
    );
  }

  #[test]
  fn duplicate_path_in_file_and_directory() {
    let mut directory = Directory::new();
    directory.mut_files().push({
      let mut file = FileNode::new();
      file.set_name("roland".to_owned());
      file.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(FILE_SIZE);
        digest.set_hash(HASH.to_owned());
        digest
      });
      file
    });
    directory.mut_directories().push({
      let mut dir = DirectoryNode::new();
      dir.set_name("roland".to_owned());
      dir.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(DIRECTORY_SIZE);
        digest.set_hash(DIRECTORY_HASH.to_owned());
        digest
      });
      dir
    });

    verify_directory_canonical(&directory).expect_err("Want error");
  }

  #[test]
  fn unsorted_path_in_directory() {
    let mut directory = Directory::new();
    directory.mut_directories().push({
      let mut dir = DirectoryNode::new();
      dir.set_name("dogs".to_owned());
      dir.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(DIRECTORY_SIZE);
        digest.set_hash(DIRECTORY_HASH.to_owned());
        digest
      });
      dir
    });
    directory.mut_directories().push({
      let mut dir = DirectoryNode::new();
      dir.set_name("cats".to_owned());
      dir.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(DIRECTORY_SIZE);
        digest.set_hash(DIRECTORY_HASH.to_owned());
        digest
      });
      dir
    });
  }

  #[test]
  fn unsorted_path_in_file() {
    let mut directory = Directory::new();
    directory.mut_files().push({
      let mut file = FileNode::new();
      file.set_name("simba".to_owned());
      file.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(DIRECTORY_SIZE);
        digest.set_hash(DIRECTORY_HASH.to_owned());
        digest
      });
      file
    });
    directory.mut_files().push({
      let mut file = FileNode::new();
      file.set_name("roland".to_owned());
      file.set_digest({
        let mut digest = Digest::new();
        digest.set_size_bytes(FILE_SIZE);
        digest.set_hash(HASH.to_owned());
        digest
      });
      file
    });
  }
}
