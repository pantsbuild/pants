// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::ffi::OsString;
use std::fmt;
use std::iter::Iterator;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use fs::{
  Dir, File, GitignoreStyleExcludes, GlobMatching, PathStat, PosixFS, PreparedPathGlobs,
  SymlinkBehavior,
};
use futures::future;
use futures::FutureExt;
use hashing::{Digest, EMPTY_DIGEST};
use itertools::Itertools;

use crate::Store;

#[derive(Eq, Hash, PartialEq)]
pub struct Snapshot {
  pub digest: Digest,
  pub path_stats: Vec<PathStat>,
}

impl Snapshot {
  pub fn empty() -> Snapshot {
    Snapshot {
      digest: EMPTY_DIGEST,
      path_stats: vec![],
    }
  }

  pub async fn from_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone + Send + 'static,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: S,
    path_stats: Vec<PathStat>,
  ) -> Result<Snapshot, String> {
    let path_stats = PathStat::normalize_path_stats(path_stats)?;
    let digest =
      Snapshot::ingest_directory_from_sorted_path_stats(store, file_digester, &path_stats).await?;
    Ok(Snapshot { digest, path_stats })
  }

  pub async fn from_digest(store: Store, digest: Digest) -> Result<Snapshot, String> {
    let path_stats_per_directory = store
      .walk(digest, |_, path_so_far, _, directory| {
        let mut path_stats = Vec::new();
        path_stats.extend(directory.directories.iter().map(move |dir_node| {
          let path = path_so_far.join(dir_node.name.clone());
          PathStat::dir(path.clone(), Dir(path))
        }));
        path_stats.extend(directory.files.iter().map(move |file_node| {
          let path = path_so_far.join(file_node.name.clone());
          PathStat::file(
            path.clone(),
            File {
              path,
              is_executable: file_node.is_executable,
            },
          )
        }));
        future::ok(path_stats).boxed()
      })
      .await?;

    let path_stats = Iterator::flatten(path_stats_per_directory.into_iter().map(Vec::into_iter))
      .collect::<Vec<_>>();
    // The path stats should already be normalized; this is an assertion that they're valid.
    let path_stats = PathStat::normalize_path_stats(path_stats)?;
    Ok(Snapshot { digest, path_stats })
  }

  pub async fn digest_from_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone + Send + 'static,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: S,
    path_stats: Vec<PathStat>,
  ) -> Result<Digest, String> {
    let path_stats = PathStat::normalize_path_stats(path_stats)?;
    Snapshot::ingest_directory_from_sorted_path_stats(store, file_digester, &path_stats).await
  }

  // NB: This function is recursive, and so cannot be directly marked async:
  //   https://rust-lang.github.io/async-book/07_workarounds/05_recursion.html
  fn ingest_directory_from_sorted_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone + Send + 'static,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: S,
    path_stats: &[PathStat],
  ) -> future::BoxFuture<'static, Result<Digest, String>> {
    let mut file_futures = Vec::new();
    let mut dir_futures: Vec<future::BoxFuture<'static, Result<remexec::DirectoryNode, String>>> =
      Vec::new();

    for (first_component, group) in &path_stats
      .iter()
      .cloned()
      .group_by(|s| s.path().components().next().unwrap().as_os_str().to_owned())
    {
      let mut path_group: Vec<PathStat> = group.collect();
      if path_group.len() == 1 && path_group[0].path().components().count() == 1 {
        // Exactly one entry with exactly one component indicates either a file in this directory,
        // or an empty directory.
        // If the child is a non-empty directory, or a file therein, there must be multiple
        // PathStats with that prefix component, and we will handle that in the recursive
        // save_directory call.

        match path_group.pop().unwrap() {
          PathStat::File { ref stat, .. } => {
            let is_executable = stat.is_executable;
            let stat = stat.clone();
            let file_digester = file_digester.clone();
            file_futures.push(async move {
              let digest_future = file_digester.store_by_digest(stat);
              let digest = digest_future.await.map_err(|e| format!("{:?}", e))?;

              let file_node = remexec::FileNode {
                name: osstring_as_utf8(first_component)?,
                digest: Some((&digest).into()),
                is_executable,
                ..remexec::FileNode::default()
              };
              Ok(file_node)
            });
          }
          PathStat::Dir { .. } => {
            let store = store.clone();
            // Because there are no children of this Dir, it must be empty.
            dir_futures.push(Box::pin(async move {
              let digest = store
                .record_directory(&remexec::Directory::default(), true)
                .await?;
              let directory_node = remexec::DirectoryNode {
                name: osstring_as_utf8(first_component).unwrap(),
                digest: Some((&digest).into()),
              };
              Ok(directory_node)
            }));
          }
        }
      } else {
        let store = store.clone();
        let file_digester = file_digester.clone();
        dir_futures.push(Box::pin(async move {
          // TODO: Memoize this in the graph
          let digest = Snapshot::ingest_directory_from_sorted_path_stats(
            store,
            file_digester,
            &paths_of_child_dir(path_group),
          )
          .await?;

          let dir_node = remexec::DirectoryNode {
            name: osstring_as_utf8(first_component)?,
            digest: Some(digest.into()),
          };
          Ok(dir_node)
        }));
      }
    }

    async move {
      let (dirs, files) = future::try_join(
        future::try_join_all(dir_futures),
        future::try_join_all(file_futures),
      )
      .await?;

      let directory = remexec::Directory {
        directories: dirs,
        files,
        ..remexec::Directory::default()
      };
      store.record_directory(&directory, true).await
    }
    .boxed()
  }

  pub fn directories_and_files(directories: &[String], files: &[String]) -> String {
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

  pub async fn get_directory_or_err(
    store: Store,
    digest: Digest,
  ) -> Result<remexec::Directory, String> {
    let maybe_dir = store.load_directory(digest).await?;
    maybe_dir
      .map(|(dir, _metadata)| dir)
      .ok_or_else(|| format!("{:?} was not known", digest))
  }

  ///
  /// Capture a Snapshot of a presumed-immutable piece of the filesystem.
  ///
  /// Note that we don't use a Graph here, and don't cache any intermediate steps, we just place
  /// the resultant Snapshot into the store and return it. This is important, because we're reading
  /// things from arbitrary filepaths which we don't want to cache in the graph, as we don't watch
  /// them for changes. Because we're not caching things, we can safely configure the virtual
  /// filesystem to be symlink-oblivious.
  ///
  /// If the `digest_hint` is given, first attempt to load the Snapshot using that Digest, and only
  /// fall back to actually walking the filesystem if we don't have it (either due to garbage
  /// collection or Digest-oblivious legacy caching).
  ///
  pub async fn capture_snapshot_from_arbitrary_root<P: AsRef<Path> + Send + 'static>(
    store: Store,
    executor: task_executor::Executor,
    root_path: P,
    path_globs: PreparedPathGlobs,
    digest_hint: Option<Digest>,
  ) -> Result<Snapshot, String> {
    // Attempt to use the digest hint to load a Snapshot without expanding the globs; otherwise,
    // expand the globs to capture a Snapshot.
    let snapshot_result = if let Some(digest) = digest_hint {
      Snapshot::from_digest(store.clone(), digest).await
    } else {
      Err("No digest hint provided.".to_string())
    };

    if let Ok(snapshot) = snapshot_result {
      Ok(snapshot)
    } else {
      let posix_fs = Arc::new(PosixFS::new_with_symlink_behavior(
        root_path,
        GitignoreStyleExcludes::create(vec![])?,
        executor,
        SymlinkBehavior::Oblivious,
      )?);

      let path_stats = posix_fs
        .expand_globs(path_globs)
        .await
        .map_err(|err| format!("Error expanding globs: {}", err))?;
      Snapshot::from_path_stats(
        store.clone(),
        OneOffStoreFileByDigest::new(store, posix_fs),
        path_stats,
      )
      .await
    }
  }
}

impl fmt::Debug for Snapshot {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(
      f,
      "Snapshot(digest={:?}, entries={})",
      self.digest,
      self.path_stats.len()
    )
  }
}

fn paths_of_child_dir(paths: Vec<PathStat>) -> Vec<PathStat> {
  paths
    .into_iter()
    .filter_map(|s| {
      if s.path().components().count() == 1 {
        return None;
      }
      Some(match s {
        PathStat::File { path, stat } => PathStat::File {
          path: path.iter().skip(1).collect(),
          stat,
        },
        PathStat::Dir { path, stat } => PathStat::Dir {
          path: path.iter().skip(1).collect(),
          stat,
        },
      })
    })
    .collect()
}

pub fn osstring_as_utf8(path: OsString) -> Result<String, String> {
  path
    .into_string()
    .map_err(|p| format!("{:?}'s file_name is not representable in UTF8", p))
}

// StoreFileByDigest allows a File to be saved to an underlying Store, in such a way that it can be
// looked up by the Digest produced by the store_by_digest method.
// It is a separate trait so that caching implementations can be written which wrap the Store (used
// to store the bytes) and VFS (used to read the files off disk if needed).
pub trait StoreFileByDigest<Error> {
  fn store_by_digest(&self, file: File) -> future::BoxFuture<'static, Result<Digest, Error>>;
}

///
/// A StoreFileByDigest which reads with a PosixFS and writes to a Store, with no caching.
///
#[derive(Clone)]
pub struct OneOffStoreFileByDigest {
  store: Store,
  posix_fs: Arc<PosixFS>,
}

impl OneOffStoreFileByDigest {
  pub fn new(store: Store, posix_fs: Arc<PosixFS>) -> OneOffStoreFileByDigest {
    OneOffStoreFileByDigest { store, posix_fs }
  }
}

impl StoreFileByDigest<String> for OneOffStoreFileByDigest {
  fn store_by_digest(&self, file: File) -> future::BoxFuture<'static, Result<Digest, String>> {
    let store = self.store.clone();
    let posix_fs = self.posix_fs.clone();
    let res = async move {
      let content = posix_fs
        .read_file(&file)
        .await
        .map_err(move |err| format!("Error reading file {:?}: {:?}", file, err))?;
      store.store_file_bytes(content.content, true).await
    };
    res.boxed()
  }
}

#[derive(Clone)]
pub struct StoreManyFileDigests {
  pub hash: HashMap<PathBuf, Digest>,
}

impl StoreFileByDigest<String> for StoreManyFileDigests {
  fn store_by_digest(&self, file: File) -> future::BoxFuture<'static, Result<Digest, String>> {
    future::ready(self.hash.get(&file.path).copied().ok_or_else(|| {
      format!(
        "Could not find file {} when storing file by digest",
        file.path.display()
      )
    }))
    .boxed()
  }
}
