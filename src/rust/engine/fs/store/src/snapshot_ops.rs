// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::{snapshot::osstring_as_utf8, Snapshot};

use async_trait::async_trait;
use bazel_protos::remote_execution as remexec;
use boxfuture::{BoxFuture, Boxable};
use fs::{
  ExpandablePathGlobs, GitignoreStyleExcludes, PathGlob, PreparedPathGlobs, RelativePath,
  DOUBLE_STAR_GLOB, SINGLE_STAR_GLOB,
};
use futures::compat::Future01CompatExt;
use futures::future::{self as future03, TryFutureExt};
use futures01::future::{self, Future};
use glob::Pattern;
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use indexmap::{self, IndexMap, IndexSet};

use std::convert::From;
use std::fmt;
use std::iter::Iterator;
use std::path::{Path, PathBuf};
use std::sync::Arc;

#[derive(Clone, Eq, PartialEq, Hash, Debug)]
pub enum SnapshotOpsError {
  String(String),
  DigestMergeFailure(String),
  GlobMatchError(String),
}

impl From<String> for SnapshotOpsError {
  fn from(err: String) -> Self {
    Self::String(err)
  }
}

///
/// Parameters used to determine which files and directories to operate on within a parent snapshot.
///
#[derive(Debug, Clone)]
pub struct SubsetParams {
  pub globs: PreparedPathGlobs,
}

///
/// Determine how to handle colliding file paths when merging multiple snapshots.
///
#[derive(Clone)]
pub enum MergeBehavior {
  ///
  /// Error out if any duplicate files are detected. Duplicate files with the same contents are
  /// still allowed.
  ///
  NoDuplicates,
  ///
  /// Any colliding file paths from separate snapshots that match the SubsetParams will be allowed
  /// without error. In that case, the first snapshot in the list to merge which contains the file
  /// will take precedence in the merged snapshot.
  ///
  /// Collisions in file paths that do *not* match the SubsetParams will still cause an error when
  /// merged. In the case when a file in one snapshot has the same path as a directory in another
  /// snapshot to be merged, an error will be raised regardless of of the SubsetParams.
  ///
  LinearCompose(SubsetParams),
}

impl MergeBehavior {
  pub fn is_allowed_duplicate(&self, path: &Path) -> bool {
    match self {
      MergeBehavior::NoDuplicates => false,
      MergeBehavior::LinearCompose(ref params) => params.globs.matches(path),
    }
  }
}

///
/// A trait that encapsulates some of the features of a Store, with nicer type signatures. This is
/// used to implement the `SnapshotOps` trait.
///
#[async_trait]
pub trait StoreWrapper: fmt::Debug + Clone + Send + Sync {
  async fn load_file_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
    &self,
    digest: Digest,
    f: F,
  ) -> Result<Option<T>, String>;

  async fn load_directory(&self, digest: Digest) -> Result<Option<remexec::Directory>, String>;
  async fn load_directory_or_err(&self, digest: Digest) -> Result<remexec::Directory, String>;

  async fn record_directory(&self, directory: &remexec::Directory) -> Result<Digest, String>;
}

///
/// When we evaluate a recursive glob during the subset() operation, we perform some relatively
/// complex logic to coalesce globs in subdirectories, and to short-circuit retrieving
/// subdirectories from the store at all if we don't need to inspect their contents
/// (e.g. if a glob ends in "**"). This struct isolates that complexity, allowing the code in
/// subset() to just operate on the higher-level GlobbedFilesAndDirectories struct.
///
struct IntermediateGlobbedFilesAndDirectories {
  globbed_files: IndexMap<PathBuf, remexec::FileNode>,
  globbed_directories: IndexMap<PathBuf, remexec::DirectoryNode>,
  cur_dir_files: IndexMap<PathBuf, remexec::FileNode>,
  cur_dir_directories: IndexMap<PathBuf, remexec::DirectoryNode>,
  todo_directories: IndexMap<PathBuf, Vec<RestrictedPathGlob>>,
  prefix: PathBuf,
  multiple_globs: MultipleGlobs,
}

struct GlobbedFilesAndDirectories {
  // All of the subdirectories of the source Directory that is currently being subsetted,
  // *regardless of whether the glob is matched yet*.
  cur_dir_directories: IndexMap<PathBuf, remexec::DirectoryNode>,
  // All of the files of the source Directory matching the current glob.
  globbed_files: IndexMap<PathBuf, remexec::FileNode>,
  // All of the matching subdirectories of the source Directory *after* being subsetted to match the
  // current glob.
  globbed_directories: IndexMap<PathBuf, remexec::DirectoryNode>,
  // All of the matching subdirectories of the source Directory, *before* being subsetted to match
  // the current glob.
  todo_directories: IndexMap<PathBuf, Vec<RestrictedPathGlob>>,
  exclude: Arc<GitignoreStyleExcludes>,
}

impl IntermediateGlobbedFilesAndDirectories {
  fn from_cur_dir_and_globs(
    cur_dir: remexec::Directory,
    multiple_globs: MultipleGlobs,
    prefix: PathBuf,
  ) -> Self {
    let cur_dir_files: IndexMap<PathBuf, remexec::FileNode> = cur_dir
      .get_files()
      .to_vec()
      .into_iter()
      .map(|file_node| (PathBuf::from(file_node.get_name()), file_node))
      .collect();
    let cur_dir_directories: IndexMap<PathBuf, remexec::DirectoryNode> = cur_dir
      .get_directories()
      .to_vec()
      .into_iter()
      .map(|directory_node| (PathBuf::from(directory_node.get_name()), directory_node))
      .collect();

    let globbed_files: IndexMap<PathBuf, remexec::FileNode> = IndexMap::new();
    let globbed_directories: IndexMap<PathBuf, remexec::DirectoryNode> = IndexMap::new();
    let todo_directories: IndexMap<PathBuf, Vec<RestrictedPathGlob>> = IndexMap::new();

    IntermediateGlobbedFilesAndDirectories {
      globbed_files,
      globbed_directories,
      cur_dir_files,
      cur_dir_directories,
      todo_directories,
      prefix,
      multiple_globs,
    }
  }

  async fn populate_globbed_files_and_directories(
    self,
  ) -> Result<GlobbedFilesAndDirectories, SnapshotOpsError> {
    let IntermediateGlobbedFilesAndDirectories {
      mut globbed_files,
      mut globbed_directories,
      // NB: When iterating over files, we can remove them from `cur_dir_files` after they are
      // successfully matched once, hence the `mut` declaration. This is a small
      // optimization. However, when iterating over directories, different DirWildcard instances
      // within a single Vec<PathGlob> can result in having multiple different DirWildcard instances
      // created after matching against a single directory node! So we do *not* mark
      // `cur_dir_directories` as `mut`.
      mut cur_dir_files,
      cur_dir_directories,
      mut todo_directories,
      prefix,
      multiple_globs: MultipleGlobs { include, exclude },
    } = self;

    // Populate globbed_{files,directories} by iterating over all the globs.
    for path_glob in include.into_iter() {
      let wildcard = match &path_glob {
        RestrictedPathGlob::Wildcard { wildcard } => wildcard,
        RestrictedPathGlob::DirWildcard { wildcard, .. } => wildcard,
      };

      let matching_files: Vec<PathBuf> = cur_dir_files
        .keys()
        .filter(|path| {
          // NB: match just the current path component against the wildcard, but use the prefix
          // when checking against the `exclude` patterns!
          wildcard.matches_path(path) && !exclude.is_ignored_path(&prefix.join(path), false)
        })
        .cloned()
        .collect();
      for file_path in matching_files.into_iter() {
        // NB: remove any matched files from `cur_dir_files`, so they are successfully matched
        // against at most once.
        let file_node = cur_dir_files.remove(&file_path).unwrap();
        globbed_files.insert(file_path, file_node);
      }

      let matching_directories: Vec<PathBuf> = cur_dir_directories
        .keys()
        .filter(|path| {
          // NB: match just the current path component against the wildcard, but use the prefix
          // when checking against the `exclude` patterns!
          wildcard.matches_path(path) && !exclude.is_ignored_path(&prefix.join(path), true)
        })
        .cloned()
        .collect();
      for directory_path in matching_directories.into_iter() {
        // NB: do *not* remove the directory for `cur_dir_directories` after it is matched
        // successfully once!
        let directory_node = cur_dir_directories.get(&directory_path).unwrap();

        // TODO(#9967): Figure out how to consume the existing glob matching logic that works on
        // `VFS` instances!
        match &path_glob {
          RestrictedPathGlob::Wildcard { wildcard } => {
            // NB: We interpret globs such that the *only* way to have a glob match the contents of
            // a whole directory is to end in '/**' or '/**/*'.
            if *wildcard == *DOUBLE_STAR_GLOB {
              globbed_directories.insert(directory_path, directory_node.clone());
            } else if !globbed_directories.contains_key(&directory_path) {
              // We know this matched a directory node, but not its contents. We produce an empty
              // directory here. We avoid doing this if we have already globbed a full directory,
              // since we take the union of all matched subglobs.
              let mut empty_node = directory_node.clone();
              empty_node.set_digest(to_bazel_digest(EMPTY_DIGEST));
              globbed_directories.insert(directory_path, empty_node);
            };
          }
          RestrictedPathGlob::DirWildcard {
            wildcard,
            remainder,
          } => {
            let mut subdir_globs: Vec<RestrictedPathGlob> = vec![];
            if (*wildcard == *DOUBLE_STAR_GLOB) || (*wildcard == *SINGLE_STAR_GLOB) {
              // Here we short-circuit all cases which would swallow up a directory without
              // subsetting it or needing to perform any further recursive work.
              let short_circuit: bool = match &remainder[..] {
                [] => true,
                // NB: Very often, /**/* is seen ending zsh-style globs, which means the same as
                // ending in /**. Because we want to *avoid* recursing and just use the subdirectory
                // as-is for /**/* and /**, we `continue` here in both cases.
                [single_glob] if *single_glob == *SINGLE_STAR_GLOB => true,
                [double_glob] if *double_glob == *DOUBLE_STAR_GLOB => true,
                [double_glob, single_glob]
                  if *double_glob == *DOUBLE_STAR_GLOB && *single_glob == *SINGLE_STAR_GLOB =>
                {
                  true
                }
                _ => false,
              };
              if short_circuit {
                globbed_directories.insert(directory_path, directory_node.clone());
                continue;
              }
              // In this case, there is a remainder glob which will be used to subset the contents
              // of any subdirectories. We ensure ** is recursive by cloning the ** and all the
              // remainder globs and pushing it to `subdir_globs` whenever we need to recurse into
              // subdirectories.
              let with_double_star = RestrictedPathGlob::DirWildcard {
                wildcard: wildcard.clone(),
                remainder: remainder.clone(),
              };
              subdir_globs.push(with_double_star);
            } else {
              assert_ne!(0, remainder.len());
            }
            match remainder.len() {
              0 => (),
              1 => {
                let next_glob = RestrictedPathGlob::Wildcard {
                  wildcard: remainder.get(0).unwrap().clone(),
                };
                subdir_globs.push(next_glob);
              }
              _ => {
                let next_glob = RestrictedPathGlob::DirWildcard {
                  wildcard: remainder.get(0).unwrap().clone(),
                  remainder: remainder[1..].to_vec(),
                };
                subdir_globs.push(next_glob);
              }
            }
            // Append to the existing globs, and collate at the end of this iteration.
            let entry = todo_directories
              .entry(directory_path)
              .or_insert_with(Vec::new);
            entry.extend(subdir_globs);
          }
        }
      }
    }

    Ok(GlobbedFilesAndDirectories {
      cur_dir_directories,
      globbed_files,
      globbed_directories,
      todo_directories,
      exclude,
    })
  }
}

async fn snapshot_glob_match<T: StoreWrapper>(
  store_wrapper: T,
  digest: Digest,
  path_globs: PreparedPathGlobs,
) -> Result<Digest, SnapshotOpsError> {
  // Split the globs into PathGlobs that can be incrementally matched against individual directory
  // components.
  let initial_match_context = UnexpandedSubdirectoryContext {
    digest,
    multiple_globs: path_globs.as_expandable_globs().into(),
  };
  let mut unexpanded_stack: IndexMap<PathBuf, UnexpandedSubdirectoryContext> =
    [(PathBuf::new(), initial_match_context)]
      .iter()
      .map(|(a, b)| (a.clone(), b.clone()))
      .collect();
  let mut partially_expanded_stack: IndexMap<PathBuf, PartiallyExpandedDirectoryContext> =
    IndexMap::new();

  // 1. Determine all the digests we need to recurse through and modify in order to respect a glob
  // which may match over multiple contiguous directory components.
  while let Some((
    prefix,
    UnexpandedSubdirectoryContext {
      digest,
      multiple_globs,
    },
  )) = unexpanded_stack.pop()
  {
    // 1a. Extract a single level of directory structure from the digest.
    let cur_dir = store_wrapper
      .load_directory(digest)
      .await?
      .ok_or_else(|| format!("directory digest {:?} was not found!", digest))?;

    // 1b. Filter files and directories by globs.
    let intermediate_globbed = IntermediateGlobbedFilesAndDirectories::from_cur_dir_and_globs(
      cur_dir,
      multiple_globs,
      prefix.clone(),
    );
    let GlobbedFilesAndDirectories {
      cur_dir_directories,
      globbed_files,
      globbed_directories,
      todo_directories,
      exclude,
    } = intermediate_globbed
      .populate_globbed_files_and_directories()
      .await?;

    // 1c. Push context structs that specify unexpanded directories onto `unexpanded_stack`.
    let dependencies: Vec<PathBuf> = todo_directories
      .keys()
      .filter_map(|subdir_path| {
        // If we ever encounter a directory *with* a remainder, we have to ensure that that
        // directory is *not* in `globbed_directories`, which are *not* subsetted at all.
        // NB: Because our goal is to *union* all of the includes, if a directory is in
        // `globbed_directories`, we can skip processing it for subsetting here!
        if globbed_directories.contains_key(subdir_path) {
          None
        } else {
          Some(prefix.join(subdir_path))
        }
      })
      .collect();

    for (subdir_name, all_path_globs) in todo_directories.into_iter() {
      let full_name = prefix.join(&subdir_name);
      let bazel_digest = cur_dir_directories
        .get(&subdir_name)
        .unwrap()
        .get_digest()
        .clone();
      let digest = to_pants_digest(bazel_digest);
      let multiple_globs = MultipleGlobs {
        include: all_path_globs,
        exclude: exclude.clone(),
      };
      unexpanded_stack.insert(
        full_name,
        UnexpandedSubdirectoryContext {
          digest,
          multiple_globs,
        },
      );
    }

    // 1d. Push a context struct onto `partially_expanded_stack` which has "dependencies" on all
    // subdirectories to be globbed in `directory_promises`. IndexMap is backed by a vector and can
    // act as a stack, so we can be sure that when we finally retrieve this context struct from the
    // stack, we will have already globbed all of its subdirectories.
    let partially_expanded_context = PartiallyExpandedDirectoryContext {
      files: globbed_files.into_iter().map(|(_, node)| node).collect(),
      known_directories: globbed_directories
        .into_iter()
        .map(|(_, node)| node)
        .collect(),
      directory_promises: dependencies,
    };
    partially_expanded_stack.insert(prefix, partially_expanded_context);
  }

  // 2. Zip back up the recursively subsetted directory protos.
  let mut completed_digests: IndexMap<PathBuf, Digest> = IndexMap::new();
  while let Some((
    prefix,
    PartiallyExpandedDirectoryContext {
      files,
      known_directories,
      directory_promises,
    },
  )) = partially_expanded_stack.pop()
  {
    let completed_nodes: Vec<remexec::DirectoryNode> = directory_promises
        .into_iter()
        .map(|dependency| {
          // NB: Note that all "dependencies" here are subdirectories that need to be globbed before
          // their parent directory can be entered into the store.
          let digest = completed_digests.get(&dependency).ok_or_else(|| {
            format!(
              "expected subdirectory to glob {:?} to be available from completed_digests {:?} -- internal error",
              &dependency, &completed_digests
            )
          })?;
          let mut fixed_directory_node = remexec::DirectoryNode::new();
          // NB: Get the name *relative* to the current directory.
          let name = dependency.strip_prefix(prefix.clone()).map_err(|e| format!("{:?}", e))?;
          fixed_directory_node.set_name(format!("{}", name.display()));
          fixed_directory_node.set_digest(to_bazel_digest(*digest));
          Ok(fixed_directory_node)
        })
        .collect::<Result<Vec<remexec::DirectoryNode>, String>>()?;

    // Create the new protobuf with the merged nodes.
    let mut final_directory = remexec::Directory::new();
    final_directory.set_files(protobuf::RepeatedField::from_vec(files));
    let all_directories: Vec<remexec::DirectoryNode> = known_directories
      .into_iter()
      .chain(completed_nodes.into_iter())
      .collect();
    final_directory.set_directories(protobuf::RepeatedField::from_vec(all_directories));
    let digest = store_wrapper.record_directory(&final_directory).await?;
    completed_digests.insert(prefix, digest);
  }

  let final_digest = completed_digests.get(&PathBuf::new()).unwrap();
  Ok(*final_digest)
}

///
/// When we perform a merge() operation, we have to perform some relatively complex logic to
/// efficiently check for duplicates. This struct encapsulates that complexity, and will recursively
/// perform the duplicate checking with `.merge_colliding_files_and_directories()`. This struct can
/// be constructed with `DigestMergeContext::from_digests()`.
///
#[derive(Debug)]
struct DigestMergeContext<T: StoreWrapper + 'static> {
  non_clashing_files: Vec<remexec::FileNode>,
  non_clashing_directories: Vec<remexec::DirectoryNode>,
  clashing_files: IndexMap<PathBuf, Vec<remexec::FileNode>>,
  clashing_directories: IndexMap<PathBuf, Vec<remexec::DirectoryNode>>,
  store: T,
}

impl<T: StoreWrapper + 'static> DigestMergeContext<T> {
  // Fetch digest contents from the store in parallel.
  async fn from_digests(digests: Vec<Digest>, store: T) -> Result<Self, SnapshotOpsError> {
    let top_level_directories: Vec<remexec::Directory> = future03::try_join_all(
      digests
        .into_iter()
        .map(|digest| store.load_directory(digest)),
    )
    .await?
    .into_iter()
    .map(|result| {
      result
        .ok_or_else(|| "could not locate digest in DigestMergeContext::from_digests()".to_string())
    })
    .collect::<Result<Vec<remexec::Directory>, String>>()?;
    Ok(Self::from_directories(top_level_directories, store))
  }

  // Flatten file and directory nodes.
  fn from_directories(top_level_directories: Vec<remexec::Directory>, store: T) -> Self {
    let (all_file_nodes, all_directory_nodes): (
      Vec<remexec::FileNode>,
      Vec<remexec::DirectoryNode>,
    ) = top_level_directories.into_iter().fold(
      (vec![], vec![]),
      |(mut all_files, mut all_directories),
       remexec::Directory {
         files, directories, ..
       }| {
        all_files.extend(files.to_vec());
        all_directories.extend(directories.to_vec());
        (all_files, all_directories)
      },
    );
    Self::from_flattened_nodes(all_file_nodes, all_directory_nodes, store)
  }

  // Determine any clashing file or directory nodes.
  fn from_flattened_nodes(
    all_file_nodes: Vec<remexec::FileNode>,
    all_directory_nodes: Vec<remexec::DirectoryNode>,
    store: T,
  ) -> Self {
    let mut files: IndexMap<PathBuf, Vec<remexec::FileNode>> = IndexMap::new();
    for file_node in all_file_nodes.into_iter() {
      let entry = files
        .entry(PathBuf::from(file_node.get_name()))
        .or_insert_with(Vec::new);
      entry.push(file_node);
    }

    let mut non_clashing_files: Vec<remexec::FileNode> = vec![];
    let mut clashing_files: IndexMap<PathBuf, Vec<remexec::FileNode>> = IndexMap::new();
    for (prefix, mut cur_clashing_files) in files.into_iter() {
      if cur_clashing_files.len() == 1 {
        non_clashing_files.push(cur_clashing_files.pop().unwrap());
      } else {
        assert!(cur_clashing_files.len() > 1);
        clashing_files.insert(prefix, cur_clashing_files);
      }
    }

    let mut directories: IndexMap<PathBuf, Vec<remexec::DirectoryNode>> = IndexMap::new();
    for directory_node in all_directory_nodes.into_iter() {
      let entry = directories
        .entry(PathBuf::from(directory_node.get_name()))
        .or_insert_with(Vec::new);
      entry.push(directory_node);
    }

    let mut non_clashing_directories: Vec<remexec::DirectoryNode> = vec![];
    let mut clashing_directories: IndexMap<PathBuf, Vec<remexec::DirectoryNode>> = IndexMap::new();
    for (prefix, mut cur_clashing_directories) in directories.into_iter() {
      if cur_clashing_directories.len() == 1 {
        non_clashing_directories.push(cur_clashing_directories.pop().unwrap());
      } else {
        assert!(cur_clashing_directories.len() > 1);
        clashing_directories.insert(prefix, cur_clashing_directories);
      }
    }

    DigestMergeContext {
      non_clashing_files,
      non_clashing_directories,
      clashing_files,
      clashing_directories,
      store,
    }
  }

  ///
  /// Generate a Directory proto which contains all files and directories in the union of all of the
  /// Digests used to create it. `behavior` dictates how colliding files will be dealt with.
  ///
  /// Note on performance: This method will recurse into any subdirectories with the same path in
  /// both digests in order to reconcile all colliding files, so it will take time proportional to
  /// the number of colliding files. A subset() operation on one of the snapshots to remove
  /// colliding files with a recursive glob before merging snapshots is cheap and will reduce the
  /// time taken for the subsequent merge operation.
  ///
  /// TODO: do the above subsetting-before-merging automatically somehow!
  ///
  async fn merge_colliding_files_and_directories(
    self,
    behavior: Arc<MergeBehavior>,
  ) -> Result<Digest, SnapshotOpsError> {
    self
      .merge_remaining_colliding_files_and_directories_recursive(behavior, PathBuf::new())
      .compat()
      .await
  }

  // NB: This function is recursive, and so cannot be directly marked async:
  //   https://rust-lang.github.io/async-book/07_workarounds/05_recursion.html
  fn merge_remaining_colliding_files_and_directories_recursive(
    self,
    behavior: Arc<MergeBehavior>,
    root: PathBuf,
  ) -> BoxFuture<Digest, SnapshotOpsError> {
    let DigestMergeContext {
      mut non_clashing_files,
      mut non_clashing_directories,
      clashing_files,
      clashing_directories,
      store,
    } = self;

    // Get distinct files, and error out if there is a conflict.
    for (prefix, cur_clashing_files) in clashing_files.into_iter() {
      let distinct_files: IndexMap<Digest, remexec::FileNode> = cur_clashing_files
        .into_iter()
        .map(|file_node| {
          let bazel_digest = file_node.get_digest();
          let fp = Fingerprint::from_hex_string(bazel_digest.get_hash()).unwrap();
          let digest = Digest(fp, bazel_digest.get_size_bytes() as usize);
          (digest, file_node)
        })
        .collect();
      if distinct_files.len() > 1 {
        let full_file_path = root.join(&prefix);
        if !behavior.is_allowed_duplicate(&full_file_path) {
          return future::err(SnapshotOpsError::DigestMergeFailure(format!(
            "got more than one unique file {:?} at path {:?}",
            distinct_files, full_file_path
          )))
          .to_boxed();
        }
      }
      let distinct_files: Vec<_> = distinct_files
        .into_iter()
        .map(|(_, file_node)| file_node)
        .collect();
      non_clashing_files.push(distinct_files.get(0).unwrap().clone());
    }

    let store2 = store.clone();
    // Get distinct directories, and recurse when there is a conflict.
    let merged_directory_nodes: BoxFuture<Vec<remexec::DirectoryNode>, SnapshotOpsError> =
      future::join_all(clashing_directories.into_iter().map(
        move |(prefix, cur_clashing_directories)| {
          let mut distinct_directories: IndexSet<Digest> = cur_clashing_directories
            .into_iter()
            .map(|directory_node| {
              let bazel_digest = directory_node.get_digest();
              let fp = Fingerprint::from_hex_string(bazel_digest.get_hash()).unwrap();
              Digest(fp, bazel_digest.get_size_bytes() as usize)
            })
            .collect();

          let merged_directory_digest: BoxFuture<Digest, _> = if distinct_directories.len() == 1 {
            future::ok(distinct_directories.pop().unwrap()).to_boxed()
          } else {
            assert!(distinct_directories.len() > 1);
            let digests: Vec<Digest> = distinct_directories.into_iter().collect();
            let store = store.clone();
            let sub_context = Box::pin(async move { Self::from_digests(digests, store).await })
              .compat()
              .to_boxed();
            let behavior = behavior.clone();
            let subdir_root = root.join(&prefix);
            sub_context
              .and_then(move |sub_context| {
                sub_context
                  .merge_remaining_colliding_files_and_directories_recursive(behavior, subdir_root)
              })
              .to_boxed()
          };

          let mut fixed_directory_node = remexec::DirectoryNode::new();
          fixed_directory_node.set_name(format!("{}", prefix.display()));

          merged_directory_digest
            .map(|merged_directory_digest| {
              let bazel_digest = to_bazel_digest(merged_directory_digest);
              fixed_directory_node.set_digest(bazel_digest);
              fixed_directory_node
            })
            .to_boxed()
        },
      ))
      .to_boxed();

    merged_directory_nodes
      .and_then(|merged_directory_nodes| {
        Box::pin(async move {
          // Add the newly merged directory nodes to the non-clashing nodes.
          non_clashing_directories.extend(merged_directory_nodes);

          // Sort the files and directories by path.
          non_clashing_files.sort_by_key(|file_node| file_node.get_name().to_string());
          non_clashing_directories
            .sort_by_key(|directory_node| directory_node.get_name().to_string());

          // Validate that no "non-clashing" file clashes with any "non-clashing" directory.
          let clashing_file_directory_names: IndexMap<&str, &remexec::FileNode> =
            non_clashing_files
              .iter()
              .map(|file_node| (file_node.get_name(), file_node))
              .collect();
          for non_clashing_directory_node in non_clashing_directories.iter() {
            if let Some(file_node) =
              clashing_file_directory_names.get(non_clashing_directory_node.get_name())
            {
              return Err(SnapshotOpsError::DigestMergeFailure(format!(
                "file name {} for node {:?} clashes with directory node {:?}",
                non_clashing_directory_node.get_name(),
                file_node,
                non_clashing_directory_node
              )));
            }
          }

          // Create the new protobuf with the merged nodes.
          let mut final_directory = remexec::Directory::new();
          final_directory.set_files(protobuf::RepeatedField::from_vec(non_clashing_files));
          final_directory
            .set_directories(protobuf::RepeatedField::from_vec(non_clashing_directories));
          let digest = store2.record_directory(&final_directory).await?;
          Ok(digest)
        })
        .compat()
        .to_boxed()
      })
      .to_boxed()
  }
}

///
/// High-level operations to manipulate and merge `Digest`s.
///
/// These methods take care to avoid redundant work when traversing Directory protos. Prefer to use
/// these primitives to compose any higher-level snapshot operations elsewhere in the codebase.
///
#[async_trait]
pub trait SnapshotOps: StoreWrapper + 'static {
  ///
  /// Given N Snapshots, returns a new Snapshot that merges them.
  ///
  async fn merge(
    &self,
    digests: Vec<Digest>,
    behavior: MergeBehavior,
  ) -> Result<Digest, SnapshotOpsError> {
    let merge_context = DigestMergeContext::from_digests(digests, self.clone()).await?;
    merge_context
      .merge_colliding_files_and_directories(Arc::new(behavior))
      .await
  }

  async fn add_prefix(
    &self,
    mut digest: Digest,
    prefix: RelativePath,
  ) -> Result<Digest, SnapshotOpsError> {
    let prefix: PathBuf = prefix.into();
    let mut prefix_iter = prefix.iter();
    while let Some(parent) = prefix_iter.next_back() {
      let mut dir_node = remexec::DirectoryNode::new();
      dir_node.set_name(osstring_as_utf8(parent.to_os_string())?);
      dir_node.set_digest((&digest).into());

      let mut out_dir = remexec::Directory::new();
      out_dir.set_directories(protobuf::RepeatedField::from_vec(vec![dir_node]));

      digest = self.record_directory(&out_dir).await?;
    }

    Ok(digest)
  }

  async fn strip_prefix(
    &self,
    root_digest: Digest,
    prefix: RelativePath,
  ) -> Result<Digest, SnapshotOpsError> {
    let mut dir = self.load_directory_or_err(root_digest).await?;
    let mut already_stripped = PathBuf::new();
    let mut prefix: PathBuf = prefix.into();
    loop {
      let has_already_stripped_any = already_stripped.components().next().is_some();

      let mut components = prefix.components();
      let component_to_strip = components.next();
      if let Some(component_to_strip) = component_to_strip {
        let remaining_prefix = components.collect();
        let component_to_strip_str = component_to_strip.as_os_str().to_string_lossy();

        let mut saw_matching_dir = false;
        let extra_directories: Vec<_> = dir
          .get_directories()
          .iter()
          .filter_map(|subdir| {
            if subdir.get_name() == component_to_strip_str {
              saw_matching_dir = true;
              None
            } else {
              Some(subdir.get_name().to_owned())
            }
          })
          .collect();
        let files: Vec<_> = dir
          .get_files()
          .iter()
          .map(|file| file.get_name().to_owned())
          .collect();

        match (saw_matching_dir, extra_directories.is_empty() && files.is_empty()) {
          (false, true) => {
            dir = remexec::Directory::new();
            break;
          },
          (false, false) => {
            // Prefer "No subdirectory found" error to "had extra files" error.
            return Err(format!(
              "Cannot strip prefix {} from root directory {:?} - {}directory{} didn't contain a directory named {}{}",
              already_stripped.join(&prefix).display(),
              root_digest,
              if has_already_stripped_any { "sub" } else { "root " },
              if has_already_stripped_any { format!(" {}", already_stripped.display()) } else { String::new() },
              component_to_strip_str,
              if !extra_directories.is_empty() || !files.is_empty() { format!(" but did contain {}", Snapshot::directories_and_files(&extra_directories, &files)) } else { String::new() },
            ).into())
          },
          (true, false) => {
            return Err(format!(
              "Cannot strip prefix {} from root directory {:?} - {}directory{} contained non-matching {}",
              already_stripped.join(&prefix).display(),
              root_digest,
              if has_already_stripped_any { "sub" } else { "root " },
              if has_already_stripped_any { format!(" {}", already_stripped.display()) } else { String::new() },
              Snapshot::directories_and_files(&extra_directories, &files),
            ).into())
          },
          (true, true) => {
            // Must be 0th index, because we've checked that we saw a matching directory, and no
            // others.
            let digest = to_pants_digest(
              dir.get_directories()[0]
                .get_digest()
                .clone());
            already_stripped = already_stripped.join(component_to_strip);
            dir = self.load_directory_or_err(digest).await?;
            prefix = remaining_prefix;
          }
        }
      } else {
        break;
      }
    }

    Ok(self.record_directory(&dir).await?)
  }

  async fn subset(&self, digest: Digest, params: SubsetParams) -> Result<Digest, SnapshotOpsError> {
    let SubsetParams { globs } = params;
    snapshot_glob_match(self.clone(), digest, globs).await
  }

  async fn create_empty_dir(&self, path: RelativePath) -> Result<Digest, SnapshotOpsError> {
    self.add_prefix(EMPTY_DIGEST, path).await
  }
}

impl<T: StoreWrapper + 'static> SnapshotOps for T {}

struct PartiallyExpandedDirectoryContext {
  pub files: Vec<remexec::FileNode>,
  pub known_directories: Vec<remexec::DirectoryNode>,
  pub directory_promises: Vec<PathBuf>,
}

#[derive(Clone, Debug)]
enum RestrictedPathGlob {
  Wildcard {
    wildcard: Pattern,
  },
  DirWildcard {
    wildcard: Pattern,
    remainder: Vec<Pattern>,
  },
}

impl From<PathGlob> for RestrictedPathGlob {
  fn from(glob: PathGlob) -> Self {
    match glob {
      PathGlob::Wildcard { wildcard, .. } => RestrictedPathGlob::Wildcard { wildcard },
      PathGlob::DirWildcard {
        wildcard,
        remainder,
        ..
      } => RestrictedPathGlob::DirWildcard {
        wildcard,
        remainder,
      },
    }
  }
}

fn to_bazel_digest(digest: Digest) -> remexec::Digest {
  let mut bazel_digest = remexec::Digest::new();
  bazel_digest.set_hash(digest.0.to_hex());
  bazel_digest.set_size_bytes(digest.1 as i64);
  bazel_digest
}

fn to_pants_digest(bazel_digest: remexec::Digest) -> Digest {
  let fp = Fingerprint::from_hex_string(bazel_digest.get_hash())
    .expect("failed to coerce bazel to pants digest");
  let size_bytes = bazel_digest.get_size_bytes() as usize;
  Digest(fp, size_bytes)
}

#[derive(Clone)]
struct MultipleGlobs {
  pub include: Vec<RestrictedPathGlob>,
  pub exclude: Arc<GitignoreStyleExcludes>,
}

impl From<ExpandablePathGlobs> for MultipleGlobs {
  fn from(globs: ExpandablePathGlobs) -> Self {
    let ExpandablePathGlobs { include, exclude } = globs;
    MultipleGlobs {
      include: include.into_iter().map(|x| x.into()).collect(),
      exclude,
    }
  }
}

#[derive(Clone)]
struct UnexpandedSubdirectoryContext {
  pub digest: Digest,
  pub multiple_globs: MultipleGlobs,
}
