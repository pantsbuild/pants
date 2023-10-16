use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use async_oncecell::OnceCell;
use deepsize::DeepSizeOf;
use futures::{FutureExt, TryFutureExt};
use parking_lot::Mutex;
use serde::Serialize;

use crate::WorkdirSymlink;
use fs::{default_cache_path, RelativePath};

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq, Hash, PartialOrd, Ord, Serialize)]
pub struct CacheName(String);

impl CacheName {
    pub fn new(name: String) -> Result<CacheName, String> {
        if name
            .chars()
            .all(|c| (c.is_ascii_alphanumeric() && c.is_ascii_lowercase()) || c == '_')
        {
            Ok(CacheName(name))
        } else {
            Err(format!(
        "Cache names may only contain lowercase alphanumeric characters or underscores: got {:?}",
        name
      ))
        }
    }

    pub fn name(&self) -> &str {
        &self.0
    }
}

///
/// Named caches are concurrency safe caches in a filesystem, subdivided by cache name.
///
/// Pants "owns" named caches, and may clear or otherwise prune them at any time.
///
struct Inner {
    /// The absolute path to the base of the directory storing named caches. This may be a local or
    /// remote/virtualized path.
    base_path: PathBuf,
    /// An initializer function used to initialize a named cache at the given absolute path, once per
    /// NamedCaches instance.
    #[allow(clippy::type_complexity)]
    initializer: Box<dyn Fn(&Path) -> futures::future::BoxFuture<Result<(), String>> + Send + Sync>,
    /// Caches which have been initialized.
    initialized: Mutex<HashMap<PathBuf, Arc<OnceCell<()>>>>,
}

#[derive(Clone)]
pub struct NamedCaches(Arc<Inner>);

impl NamedCaches {
    /// Create a NamedCache, potentially in a virtualized filesystem. Cache entries will be created
    /// using the given initializer function.
    pub fn new(
        base_path: PathBuf,
        initializer: impl Fn(&Path) -> futures::future::BoxFuture<Result<(), String>>
            + Send
            + Sync
            + 'static,
    ) -> Self {
        Self(Arc::new(Inner {
            base_path,
            initializer: Box::new(initializer),
            initialized: Mutex::default(),
        }))
    }

    /// Create a NamedCache in the local filesystem.
    pub fn new_local(base_path: PathBuf) -> Self {
        Self::new(base_path, |dst| {
            tokio::fs::create_dir_all(dst)
                .map_err(|e| format!("Failed to create path {}: {e}", dst.display()))
                .boxed()
        })
    }

    pub fn base_path(&self) -> &Path {
        &self.0.base_path
    }

    // This default suffix is also hard-coded into the Python options code in global_options.py
    pub fn default_local_path() -> PathBuf {
        default_cache_path().join("named_caches")
    }

    fn cache_cell(&self, path: PathBuf) -> Arc<OnceCell<()>> {
        let mut cells = self.0.initialized.lock();
        if let Some(cell) = cells.get(&path) {
            cell.clone()
        } else {
            let cell = Arc::new(OnceCell::new());
            cells.insert(path, cell.clone());
            cell
        }
    }

    ///
    /// Returns symlinks to create for the given set of NamedCaches, initializing them if necessary.
    ///
    pub async fn paths<'a>(
        &'a self,
        caches: &'a BTreeMap<CacheName, RelativePath>,
    ) -> Result<Vec<WorkdirSymlink>, String> {
        // Collect the symlinks to create, and their destination cache cells.
        let (symlinks, initialization_futures): (Vec<_>, Vec<_>) = {
            caches
                .iter()
                .map(move |(cache_name, workdir_rel_path)| {
                    let symlink = WorkdirSymlink {
                        src: workdir_rel_path.clone(),
                        dst: self.0.base_path.join(&cache_name.0),
                    };

                    // Create the initialization future under the lock, but await it outside.
                    let dst: PathBuf = symlink.dst.clone();
                    let named_caches: NamedCaches = self.clone();
                    let initialization_future = async move {
                        named_caches
                            .cache_cell(dst.clone())
                            .get_or_try_init(
                                async move { (named_caches.0.initializer)(&dst).await },
                            )
                            .await?;
                        Ok::<_, String>(())
                    };

                    (symlink, initialization_future)
                })
                .unzip()
        };

        // Ensure that all cache destinations have been created.
        futures::future::try_join_all(initialization_futures).await?;

        Ok(symlinks)
    }
}
