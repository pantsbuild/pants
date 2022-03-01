// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::ffi::OsString;
use std::fmt;
use std::hash;
use std::iter::Iterator;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use deepsize::DeepSizeOf;
use futures::future;
use futures::FutureExt;

use fs::{
  DigestTrie, Dir, DirectoryDigest, File, GitignoreStyleExcludes, GlobMatching, PathStat, PosixFS,
  PreparedPathGlobs, SymlinkBehavior, EMPTY_DIGEST_TREE,
};
use hashing::{Digest, EMPTY_DIGEST};
use protos::gen::build::bazel::remote::execution::v2 as remexec;

use crate::Store;

/// The listing of a DirectoryDigest.
///
/// Similar to DirectoryDigest, the presence of the DigestTrie does _not_ guarantee that
/// the contents of the Digest have been persisted to the Store. See that struct's docs.
#[derive(Clone, DeepSizeOf)]
pub struct Snapshot {
  pub digest: Digest,
  pub tree: DigestTrie,
}

impl Eq for Snapshot {}

impl PartialEq for Snapshot {
  fn eq(&self, other: &Self) -> bool {
    self.digest == other.digest
  }
}

impl hash::Hash for Snapshot {
  fn hash<H: hash::Hasher>(&self, state: &mut H) {
    self.digest.hash(state);
  }
}

impl Snapshot {
  pub fn empty() -> Self {
    Self {
      digest: EMPTY_DIGEST,
      tree: EMPTY_DIGEST_TREE.clone(),
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
    let (paths, files): (Vec<_>, Vec<_>) = path_stats
      .iter()
      .filter_map(|ps| match ps {
        PathStat::File { path, stat } => Some((path.clone(), stat.clone())),
        _ => None,
      })
      .unzip();
    let file_digests = future::try_join_all(
      files
        .into_iter()
        .map(|file| file_digester.store_by_digest(file))
        .collect::<Vec<_>>(),
    )
    .await
    .map_err(|e| format!("Failed to digest inputs: {e:?}"))?;

    let file_digests_map = paths
      .into_iter()
      .zip(file_digests)
      .collect::<HashMap<_, _>>();

    let tree = DigestTrie::from_path_stats(path_stats, &file_digests_map)?;
    // TODO: When "enough" intrinsics are ported to directly producing/consuming DirectoryDigests
    // this call to persist the tree to the store should be removed, and the tree will be in-memory
    // only (as allowed by the DirectoryDigest contract).
    let directory_digest = store.record_digest_tree(tree.clone(), true).await?;
    Ok(Self {
      digest: directory_digest.digest,
      tree,
    })
  }

  pub async fn from_digest(store: Store, digest: DirectoryDigest) -> Result<Snapshot, String> {
    if let Some(tree) = digest.tree {
      // The DigestTrie is already loaded.
      return Ok(Self {
        digest: digest.digest,
        tree,
      });
    }

    // The DigestTrie needs to be loaded from the Store.
    // TODO: Add a native implementation that skips creating PathStats and directly produces
    // a DigestTrie.
    let path_stats_per_directory = store
      .walk(digest.digest, |_, path_so_far, _, directory| {
        let mut path_stats = Vec::new();
        path_stats.extend(directory.directories.iter().map(move |dir_node| {
          let path = path_so_far.join(dir_node.name.clone());
          (PathStat::dir(path.clone(), Dir(path)), None)
        }));
        path_stats.extend(directory.files.iter().map(move |file_node| {
          let path = path_so_far.join(file_node.name.clone());
          (
            PathStat::file(
              path.clone(),
              File {
                path: path.clone(),
                is_executable: file_node.is_executable,
              },
            ),
            Some((path, file_node.digest.as_ref().unwrap().try_into().unwrap())),
          )
        }));
        future::ok(path_stats).boxed()
      })
      .await?;

    let (path_stats, maybe_digests): (Vec<_>, Vec<_>) =
      Iterator::flatten(path_stats_per_directory.into_iter().map(Vec::into_iter)).unzip();
    let file_digests = maybe_digests.into_iter().flatten().collect();

    let tree = DigestTrie::from_path_stats(path_stats, &file_digests)?;
    let computed_digest = tree.compute_root_digest();
    if digest.digest != computed_digest {
      return Err(format!(
        "Computed digest for Snapshot loaded from store mismatched: {:?} vs {:?}",
        digest.digest, computed_digest
      ));
    }
    Ok(Self {
      digest: digest.digest,
      tree,
    })
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
    maybe_dir.ok_or_else(|| format!("{:?} was not known", digest))
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
    digest_hint: Option<DirectoryDigest>,
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
        .expand_globs(path_globs, None)
        .await
        .map_err(|err| format!("Error expanding globs: {}", err))?;
      Snapshot::from_path_stats(
        store.clone(),
        OneOffStoreFileByDigest::new(store, posix_fs, true),
        path_stats,
      )
      .await
    }
  }

  /// # Safety
  ///
  /// This should only be used for testing, as this will always create an invalid Snapshot.
  pub unsafe fn create_for_testing_ffi(
    digest: Digest,
    files: Vec<String>,
    dirs: Vec<String>,
  ) -> Result<Self, String> {
    // NB: All files receive the EMPTY_DIGEST.
    let file_digests = files
      .iter()
      .map(|s| (PathBuf::from(&s), EMPTY_DIGEST))
      .collect();
    let file_path_stats: Vec<PathStat> = files
      .into_iter()
      .map(|s| {
        PathStat::file(
          PathBuf::from(s.clone()),
          File {
            path: PathBuf::from(s),
            is_executable: false,
          },
        )
      })
      .collect();
    let dir_path_stats: Vec<PathStat> = dirs
      .into_iter()
      .map(|s| PathStat::dir(PathBuf::from(&s), Dir(PathBuf::from(s))))
      .collect();

    let tree =
      DigestTrie::from_path_stats([file_path_stats, dir_path_stats].concat(), &file_digests)?;
    Ok(Self {
      // NB: The DigestTrie's computed digest is ignored in favor of the given Digest.
      digest,
      tree,
    })
  }
}

impl fmt::Debug for Snapshot {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(
      f,
      "Snapshot(digest={:?}, entries={})",
      self.digest,
      self.tree.digests().len()
    )
  }
}

impl From<Snapshot> for DirectoryDigest {
  fn from(s: Snapshot) -> Self {
    DirectoryDigest {
      digest: s.digest,
      tree: Some(s.tree),
    }
  }
}

pub fn osstring_as_utf8(path: OsString) -> Result<String, String> {
  path
    .into_string()
    .map_err(|p| format!("{:?}'s file_name is not representable in UTF8", p))
}

// StoreFileByDigest allows a File to be saved to an underlying Store, in such a way that it can be
// looked up by the Digest produced by the store_by_digest method.
// It is a separate trait so that caching implementations can be written which wrap the Store (used
// to store the bytes) and Vfs (used to read the files off disk if needed).
pub trait StoreFileByDigest<Error> {
  fn store_by_digest(&self, file: File) -> future::BoxFuture<'static, Result<Digest, Error>>;
}

///
/// A StoreFileByDigest which reads immutable files with a PosixFS and writes to a Store, with no
/// caching.
///
#[derive(Clone)]
pub struct OneOffStoreFileByDigest {
  store: Store,
  posix_fs: Arc<PosixFS>,
  immutable: bool,
}

impl OneOffStoreFileByDigest {
  pub fn new(store: Store, posix_fs: Arc<PosixFS>, immutable: bool) -> OneOffStoreFileByDigest {
    OneOffStoreFileByDigest {
      store,
      posix_fs,
      immutable,
    }
  }
}

impl StoreFileByDigest<String> for OneOffStoreFileByDigest {
  fn store_by_digest(&self, file: File) -> future::BoxFuture<'static, Result<Digest, String>> {
    let store = self.store.clone();
    let posix_fs = self.posix_fs.clone();
    let immutable = self.immutable;
    let res = async move {
      let path = posix_fs.file_path(&file);
      store
        .store_file(true, immutable, move || std::fs::File::open(&path))
        .await
    };
    res.boxed()
  }
}
