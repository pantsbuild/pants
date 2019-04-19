use crate::remote_execution;
use protobuf;

use std::collections::HashSet;

pub fn verify_directory_canonical(directory: &remote_execution::Directory) -> Result<(), String> {
  verify_no_unknown_fields(directory)?;
  verify_nodes(directory.get_files(), |n| n.get_name(), |n| n.get_digest())?;
  verify_nodes(
    directory.get_directories(),
    |n| n.get_name(),
    |n| n.get_digest(),
  )?;
  let file_names: HashSet<&str> = directory
    .get_files()
    .iter()
    .map(remote_execution::FileNode::get_name)
    .chain(
      directory
        .get_directories()
        .iter()
        .map(remote_execution::DirectoryNode::get_name),
    )
    .collect();
  if file_names.len() != directory.get_files().len() + directory.get_directories().len() {
    return Err(format!(
      "Children must be unique, but a path was both a file and a directory: {:?}",
      directory
    ));
  }
  Ok(())
}

fn verify_nodes<Node, GetName, GetDigest>(
  nodes: &[Node],
  get_name: GetName,
  get_digest: GetDigest,
) -> Result<(), String>
where
  Node: protobuf::Message,
  GetName: Fn(&Node) -> &str,
  GetDigest: Fn(&Node) -> &remote_execution::Digest,
{
  let mut prev: Option<&Node> = None;
  for node in nodes {
    verify_no_unknown_fields(node)?;
    verify_no_unknown_fields(get_digest(node))?;
    if get_name(node).contains('/') {
      return Err(format!(
        "All children must have one path segment, but found {}",
        get_name(node)
      ));
    }
    if let Some(p) = prev {
      if get_name(node) <= get_name(p) {
        return Err(format!(
          "Children must be sorted and unique, but {} was before {}",
          get_name(p),
          get_name(node)
        ));
      }
    }
    prev = Some(node);
  }
  Ok(())
}

fn verify_no_unknown_fields(message: &dyn protobuf::Message) -> Result<(), String> {
  if message.get_unknown_fields().fields.is_some() {
    return Err(format!(
      "Found unknown fields: {:?}",
      message.get_unknown_fields()
    ));
  }
  Ok(())
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
