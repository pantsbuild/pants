// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeMap;
use std::fmt;
use std::io::{self, Write};
use std::pin::Pin;
use std::sync::Arc;

use async_trait::async_trait;
use bytes::{BufMut, Bytes};
use futures::stream::StreamExt;
use hashing::Digest;
use humansize::{file_size_opts, FileSize};
use reqwest::header::{HeaderMap, HeaderName};
use reqwest::Error;
use tokio_retry::strategy::{jitter, ExponentialBackoff};
use tokio_retry::RetryIf;
use url::Url;

use crate::context::Core;
use workunit_store::{in_workunit, Level};

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
        core: &Arc<Core>,
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

        let response = core
      .http_client
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
    core: &Arc<Core>,
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
            Box::new(NetDownload::start(core, url.clone(), auth_headers.clone(), file_name).await?)
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

pub async fn download(
    core: Arc<Core>,
    url: Url,
    auth_headers: BTreeMap<String, String>,
    file_name: String,
    expected_digest: hashing::Digest,
) -> Result<(), String> {
    let core2 = core.clone();
    let mut attempt_number = 0;
    let (actual_digest, bytes) = in_workunit!(
        "download_file",
        Level::Debug,
        desc = Some(format!(
            "Downloading: {url} ({})",
            expected_digest
                .size_bytes
                .file_size(file_size_opts::CONVENTIONAL)
                .unwrap()
        )),
        |_workunit| async move {
            // TODO: Allow the retry strategy to be configurable?
            // For now we retry after 10ms, 100ms, 1s, and 10s.
            let retry_strategy = ExponentialBackoff::from_millis(10).map(jitter).take(4);
            RetryIf::spawn(
                retry_strategy,
                || {
                    attempt_number += 1;
                    log::debug!("Downloading {} (attempt #{})", &url, &attempt_number);

                    attempt_download(
                        &core2,
                        &url,
                        &auth_headers,
                        file_name.clone(),
                        expected_digest,
                    )
                },
                |err: &StreamingError| {
                    let is_retryable = matches!(err, StreamingError::Retryable(_));
                    log::debug!("Error while downloading {}: {}", &url, err);
                    is_retryable
                },
            )
            .await
        }
    )
    .await?;

    if expected_digest != actual_digest {
        return Err(format!(
            "Wrong digest for downloaded file: want {expected_digest:?} got {actual_digest:?}"
        ));
    }

    let _ = core.store().store_file_bytes(bytes, true).await?;
    Ok(())
}
