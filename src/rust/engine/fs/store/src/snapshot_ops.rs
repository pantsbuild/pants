// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::{snapshot::osstring_as_utf8, Snapshot};

use async_trait::async_trait;
use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use bytes::BytesMut;
use fs::{
  ExpandablePathGlobs, GitignoreStyleExcludes, PathGlob, PreparedPathGlobs, RelativePath,
  DOUBLE_STAR_GLOB, SINGLE_STAR_GLOB,
};
use futures::future::{self as future03, FutureExt, TryFutureExt};
use glob::Pattern;
use hashing::{Digest, Fingerprint, EMPTY_DIGEST};
use indexmap::{self, IndexMap};
use itertools::Itertools;
use log::log_enabled;

use std::collections::HashSet;
use std::convert::{From, TryInto};
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
/// A trait that encapsulates some of the features of a Store, with nicer type signatures. This is
/// used to implement the `SnapshotOps` trait.
///
#[async_trait]
pub trait StoreWrapper: Clone + Send + Sync {
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
/// Given Digest(s) representing Directory instances, merge them recursively into a single
/// output Directory Digest.
///
/// If a file is present with the same name and contents multiple times, it will appear once.
/// If a file is present with the same name, but different contents, an error will be returned.
///
async fn merge_directories<T: StoreWrapper + 'static>(
  store_wrapper: T,
  dir_digests: Vec<Digest>,
) -> Result<Digest, String> {
  merge_directories_recursive(store_wrapper, PathBuf::new(), dir_digests).await
}

// NB: This function is recursive, and so cannot be directly marked async:
//   https://rust-lang.github.io/async-book/07_workarounds/05_recursion.html
fn merge_directories_recursive<T: StoreWrapper + 'static>(
  store_wrapper: T,
  parent_path: PathBuf,
  dir_digests: Vec<Digest>,
) -> future03::BoxFuture<'static, Result<Digest, String>> {
  async move {
    if dir_digests.is_empty() {
      return Ok(EMPTY_DIGEST);
    } else if dir_digests.len() == 1 {
      let mut dir_digests = dir_digests;
      return Ok(dir_digests.pop().unwrap());
    }

    let directories = future03::try_join_all(
      dir_digests
        .into_iter()
        .map(|digest| {
          store_wrapper
            .load_directory(digest)
            .and_then(move |maybe_directory| {
              future03::ready(
                maybe_directory
                  .ok_or_else(|| format!("Digest {:?} did not exist in the Store.", digest)),
              )
            })
        })
        .collect::<Vec<_>>(),
    )
    .await?;

    let mut out_dir = remexec::Directory::default();

    // Merge FileNodes.
    let file_nodes = Iterator::flatten(directories.iter().map(|directory| directory.files.iter()))
      .sorted_by(|a, b| a.name.cmp(&b.name));

    out_dir.files = file_nodes.into_iter().dedup().cloned().collect();

    // Group and recurse for DirectoryNodes.
    let child_directory_futures = {
      let store = store_wrapper.clone();
      let parent_path = parent_path.clone();
      let mut directories_to_merge = Iterator::flatten(
        directories
          .iter()
          .map(|directory| directory.directories.iter()),
      )
      .collect::<Vec<_>>();
      directories_to_merge.sort_by(|a, b| a.name.cmp(&b.name));
      directories_to_merge
        .into_iter()
        .group_by(|d| d.name.clone())
        .into_iter()
        .map(move |(child_name, group)| {
          let store = store.clone();
          let digests: Vec<Digest> = group
            .map(|d| to_pants_digest_opt(d.digest.clone()))
            .collect();
          let child_path = parent_path.join(&child_name);
          async move {
            let merged_digest = merge_directories_recursive(store, child_path, digests).await?;
            let child_dir = remexec::DirectoryNode {
              name: child_name,
              digest: Some(merged_digest.into()),
            };
            let res: Result<_, String> = Ok(child_dir);
            res
          }
        })
        .collect::<Vec<_>>()
    };

    let child_directories = future03::try_join_all(child_directory_futures).await?;

    out_dir.directories = child_directories;

    error_for_collisions(&store_wrapper, &parent_path, &out_dir).await?;
    store_wrapper.record_directory(&out_dir).await
  }
  .boxed()
}

///
/// Ensure merge is unique and fail with debugging info if not.
///
async fn error_for_collisions<T: StoreWrapper + 'static>(
  store_wrapper: &T,
  parent_path: &Path,
  dir: &remexec::Directory,
) -> Result<(), String> {
  // Attempt to cheaply check for collisions to bail out early if there aren't any.
  let unique_count = dir
    .files
    .iter()
    .map(|n| n.name.clone())
    .chain(dir.directories.iter().map(|n| n.name.clone()))
    .collect::<HashSet<_>>()
    .len();
  if unique_count == (dir.files.len() + dir.directories.len()) {
    return Ok(());
  }

  let file_details_by_name = dir
    .files
    .iter()
    .map(|file_node| async move {
      let digest: Digest = file_node
        .digest
        .as_ref()
        .map(|d| d.try_into())
        .unwrap_or(Ok(EMPTY_DIGEST))?;
      let header = format!("file digest={} size={}:\n\n", digest.0, digest.1);

      let contents = store_wrapper
        .load_file_bytes_with(digest, |bytes| {
          const MAX_LENGTH: usize = 1024;
          let content_length = bytes.len();
          let mut bytes = BytesMut::from(&bytes[0..std::cmp::min(content_length, MAX_LENGTH)]);
          if content_length > MAX_LENGTH && !log_enabled!(log::Level::Debug) {
            bytes.extend_from_slice(
              format!(
                "\n... TRUNCATED contents from {}B to {}B \
                  (Pass -ldebug to see full contents).",
                content_length, MAX_LENGTH
              )
              .as_bytes(),
            );
          }
          String::from_utf8_lossy(bytes.to_vec().as_slice()).to_string()
        })
        .await?
        .unwrap_or_else(|| "<could not load contents>".to_string());
      let detail = format!("{}{}", header, contents);
      let res: Result<_, String> = Ok((file_node.name.clone(), detail));
      res
    })
    .map(|f| f.boxed());
  let dir_details_by_name = dir
    .directories
    .iter()
    .map(|dir_node| async move {
      // TODO(tonic): Avoid using .unwrap here!
      let detail = format!(
        "dir digest={} size={}:\n\n",
        dir_node.digest.as_ref().unwrap().hash,
        dir_node.digest.as_ref().unwrap().size_bytes
      );
      let res: Result<_, String> = Ok((dir_node.name.clone(), detail));
      res
    })
    .map(|f| f.boxed());

  let duplicate_details = async move {
    let details_by_name = future03::try_join_all(
      file_details_by_name
        .chain(dir_details_by_name)
        .collect::<Vec<_>>(),
    )
    .await?
    .into_iter()
    .into_group_map();

    let enumerated_details =
      std::iter::Iterator::flatten(details_by_name.iter().filter_map(|(name, details)| {
        if details.len() > 1 {
          Some(
            details
              .iter()
              .enumerate()
              .map(move |(index, detail)| format!("`{}`: {}.) {}", name, index + 1, detail)),
          )
        } else {
          None
        }
      }))
      .collect();

    let res: Result<Vec<String>, String> = Ok(enumerated_details);
    res
  }
  .await
  .unwrap_or_else(|err| vec![format!("Failed to load contents for comparison: {}", err)]);

  Err(format!(
    "Can only merge Directories with no duplicates, but found {} duplicate entries in {}:\
      \n\n{}",
    duplicate_details.len(),
    parent_path.display(),
    duplicate_details.join("\n\n")
  ))
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
      .files
      .into_iter()
      .map(|file_node| (PathBuf::from(file_node.name.clone()), file_node))
      .collect();
    let cur_dir_directories: IndexMap<PathBuf, remexec::DirectoryNode> = cur_dir
      .directories
      .into_iter()
      .map(|directory_node| (PathBuf::from(directory_node.name.clone()), directory_node))
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
              empty_node.digest = Some(to_bazel_digest(EMPTY_DIGEST));
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
        .digest
        .clone();
      let digest = bazel_digest.map(to_pants_digest).unwrap_or(EMPTY_DIGEST);
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
          // NB: Get the name *relative* to the current directory.
          let name = dependency.strip_prefix(prefix.clone()).map_err(|e| format!("{:?}", e))?;
          let fixed_directory_node = remexec::DirectoryNode {
            name: format!("{}", name.display()),
            digest: Some(to_bazel_digest(*digest)),
          };
          Ok(fixed_directory_node)
        })
        .collect::<Result<Vec<remexec::DirectoryNode>, String>>()?;

    // Create the new protobuf with the merged nodes.
    let all_directories: Vec<remexec::DirectoryNode> = known_directories
      .into_iter()
      .chain(completed_nodes.into_iter())
      .collect();
    let final_directory = remexec::Directory {
      files,
      directories: all_directories,
      ..remexec::Directory::default()
    };
    let digest = store_wrapper.record_directory(&final_directory).await?;
    completed_digests.insert(prefix, digest);
  }

  let final_digest = completed_digests.get(&PathBuf::new()).unwrap();
  Ok(*final_digest)
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
  async fn merge(&self, digests: Vec<Digest>) -> Result<Digest, SnapshotOpsError> {
    merge_directories(self.clone(), digests)
      .await
      .map_err(|e| e.into())
  }

  async fn add_prefix(
    &self,
    mut digest: Digest,
    prefix: RelativePath,
  ) -> Result<Digest, SnapshotOpsError> {
    let prefix: PathBuf = prefix.into();
    let mut prefix_iter = prefix.iter();
    while let Some(parent) = prefix_iter.next_back() {
      let dir_node = remexec::DirectoryNode {
        name: osstring_as_utf8(parent.to_os_string())?,
        digest: Some((&digest).into()),
      };

      let out_dir = remexec::Directory {
        directories: vec![dir_node],
        ..remexec::Directory::default()
      };

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
          .directories
          .iter()
          .filter_map(|subdir| {
            if subdir.name == component_to_strip_str {
              saw_matching_dir = true;
              None
            } else {
              Some(subdir.name.to_owned())
            }
          })
          .collect();
        let files: Vec<_> = dir.files.iter().map(|file| file.name.to_owned()).collect();

        match (saw_matching_dir, extra_directories.is_empty() && files.is_empty()) {
          (false, true) => {
            dir = remexec::Directory::default();
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
            // TODO(tonic): Match safely to access first directory?
            let digest = to_pants_digest(
              dir.directories[0]
                .digest
                .as_ref()
                .unwrap()
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

// TODO(tonic): Replace uses of this method with `.into` or equivalent.
fn to_bazel_digest(digest: Digest) -> remexec::Digest {
  remexec::Digest {
    hash: digest.0.to_hex(),
    size_bytes: digest.1 as i64,
  }
}

// TODO(tonic): Replace uses of this method with `.into` or equivalent.
fn to_pants_digest(bazel_digest: remexec::Digest) -> Digest {
  let fp = Fingerprint::from_hex_string(&bazel_digest.hash)
    .expect("failed to coerce bazel to pants digest");
  let size_bytes = bazel_digest.size_bytes as usize;
  Digest(fp, size_bytes)
}

// TODO(tonic): Replace use of this method with `.into` or equivalent.
fn to_pants_digest_opt(bazel_digest: Option<remexec::Digest>) -> Digest {
  match bazel_digest {
    Some(d) => to_pants_digest(d),
    None => EMPTY_DIGEST,
  }
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
