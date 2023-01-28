// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashSet;

use hashing::Digest;

use crate::gen::build::bazel::remote::execution::v2 as remote_execution;

pub fn verify_directory_canonical(
  digest: Digest,
  directory: &remote_execution::Directory,
) -> Result<(), String> {
  verify_nodes(&directory.files, |n| &n.name, |n| n.digest.as_ref())
    .map_err(|e| format!("Invalid file in {digest:?}: {e}"))?;
  verify_nodes(&directory.directories, |n| &n.name, |n| n.digest.as_ref())
    .map_err(|e| format!("Invalid directory in {digest:?}: {e}"))?;
  let child_names: HashSet<&str> = directory
    .files
    .iter()
    .map(|file_node| file_node.name.as_str())
    .chain(
      directory
        .directories
        .iter()
        .map(|dir_node| dir_node.name.as_str()),
    )
    .collect();
  if child_names.len() != directory.files.len() + directory.directories.len() {
    return Err(format!(
      "Child paths must be unique, but a child path of {digest:?} was both a file and a directory: {directory:?}"
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
  Node: prost::Message,
  GetName: Fn(&Node) -> &str,
  GetDigest: Fn(&Node) -> Option<&remote_execution::Digest>,
{
  let mut prev: Option<&Node> = None;
  for node in nodes {
    let name = get_name(node);
    if name.is_empty() {
      return Err(format!(
        "A child name must not be empty, but {:?} had an empty name.",
        get_digest(node),
      ));
    } else if name.contains('/') {
      return Err(format!(
        "All children must have one path segment, but found {name}"
      ));
    }
    if let Some(p) = prev {
      if name <= get_name(p) {
        return Err(format!(
          "Children must be sorted and unique, but {} was before {}",
          get_name(p),
          name,
        ));
      }
    }
    prev = Some(node);
  }
  Ok(())
}
