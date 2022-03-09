// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::fmt::{self, Debug};
use std::hash::{self, Hash};
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

use crate::{PathStat, RelativePath};

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
  // NB: Private in order to force a choice between `todo_as_digest` and `as_digest`.
  digest: Digest,
  pub tree: Option<DigestTrie>,
}

impl workunit_store::DirectoryDigest for DirectoryDigest {
  fn as_any(&self) -> &dyn std::any::Any {
    self
  }
}

impl Eq for DirectoryDigest {}

impl PartialEq for DirectoryDigest {
  fn eq(&self, other: &Self) -> bool {
    self.digest == other.digest
  }
}

impl Hash for DirectoryDigest {
  fn hash<H: hash::Hasher>(&self, state: &mut H) {
    self.digest.hash(state);
  }
}

impl Debug for DirectoryDigest {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    // NB: To avoid over-large output, we don't render the Trie. It would likely be best rendered
    // as e.g. JSON.
    let tree = if self.tree.is_some() {
      "Some(..)"
    } else {
      "None"
    };
    write!(f, "DirectoryDigest({:?}, tree: {})", self.digest, tree)
  }
}

impl DirectoryDigest {
  /// Construct a DirectoryDigest from a Digest and DigestTrie (by asserting that the Digest
  /// identifies the DigestTrie).
  pub fn new(digest: Digest, tree: DigestTrie) -> Self {
    if cfg!(debug_assertions) {
      assert!(digest == tree.compute_root_digest());
    }
    Self {
      digest,
      tree: Some(tree),
    }
  }

  /// Creates a DirectoryDigest which asserts that the given Digest represents a Directory structure
  /// which is persisted in a Store.
  ///
  /// Use of this method should be rare: code should prefer to pass around a `DirectoryDigest` rather
  /// than to create one from a `Digest` (as the latter requires loading the content from disk).
  ///
  /// TODO: If a callsite needs to create a `DirectoryDigest` as a convenience (i.e. in a location
  /// where its signature could be changed to accept a `DirectoryDigest` instead of constructing
  /// one) during the porting effort of #13112, it should use `todo_from_digest` rather than
  /// `from_persisted_digest`.
  pub fn from_persisted_digest(digest: Digest) -> Self {
    Self { digest, tree: None }
  }

  /// Marks a callsite that is creating a `DirectoryDigest` as a temporary convenience, rather than
  /// accepting a `DirectoryDigest` in its signature. All usages of this method should be removed
  /// before closing #13112.
  pub fn todo_from_digest(digest: Digest) -> Self {
    Self { digest, tree: None }
  }

  pub fn from_tree(tree: DigestTrie) -> Self {
    Self {
      digest: tree.compute_root_digest(),
      tree: Some(tree),
    }
  }

  /// Returns the `Digest` for this `DirectoryDigest`.
  ///
  /// TODO: If a callsite needs to convert to `Digest` as a convenience (i.e. in a location where
  /// its signature could be changed to return a `DirectoryDigest` instead) during the porting
  /// effort of #13112, it should use `todo_as_digest` rather than `as_digest`.
  pub fn as_digest(&self) -> Digest {
    self.digest
  }

  /// Marks a callsite that is discarding the `DigestTrie` held by this `DirectoryDigest` as a
  /// temporary convenience, rather than updating its signature to return a `DirectoryDigest`. All
  /// usages of this method should be removed before closing #13112.
  pub fn todo_as_digest(self) -> Digest {
    self.digest
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

/// A single component of a filesystem path.
///
/// For example: the path `foo/bar` will be broken up into `Name("foo")` and `Name("bar")`.
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
struct Name(Intern<String>);
// NB: Calculating the actual deep size of an `Intern` is very challenging, because it does not
// keep any record of the number of held references, and instead effectively makes its held value
// static. Switching to `ArcIntern` would get accurate counts at the cost of performance and size.
known_deep_size!(0; Name);

impl Deref for Name {
  type Target = Intern<String>;

  fn deref(&self) -> &Intern<String> {
    &self.0
  }
}

#[derive(Clone, DeepSizeOf)]
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

#[derive(Clone, DeepSizeOf)]
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

  pub fn name(&self) -> &str {
    self.name.as_ref()
  }

  pub fn digest(&self) -> Digest {
    self.digest
  }

  pub fn tree(&self) -> &DigestTrie {
    &self.tree
  }

  pub fn as_remexec_directory(&self) -> remexec::Directory {
    self.tree.as_remexec_directory()
  }

  pub fn as_remexec_directory_node(&self) -> remexec::DirectoryNode {
    remexec::DirectoryNode {
      name: self.name.as_ref().to_owned(),
      digest: Some((&self.digest).into()),
    }
  }
}

#[derive(Clone, DeepSizeOf)]
pub struct File {
  name: Name,
  digest: Digest,
  is_executable: bool,
}

impl File {
  pub fn name(&self) -> &str {
    self.name.as_ref()
  }

  pub fn digest(&self) -> Digest {
    self.digest
  }

  pub fn is_executable(&self) -> bool {
    self.is_executable
  }

  pub fn as_remexec_file_node(&self) -> remexec::FileNode {
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
  /// Create a DigestTrie from unique PathStats. Fails for duplicate items.
  pub fn from_path_stats(
    mut path_stats: Vec<PathStat>,
    file_digests: &HashMap<PathBuf, Digest>,
  ) -> Result<Self, String> {
    // Sort and ensure that there were no duplicate entries.
    //#[allow(clippy::unnecessary_sort_by)]
    path_stats.sort_by(|a, b| a.path().cmp(b.path()));

    // The helper assumes that if a Path has multiple children, it must be a directory.
    // Proactively error if we run into identically named files, because otherwise we will treat
    // them like empty directories.
    let pre_dedupe_len = path_stats.len();
    path_stats.dedup_by(|a, b| a.path() == b.path());
    if path_stats.len() != pre_dedupe_len {
      return Err(format!(
        "Snapshots must be constructed from unique path stats; got duplicates in {:?}",
        path_stats
      ));
    }

    Self::from_sorted_paths(
      PathBuf::new(),
      path_stats.iter().map(|p| p.into()).collect(),
      file_digests,
    )
  }

  fn from_sorted_paths(
    prefix: PathBuf,
    paths: Vec<TypedPath>,
    file_digests: &HashMap<PathBuf, Digest>,
  ) -> Result<Self, String> {
    let mut entries = Vec::new();

    for (name_res, group) in &paths
      .into_iter()
      .group_by(|s| first_path_component_to_name(s))
    {
      let name = name_res?;
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
            paths_of_child_dir(name, path_group),
            file_digests,
          )?,
        )));
      }
    }

    Ok(Self(entries.into()))
  }

  pub fn as_remexec_directory(&self) -> remexec::Directory {
    let mut files = Vec::new();
    let mut directories = Vec::new();

    for entry in &*self.0 {
      match entry {
        Entry::File(f) => files.push(f.as_remexec_file_node()),
        Entry::Directory(d) => directories.push(d.as_remexec_directory_node()),
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

    Digest::of_bytes(&self.as_remexec_directory().to_bytes())
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

  /// Add the given path as a prefix for this trie, returning the resulting trie.
  pub fn add_prefix(self, prefix: &RelativePath) -> Result<DigestTrie, String> {
    let mut prefix_iter = prefix.iter();
    let mut tree = self;
    while let Some(parent) = prefix_iter.next_back() {
      let directory = Directory {
        name: first_path_component_to_name(parent.as_ref())?,
        digest: tree.compute_root_digest(),
        tree,
      };

      tree = DigestTrie(vec![Entry::Directory(directory)].into());
    }

    Ok(tree)
  }

  /// Remove the given prefix from this trie, returning the resulting trie.
  pub fn remove_prefix(self, prefix: &RelativePath) -> Result<DigestTrie, String> {
    let root = self.clone();
    let mut tree = self;
    let mut already_stripped = PathBuf::new();
    for component_to_strip in prefix.components() {
      let component_to_strip = component_to_strip.as_os_str();
      let mut matching_dir = None;
      let mut extra_directories = Vec::new();
      let mut files = Vec::new();
      for entry in tree.entries() {
        match entry {
          Entry::Directory(d) if Path::new(d.name.as_ref()).as_os_str() == component_to_strip => {
            matching_dir = Some(d)
          }
          Entry::Directory(d) => extra_directories.push(d.name.as_ref().to_owned()),
          Entry::File(f) => files.push(f.name.as_ref().to_owned()),
        }
      }

      let has_already_stripped_any = already_stripped.components().next().is_some();
      match (
        matching_dir,
        extra_directories.is_empty() && files.is_empty(),
      ) {
        (None, true) => {
          tree = EMPTY_DIGEST_TREE.clone();
          break;
        }
        (None, false) => {
          // Prefer "No subdirectory found" error to "had extra files" error.
          return Err(format!(
            "Cannot strip prefix {} from root directory (Digest with hash {:?}) - \
             {}directory{} didn't contain a directory named {}{}",
            prefix.display(),
            root.compute_root_digest().hash,
            if has_already_stripped_any {
              "sub"
            } else {
              "root "
            },
            if has_already_stripped_any {
              format!(" {}", already_stripped.display())
            } else {
              String::new()
            },
            Path::new(component_to_strip).display(),
            if !extra_directories.is_empty() || !files.is_empty() {
              format!(
                " but did contain {}",
                format_directories_and_files(&extra_directories, &files)
              )
            } else {
              String::new()
            },
          ));
        }
        (Some(_), false) => {
          return Err(format!(
            "Cannot strip prefix {} from root directory (Digest with hash {:?}) - \
             {}directory{} contained non-matching {}",
            prefix.display(),
            root.compute_root_digest().hash,
            if has_already_stripped_any {
              "sub"
            } else {
              "root "
            },
            if has_already_stripped_any {
              format!(" {}", already_stripped.display())
            } else {
              String::new()
            },
            format_directories_and_files(&extra_directories, &files),
          ))
        }
        (Some(d), true) => {
          already_stripped = already_stripped.join(component_to_strip);
          tree = d.tree.clone();
        }
      }
    }

    Ok(tree)
  }

  /// Given DigestTries, merge them recursively into a single DigestTrie.
  ///
  /// If a file is present with the same name and contents multiple times, it will appear once.
  /// If a file is present with the same name, but different contents, an error will be returned.
  pub fn merge(trees: Vec<DigestTrie>) -> Result<DigestTrie, MergeError> {
    Self::merge_helper(PathBuf::new(), trees)
  }

  fn merge_helper(parent_path: PathBuf, trees: Vec<DigestTrie>) -> Result<DigestTrie, MergeError> {
    if trees.is_empty() {
      return Ok(EMPTY_DIGEST_TREE.clone());
    } else if trees.len() == 1 {
      let mut trees = trees;
      return Ok(trees.pop().unwrap());
    }

    // Merge and sort Entries.
    let input_entries = trees
      .iter()
      .map(|tree| tree.entries())
      .flatten()
      .sorted_by(|a, b| a.name().cmp(&b.name()));

    // Then group by name, and merge into an output list.
    let mut entries: Vec<Entry> = Vec::new();
    for (name, group) in &input_entries.into_iter().group_by(|e| e.name()) {
      let mut group = group.peekable();
      let first = group.next().unwrap();
      if group.peek().is_none() {
        // There was only one Entry: emit it.
        entries.push(first.clone());
        continue;
      }

      match first {
        Entry::File(f) => {
          // If any Entry is a File, then they must all be identical.
          let (mut mismatched_files, mismatched_dirs) = collisions(f.digest, group);
          if !mismatched_files.is_empty() || !mismatched_dirs.is_empty() {
            mismatched_files.push(f);
            return Err(MergeError::duplicates(
              parent_path,
              mismatched_files,
              mismatched_dirs,
            ));
          }

          // All entries matched: emit one copy.
          entries.push(first.clone());
        }
        Entry::Directory(d) => {
          // If any Entry is a Directory, then they must all be Directories which will be merged.
          let (mismatched_files, mut mismatched_dirs) = collisions(d.digest, group);

          // If there were any Files, error.
          if !mismatched_files.is_empty() {
            mismatched_dirs.push(d);
            return Err(MergeError::duplicates(
              parent_path,
              mismatched_files,
              mismatched_dirs,
            ));
          }

          if mismatched_dirs.is_empty() {
            // All directories matched: emit one copy.
            entries.push(first.clone());
          } else {
            // Some directories mismatched, so merge all of them into a new entry and emit that.
            mismatched_dirs.push(d);
            let merged_tree = Self::merge_helper(
              parent_path.join(name.as_ref()),
              mismatched_dirs
                .into_iter()
                .map(|d| d.tree.clone())
                .collect(),
            )?;
            entries.push(Entry::Directory(Directory::from_digest_tree(
              name,
              merged_tree,
            )));
          }
        }
      }
    }

    Ok(DigestTrie(entries.into()))
  }
}

pub enum MergeError {
  Duplicates {
    parent_path: PathBuf,
    files: Vec<File>,
    directories: Vec<Directory>,
  },
}

impl MergeError {
  fn duplicates(parent_path: PathBuf, files: Vec<&File>, directories: Vec<&Directory>) -> Self {
    MergeError::Duplicates {
      parent_path,
      files: files.into_iter().cloned().collect(),
      directories: directories.into_iter().cloned().collect(),
    }
  }
}

fn paths_of_child_dir(name: Name, paths: Vec<TypedPath>) -> Vec<TypedPath> {
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
          path: path.strip_prefix(name.as_ref()).unwrap(),
          is_executable,
        },
        TypedPath::Dir(path) => TypedPath::Dir(path.strip_prefix(name.as_ref()).unwrap()),
      })
    })
    .collect()
}

fn first_path_component_to_name(path: &Path) -> Result<Name, String> {
  let first_path_component = path
    .components()
    .next()
    .ok_or_else(|| format!("Path `{}` was unexpectedly empty", path.display()))?;
  let name = first_path_component
    .as_os_str()
    .to_str()
    .ok_or_else(|| format!("{:?} is not representable in UTF8", first_path_component))?;
  Ok(Name(Intern::from(name)))
}

/// Return any entries which did not have the same Digest as the given Entry.
fn collisions<'a>(
  digest: Digest,
  entries: impl Iterator<Item = &'a Entry>,
) -> (Vec<&'a File>, Vec<&'a Directory>) {
  let mut mismatched_files = Vec::new();
  let mut mismatched_dirs = Vec::new();
  for entry in entries {
    match entry {
      Entry::File(other) if other.digest != digest => mismatched_files.push(other),
      Entry::Directory(other) if other.digest != digest => mismatched_dirs.push(other),
      _ => (),
    }
  }
  (mismatched_files, mismatched_dirs)
}

/// Format directories and files as a human readable string.
fn format_directories_and_files(directories: &[String], files: &[String]) -> String {
  format!(
    "{}{}{}",
    if directories.is_empty() {
      String::new()
    } else {
      format!(
        "director{} named: {}",
        if directories.len() == 1 { "y" } else { "ies" },
        directories.join(", ")
      )
    },
    if !directories.is_empty() && !files.is_empty() {
      " and "
    } else {
      ""
    },
    if files.is_empty() {
      String::new()
    } else {
      format!(
        "file{} named: {}",
        if files.len() == 1 { "" } else { "s" },
        files.join(", ")
      )
    },
  )
}
