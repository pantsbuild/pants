// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::cmp::Ordering;
use std::collections::HashMap;
use std::fmt::{self, Debug, Display};
use std::hash::{self, Hash};
use std::ops::Deref;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;

use deepsize::{known_deep_size, DeepSizeOf};
use internment::Intern;
use itertools::Itertools;
use lazy_static::lazy_static;
use log::warn;
use serde::Serialize;

// TODO: Extract protobuf-specific pieces to a new crate.
use grpc_util::prost::MessageExt;
use hashing::{Digest, EMPTY_DIGEST};
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::require_digest;

use crate::{LinkDepth, PathStat, RelativePath, MAX_LINK_DEPTH};

lazy_static! {
    pub static ref EMPTY_DIGEST_TREE: DigestTrie = DigestTrie(vec![].into());
    pub static ref EMPTY_DIRECTORY_DIGEST: DirectoryDigest = DirectoryDigest {
        digest: EMPTY_DIGEST,
        tree: Some(EMPTY_DIGEST_TREE.clone()),
    };
}

#[derive(Clone, Copy)]
pub enum SymlinkBehavior {
    /// Treat symlinks as a distinctive element.
    Aware,
    /// Follow symlinks to their target.
    Oblivious,
}

/// A Digest for a directory, optionally with its content stored as a DigestTrie.
///
/// If a DirectoryDigest has a DigestTrie reference, then its Digest _might not_ be persisted to
/// the Store. If the DirectoryDigest does not hold a DigestTrie, then that Digest _must_ have been
/// persisted to the Store (either locally or remotely). The field thus acts likes a cache in some
/// cases, but in other cases is an indication that the tree must first be persisted (or loaded)
/// before the Digest may be operated on.
#[derive(Clone, DeepSizeOf, Serialize)]
pub struct DirectoryDigest {
    // NB: Private in order to force a choice between `todo_as_digest` and `as_digest`.
    digest: Digest,
    #[serde(skip_serializing)]
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
        f.debug_struct("DirectoryDigest")
            .field("digest", &self.digest)
            .field("tree", &tree)
            .finish()
    }
}

impl DirectoryDigest {
    /// Construct a DirectoryDigest from a Digest and DigestTrie (by asserting that the Digest
    /// identifies the DigestTrie).
    pub fn new(digest: Digest, tree: DigestTrie) -> Self {
        if cfg!(debug_assertions) {
            let actual = tree.compute_root_digest();
            assert!(digest == actual, "Expected {digest:?} but got {actual:?}");
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
    pub fn from_persisted_digest(digest: Digest) -> Self {
        Self { digest, tree: None }
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
    pub fn todo_as_digest(&self) -> Digest {
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
#[derive(Copy, Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct Name(Intern<String>);
// NB: Calculating the actual deep size of an `Intern` is very challenging, because it does not
// keep any record of the number of held references, and instead effectively makes its held value
// static. Switching to `ArcIntern` would get accurate counts at the cost of performance and size.
known_deep_size!(0; Name);

impl Name {
    pub fn new(name: &str) -> Self {
        if cfg!(debug_assertions) {
            assert!(Path::new(name).components().count() < 2)
        }
        Name(Intern::from(name))
    }
}

impl Deref for Name {
    type Target = Intern<String>;

    fn deref(&self) -> &Intern<String> {
        &self.0
    }
}

impl Display for Name {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(f, "{}", self.0.as_ref())
    }
}

#[derive(Clone, Debug, DeepSizeOf)]
pub enum Entry {
    Directory(Directory),
    File(File),
    Symlink(Symlink),
}

impl Entry {
    pub fn name(&self) -> Name {
        match self {
            Entry::Directory(d) => d.name,
            Entry::File(f) => f.name,
            Entry::Symlink(s) => s.name,
        }
    }

    pub fn digest(&self) -> Digest {
        match self {
            Entry::Directory(d) => d.digest,
            Entry::File(f) => f.digest,
            Entry::Symlink(_) => EMPTY_DIGEST,
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
    pub(crate) fn new(name: Name, entries: Vec<Entry>) -> Self {
        Self::from_digest_tree(name, DigestTrie(entries.into()))
    }

    fn from_remexec_directory_node(
        dir_node: &remexec::DirectoryNode,
        directories_by_digest: &HashMap<Digest, remexec::Directory>,
    ) -> Result<Self, String> {
        let digest = require_digest(&dir_node.digest)?;
        let directory = directories_by_digest.get(&digest).ok_or_else(|| {
            format!(
                "Child of {name} with {digest:?} was not present.",
                name = dir_node.name
            )
        })?;
        Ok(Self {
            name: Name(Intern::from(&dir_node.name)),
            digest,
            tree: DigestTrie::from_remexec_directories(directory, directories_by_digest)?,
        })
    }

    fn from_digest_tree(name: Name, tree: DigestTrie) -> Self {
        Self {
            name,
            digest: tree.compute_root_digest(),
            tree,
        }
    }

    pub fn name(&self) -> Name {
        self.name
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
}

impl Debug for Directory {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // NB: To avoid over-large output, we don't render the Trie. It would likely be best rendered
        // as e.g. JSON.
        f.debug_struct("Directory")
            .field("name", &self.name)
            .field("digest", &self.digest)
            .field("tree", &"..")
            .finish()
    }
}

impl From<&Directory> for remexec::DirectoryNode {
    fn from(dir: &Directory) -> Self {
        remexec::DirectoryNode {
            name: dir.name.as_ref().to_owned(),
            digest: Some((&dir.digest).into()),
        }
    }
}

#[derive(Clone, Debug, DeepSizeOf)]
pub struct File {
    name: Name,
    digest: Digest,
    is_executable: bool,
}

impl File {
    pub fn name(&self) -> Name {
        self.name
    }

    pub fn digest(&self) -> Digest {
        self.digest
    }

    pub fn is_executable(&self) -> bool {
        self.is_executable
    }
}

impl TryFrom<&remexec::FileNode> for File {
    type Error = String;

    fn try_from(file_node: &remexec::FileNode) -> Result<Self, Self::Error> {
        Ok(Self {
            name: Name(Intern::from(&file_node.name)),
            digest: require_digest(&file_node.digest)?,
            is_executable: file_node.is_executable,
        })
    }
}

impl From<&File> for remexec::FileNode {
    fn from(file: &File) -> Self {
        remexec::FileNode {
            name: file.name.as_ref().to_owned(),
            digest: Some(file.digest.into()),
            is_executable: file.is_executable,
            ..remexec::FileNode::default()
        }
    }
}

#[derive(Clone, Debug, DeepSizeOf)]
pub struct Symlink {
    name: Name,
    target: PathBuf,
}

impl Symlink {
    pub fn name(&self) -> Name {
        self.name
    }

    pub fn target(&self) -> &Path {
        &self.target
    }
}

impl TryFrom<&remexec::SymlinkNode> for Symlink {
    type Error = String;

    fn try_from(symlink_node: &remexec::SymlinkNode) -> Result<Self, Self::Error> {
        Ok(Self {
            name: Name(Intern::from(&symlink_node.name)),
            target: PathBuf::from(&symlink_node.target),
        })
    }
}

impl From<&Symlink> for remexec::SymlinkNode {
    fn from(symlink: &Symlink) -> Self {
        remexec::SymlinkNode {
            name: symlink.name.as_ref().to_owned(),
            target: symlink.target.to_str().unwrap().to_string(),
            ..remexec::SymlinkNode::default()
        }
    }
}

// TODO: `PathStat` owns its path, which means it can't be used via recursive slicing. See
// whether these types can be merged.
pub enum TypedPath<'a> {
    File { path: &'a Path, is_executable: bool },
    Link { path: &'a Path, target: &'a Path },
    Dir(&'a Path),
}

impl<'a> Deref for TypedPath<'a> {
    type Target = Path;

    fn deref(&self) -> &Path {
        match self {
            TypedPath::File { path, .. } => path,
            TypedPath::Link { path, .. } => path,
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
            PathStat::Link { path, stat } => TypedPath::Link {
                path,
                target: &stat.target,
            },
            PathStat::Dir { path, .. } => TypedPath::Dir(path),
        }
    }
}

#[derive(Clone, DeepSizeOf)]
pub struct DigestTrie(Arc<[Entry]>);

// TODO: This avoids a `rustc` crasher (repro on 7f319ee84ad41bc0aea3cb01fb2f32dcd51be704).
unsafe impl Sync for DigestTrie {}

impl From<DigestTrie> for DirectoryDigest {
    fn from(tree: DigestTrie) -> Self {
        Self {
            digest: tree.compute_root_digest(),
            tree: Some(tree),
        }
    }
}

impl DigestTrie {
    /// Create a DigestTrie from unique TypedPath. Fails for duplicate items.
    pub fn from_unique_paths(
        mut path_stats: Vec<TypedPath>,
        file_digests: &HashMap<PathBuf, Digest>,
    ) -> Result<Self, String> {
        // Sort and ensure that there were no duplicate entries.
        #[allow(clippy::unnecessary_sort_by)]
        path_stats.sort_by(|a, b| (**a).cmp(&**b));

        // The helper assumes that if a Path has multiple children, it must be a directory.
        // Proactively error if we run into identically named files, because otherwise we will treat
        // them like empty directories.
        let pre_dedupe_len = path_stats.len();
        path_stats.dedup_by(|a, b| **a == **b);
        if path_stats.len() != pre_dedupe_len {
            return Err(format!(
                "Snapshots must be constructed from unique path stats; got duplicates in {:?}",
                path_stats
                    .iter()
                    .map(|p| (**p).to_str())
                    .collect::<Vec<_>>()
            ));
        }

        Self::from_sorted_paths(PathBuf::new(), path_stats, file_digests)
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
                    TypedPath::Link { target, .. } => {
                        entries.push(Entry::Symlink(Symlink {
                            name,
                            target: target.to_path_buf(),
                        }));
                    }
                    TypedPath::Dir { .. } => {
                        // Because there are no children of this Dir, it must be empty.
                        entries.push(Entry::Directory(Directory::new(name, vec![])));
                    }
                }
            } else {
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

    /// Create a DigestTrie from a root remexec::Directory and a map of its transitive children.
    fn from_remexec_directories(
        root: &remexec::Directory,
        children_by_digest: &HashMap<Digest, remexec::Directory>,
    ) -> Result<Self, String> {
        let mut entries = root
            .files
            .iter()
            .map(|f| File::try_from(f).map(Entry::File))
            .chain(
                root.symlinks
                    .iter()
                    .map(|s| Symlink::try_from(s).map(Entry::Symlink)),
            )
            .chain(root.directories.iter().map(|d| {
                Directory::from_remexec_directory_node(d, children_by_digest).map(Entry::Directory)
            }))
            .collect::<Result<Vec<_>, _>>()?;
        entries.sort_by_key(|e| e.name());
        Ok(Self(entries.into()))
    }

    pub fn as_remexec_directory(&self) -> remexec::Directory {
        let mut files = Vec::new();
        let mut directories = Vec::new();
        let mut symlinks = Vec::new();

        for entry in &*self.0 {
            match entry {
                Entry::File(f) => files.push(f.into()),
                Entry::Symlink(s) => symlinks.push(s.into()),
                Entry::Directory(d) => directories.push(d.into()),
            }
        }

        remexec::Directory {
            directories,
            files,
            symlinks,
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
        &self.0
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
                // There is no digest for a symlink
                Entry::Symlink(_) => (),
            }
        }
        digests
    }

    pub fn files(&self, symlink_behavior: SymlinkBehavior) -> Vec<PathBuf> {
        let mut files = Vec::new();
        self.walk(symlink_behavior, &mut |path, entry| {
            if let Entry::File(_) = entry {
                files.push(path.to_owned())
            }
        });
        files
    }

    pub fn directories(&self, symlink_behavior: SymlinkBehavior) -> Vec<PathBuf> {
        let mut directories = Vec::new();
        self.walk(symlink_behavior, &mut |path, entry| {
            match entry {
                Entry::Directory(d) if d.name.is_empty() => {
                    // Is the root directory, which is not emitted here.
                }
                Entry::Directory(_) => directories.push(path.to_owned()),
                _ => (),
            }
        });
        directories
    }

    pub fn symlinks(&self) -> Vec<PathBuf> {
        let mut symlinks = Vec::new();
        self.walk(SymlinkBehavior::Aware, &mut |path, entry| {
            if let Entry::Symlink(_) = entry {
                symlinks.push(path.to_owned())
            }
        });
        symlinks
    }

    /// The paths of all "leaf" nodes of the DigestTrie: empty directories, files, or symlinks.
    pub fn leaf_paths(&self) -> Vec<PathBuf> {
        let mut paths = Vec::new();
        self.walk(SymlinkBehavior::Aware, &mut |path, entry| match entry {
            Entry::Directory(d) if d.tree.0.is_empty() => paths.push(path.to_owned()),
            Entry::Directory(_) => {}
            Entry::File(_) | Entry::Symlink(_) => paths.push(path.to_owned()),
        });
        paths
    }

    /// Visit every node in the tree, calling the given function with the path to the Node, and its
    /// entries.
    /// NOTE: if SymlinkBehavior::Oblivious, `f` will never be called with a `SymlinkEntry`.
    pub fn walk(&self, symlink_behavior: SymlinkBehavior, f: &mut impl FnMut(&Path, &Entry)) {
        {
            // TODO: It's likely that a DigestTrie should hold its own Digest, to avoid re-computing it
            // here.
            let root = Entry::Directory(Directory::from_digest_tree(
                Name(Intern::from("")),
                self.clone(),
            ));
            f(&PathBuf::new(), &root);
        }
        self.walk_helper(self, PathBuf::new(), symlink_behavior, 0, f)
    }

    fn walk_helper(
        &self,
        root: &DigestTrie,
        path_so_far: PathBuf,
        symlink_behavior: SymlinkBehavior,
        mut link_depth: LinkDepth,
        f: &mut impl FnMut(&Path, &Entry),
    ) {
        for entry in &*self.0 {
            let path = path_so_far.join(entry.name().as_ref());
            let mut entry = entry;
            if let SymlinkBehavior::Oblivious = symlink_behavior {
                if let Entry::Symlink(s) = entry {
                    link_depth += 1;
                    if s.target == Component::CurDir.as_os_str() {
                        if link_depth >= MAX_LINK_DEPTH {
                            warn!("Exceeded the maximum link depth while traversing links. Stopping traversal.");
                            return;
                        }
                        self.walk_helper(root, path.clone(), symlink_behavior, link_depth, f);
                        return;
                    }

                    let destination_path = path_so_far.join(s.target.clone());
                    let destination_entry = root.entry_helper(root, &destination_path, link_depth);
                    if let Ok(Some(valid_entry)) = destination_entry {
                        entry = valid_entry;
                    } else {
                        continue;
                    }
                }
            }

            match entry {
                Entry::Directory(d) => {
                    f(&path, entry);
                    d.tree
                        .walk_helper(root, path.to_path_buf(), symlink_behavior, link_depth, f);
                }
                _ => f(&path, entry),
            };
        }
    }

    pub fn diff(&self, other: &DigestTrie) -> DigestTrieDiff {
        let mut result = DigestTrieDiff::default();
        self.diff_helper(other, PathBuf::new(), &mut result);
        result
    }

    // NB: The current implementation assumes that the entries are sorted (by name, irrespective of
    // whether the entry is a file/dir).
    fn diff_helper(&self, them: &DigestTrie, path_so_far: PathBuf, result: &mut DigestTrieDiff) {
        let mut our_iter = self.0.iter();
        let mut their_iter = them.0.iter();
        let mut ours = our_iter.next();
        let mut theirs = their_iter.next();

        let add_unique = |entry: &Entry,
                          unique_files: &mut Vec<PathBuf>,
                          unique_dirs: &mut Vec<PathBuf>,
                          unique_symlinks: &mut Vec<PathBuf>| {
            let path = path_so_far.join(entry.name().as_ref());
            match entry {
                Entry::File(_) => unique_files.push(path),
                Entry::Symlink(_) => unique_symlinks.push(path),
                Entry::Directory(_) => unique_dirs.push(path),
            }
        };

        let add_ours = |entry: &Entry, diff: &mut DigestTrieDiff| {
            add_unique(
                entry,
                &mut diff.our_unique_files,
                &mut diff.our_unique_dirs,
                &mut diff.our_unique_symlinks,
            );
        };
        let add_theirs = |entry: &Entry, diff: &mut DigestTrieDiff| {
            add_unique(
                entry,
                &mut diff.their_unique_files,
                &mut diff.their_unique_dirs,
                &mut diff.their_unique_symlinks,
            );
        };

        while let Some(our_entry) = ours {
            match theirs {
                Some(their_entry) => match our_entry.name().cmp(&their_entry.name()) {
                    Ordering::Less => {
                        add_ours(our_entry, result);
                        ours = our_iter.next();
                        continue;
                    }
                    Ordering::Greater => {
                        add_theirs(their_entry, result);
                        theirs = their_iter.next();
                        continue;
                    }
                    Ordering::Equal => match (our_entry, their_entry) {
                        (Entry::File(our_file), Entry::File(their_file)) => {
                            if our_file.digest != their_file.digest {
                                result
                                    .changed_files
                                    .push(path_so_far.join(our_file.name().as_ref()));
                            }
                            ours = our_iter.next();
                            theirs = their_iter.next();
                        }
                        (Entry::Symlink(our_symlink), Entry::Symlink(their_symlink)) => {
                            if our_symlink.target != their_symlink.target {
                                result
                                    .changed_symlinks
                                    .push(path_so_far.join(our_symlink.name.as_ref()));
                            }
                            ours = our_iter.next();
                            theirs = their_iter.next();
                        }
                        (Entry::Directory(our_dir), Entry::Directory(their_dir)) => {
                            if our_dir.digest != their_dir.digest {
                                our_dir.tree.diff_helper(
                                    &their_dir.tree,
                                    path_so_far.join(our_dir.name().as_ref()),
                                    result,
                                )
                            }
                            ours = our_iter.next();
                            theirs = their_iter.next();
                        }
                        _ => {
                            add_ours(our_entry, result);
                            add_theirs(their_entry, result);
                            ours = our_iter.next();
                            theirs = their_iter.next();
                        }
                    },
                },
                None => {
                    add_ours(our_entry, result);
                    ours = our_iter.next();
                }
            }
        }

        while let Some(their_entry) = &theirs {
            add_theirs(their_entry, result);
            theirs = their_iter.next();
        }
    }

    /// Add the given path as a prefix for this trie, returning the resulting trie.
    pub fn add_prefix(self, prefix: &RelativePath) -> Result<DigestTrie, String> {
        let mut prefix_iter = prefix.iter();
        let mut tree = self;
        while let Some(parent) = prefix_iter.next_back() {
            let directory =
                Directory::from_digest_tree(first_path_component_to_name(parent.as_ref())?, tree);
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
            let mut symlinks = Vec::new();
            for entry in tree.entries() {
                match entry {
                    Entry::Directory(d)
                        if Path::new(d.name.as_ref()).as_os_str() == component_to_strip =>
                    {
                        matching_dir = Some(d)
                    }
                    Entry::Directory(d) => extra_directories.push(d.name.as_ref().to_owned()),
                    Entry::File(f) => files.push(f.name.as_ref().to_owned()),
                    Entry::Symlink(s) => symlinks.push(s.name.as_ref().to_owned()),
                }
            }

            let has_already_stripped_any = already_stripped.components().next().is_some();
            match (
                matching_dir,
                extra_directories.is_empty() && files.is_empty() && symlinks.is_empty(),
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
                        if !extra_directories.is_empty()
                            || !files.is_empty()
                            || !symlinks.is_empty()
                        {
                            format!(
                                " but did contain {}",
                                format_entries(&extra_directories, &files, &symlinks)
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
                        format_entries(&extra_directories, &files, &symlinks),
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

    /// Return the Entry at the given relative path in the trie, or None if no such path was present.
    /// If a directory component is a symlink, will follow the symlink. In cases where a symlink points
    /// to a parent or current dir, the return may be None due to exceeding the link depth.
    ///
    /// Cannot follow a symlink above `self` (returns None).
    ///
    /// An error will be returned if the given path attempts to traverse below a file entry.
    pub fn entry<'a>(&'a self, path: &Path) -> Result<Option<&'a Entry>, String> {
        self.entry_helper(self, path, 0)
    }

    fn entry_helper<'a>(
        &'a self,
        root: &'a DigestTrie,
        requested_path: &Path,
        link_depth: LinkDepth,
    ) -> Result<Option<&'a Entry>, String> {
        let mut tree = self;
        let mut path_so_far = PathBuf::new();
        // Identical to path_so_far, but doesn't have components for "CurDir" symlinks
        // E.g. If path_so_far is "dir/self/self/foo" and "dir/self -> .", then logical_path will be
        // "dir/foo".
        let mut logical_path = PathBuf::new();
        let mut components = requested_path.components();
        let mut current_entry: Option<&Entry> = None;
        while let Some(component) = components.next() {
            if component == Component::CurDir {
                // NB: This only happens if "." is the first component in a path.
                continue;
            }

            if let Some(Entry::File(_)) = current_entry {
                return Err(format!(
                    "{tree_digest:?} cannot contain a path at {requested_path:?}, \
          because a file was encountered at {path_so_far:?}.",
                    tree_digest = self.compute_root_digest()
                ));
            }

            if let Some(Entry::Directory(d)) = current_entry {
                tree = &d.tree;
            }

            path_so_far.push(component);
            logical_path.push(component);
            if component == Component::ParentDir {
                if let Some(grandparent) = logical_path.parent().unwrap().parent() {
                    let full_path = grandparent.join(components.as_path());
                    return root.entry_helper(root, &full_path, link_depth);
                }
                return Ok(None);
            }

            let component = component.as_os_str();
            let maybe_matching_entry = tree
                .entries()
                .binary_search_by_key(&component, |entry| {
                    Path::new(entry.name().as_ref()).as_os_str()
                })
                .ok()
                .map(|idx| &tree.entries()[idx]);
            if maybe_matching_entry.is_none() {
                return Ok(None);
            }

            if let Some(Entry::Symlink(s)) = maybe_matching_entry {
                if link_depth >= MAX_LINK_DEPTH {
                    warn!("Exceeded the maximum link depth while traversing links. Stopping traversal.");
                    return Ok(None);
                }

                if s.target.as_os_str() == Component::CurDir.as_os_str() {
                    logical_path = logical_path.parent().unwrap().to_path_buf();
                    continue;
                }
                let full_path = path_so_far
                    .parent()
                    .unwrap()
                    .join(&s.target)
                    .join(components.as_path());
                return root.entry_helper(root, &full_path, link_depth + 1);
            }

            current_entry = maybe_matching_entry;
        }
        Ok(current_entry)
    }

    /// Given DigestTries, merge them recursively into a single DigestTrie.
    ///
    /// If a file is present with the same name and contents multiple times, it will appear once.
    /// If a file is present with the same name, but different contents, an error will be returned.
    pub fn merge(trees: Vec<DigestTrie>) -> Result<DigestTrie, MergeError> {
        Self::merge_helper(PathBuf::new(), trees)
    }

    fn merge_helper(
        parent_path: PathBuf,
        trees: Vec<DigestTrie>,
    ) -> Result<DigestTrie, MergeError> {
        if trees.is_empty() {
            return Ok(EMPTY_DIGEST_TREE.clone());
        } else if trees.len() == 1 {
            let mut trees = trees;
            return Ok(trees.pop().unwrap());
        }

        // Merge sorted Entries.
        let input_entries = trees
            .iter()
            .map(|tree| tree.entries().iter())
            .kmerge_by(|a, b| a.name() < b.name());

        // Then group by name, and merge into an output list.
        let mut entries: Vec<Entry> = Vec::new();
        for (name, group) in &input_entries.group_by(|e| e.name()) {
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
                    let (mut mismatched_files, mismatched_dirs, mismatched_symlinks) =
                        collisions(f.digest, group);
                    if !mismatched_files.is_empty()
                        || !mismatched_dirs.is_empty()
                        || !mismatched_symlinks.is_empty()
                    {
                        mismatched_files.push(f);
                        return Err(MergeError::duplicates(
                            parent_path,
                            mismatched_files,
                            mismatched_dirs,
                            mismatched_symlinks,
                        ));
                    }

                    // All entries matched: emit one copy.
                    entries.push(first.clone());
                }
                Entry::Symlink(s) => {
                    let mut mismatched_files = Vec::new();
                    let mut mismatched_dirs = Vec::new();
                    let mut mismatched_symlinks = Vec::new();
                    for entry in group {
                        match entry {
                            Entry::File(other) => mismatched_files.push(other),
                            Entry::Symlink(other) if other.target != s.target => {
                                mismatched_symlinks.push(other)
                            }
                            Entry::Directory(other) => mismatched_dirs.push(other),
                            _ => (),
                        }
                    }

                    if !mismatched_files.is_empty()
                        || !mismatched_dirs.is_empty()
                        || !mismatched_symlinks.is_empty()
                    {
                        mismatched_symlinks.push(s);
                        return Err(MergeError::duplicates(
                            parent_path,
                            mismatched_files,
                            mismatched_dirs,
                            mismatched_symlinks,
                        ));
                    }

                    // All entries matched: emit one copy.
                    entries.push(first.clone());
                }
                Entry::Directory(d) => {
                    // If any Entry is a Directory, then they must all be Directories which will be merged.
                    let (mismatched_files, mut mismatched_dirs, mismatched_symlinks) =
                        collisions(d.digest, group);

                    // If there were any Files, error.
                    if !mismatched_files.is_empty() || !mismatched_symlinks.is_empty() {
                        mismatched_dirs.push(d);
                        return Err(MergeError::duplicates(
                            parent_path,
                            mismatched_files,
                            mismatched_dirs,
                            mismatched_symlinks,
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

impl TryFrom<remexec::Tree> for DigestTrie {
    type Error = String;

    fn try_from(tree: remexec::Tree) -> Result<Self, Self::Error> {
        let root = tree
            .root
            .as_ref()
            .ok_or_else(|| format!("Corrupt tree, no root: {tree:?}"))?;
        let children = tree
            .children
            .into_iter()
            .map(|d| (Digest::of_bytes(&d.to_bytes()), d))
            .collect::<HashMap<_, _>>();

        Self::from_remexec_directories(root, &children)
    }
}

impl From<&DigestTrie> for remexec::Tree {
    fn from(trie: &DigestTrie) -> Self {
        let mut tree = remexec::Tree::default();
        trie.walk(SymlinkBehavior::Aware, &mut |_, entry| {
            match entry {
                Entry::File(_) => (),
                Entry::Symlink(_) => (),
                Entry::Directory(d) if d.name.is_empty() => {
                    // Is the root directory.
                    tree.root = Some(d.tree.as_remexec_directory());
                }
                Entry::Directory(d) => {
                    // Is a child directory.
                    tree.children.push(d.tree.as_remexec_directory());
                }
            }
        });
        tree
    }
}

#[derive(Default)]
pub struct DigestTrieDiff {
    pub our_unique_files: Vec<PathBuf>,
    pub our_unique_symlinks: Vec<PathBuf>,
    pub our_unique_dirs: Vec<PathBuf>,
    pub their_unique_files: Vec<PathBuf>,
    pub their_unique_symlinks: Vec<PathBuf>,
    pub their_unique_dirs: Vec<PathBuf>,
    pub changed_files: Vec<PathBuf>,
    pub changed_symlinks: Vec<PathBuf>,
}

pub enum MergeError {
    Duplicates {
        parent_path: PathBuf,
        files: Vec<File>,
        directories: Vec<Directory>,
        symlinks: Vec<Symlink>,
    },
}

impl MergeError {
    fn duplicates(
        parent_path: PathBuf,
        files: Vec<&File>,
        directories: Vec<&Directory>,
        symlinks: Vec<&Symlink>,
    ) -> Self {
        MergeError::Duplicates {
            parent_path,
            files: files.into_iter().cloned().collect(),
            directories: directories.into_iter().cloned().collect(),
            symlinks: symlinks.into_iter().cloned().collect(),
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
                TypedPath::Link { path, target } => TypedPath::Link {
                    path: path.strip_prefix(name.as_ref()).unwrap(),
                    target: target.strip_prefix(name.as_ref()).unwrap_or(target),
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
        .ok_or_else(|| format!("{first_path_component:?} is not representable in UTF8"))?;
    Ok(Name(Intern::from(name)))
}

/// Return any entries which did not have the same Digest as the given Entry.
fn collisions<'a>(
    digest: Digest,
    entries: impl Iterator<Item = &'a Entry>,
) -> (Vec<&'a File>, Vec<&'a Directory>, Vec<&'a Symlink>) {
    let mut mismatched_files = Vec::new();
    let mut mismatched_dirs = Vec::new();
    let mut mismatched_symlinks = Vec::new();
    for entry in entries {
        match entry {
            Entry::File(other) if other.digest != digest => mismatched_files.push(other),
            // Symlinks can't have the same digest as files/directories, as they have no digest
            Entry::Symlink(other) => mismatched_symlinks.push(other),
            Entry::Directory(other) if other.digest != digest => mismatched_dirs.push(other),
            _ => (),
        }
    }
    (mismatched_files, mismatched_dirs, mismatched_symlinks)
}

/// Format entries as a human readable string.
fn format_entries(directories: &[String], files: &[String], symlinks: &[String]) -> String {
    format!(
        "{}{}{}{}{}",
        if directories.is_empty() {
            String::new()
        } else {
            format!(
                "director{} named: {}",
                if directories.len() == 1 { "y" } else { "ies" },
                directories.join(", ")
            )
        },
        if !directories.is_empty() && (!files.is_empty() || !symlinks.is_empty()) {
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
        if (!directories.is_empty() || !files.is_empty()) && !symlinks.is_empty() {
            " and "
        } else {
            ""
        },
        if symlinks.is_empty() {
            String::new()
        } else {
            format!(
                "symlink{} named: {}",
                if symlinks.len() == 1 { "" } else { "s" },
                symlinks.join(", ")
            )
        },
    )
}
