use boxfuture::{BoxFuture, Boxable};
use fs::{
  File, GitignoreStyleExcludes, GlobExpansionConjunction, GlobMatching, PosixFS, PreparedPathGlobs,
  StrictGlobMatching,
};
use hashing::{Digest, Fingerprint};
use sharded_lmdb::{Bytes as PantsBytes, ShardedLmdb, VersionedFingerprint};
use store::{Snapshot, Store, StoreFileByDigest};
use task_executor::Executor;

use anyhow;
use async_trait::async_trait;
pub use cargo_fetcher::{self, Bytes, Krate, Source as KrateSource};
use chrono;
use futures::future::{join_all, TryFutureExt};
use serde_json;

use std::collections::HashMap;
use std::convert::{From, TryFrom};
use std::fmt;
use std::io;
use std::path::PathBuf;
use std::process;
use std::str;
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug)]
pub enum CargoFetcherError {
  IoError(io::Error),
  Anyhow(anyhow::Error),
  Serde(serde_json::Error),
  Utf8(str::Utf8Error),
}

impl From<io::Error> for CargoFetcherError {
  fn from(err: io::Error) -> Self {
    CargoFetcherError::IoError(err)
  }
}

impl From<anyhow::Error> for CargoFetcherError {
  fn from(err: anyhow::Error) -> Self {
    CargoFetcherError::Anyhow(err)
  }
}

impl From<String> for CargoFetcherError {
  fn from(err: String) -> Self {
    CargoFetcherError::Anyhow(anyhow::Error::msg(err))
  }
}

impl From<serde_json::Error> for CargoFetcherError {
  fn from(err: serde_json::Error) -> Self {
    CargoFetcherError::Serde(err)
  }
}

impl From<str::Utf8Error> for CargoFetcherError {
  fn from(err: str::Utf8Error) -> Self {
    CargoFetcherError::Utf8(err)
  }
}

pub fn registry_index_reldir() -> PathBuf {
  PathBuf::from(cargo_fetcher::sync::INDEX_DIR)
}

#[derive(Eq, PartialEq, Hash, Clone, Debug)]
pub struct GitRevision(String);

pub async fn get_registry_git_revision(
  registry_download_dir: PathBuf,
  executor: Executor,
) -> Result<GitRevision, CargoFetcherError> {
  let get_git_revision: Result<String, CargoFetcherError> = executor
    .spawn_blocking(move || {
      let output = process::Command::new("git")
        .args(&["rev-parse", "HEAD"])
        .current_dir(&registry_download_dir)
        .output()?;
      let trimmed_output = str::from_utf8(&output.stdout)?.trim_end();
      Ok(trimmed_output.to_string())
    })
    .await;
  Ok(GitRevision(get_git_revision?))
}

const REGISTRY_INDEX_URL: &str = "git+https://github.com/rust-lang/crates.io-index.git";

///
/// Synthesize a Krate instance representing a specific revision of the git repo. We will use this
/// to avoid snapshotting the registry more than once per (time the registry's git repository is
/// fetched).
///
fn registry_index_crate(git_revision: GitRevision) -> Result<Krate, anyhow::Error> {
  let GitRevision(git_revision) = git_revision;
  let url = cargo_fetcher::Url::parse(REGISTRY_INDEX_URL).unwrap();
  let canonicalized = cargo_fetcher::util::Canonicalized::try_from(&url).unwrap();
  Ok(Krate {
    name: "crates.io-index".to_string(),
    version: git_revision.clone(),
    source: cargo_fetcher::Source::Git {
      url: cargo_fetcher::UrlWrapper {
        url: canonicalized.as_ref().clone(),
      },
      ident: canonicalized.ident(),
      rev: git_revision,
    },
  })
}

fn fingerprint_krate(krate: &Krate) -> Result<Fingerprint, serde_json::Error> {
  let krate_json = serde_json::to_string(krate)?;
  let Digest(fingerprint, _) = Digest::of_bytes(krate_json.as_bytes());
  Ok(fingerprint)
}

#[derive(Clone)]
pub struct FileDigester {
  pub vfs: Arc<PosixFS>,
  pub store: Store,
}

impl StoreFileByDigest<String> for FileDigester {
  fn store_by_digest(&self, file: File) -> BoxFuture<Digest, String> {
    let digester = self.clone();
    Box::pin(async move {
      let content = digester
        .vfs
        .read_file(&file)
        .await
        .map_err(|e| format!("{:?}", e))?;
      digester.store.store_file_bytes(content.content, true).await
    })
    .compat()
    .to_boxed()
  }
}

pub struct CargoPackageFetcher {
  pub krate_lookup: ShardedLmdb,
  pub krate_data: ShardedLmdb,
  pub krate_digest_mapping: ShardedLmdb,
  pub fetch_cache: ShardedLmdb,
  pub store: Store,
  pub executor: Executor,
  pub download_dir: PathBuf,
  pub timeout: Duration,
}

pub struct PackageFetchResult {
  pub krate_mapping: HashMap<Krate, Digest>,
  pub current_registry_index_krate: Krate,
  pub current_registry_index_digest: Digest,
}

impl PackageFetchResult {
  pub fn registry_index_revision(&self) -> GitRevision {
    GitRevision(self.current_registry_index_krate.version.clone())
  }

  pub fn to_json(&self) -> Result<serde_json::Value, CargoFetcherError> {
    let mut result: HashMap<String, serde_json::Value> = HashMap::new();
    result.insert(
      "current_registry_index_krate".to_string(),
      serde_json::to_value(&self.current_registry_index_krate)?,
    );
    result.insert(
      "current_registry_index_digest".to_string(),
      serde_json::to_value(&self.current_registry_index_digest)?,
    );

    let mapping: HashMap<String, serde_json::Value> = self
      .krate_mapping
      .iter()
      .map(|(krate, digest)| {
        Ok((
          serde_json::to_string(&krate)?,
          serde_json::to_value(&digest)?,
        ))
      })
      .collect::<Result<HashMap<String, serde_json::Value>, CargoFetcherError>>()?;
    result.insert("krate_mapping".to_string(), serde_json::to_value(&mapping)?);

    Ok(serde_json::to_value(&result)?)
  }

  pub fn from_json(json: serde_json::Value) -> Result<Self, CargoFetcherError> {
    let current_registry_index_krate: Krate = serde_json::from_value(
      json
        .get("current_registry_index_krate")
        .cloned()
        .ok_or_else(|| "failed to extract current_registry_index_krate".to_string())?,
    )?;
    let current_registry_index_digest: Digest = serde_json::from_value(
      json
        .get("current_registry_index_digest")
        .cloned()
        .ok_or_else(|| "failed to extract current_registry_index_digest".to_string())?,
    )?;

    let mapping: HashMap<String, serde_json::Value> = serde_json::from_value(
      json
        .get("krate_mapping")
        .cloned()
        .ok_or_else(|| "failed to extract krate_mapping".to_string())?,
    )?;
    let krate_mapping: HashMap<Krate, Digest> = mapping
      .into_iter()
      .map(|(krate_str, digest_str)| {
        let krate: Krate = serde_json::from_str(&krate_str)?;
        let digest: Digest = serde_json::from_value(digest_str)?;
        Ok((krate, digest))
      })
      .collect::<Result<HashMap<Krate, Digest>, CargoFetcherError>>()?;

    Ok(PackageFetchResult {
      krate_mapping,
      current_registry_index_krate,
      current_registry_index_digest,
    })
  }
}

impl CargoPackageFetcher {
  pub async fn fetch_packages_from_lockfile(
    &self,
    cargo_lock_file_contents: &str,
  ) -> Result<PackageFetchResult, CargoFetcherError> {
    // 1. Determine the crates to download from the Cargo.lock file.
    let krates = cargo_fetcher::read_lock_file_contents(cargo_lock_file_contents)?;
    self.fetch_packages(&krates).await
  }

  pub async fn fetch_packages(
    &self,
    krates: &[Krate],
  ) -> Result<PackageFetchResult, CargoFetcherError> {
    // 2. Check if we have performed this fetch already.
    if let Some(cached_result) = self.try_cached_fetch(krates).await? {
      return Ok(cached_result);
    }

    // 3. Update the index, and ensure all git and crates.io packages have been downloaded into
    // `self.download_dir`.
    let vfs = Arc::new(PosixFS::new(
      &self.download_dir,
      GitignoreStyleExcludes::empty(),
      self.executor.clone(),
    )?);
    let backend: Arc<dyn cargo_fetcher::Backend + Send + Sync> = Arc::new(PantsBackend {
      krate_lookup: self.krate_lookup.clone(),
      krate_data: self.krate_data.clone(),
      store: self.store.clone(),
      executor: self.executor.clone(),
      download_dir: self.download_dir.clone(),
      prefix: "".to_string(),
    });
    let ctx = cargo_fetcher::Ctx::new(
      Some(self.download_dir.clone()),
      Arc::clone(&backend),
      krates.to_vec(),
    )?;
    // From diff_cargo.rs in the `cargo-fetcher` package:
    cargo_fetcher::mirror::registry_index(Arc::clone(&backend), self.timeout).await?;
    cargo_fetcher::mirror::crates(&ctx).await?;
    ctx.prep_sync_dirs()?;
    // In the diff_cargo.rs file, these operations are in reverse order. It appears that the
    // crates.io git registry isn't used to fetch crates, and is purely for the use of cargo, so
    // switching the order should not change behavior.
    cargo_fetcher::sync::registry_index(ctx.root_dir.clone(), Arc::clone(&backend)).await?;
    cargo_fetcher::sync::crates(&ctx).await?;
    // `self.download_dir` should now contain all the necessary dependency crates!

    // 4. Snapshot all the now-downloaded crates.
    let digester = FileDigester {
      vfs: Arc::clone(&vfs),
      store: self.store.clone(),
    };
    let digests = join_all(krates.iter().map(|krate| {
      self.snapshot_package(&krate, self.get_krate_download_dir(&krate), &vfs, &digester)
    }))
    .await
    .into_iter()
    .collect::<Result<Vec<Digest>, CargoFetcherError>>()?;

    let krate_mapping: HashMap<Krate, Digest> =
      krates.iter().cloned().zip(digests.into_iter()).collect();

    // 5. If the registry was updated, snapshot it.
    let registry_reldir = registry_index_reldir();
    let git_revision = get_registry_git_revision(
      self.download_dir.join(&registry_reldir),
      self.executor.clone(),
    )
    .await?;
    let current_registry_index_krate = registry_index_crate(git_revision)?;
    let current_registry_index_digest = self
      .snapshot_package(
        &current_registry_index_krate,
        registry_reldir,
        &vfs,
        &digester,
      )
      .await?;

    // 6. Write this result to the fetch cache.
    let krates_json = serde_json::to_string(krates)?;
    let Digest(krates_fingerprint, _) = Digest::of_bytes(krates_json.as_bytes());
    let ret = PackageFetchResult {
      krate_mapping,
      current_registry_index_krate,
      current_registry_index_digest,
    };
    let ret_json = serde_json::to_string(&ret.to_json()?)?;
    self
      .fetch_cache
      .store_bytes(
        krates_fingerprint,
        PantsBytes::from(ret_json.as_bytes()),
        true,
      )
      .await?;

    Ok(ret)
  }

  fn get_crates_io_src_dir(&self) -> PathBuf {
    PathBuf::from(cargo_fetcher::sync::SRC_DIR)
  }

  fn get_git_checkout_dir(&self) -> PathBuf {
    PathBuf::from(cargo_fetcher::sync::GIT_CO_DIR)
  }

  // Cobbled together from multiple different sections of sync.rs in the cargo-fetcher package.
  fn get_krate_download_dir(&self, krate: &Krate) -> PathBuf {
    match &krate.source {
      KrateSource::CratesIo(_) => self
        .get_crates_io_src_dir()
        .join(format!("{}", krate.local_id()))
        // A .crate extension is applied to the krate's local id. This is removed when untarring
        // the crate in sync.rs in the cargo-fetcher package.
        .with_extension(""),
      KrateSource::Git { rev, .. } => {
        self
          .get_git_checkout_dir()
          .join(format!("{}/{}", krate.local_id(), rev))
      }
    }
  }

  pub async fn try_cached_fetch(
    &self,
    krates: &[Krate],
  ) -> Result<Option<PackageFetchResult>, CargoFetcherError> {
    let krates_json = serde_json::to_string(krates)?;
    let Digest(fingerprint, _) = Digest::of_bytes(krates_json.as_bytes());

    match self
      .fetch_cache
      .load_bytes_with(fingerprint, |bytes| Ok(Bytes::copy_from_slice(&bytes[..])))
      .await?
    {
      Some(result_bytes) => {
        let json_str = str::from_utf8(&result_bytes)?;
        let ret = PackageFetchResult::from_json(serde_json::from_str(&json_str)?)?;
        Ok(Some(ret))
      }
      None => Ok(None),
    }
  }

  pub async fn lookup_digest(&self, krate: &Krate) -> Result<Option<Digest>, CargoFetcherError> {
    let krate_fingerprint = fingerprint_krate(krate)?;
    if let Some(digest_bytes) = self
      .krate_digest_mapping
      .load_bytes_with(krate_fingerprint, |bytes| {
        Ok(Bytes::copy_from_slice(&bytes[..]))
      })
      .await?
    {
      let digest_str = str::from_utf8(&digest_bytes)?;
      let digest: Digest = serde_json::from_str(digest_str)?;
      Ok(Some(digest))
    } else {
      Ok(None)
    }
  }

  async fn snapshot_package(
    &self,
    krate: &Krate,
    krate_download_reldir: PathBuf,
    vfs: &Arc<PosixFS>,
    digester: &FileDigester,
  ) -> Result<Digest, CargoFetcherError> {
    // Check if the krate was previously snapshotted by this method from a separate, usually
    // previous fetch_packages() invocation.
    if let Some(digest) = self.lookup_digest(krate).await? {
      return Ok(digest);
    }

    // If the krate was not already snapshotted, do so now from the expected download
    // directory. This will work equally for git and crates.io downloads.

    // 1. Snapshot the untarred contents. This is composed of two steps -- getting all the
    // PathStats for the download directory contents, then uploading those to the file store.
    let download_globs = PreparedPathGlobs::create(
      vec![format!("{}/**", krate_download_reldir.as_path().display())],
      StrictGlobMatching::Error(format!(
        "failed to expand the contents of krate {} at {}",
        krate,
        krate_download_reldir.as_path().display()
      )),
      GlobExpansionConjunction::AllMatch,
    )?;
    let path_stats = vfs.expand(download_globs).await?;
    let snapshot =
      Snapshot::from_path_stats(self.store.clone(), digester.clone(), path_stats).await?;

    // 2. Enter the digest for the krate into the third lmdb instance so it can be retrieved in
    // subsequent invocations of this method.
    let serialized_digest = serde_json::to_string(&snapshot.digest)?;
    let krate_fingerprint = fingerprint_krate(krate)?;
    self
      .krate_digest_mapping
      .store_bytes(
        krate_fingerprint,
        PantsBytes::from(serialized_digest.as_bytes()),
        true,
      )
      .await?;

    Ok(snapshot.digest)
  }
}

struct PantsBackend {
  pub krate_lookup: ShardedLmdb,
  pub krate_data: ShardedLmdb,
  pub store: Store,
  pub executor: Executor,
  pub download_dir: PathBuf,
  // FIXME: this appears to be a leaky implementation detail of the cargo-fetcher crate.
  pub prefix: String,
}

impl fmt::Debug for PantsBackend {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(
      f,
      "PantsBackend(prefix = {}, krate_data = ...)",
      self.prefix
    )
  }
}

impl PantsBackend {
  fn prefix_len(&self) -> usize {
    self.prefix.len()
  }
}

#[async_trait]
impl cargo_fetcher::Backend for PantsBackend {
  async fn fetch(&self, krate: &Krate) -> Result<Bytes, anyhow::Error> {
    let krate_fingerprint = fingerprint_krate(krate)?;
    self
      .krate_data
      .load_bytes_with(krate_fingerprint, |bytes| {
        Ok(Bytes::copy_from_slice(&bytes[..]))
      })
      .await
      .map_err(anyhow::Error::msg)?
      .ok_or_else(|| anyhow::Error::msg(format!("krate {:?} not found!", krate)))
  }

  async fn upload(&self, source: Bytes, krate: &Krate) -> Result<usize, anyhow::Error> {
    let source = PantsBytes::from(&source[..]);
    let len = source.len();
    let krate_fingerprint = fingerprint_krate(krate)?;

    // 1. Serialize the krate to json and store that in a separate table than the package contents
    // table. This will be consumed by list().
    let krate_json = serde_json::to_string(krate)?;
    self
      .krate_lookup
      .store_bytes(
        krate_fingerprint,
        PantsBytes::from(krate_json.as_bytes()),
        false,
      )
      .await
      .map_err(anyhow::Error::msg)?;

    // 2. Using the same key, store the package bytes into the package contents table. This will be
    // consumed by fetch().
    self
      .krate_data
      .store_bytes(krate_fingerprint, source, false)
      .await
      .map_err(anyhow::Error::msg)?;

    Ok(len)
  }

  async fn list(&self) -> Result<Vec<String>, anyhow::Error> {
    let keys_as_bytes: Vec<&[u8]> = self
      .krate_lookup
      .all_entry_keys()
      .await
      .map_err(anyhow::Error::msg)?;

    let krates_as_bytes: Vec<PantsBytes> = join_all(keys_as_bytes.into_iter().map(|key| {
      let fp = VersionedFingerprint::from_bytes_unsafe(key);
      self
        .krate_lookup
        .load_bytes_with(fp.get_fingerprint(), |bytes| {
          Ok(PantsBytes::from(&bytes[..]))
        })
    }))
    .await
    .into_iter()
    .map(|maybe_bytes| maybe_bytes.map(|bytes| bytes.unwrap()))
    .collect::<Result<Vec<PantsBytes>, String>>()
    .map_err(|e| anyhow::Error::msg(format!("{:?}", e)))?;

    let pfx_len = self.prefix_len();
    let ret: Vec<String> = krates_as_bytes
      .into_iter()
      .map(|krate_bytes| {
        let krate_str = str::from_utf8(&krate_bytes[..]).map_err(|e| format!("{:?}", e))?;
        let krate: Krate = serde_json::from_str(krate_str).map_err(|e| format!("{:?}", e))?;
        let ret: String = krate.name[pfx_len..].to_owned();
        Ok(ret)
      })
      .collect::<Result<Vec<String>, String>>()
      .map_err(anyhow::Error::msg)?;
    Ok(ret)
  }

  async fn updated(
    &self,
    krate: &Krate,
  ) -> Result<Option<chrono::DateTime<chrono::Utc>>, anyhow::Error> {
    let krate_fingerprint = fingerprint_krate(krate)?;
    Ok(
      self
        .krate_data
        .get_lease_time(krate_fingerprint)
        .map_err(anyhow::Error::msg)?
        .map(|unix_time: u64| {
          // FIXME: why does this `chrono` package read time as an i64 instead of a u64 like the
          // stdlib???
          let native_time = chrono::NaiveDateTime::from_timestamp(unix_time as i64, 0);
          chrono::DateTime::<chrono::Utc>::from_utc(native_time, chrono::Utc)
        }),
    )
  }

  fn set_prefix(&mut self, prefix: &str) {
    self.prefix = prefix.to_owned();
  }
}
