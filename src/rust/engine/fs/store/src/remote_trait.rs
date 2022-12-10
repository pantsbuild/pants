use std::collections::HashSet;
use std::fmt;
use std::ops::Range;
use std::sync::Arc;

use async_trait::async_trait;
use bytes::Bytes;
use hashing::Digest;

use crate::StoreError;

pub struct RemoteCacheError {
  retryable: bool,
  msg: String,
}

type ByteSource<'a> = &'a dyn Fn(Range<usize>) -> Bytes + Send + Sync + 'static;

#[async_trait]
pub trait RemoteCacheConnection: Sync {
  async fn store_bytes(&self, digest: Digest, bytes: ByteSource) -> Result<(), RemoteCacheError>;
  async fn load_bytes(&self, digest: Digest) -> Result<Option<Bytes>, String>;

  /// List any missing digests.
  ///
  /// None = not supported.
  async fn list_missing_digests(&self, digests: &mut dyn Iterator<Item=Digest>) -> Result<Option<HashSet<Digest>>, RemoteCacheError> {
    Ok(None)
  }

  fn chunk_size_bytes(&self) -> usize;
}

pub struct RemoteCache {
  connection: Box<dyn RemoteCacheConnection + Sync + 'static>
}

impl fmt::Debug for RemoteCache {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "RemoteCache(FIXME)")
  }
}

impl RemoteCache {
  pub fn new(connection: Box<dyn RemoteCacheConnection + Sync + 'static>) -> RemoteCache {
    RemoteCache { connection }
  }

  pub(crate) fn chunk_size_bytes(&self) -> usize {
    self.connection.chunk_size_bytes()
  }

  pub async fn store_buffered<WriteToBuffer, WriteResult>(
    &self,
    digest: Digest,
    mut write_to_buffer: WriteToBuffer,
  ) -> Result<(), StoreError>
  where
    WriteToBuffer: FnMut(std::fs::File) -> WriteResult,
    WriteResult: Future<Output = Result<(), StoreError>>,
  {
    let write_buffer = tempfile::tempfile().map_err(|e| {
      format!(
        "Failed to create a temporary blob upload buffer for {digest:?}: {err}",
        digest = digest,
        err = e
      )
    })?;
    let read_buffer = write_buffer.try_clone().map_err(|e| {
      format!(
        "Failed to create a read handle for the temporary upload buffer for {digest:?}: {err}",
        digest = digest,
        err = e
      )
    })?;
    write_to_buffer(write_buffer).await?;

    // Unsafety: Mmap presents an immutable slice of bytes, but the underlying file that is mapped
    // could be mutated by another process. We guard against this by creating an anonymous
    // temporary file and ensuring it is written to and closed via the only other handle to it in
    // the code just above.
    let mmap = Arc::new(unsafe {
      let mapping = memmap::Mmap::map(&read_buffer).map_err(|e| {
        format!(
          "Failed to memory map the temporary file buffer for {digest:?}: {err}",
          digest = digest,
          err = e
        )
      })?;
      if let Err(err) = madvise::madvise(
        mapping.as_ptr(),
        mapping.len(),
        madvise::AccessPattern::Sequential,
      ) {
        log::warn!(
          "Failed to madvise(MADV_SEQUENTIAL) for the memory map of the temporary file buffer for \
           {digest:?}. Continuing with possible reduced performance: {err}",
          digest = digest,
          err = err
        )
      }
      Ok(mapping) as Result<memmap::Mmap, String>
    }?);

    retry_call(
      mmap,
      |mmap| self.store_bytes_source(digest, move |range| Bytes::copy_from_slice(&mmap[range])),
      |err| err.retryable,
    )
      .await
      .map_err(|err| err.msg.into())
  }

  pub async fn store_bytes(&self, bytes: Bytes) -> Result<(), String> {
    let digest = Digest::of_bytes(&bytes);
    retry_call(
      bytes,
      |bytes| self.store_bytes_source(digest, move |range| bytes.slice(range)),
      |err| err.retryable,
    )
      .await
      .map_err(|err| err.msg)
  }

  async fn store_bytes_source(&self, digest: Digest, bytes: ByteSource) -> Result<(), String> {
    let len = digest.size_bytes;

    in_workunit!(
      "store_bytes",
      Level::Trace,
      desc = Some(format!("Storing {digest:?}")),
      |workunit| async move {
        let result = self.connection.store_bytes(digest, bytes).await;

        if result.is_ok() {
          workunit.record_observation(ObservationMetric::RemoteStoreBlobBytesUploaded, len as u64);
        }

        result
      }
    )
      .await

  }

  pub async fn load_bytes_with<
      T: Send + 'static,
    F: Fn(Bytes) -> Result<T, String> + Send + Sync + Clone + 'static,
    >(
    &self,
    digest: Digest,
    f: F,
  ) -> Result<Option<T>, String> {
    let workunit_desc = format!("Loading {digest.size_bytes} bytes for {digest.hash}");
    let result_future = async move {
      match self.connection.load_bytes(digest).await? {
        Some(bytes) => Ok(Some(f(bytes)?)),
        None => Ok(None),
      }
    };

    in_workunit!(
      "load_bytes_with",
      Level::Trace,
      desc = Some(workunit_desc),
      |workunit| async move {
        let result = result_future.await;
        workunit.record_observation(
          ObservationMetric::RemoteStoreReadBlobTimeMicros,
          start.elapsed().as_micros() as u64,
        );
        if result.is_ok() {
          workunit.record_observation(
            ObservationMetric::RemoteStoreBlobBytesDownloaded,
            digest.size_bytes as u64,
          );
        }
        result
      }
    )
      .await
  }



  pub async fn list_missing_digests(&self, digests: impl IntoIterator<Item = Digest>) -> Result<Option<HashSet<Digest>>, String> {
    in_workunit!(
      "list_missing_digests",
      Level::Trace,
      |_workunit| async move {
        self.connection.list_missing_digests(&mut digests.into_iter()).await
      }
    ).await
  }
}
