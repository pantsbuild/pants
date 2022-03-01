// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::fmt::{self, Debug};
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use deepsize::{known_deep_size, DeepSizeOf};
use internment::Intern;
use itertools::Itertools;

// TODO: Extract protobuf-specific pieces to a new crate.
use grpc_util::prost::MessageExt;
use hashing::{Digest, EMPTY_DIGEST};
use protos::gen::build::bazel::remote::execution::v2 as remexec;

use crate::PathStat;

pub const EMPTY_DIRECTORY_DIGEST: DirectoryDigest = DirectoryDigest {
  digest: EMPTY_DIGEST,
  tree: None,
};

/// A Digest for a directory, optionally with its content stored as a DigestTrie.
///
/// If a DirectoryDigest has a DigestTrie reference, then its Digest _might not_ be persisted to
/// the Store. If the DirectoryDigest does not hold a DigestTrie, then that Digest _must_ have been
/// persisted to the Store (either locally or remotely). The field thus acts likes a cache in some
/// cases, but in other cases is an indication that the tree must first be persisted (or loaded)
/// before the Digest may be operated on.
#[derive(Clone, DeepSizeOf)]
pub struct DirectoryDigest {
  pub digest: Digest,
  pub tree: Option<DigestTrie>,
}

impl Eq for DirectoryDigest {}

impl PartialEq for DirectoryDigest {
  fn eq(&self, other: &Self) -> bool {
    self.digest == other.digest
  }
}

impl Debug for DirectoryDigest {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    let tree = if self.tree.is_some() {
      "Some(..)"
    } else {
      "None"
    };
    write!(f, "DirectoryDigest({:?}, tree: {})", self.digest, tree)
  }
}

impl DirectoryDigest {
  /// Creates a DirectoryDigest which asserts that the given Digest represents a Directory structure
  /// which is persisted in a Store.
  pub fn new(digest: Digest) -> Self {
    Self { digest, tree: None }
  }

  pub fn from_path_stats(
    path_stats: Vec<PathStat>,
    file_digests: &HashMap<PathBuf, Digest>,
  ) -> Result<Self, String> {
    let path_stats = PathStat::normalize_path_stats(path_stats)?;
    let digest_tree = DigestTrie::from_sorted_paths(
      PathBuf::new(),
      path_stats.iter().map(|p| p.into()).collect(),
      file_digests,
    );
    Ok(Self {
      digest: digest_tree.compute_root_digest(),
      tree: Some(digest_tree),
    })
  }

  /// Returns the digests reachable from this DirectoryDigest.
  ///
  /// If this DirectoryDigest has been persisted to disk (i.e., does not have a DigestTrie) then
  /// this will only include the root.
  pub fn digests(&self) -> Vec<Digest> {
    let tree = if let Some(tree) = &self.tree {
      tree
    } else {
      return vec![self.digest];
    };

    // Walk the tree and collect Digests.
    let mut digests = Vec::new();
    digests.push(self.digest);
    let mut stack = tree.0.iter().collect::<Vec<_>>();
    while let Some(entry) = stack.pop() {
      match entry {
        Entry::Directory(d) => {
          digests.push(d.digest);
          stack.extend(d.tree.0.iter());
        }
        Entry::File(f) => {
          digests.push(f.digest);
        }
      }
    }
    digests
  }
}

#[derive(Copy, Clone, Eq, PartialEq)]
struct Name(Intern<String>);
known_deep_size!(0; Name);

impl Deref for Name {
  type Target = Intern<String>;

  fn deref(&self) -> &Intern<String> {
    &self.0
  }
}

#[derive(Clone, DeepSizeOf)]
enum Entry {
  Directory(Directory),
  File(File),
}

#[derive(Clone, DeepSizeOf)]
struct Directory {
  name: Name,
  digest: Digest,
  tree: DigestTrie,
}

impl Directory {
  fn new(name: Name, entries: Vec<Entry>) -> Self {
    Self::from_digest_tree(name, DigestTrie(entries.into()))
  }

  fn from_digest_tree(name: Name, tree: DigestTrie) -> Self {
    Self {
      name,
      digest: tree.compute_root_digest(),
      tree,
    }
  }
}

#[derive(Clone, DeepSizeOf)]
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

#[derive(Clone, DeepSizeOf)]
pub struct DigestTrie(Arc<[Entry]>);

impl DigestTrie {
  fn from_sorted_paths(
    prefix: PathBuf,
    paths: Vec<TypedPath>,
    file_digests: &HashMap<PathBuf, Digest>,
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

  fn compute_root_digest(&self) -> Digest {
    if self.0.is_empty() {
      return EMPTY_DIGEST;
    }

    let mut files = Vec::new();
    let mut directories = Vec::new();
    for entry in &*self.0 {
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
    Digest::of_bytes(
      &remexec::Directory {
        directories,
        files,
        ..remexec::Directory::default()
      }
      .to_bytes(),
    )
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
  Ok(Name(Intern::from(name)))
}
