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
use lazy_static::lazy_static;

// TODO: Extract protobuf-specific pieces to a new crate.
use grpc_util::prost::MessageExt;
use hashing::{Digest, EMPTY_DIGEST};
use protos::gen::build::bazel::remote::execution::v2 as remexec;

use crate::PathStat;

lazy_static! {
  pub static ref EMPTY_DIGEST_TREE: DigestTrie = DigestTrie(vec![].into());
  pub static ref EMPTY_DIRECTORY_DIGEST: DirectoryDigest = DirectoryDigest {
    digest: EMPTY_DIGEST,
    tree: Some(EMPTY_DIGEST_TREE.clone()),
  };
}

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

  /// Returns the digests reachable from this DirectoryDigest.
  ///
  /// If this DirectoryDigest has been persisted to disk (i.e., does not have a DigestTrie) then
  /// this will only include the root.
  pub fn digests(&self) -> Vec<Digest> {
    if let Some(tree) = &self.tree {
      let mut digests = tree.digests();
      digests.push(self.digest);
      digests
    } else {
      vec![self.digest]
    }
  }
}

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
struct Name(Intern<String>);
known_deep_size!(0; Name);

impl Deref for Name {
  type Target = Intern<String>;

  fn deref(&self) -> &Intern<String> {
    &self.0
  }
}

#[derive(DeepSizeOf)]
pub enum Entry {
  Directory(Directory),
  File(File),
}

impl Entry {
  fn name(&self) -> Name {
    match self {
      Entry::Directory(d) => d.name,
      Entry::File(f) => f.name,
    }
  }
}

#[derive(DeepSizeOf)]
pub struct Directory {
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

  pub fn as_directory(&self) -> remexec::Directory {
    self.tree.as_directory()
  }

  pub fn as_directory_node(&self) -> remexec::DirectoryNode {
    remexec::DirectoryNode {
      name: self.name.as_ref().to_owned(),
      digest: Some((&self.digest).into()),
    }
  }
}

#[derive(DeepSizeOf)]
pub struct File {
  name: Name,
  digest: Digest,
  is_executable: bool,
}

impl File {
  pub fn as_file_node(&self) -> remexec::FileNode {
    remexec::FileNode {
      name: self.name.as_ref().to_owned(),
      digest: Some(self.digest.into()),
      is_executable: self.is_executable,
      ..remexec::FileNode::default()
    }
  }
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

// TODO: This avoids a `rustc` crasher (repro on 7f319ee84ad41bc0aea3cb01fb2f32dcd51be704).
unsafe impl Sync for DigestTrie {}

impl DigestTrie {
  pub fn from_path_stats(
    path_stats: Vec<PathStat>,
    file_digests: &HashMap<PathBuf, Digest>,
  ) -> Result<Self, String> {
    let path_stats = PathStat::normalize_path_stats(path_stats)?;
    Ok(Self::from_sorted_paths(
      PathBuf::new(),
      path_stats.iter().map(|p| p.into()).collect(),
      file_digests,
    ))
  }

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
            let digest = *file_digests.get(prefix.join(path).as_path()).unwrap();

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

  pub fn as_directory(&self) -> remexec::Directory {
    let mut files = Vec::new();
    let mut directories = Vec::new();

    for entry in &*self.0 {
      match entry {
        Entry::File(f) => files.push(f.as_file_node()),
        Entry::Directory(d) => directories.push(d.as_directory_node()),
      }
    }

    remexec::Directory {
      directories,
      files,
      ..remexec::Directory::default()
    }
  }

  pub fn compute_root_digest(&self) -> Digest {
    if self.0.is_empty() {
      return EMPTY_DIGEST;
    }

    Digest::of_bytes(&self.as_directory().to_bytes())
  }

  pub fn entries(&self) -> &[Entry] {
    &*self.0
  }

  /// Returns the digests reachable from this DigestTrie.
  pub fn digests(&self) -> Vec<Digest> {
    // Walk the tree and collect Digests.
    let mut digests = Vec::new();
    let mut stack = self.0.iter().collect::<Vec<_>>();
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

  /// Return a pair of Vecs of the file paths and directory paths in this DigestTrie, each in
  /// sorted order.
  ///
  /// TODO: This should probably be implemented directly by consumers via `walk`, since they
  /// can directly allocate the collections that they need.
  pub fn files_and_directories(&self) -> (Vec<PathBuf>, Vec<PathBuf>) {
    let mut files = Vec::new();
    let mut directories = Vec::new();
    self.walk(&mut |path, entry| {
      match entry {
        Entry::File(_) => files.push(path.to_owned()),
        Entry::Directory(d) if d.name.is_empty() => {
          // Is the root directory, which is not emitted here.
        }
        Entry::Directory(_) => directories.push(path.to_owned()),
      }
    });
    (files, directories)
  }

  /// Visit every node in the tree, calling the given function with the path to the Node, and its
  /// entries.
  pub fn walk(&self, f: &mut impl FnMut(&Path, &Entry)) {
    {
      // TODO: It's likely that a DigestTrie should hold its own Digest, to avoid re-computing it
      // here.
      let root = Entry::Directory(Directory::from_digest_tree(
        Name(Intern::from("")),
        self.clone(),
      ));
      f(&PathBuf::new(), &root);
    }
    self.walk_helper(PathBuf::new(), f)
  }

  fn walk_helper(&self, path_so_far: PathBuf, f: &mut impl FnMut(&Path, &Entry)) {
    for entry in &*self.0 {
      let path = path_so_far.join(entry.name().as_ref());
      f(&path, entry);
      if let Entry::Directory(d) = entry {
        d.tree.walk_helper(path, f);
      }
    }
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
