use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use double_checked_cell_async::DoubleCheckedCell;
use fs::{Permissions, RelativePath};
use hashing::Digest;
use parking_lot::Mutex;
use store::Store;
use tempfile::TempDir;

use crate::WorkdirSymlink;

/// Holds Digests materialized into a temporary directory, for symlinking into local sandboxes.
pub struct ImmutableInputs {
  store: Store,
  // The TempDir that digests are materialized in.
  workdir: TempDir,
  // A map from Digest to the location it has been materialized at. The DoubleCheckedCell allows
  // for cooperation between threads attempting to create Digests.
  contents: Mutex<HashMap<Digest, Arc<DoubleCheckedCell<PathBuf>>>>,
}

impl ImmutableInputs {
  pub fn new(store: Store, base: &Path) -> Result<Self, String> {
    let workdir = TempDir::new_in(base).map_err(|e| {
      format!(
        "Failed to create temporary directory for immutable inputs: {}",
        e
      )
    })?;
    Ok(Self {
      store,
      workdir,
      contents: Mutex::default(),
    })
  }

  /// Returns an absolute Path to immutably consume the given Digest from.
  async fn path(&self, digest: Digest) -> Result<PathBuf, String> {
    let cell = self.contents.lock().entry(digest).or_default().clone();
    let value: Result<_, String> = cell
      .get_or_try_init(async {
        let digest_str = digest.hash.to_hex();

        let path = self.workdir.path().join(digest_str);
        if let Ok(meta) = tokio::fs::metadata(&path).await {
          // TODO: If this error triggers, it indicates that we have previously checked out this
          // directory, either due to a race condition, or due to a previous failure to
          // materialize. See https://github.com/pantsbuild/pants/issues/13899
          return Err(format!(
            "Destination for immutable digest already exists: {:?}",
            meta
          ));
        }
        self
          .store
          .materialize_directory(path.clone(), digest, Permissions::ReadOnly)
          .await?;
        Ok(path)
      })
      .await;
    Ok(value?.clone())
  }

  ///
  /// Returns symlinks to create for the given set of immutable cache paths.
  ///
  pub(crate) async fn local_paths(
    &self,
    immutable_inputs: &BTreeMap<RelativePath, Digest>,
  ) -> Result<Vec<WorkdirSymlink>, String> {
    let dsts = futures::future::try_join_all(
      immutable_inputs
        .values()
        .map(|d| self.path(*d))
        .collect::<Vec<_>>(),
    )
    .await?;

    Ok(
      immutable_inputs
        .keys()
        .zip(dsts.into_iter())
        .map(|(src, dst)| WorkdirSymlink {
          src: src.clone(),
          dst,
        })
        .collect(),
    )
  }
}
