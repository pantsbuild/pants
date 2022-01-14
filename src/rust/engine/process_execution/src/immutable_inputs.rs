use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use async_oncecell::OnceCell;
use fs::{Permissions, RelativePath};
use futures::TryFutureExt;
use hashing::Digest;
use parking_lot::Mutex;
use store::Store;
use tempfile::TempDir;

use crate::WorkdirSymlink;

async fn rename_readonly_directory(
  src: impl AsRef<Path>,
  dest: impl AsRef<Path>,
  map_rename_err: impl Fn(std::io::Error) -> String,
) -> Result<(), String> {
  // If you try to rename a read-only directory (mode 0o555) under masOS you get permission
  // denied; so we temporarily make the directory writeable by the current process in order to be
  // able to rename it without error.
  #[cfg(target_os = "macos")]
  {
    use std::os::unix::fs::PermissionsExt;
    tokio::fs::set_permissions(&src, std::fs::Permissions::from_mode(0o755))
      .map_err(|e| {
        format!(
          "Failed to prepare {src:?} perms for a rename to {dest:?}: {err}",
          src = src.as_ref(),
          dest = dest.as_ref(),
          err = e
        )
      })
      .await?;
  }
  tokio::fs::rename(&src, &dest)
    .map_err(map_rename_err)
    .await?;
  #[cfg(target_os = "macos")]
  {
    use std::os::unix::fs::PermissionsExt;
    tokio::fs::set_permissions(&dest, std::fs::Permissions::from_mode(0o555))
      .map_err(|e| {
        format!(
          "Failed to seal {dest:?} as read-only: {err}",
          dest = dest.as_ref(),
          err = e
        )
      })
      .await?;
  }
  Ok(())
}

/// Holds Digests materialized into a temporary directory, for symlinking into local sandboxes.
pub struct ImmutableInputs {
  store: Store,
  // The TempDir that digests are materialized in.
  workdir: TempDir,
  // A map from Digest to the location it has been materialized at. The DoubleCheckedCell allows
  // for cooperation between threads attempting to create Digests.
  contents: Mutex<HashMap<Digest, Arc<OnceCell<PathBuf>>>>,
}

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
    Ok(Self {
      store,
      workdir,
      contents: Mutex::default(),
    })
  }

  /// Returns an absolute Path to immutably consume the given Digest from.
  async fn path(&self, digest: Digest) -> Result<PathBuf, String> {
    let cell = self.contents.lock().entry(digest).or_default().clone();
    let value = cell
      .get_or_try_init(async {
        let chroot = TempDir::new_in(self.workdir.path()).map_err(|e| {
          format!(
            "Failed to create a temporary directory for materialization of immutable input \
            digest {:?}: {}",
            digest, e
          )
        })?;
        self
          .store
          .materialize_directory(chroot.path().to_path_buf(), digest, Permissions::ReadOnly)
          .await?;
        let src = chroot.into_path();
        let dest = self.workdir.path().join(digest.hash.to_hex());
        rename_readonly_directory(&src, &dest, |e| {
          // TODO(John Sirois): This diagnostic is over the top and should be trimmed down once
          //  we have confidence in the fix. We've had issues with permission denied errors in
          //  the past though; so all this information is in here to root-cause the issue should
          //  it persist.
          let maybe_collision_metadata = std::fs::metadata(&dest);
          let maybe_unwriteable_parent_metadata = dest
            .parent()
            .ok_or(format!(
              "The destination directory for digest {:?} of {:?} has no parent dir.",
              &digest, &dest
            ))
            .map(|p| std::fs::metadata(&p));
          format!(
            "Failed to move materialized immutable input for {digest:?} from {src:?} to \
              {dest:?}: {err}\n\
              Parent directory (un-writeable parent dir?) metadata: {parent_metadata:?}\n\
              Destination directory (collision?) metadata: {existing_metadata:?}\n\
              Current immutable check outs (~dup fingerprints / differing sizes?): {contents:?}
              ",
            digest = digest,
            src = src,
            dest = &dest,
            // If the parent dir is un-writeable, which is unexpected, we will get permission
            // denied on the rename.
            parent_metadata = maybe_unwriteable_parent_metadata,
            // If the destination directory already exists then we have a leaky locking regime or
            // broken materialization failure cleanup.
            existing_metadata = maybe_collision_metadata,
            // Two digests that have different size_bytes but the same fingerprint is a bug in its
            // own right, but would lead to making the same `digest_str` accessible via two
            // different Digest keys here; so display all the keys and values to be able to spot
            // this should it occur.
            contents = self.contents.lock(),
            err = e
          )
        })
        .await?;
        Ok::<_, String>(dest)
      })
      .await?;
    Ok(value.clone())
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
