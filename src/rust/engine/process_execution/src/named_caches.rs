use std::collections::BTreeSet;
use std::ffi::OsString;
use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq, Hash, PartialOrd, Ord)]
pub struct NamedCache(String);

impl NamedCache {
  pub fn new(name: String) -> Result<NamedCache, String> {
    if name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
      Ok(NamedCache(name.to_lowercase()))
    } else {
      Err(format!(
        "Cache names may only contain alphanumeric characters and underscores: got {:?}",
        name
      ))
    }
  }
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

  pub fn local_paths<'a>(
    &'a self,
    caches: &'a BTreeSet<NamedCache>,
  ) -> impl Iterator<Item = PathBuf> + 'a {
    caches
      .iter()
      .map(move |cache_name| self.local_base.join(&cache_name.0))
  }

  ///
  /// Computes the environment variables that should be set in the environment of a local process
  /// using the given named caches.
  ///
  pub fn local_env<'a>(
    &'a self,
    caches: &'a BTreeSet<NamedCache>,
  ) -> impl Iterator<Item = (OsString, OsString)> + 'a {
    caches
      .iter()
      .zip(self.local_paths(caches))
      .map(|(cache_name, local_path)| {
        (
          format!("_APPEND_ONLY_CACHE_{}", cache_name.0).into(),
          local_path.into(),
        )
      })
  }
}
