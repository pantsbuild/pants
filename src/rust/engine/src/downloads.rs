// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeMap;
use std::fmt;
use std::io::{self, Write};
use std::num::NonZeroUsize;
use std::pin::Pin;
use std::time::Duration;

use async_trait::async_trait;
use bytes::{BufMut, Bytes};
use futures::TryFutureExt;
use futures::stream::StreamExt;
use hashing::Digest;
use reqwest::Error;
use reqwest::header::{HeaderMap, HeaderName};
use store::Store;
use tokio_retry2::{Retry, RetryError, strategy::ExponentialFactorBackoff};
use url::Url;

use workunit_store::{Level, in_workunit};

#[derive(Debug)]
enum StreamingError {
    Retryable(String),
    Permanent(String),
}

impl fmt::Display for StreamingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StreamingError::Retryable(inner) => write!(f, "{} (retryable)", inner.as_str()),
            StreamingError::Permanent(inner) => write!(f, "{} (unretryable)", inner.as_str()),
        }
    }
}

impl std::error::Error for StreamingError {}

impl From<StreamingError> for String {
    fn from(err: StreamingError) -> Self {
        match err {
            StreamingError::Retryable(s) | StreamingError::Permanent(s) => s,
        }
    }
}

#[async_trait]
trait StreamingDownload: Send {
    async fn next(&mut self) -> Option<Result<Bytes, String>>;
}

struct NetDownload {
    stream: futures_core::stream::BoxStream<'static, Result<Bytes, Error>>,
}

impl NetDownload {
    async fn start(
        http_client: &reqwest::Client,
        url: Url,
        auth_headers: BTreeMap<String, String>,
        file_name: String,
    ) -> Result<NetDownload, StreamingError> {
        let mut headers = HeaderMap::new();
        for (k, v) in &auth_headers {
            headers.insert(
                HeaderName::from_bytes(k.as_bytes()).unwrap(),
                v.parse().unwrap(),
            );
        }

        let response = http_client
      .get(url.clone())
      .headers(headers)
      .send()
      .await
      .map_err(|err| StreamingError::Retryable(format!("Error downloading file: {err}")))
      .and_then(|res|
        // Handle common HTTP errors.
        if res.status().is_server_error() {
          Err(StreamingError::Retryable(format!(
            "Server error ({}) downloading file {} from {}",
            res.status().as_str(),
            file_name,
            url,
          )))
        } else if res.status().is_client_error() {
          Err(StreamingError::Permanent(format!(
            "Client error ({}) downloading file {} from {}",
            res.status().as_str(),
            file_name,
            url,
          )))
        } else {
          Ok(res)
        })?;

        let byte_stream = Pin::new(Box::new(response.bytes_stream()));
        Ok(NetDownload {
            stream: byte_stream,
        })
    }
}

#[async_trait]
impl StreamingDownload for NetDownload {
    async fn next(&mut self) -> Option<Result<Bytes, String>> {
        self.stream
            .next()
            .await
            .map(|result| result.map_err(|err| err.to_string()))
    }
}

struct FileDownload {
    stream: tokio_util::io::ReaderStream<tokio::fs::File>,
}

impl FileDownload {
    async fn start(path: &str, file_name: String) -> Result<FileDownload, StreamingError> {
        let file = tokio::fs::File::open(path).await.map_err(|e| {
            let msg = format!("Error ({e}) opening file at {path} for download to {file_name}");
            // Fail quickly for non-existent files.
            if e.kind() == io::ErrorKind::NotFound {
                StreamingError::Permanent(msg)
            } else {
                StreamingError::Retryable(msg)
            }
        })?;
        let stream = tokio_util::io::ReaderStream::new(file);
        Ok(FileDownload { stream })
    }
}

#[async_trait]
impl StreamingDownload for FileDownload {
    async fn next(&mut self) -> Option<Result<Bytes, String>> {
        self.stream
            .next()
            .await
            .map(|result| result.map_err(|err| err.to_string()))
    }
}

async fn attempt_download(
    http_client: &reqwest::Client,
    url: &Url,
    auth_headers: &BTreeMap<String, String>,
    file_name: String,
    expected_digest: Digest,
) -> Result<(Digest, Bytes), StreamingError> {
    let mut response_stream: Box<dyn StreamingDownload> = {
        if url.scheme() == "file" {
            if let Some(host) = url.host_str() {
                return Err(StreamingError::Permanent(format!(
                    "The file Url `{}` has a host component. Instead, use `file:$path`, \
          which in this case might be either `file:{}{}` or `file:{}`.",
                    url,
                    host,
                    url.path(),
                    url.path(),
                )));
            }
            Box::new(FileDownload::start(url.path(), file_name).await?)
        } else {
            Box::new(
                NetDownload::start(http_client, url.clone(), auth_headers.clone(), file_name)
                    .await?,
            )
        }
    };

    struct SizeLimiter<W: std::io::Write> {
        writer: W,
        written: usize,
        size_limit: usize,
    }

    impl<W: std::io::Write> Write for SizeLimiter<W> {
        fn write(&mut self, buf: &[u8]) -> Result<usize, std::io::Error> {
            let new_size = self.written + buf.len();
            if new_size > self.size_limit {
                Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "Downloaded file was larger than expected digest",
                ))
            } else {
                self.written = new_size;
                self.writer.write_all(buf)?;
                Ok(buf.len())
            }
        }

        fn flush(&mut self) -> Result<(), std::io::Error> {
            self.writer.flush()
        }
    }

    let mut hasher = hashing::WriterHasher::new(SizeLimiter {
        writer: bytes::BytesMut::with_capacity(expected_digest.size_bytes).writer(),
        written: 0,
        size_limit: expected_digest.size_bytes,
    });

    while let Some(next_chunk) = response_stream.next().await {
        let chunk = next_chunk.map_err(|err| {
            StreamingError::Retryable(format!("Error reading URL fetch response: {err}"))
        })?;
        hasher.write_all(&chunk).map_err(|err| {
            StreamingError::Retryable(format!("Error hashing/capturing URL fetch response: {err}"))
        })?;
    }
    let (digest, bytewriter) = hasher.finish();
    Ok((digest, bytewriter.writer.into_inner().freeze()))
}

pub fn jitter(duration: Duration) -> Duration {
    duration.mul_f64(rand::random::<f64>())
}

pub async fn download(
    http_client: &reqwest::Client,
    store: Store,
    url: Url,
    auth_headers: BTreeMap<String, String>,
    file_name: String,
    expected_digest: hashing::Digest,
    error_delay: Duration,
    max_attempts: NonZeroUsize,
) -> Result<(), String> {
    let mut attempt_number = 0;
    let (actual_digest, bytes) = in_workunit!(
        "download_file",
        Level::Debug,
        desc = Some(format!(
            "Downloading: {url} ({})",
            filesize_with_suffix(expected_digest.size_bytes)
        )),
        |_workunit| async move {
            let retry_strategy =
                ExponentialFactorBackoff::from_millis(error_delay.as_millis() as u64, 2.0)
                    .map(jitter)
                    .take(max_attempts.get() - 1);

            return Retry::spawn(retry_strategy, || {
                attempt_number += 1;
                log::debug!("Downloading {} (attempt #{})", &url, &attempt_number);
                attempt_download(
                    http_client,
                    &url,
                    &auth_headers,
                    file_name.clone(),
                    expected_digest,
                )
                .map_err(|err| {
                    log::debug!("Error while downloading {}: {}", &url, err);
                    match err {
                        StreamingError::Retryable(msg) => RetryError::transient(msg),
                        StreamingError::Permanent(msg) => RetryError::permanent(msg),
                    }
                })
            })
            .await;
        }
    )
    .await?;

    if expected_digest != actual_digest {
        return Err(format!(
            "Wrong digest for downloaded file: want {expected_digest:?} got {actual_digest:?}"
        ));
    }

    let _ = store.store_file_bytes(bytes, true).await?;
    Ok(())
}

/// Converts the input size to a string with a trailing metric suffix.
///
/// Values larger than 1KB are rendered with 2 decimal places. The largest
/// suffix returned is "GB".
fn filesize_with_suffix(filesize: usize) -> String {
    const KB: usize = 1024;
    const MB: usize = KB * 1024;
    const GB: usize = MB * 1024;
    let filesize_f64 = filesize as f64;
    match filesize {
        0..KB => format!("{} B", filesize),
        KB..MB => format!("{:.2} KB", filesize_f64 / KB as f64),
        MB..GB => format!("{:.2} MB", filesize_f64 / MB as f64),
        _ => format!("{:.2} GB", filesize_f64 / GB as f64),
    }
}

#[cfg(test)]
mod tests {
    use std::{
        collections::{BTreeMap, HashSet},
        net::SocketAddr,
        num::NonZeroUsize,
        sync::{
            Arc,
            atomic::{AtomicU32, Ordering},
        },
        time::Duration,
    };

    use axum::{Router, extract::State, response::IntoResponse, routing::get};
    use hashing::Digest;
    use maplit::hashset;
    use reqwest::StatusCode;
    use store::Store;
    use tempfile::TempDir;
    use url::Url;
    use workunit_store::WorkunitStore;

    use super::{download, filesize_with_suffix};

    const TEST_RESPONSE: &[u8] = b"xyzzy";

    #[tokio::test]
    async fn test_download_intrinsic_basic() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();

        let dir = TempDir::new().unwrap();
        let store = Store::local_only(task_executor::Executor::new(), dir.path()).unwrap();

        let bind_addr = "127.0.0.1:0".parse::<SocketAddr>().unwrap();
        let listener = std::net::TcpListener::bind(bind_addr).unwrap();
        listener.set_nonblocking(true).unwrap();
        let addr = listener.local_addr().unwrap();

        let router = Router::new().route("/foo.txt", get(|| async { TEST_RESPONSE }));

        tokio::spawn(async move {
            axum_server::from_tcp(listener)
                .expect("Unable to create Server from std::net::TcpListener")
                .serve(router.into_make_service())
                .await
                .unwrap();
        });

        let http_client = reqwest::Client::new();
        let url = Url::parse(&format!("http://127.0.0.1:{}/foo.txt", addr.port())).unwrap();
        let auth_headers = BTreeMap::new();
        let expected_digest = Digest::of_bytes(TEST_RESPONSE);
        download(
            &http_client,
            store.clone(),
            url,
            auth_headers,
            "foo.txt".into(),
            expected_digest,
            Duration::from_millis(10),
            NonZeroUsize::new(1).unwrap(),
        )
        .await
        .unwrap();

        let file_digests_set = hashset!(expected_digest);
        store
            .ensure_downloaded(file_digests_set, HashSet::new())
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn test_download_intrinsic_retries() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();

        let dir = TempDir::new().unwrap();
        let store = Store::local_only(task_executor::Executor::new(), dir.path()).unwrap();

        let bind_addr = "127.0.0.1:0".parse::<SocketAddr>().unwrap();
        let listener = std::net::TcpListener::bind(bind_addr).unwrap();
        listener.set_nonblocking(true).unwrap();
        let addr = listener.local_addr().unwrap();

        #[derive(Clone)]
        struct HandlerState {
            attempt: Arc<AtomicU32>,
        }

        let attempt = Arc::new(AtomicU32::new(0));
        let router = Router::new()
            .route(
                "/foo.txt",
                get(move |State(state): State<HandlerState>| async move {
                    let attempt = state
                        .attempt
                        .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                    if attempt == 0 {
                        // This error code is retryable.
                        (StatusCode::BAD_GATEWAY, &b"502"[..]).into_response()
                    } else if attempt == 1 {
                        (StatusCode::OK, TEST_RESPONSE).into_response()
                    } else {
                        (StatusCode::INTERNAL_SERVER_ERROR, &b"unexpected"[..]).into_response()
                    }
                }),
            )
            .with_state(HandlerState {
                attempt: Arc::clone(&attempt),
            });

        tokio::spawn(async move {
            axum_server::from_tcp(listener)
                .expect("Unable to create Server from std::net::TcpListener")
                .serve(router.into_make_service())
                .await
                .unwrap();
        });

        let http_client = reqwest::Client::new();
        let url = Url::parse(&format!("http://127.0.0.1:{}/foo.txt", addr.port())).unwrap();
        let auth_headers = BTreeMap::new();
        let expected_digest = Digest::of_bytes(TEST_RESPONSE);
        download(
            &http_client,
            store.clone(),
            url,
            auth_headers,
            "foo.txt".into(),
            expected_digest,
            Duration::from_millis(10),
            NonZeroUsize::new(3).unwrap(),
        )
        .await
        .unwrap();

        let final_count = attempt.load(Ordering::SeqCst);
        assert_eq!(final_count, 2);

        let file_digests_set = hashset!(expected_digest);
        store
            .ensure_downloaded(file_digests_set, HashSet::new())
            .await
            .unwrap();
    }

    #[test]
    fn test_filesize_with_suffix() {
        assert_eq!(filesize_with_suffix(0), "0 B");
        assert_eq!(filesize_with_suffix(1), "1 B");
        assert_eq!(filesize_with_suffix(42), "42 B");
        assert_eq!(filesize_with_suffix(1023), "1023 B");

        assert_eq!(filesize_with_suffix(1024), "1.00 KB");
        assert_eq!(filesize_with_suffix(1025), "1.00 KB");
        assert_eq!(filesize_with_suffix(1_000_000), "976.56 KB");
        assert_eq!(filesize_with_suffix(1_048_575), "1024.00 KB");

        assert_eq!(filesize_with_suffix(1_048_576), "1.00 MB");
        assert_eq!(filesize_with_suffix(1_048_577), "1.00 MB");
        assert_eq!(filesize_with_suffix(1_000_000_000), "953.67 MB");
        assert_eq!(filesize_with_suffix(1_073_741_823), "1024.00 MB");

        assert_eq!(filesize_with_suffix(1_073_741_824), "1.00 GB");
        assert_eq!(filesize_with_suffix(1_000_000_000_000), "931.32 GB");
        assert_eq!(filesize_with_suffix(100_000_000_000_000), "93132.26 GB");
    }
}
