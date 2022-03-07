// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::convert::From;
use std::iter::Iterator;
use std::path::PathBuf;
use std::sync::Arc;

use async_trait::async_trait;
use bytes::BytesMut;
use fs::{
  directory, DigestTrie, DirectoryDigest, ExpandablePathGlobs, GitignoreStyleExcludes, PathGlob,
  PreparedPathGlobs, RelativePath, DOUBLE_STAR_GLOB, EMPTY_DIRECTORY_DIGEST, SINGLE_STAR_GLOB,
};
use futures::future::{self, FutureExt};
use glob::Pattern;
use hashing::{Digest, EMPTY_DIGEST};
use indexmap::{self, IndexMap};
use itertools::Itertools;
use log::log_enabled;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::require_digest;

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
/// Given Digest(s) representing Directory instances, merge them recursively into a single
/// output Directory Digest.
///
/// If a file is present with the same name and contents multiple times, it will appear once.
/// If a file is present with the same name, but different contents, an error will be returned.
///
async fn merge_directories<T: SnapshotOps + 'static>(
  store: T,
  dir_digests: Vec<DirectoryDigest>,
) -> Result<DirectoryDigest, String> {
  let trees = future::try_join_all(
    dir_digests
      .into_iter()
      .map(|dd| store.load_digest_trie(dd))
      .collect::<Vec<_>>(),
  )
  .await?;

  let tree = match DigestTrie::merge(trees) {
    Ok(tree) => tree,
    Err(merge_error) => {
      // TODO: Use https://doc.rust-lang.org/nightly/std/result/enum.Result.html#method.into_ok_or_err
      // once it is stable.
      let err_string = match render_merge_error(&store, merge_error).await {
        Ok(e) | Err(e) => e,
      };
      return Err(err_string);
    }
  };

  // TODO: Remove persistence as the final step of #13112.
  let directory_digest = store.record_digest_trie(tree.clone()).await?;

  Ok(directory_digest)
}

///
/// Render a directory::MergeError (or fail with a less specific error if some content cannot be
/// loaded).
///
async fn render_merge_error<T: SnapshotOps + 'static>(
  store: &T,
  err: directory::MergeError,
) -> Result<String, String> {
  let directory::MergeError::Duplicates {
    parent_path,
    files,
    directories,
  } = err;
  let file_details_by_name = files
    .iter()
    .map(|file| async move {
      let digest: Digest = file.digest();
      let header = format!(
        "file digest={} size={}:\n\n",
        digest.hash, digest.size_bytes
      );

      let contents = store
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
      let res: Result<_, String> = Ok((file.name().to_owned(), detail));
      res
    })
    .map(|f| f.boxed());
  let dir_details_by_name = directories
    .iter()
    .map(|dir| async move {
      let digest = dir.digest();
      let detail = format!("dir digest={} size={}:\n\n", digest.hash, digest.size_bytes);
      let res: Result<_, String> = Ok((dir.name().to_owned(), detail));
      res
    })
    .map(|f| f.boxed());

  let duplicate_details = async move {
    let details_by_name = future::try_join_all(
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

  Ok(format!(
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

      // TODO(#12462): Remove allow once upstream resolves https://github.com/rust-lang/rust-clippy/issues/6066.
      #[allow(clippy::needless_collect)]
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

      // TODO(#12462): Remove allow once upstream resolves https://github.com/rust-lang/rust-clippy/issues/6066.
      #[allow(clippy::needless_collect)]
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
        // `Vfs` instances!
        match &path_glob {
          RestrictedPathGlob::Wildcard { wildcard } => {
            // NB: We interpret globs such that the *only* way to have a glob match the contents of
            // a whole directory is to end in '/**' or '/**/*'.

            if exclude.maybe_is_parent_of_ignored_path(&directory_path) {
              // Leave this directory in todo_directories, so we process ignore patterns correctly.
              continue;
            }

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
              let is_short_circuit_pattern: bool = match &remainder[..] {
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
              if is_short_circuit_pattern
                && !exclude.maybe_is_parent_of_ignored_path(&directory_path)
              {
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

async fn snapshot_glob_match<T: SnapshotOps + 'static>(
  store: T,
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
    let cur_dir = store
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
      // TODO(tonic): Use require_digest here by figure out how to properly return the error.
      let digest = require_digest(bazel_digest.as_ref())
        .map_err(|msg| SnapshotOpsError::String(format!("Failed to parse digest: {}", msg)))?;
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
    let digest = store.record_directory(&final_directory).await?;
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
pub trait SnapshotOps: Clone + Send + Sync + 'static {
  async fn load_file_bytes_with<T: Send + 'static, F: Fn(&[u8]) -> T + Send + Sync + 'static>(
    &self,
    digest: Digest,
    f: F,
  ) -> Result<Option<T>, String>;

  async fn load_digest_trie(&self, digest: DirectoryDigest) -> Result<DigestTrie, String>;
  async fn load_directory(&self, digest: Digest) -> Result<Option<remexec::Directory>, String>;
  async fn load_directory_or_err(&self, digest: Digest) -> Result<remexec::Directory, String>;

  async fn record_digest_trie(&self, tree: DigestTrie) -> Result<DirectoryDigest, String>;
  async fn record_directory(&self, directory: &remexec::Directory) -> Result<Digest, String>;

  ///
  /// Given N Snapshots, returns a new Snapshot that merges them.
  ///
  async fn merge(
    &self,
    digests: Vec<DirectoryDigest>,
  ) -> Result<DirectoryDigest, SnapshotOpsError> {
    merge_directories(self.clone(), digests).await.map_err(|e| {
      let e: SnapshotOpsError = e.into();
      e
    })
  }

  async fn add_prefix(
    &self,
    digest: DirectoryDigest,
    prefix: &RelativePath,
  ) -> Result<DirectoryDigest, SnapshotOpsError> {
    let tree = self.load_digest_trie(digest).await?.add_prefix(prefix)?;
    // TODO: Remove persistence as the final step of #13112.
    Ok(self.record_digest_trie(tree).await?)
  }

  async fn strip_prefix(
    &self,
    digest: DirectoryDigest,
    prefix: &RelativePath,
  ) -> Result<DirectoryDigest, SnapshotOpsError> {
    let tree = self.load_digest_trie(digest).await?.remove_prefix(prefix)?;
    // TODO: Remove persistence as the final step of #13112.
    Ok(self.record_digest_trie(tree).await?)
  }

  async fn subset(&self, digest: Digest, params: SubsetParams) -> Result<Digest, SnapshotOpsError> {
    let SubsetParams { globs } = params;
    snapshot_glob_match(self.clone(), digest, globs).await
  }

  async fn create_empty_dir(
    &self,
    path: &RelativePath,
  ) -> Result<DirectoryDigest, SnapshotOpsError> {
    self.add_prefix(EMPTY_DIRECTORY_DIGEST.clone(), path).await
  }
}

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
    hash: digest.hash.to_hex(),
    size_bytes: digest.size_bytes as i64,
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
