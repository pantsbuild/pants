use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use async_oncecell::OnceCell;
use fs::{DirectoryDigest, Permissions, RelativePath};
use hashing::Digest;
use parking_lot::Mutex;
use store::{Store, StoreError};
use tempfile::TempDir;

use crate::WorkdirSymlink;

struct Inner {
    store: Store,
    // The TempDir that digests are materialized in.
    workdir: TempDir,
    // A map from Digest to the location it has been materialized at. The OnceCell allows
    // for cooperation between threads attempting to create Digests.
    contents: Mutex<HashMap<Digest, Arc<OnceCell<PathBuf>>>>,
}

///
/// Holds Digests materialized into a temporary directory, for symlinking into local sandboxes.
///
#[derive(Clone)]
pub struct ImmutableInputs(Arc<Inner>);

impl ImmutableInputs {
    pub fn new(store: Store, base: &Path) -> Result<Self, String> {
        let workdir = tempfile::Builder::new()
            .prefix("immutable_inputs")
            .tempdir_in(base)
            .map_err(|e| {
                format!(
                    "Failed to create temporary directory for immutable inputs: {}",
                    e
                )
            })?;
        Ok(Self(Arc::new(Inner {
            store,
            workdir,
            contents: Mutex::default(),
        })))
    }

    pub fn workdir(&self) -> &Path {
        self.0.workdir.path()
    }

    /// Returns an absolute Path to immutably consume the given Digest from.
    async fn path(&self, directory_digest: DirectoryDigest) -> Result<PathBuf, StoreError> {
        let digest = directory_digest.as_digest();
        let cell = self.0.contents.lock().entry(digest).or_default().clone();

        // We (might) need to initialize the value.
        //
        // Because this code executes a side-effect which could be observed elsewhere within this
        // process (other threads can observe the contents of the temporary directory), we need to
        // ensure that if this method is cancelled (via async Drop), whether the cell has been
        // initialized or not stays in sync with whether the side-effect is visible.
        //
        // Making the initialization "cancellation safe", involves either:
        //
        //   1. Adding a Drop guard to "undo" the side-effect if we're dropped before we fully
        //      initialize the cell.
        //       * This is challenging to do correctly in this case, because the `Drop` guard cannot
        //         be created until after initialization begins, but cannot be cleared until after the
        //         cell has been initialized (i.e., after `get_or_try_init` returns).
        //   2. Shielding ourselves from cancellation by `spawn`ing a new Task to guarantee that the
        //      cell initialization always runs to completion.
        //       * This would work, but would mean that we would finish initializing cells even when
        //         work was cancelled. Cancellation usually means that the work is no longer necessary,
        //         and so that could result in a lot of spurious IO (in e.g. warm cache cases which
        //         never end up actually needing any inputs).
        //       * An advanced variant of this approach would be to _pause_ work on materializing a
        //         Digest when demand for it disappeared, and resume the work if another caller
        //         requested that Digest.
        //   3. Using anonymous destination paths, such that multiple attempts to initialize cannot
        //      collide.
        //       * This means that although the side-effect is visible, it can never collide.
        //
        // We take the final approach here currently (for simplicity's sake), but the advanced variant
        // of approach 2 might eventually be worthwhile.
        cell.get_or_try_init(async {
            let chroot = TempDir::new_in(self.0.workdir.path()).map_err(|e| {
                format!(
            "Failed to create a temporary directory for materialization of immutable input \
            digest {:?}: {}",
            digest, e
          )
            })?;

            let dest = chroot.path().join(digest.hash.to_hex());
            self.0
                .store
                .materialize_directory(dest.clone(), directory_digest, Permissions::ReadOnly)
                .await?;

            // Now that we've successfully initialized the destination, forget the TempDir so that it
            // is not cleaned up.
            let _ = chroot.into_path();

            Ok(dest)
        })
        .await
        .cloned()
    }

    ///
    /// Returns symlinks to create for the given set of immutable cache paths.
    ///
    pub(crate) async fn local_paths(
        &self,
        immutable_inputs: &BTreeMap<RelativePath, DirectoryDigest>,
    ) -> Result<Vec<WorkdirSymlink>, StoreError> {
        let dsts = futures::future::try_join_all(
            immutable_inputs
                .values()
                .map(|d| self.path(d.clone()))
                .collect::<Vec<_>>(),
        )
        .await?;

        Ok(immutable_inputs
            .keys()
            .zip(dsts.into_iter())
            .map(|(src, dst)| WorkdirSymlink {
                src: src.clone(),
                dst,
            })
            .collect())
    }
}
