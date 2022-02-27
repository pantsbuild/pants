// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use internment::Intern;
use itertools::Itertools;

// TODO: Extract protobuf-specific pieces to a new crate.
use grpc_util::prost::MessageExt;
use hashing::{Digest, EMPTY_DIGEST};
use protos::gen::build::bazel::remote::execution::v2 as remexec;

use crate::PathStat;

type Name = Intern<String>;

enum Entry {
  Directory(Directory),
  File(File),
}

struct Directory {
  name: Name,
  digest: Digest,
  #[allow(dead_code)]
  tree: DigestTrie,
}

impl Directory {
  fn new(name: Name, entries: Vec<Entry>) -> Self {
    Self::from_digest_tree(name, DigestTrie(entries.into()))
  }

  fn from_digest_tree(name: Name, tree: DigestTrie) -> Self {
    if tree.0.is_empty() {
      return Self {
        name,
        digest: EMPTY_DIGEST,
        tree,
      };
    }

    let mut files = Vec::new();
    let mut directories = Vec::new();
    for entry in &*tree.0 {
      match entry {
        Entry::File(f) => files.push(remexec::FileNode {
          name: f.name.as_ref().to_owned(),
          digest: Some(f.digest.into()),
          is_executable: f.is_executable,
          ..remexec::FileNode::default()
        }),
        Entry::Directory(d) => directories.push(remexec::DirectoryNode {
          name: d.name.as_ref().to_owned(),
          digest: Some((&d.digest).into()),
        }),
      }
    }
    let digest = Digest::of_bytes(
      &remexec::Directory {
        directories,
        files,
        ..remexec::Directory::default()
      }
      .to_bytes(),
    );

    Self { name, digest, tree }
  }
}

struct File {
  name: Name,
  digest: Digest,
  is_executable: bool,
}

// TODO: `PathStat` owns its path, which means it can't be used via recursive slicing. See
// whether these types can be merged.
enum TypedPath<'a> {
  File { path: &'a Path, is_executable: bool },
  Dir(&'a Path),
}

impl<'a> Deref for TypedPath<'a> {
  type Target = Path;

  fn deref(&self) -> &Path {
    match self {
      TypedPath::File { path, .. } => path,
      TypedPath::Dir(d) => d,
    }
  }
}

impl<'a> From<&'a PathStat> for TypedPath<'a> {
  fn from(p: &'a PathStat) -> Self {
    match p {
      PathStat::File { path, stat } => TypedPath::File {
        path,
        is_executable: stat.is_executable,
      },
      PathStat::Dir { path, .. } => TypedPath::Dir(path),
    }
  }
}

pub struct DigestTrie(Arc<[Entry]>);

impl DigestTrie {
  #[allow(dead_code)]
  pub fn from_sorted_path_stats(
    path_stats: &[PathStat],
    file_digests: &HashMap<&Path, Digest>,
  ) -> Self {
    Self::from_sorted_paths(
      PathBuf::new(),
      path_stats.iter().map(|p| p.into()).collect(),
      file_digests,
    )
  }

  fn from_sorted_paths(
    prefix: PathBuf,
    paths: Vec<TypedPath>,
    file_digests: &HashMap<&Path, Digest>,
  ) -> Self {
    let mut entries = Vec::new();

    for (name, group) in &paths
      .into_iter()
      .group_by(|s| path_name_to_name(s).unwrap())
    {
      let mut path_group: Vec<TypedPath> = group.collect();
      if path_group.len() == 1 && path_group[0].components().count() == 1 {
        // Exactly one entry with exactly one component indicates either a file in this directory,
        // or an empty directory.
        // If the child is a non-empty directory, or a file therein, there must be multiple
        // PathStats with that prefix component, and we will handle that recursively.

        match path_group.pop().unwrap() {
          TypedPath::File {
            path,
            is_executable,
          } => {
            let digest = file_digests
              .get(prefix.join(path).as_path())
              .unwrap()
              .clone();

            entries.push(Entry::File(File {
              name,
              digest,
              is_executable,
            }));
          }
          TypedPath::Dir { .. } => {
            // Because there are no children of this Dir, it must be empty.
            entries.push(Entry::Directory(Directory::new(name, vec![])));
          }
        }
      } else {
        // Because there are no children of this Dir, it must be empty.
        entries.push(Entry::Directory(Directory::from_digest_tree(
          name,
          Self::from_sorted_paths(
            prefix.join(name.as_ref()),
            paths_of_child_dir(name.as_ref(), path_group),
            file_digests,
          ),
        )));
      }
    }

    Self(entries.into())
  }
}

fn paths_of_child_dir<'a>(name: &str, paths: Vec<TypedPath<'a>>) -> Vec<TypedPath<'a>> {
  paths
    .into_iter()
    .filter_map(|s| {
      if s.components().count() == 1 {
        return None;
      }
      Some(match s {
        TypedPath::File {
          path,
          is_executable,
        } => TypedPath::File {
          path: path.strip_prefix(name).unwrap(),
          is_executable,
        },
        TypedPath::Dir(path) => TypedPath::Dir(path.strip_prefix(name).unwrap()),
      })
    })
    .collect()
}

fn path_name_to_name(path: &Path) -> Result<Name, String> {
  let path_name = path
    .components()
    .next()
    .ok_or_else(|| format!("Path `{}` was unexpectedly empty", path.display()))?;
  let name = path_name
    .as_os_str()
    .to_str()
    .ok_or_else(|| format!("{:?} is not representable in UTF8", path_name))?;
  Ok(Intern::from(name))
}
