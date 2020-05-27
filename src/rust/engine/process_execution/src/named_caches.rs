use std::collections::BTreeSet;
use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq, Hash, PartialOrd, Ord)]
pub struct NamedCache(String);

impl NamedCache {
  pub fn new(name: String) -> Result<NamedCache, String> {
    if name
      .chars()
      .all(|c| (c.is_ascii_alphanumeric() && c.is_ascii_lowercase()) || c == '_')
    {
      Ok(NamedCache(name))
    } else {
      Err(format!(
        "Cache names may only contain lowercase alphanumeric characters or underscores: got {:?}",
        name
      ))
    }
  }
}

const WORKSPACE_CACHE_BASE: &str = ".cache";

#[derive(Debug)]
pub struct NamedCacheSymlink {
  pub src: PathBuf,
  pub dst: PathBuf,
}

#[derive(Clone)]
pub struct NamedCaches {
  ///
  /// The absolute path to the base of the directory storing named caches. Pants "owns" this
  /// directory, and may clear or otherwise prune it at any time.
  ///
  local_base: PathBuf,
}

impl NamedCaches {
  pub fn new(local_base: PathBuf) -> NamedCaches {
    NamedCaches { local_base }
  }

  ///
  /// Returns symlinks to create for the given set of NamedCaches.
  ///
  pub fn local_paths<'a>(
    &'a self,
    caches: &'a BTreeSet<NamedCache>,
  ) -> impl Iterator<Item = NamedCacheSymlink> + 'a {
    caches.iter().map(move |cache_name| NamedCacheSymlink {
      src: self.local_base.join(&cache_name.0),
      dst: PathBuf::from(WORKSPACE_CACHE_BASE).join(&cache_name.0),
    })
  }
}
