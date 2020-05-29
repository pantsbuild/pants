use crate::remote_execution;

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
