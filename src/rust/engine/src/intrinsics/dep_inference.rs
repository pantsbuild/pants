// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::PathBuf;
use std::sync::Arc;

use bytes::Bytes;
use dep_inference::javascript::ParsedJavascriptDependencies;
use dep_inference::python::ParsedPythonDependencies;
use dep_inference::{javascript, python};
use fs::{DirectoryDigest, Entry, SymlinkBehavior};
use futures::future::{BoxFuture, FutureExt};
use grpc_util::prost::MessageExt;
use hashing::Digest;
use protos::gen::pants::cache::{
    dependency_inference_request, CacheKey, CacheKeyType, DependencyInferenceRequest,
};
use pyo3::{Python, ToPyObject};
use store::Store;
use workunit_store::{in_workunit, Level};

use crate::context::Context;
use crate::externs::dep_inference::PyNativeDependenciesRequest;
use crate::nodes::NodeResult;
use crate::python::Value;
use crate::{externs, Core};

pub(crate) struct PreparedInferenceRequest {
    digest: Digest,
    /// The request that's guaranteed to have been constructed via ::prepare().
    ///
    /// NB. this `inner` value is used as the cache key, so anything that can influence the dep
    /// inference should (also) be inside it, not just a key on the outer struct
    inner: DependencyInferenceRequest,
}

impl PreparedInferenceRequest {
    pub async fn prepare(
        args: Vec<Value>,
        store: &Store,
        backend: &str,
        impl_hash: &str,
    ) -> NodeResult<Self> {
        let PyNativeDependenciesRequest {
            directory_digest,
            metadata,
        } = Python::with_gil(|py| (*args[0]).as_ref(py).extract())?;

        let (path, digest) = Self::find_one_file(directory_digest, store, backend).await?;
        let str_path = path.display().to_string();

        Ok(Self {
            digest,
            inner: DependencyInferenceRequest {
                input_file_path: str_path,
                input_file_digest: Some(digest.into()),
                metadata,
                impl_hash: impl_hash.to_string(),
            },
        })
    }

    pub async fn read_digest(&self, store: &Store) -> NodeResult<String> {
        let bytes = store
            .load_file_bytes_with(self.digest, |bytes| Vec::from(bytes))
            .await?;

        Ok(String::from_utf8(bytes)
            .map_err(|err| format!("Failed to convert digest bytes to utf-8: {err}"))?)
    }

    async fn find_one_file(
        directory_digest: DirectoryDigest,
        store: &Store,
        backend: &str,
    ) -> NodeResult<(PathBuf, Digest)> {
        let mut path = None;
        let mut digest = None;
        store
            .load_digest_trie(directory_digest.clone())
            .await?
            .walk(SymlinkBehavior::Oblivious, &mut |node_path, entry| {
                if let Entry::File(file) = entry {
                    path = Some(node_path.to_owned());
                    digest = Some(file.digest());
                }
            });
        if digest.is_none() || path.is_none() {
            Err(format!(
                "Couldn't find a file in digest for {backend} inference: {directory_digest:?}"
            ))?
        }
        let path = path.unwrap();
        let digest = digest.unwrap();
        Ok((path, digest))
    }

    fn cache_key(&self) -> CacheKey {
        CacheKey {
            key_type: CacheKeyType::DepInferenceRequest.into(),
            digest: Some(Digest::of_bytes(&self.inner.to_bytes()).into()),
        }
    }
}

pub(crate) fn parse_python_deps(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let core = &context.core;
        let store = core.store();
        let prepared_inference_request =
            PreparedInferenceRequest::prepare(args, &store, "Python", python::IMPL_HASH).await?;
        in_workunit!(
            "parse_python_dependencies",
            Level::Debug,
            desc = Some(format!(
                "Determine Python dependencies for {:?}",
                &prepared_inference_request.inner.input_file_path
            )),
            |_workunit| async move {
                let result: ParsedPythonDependencies = get_or_create_inferred_dependencies(
                    core,
                    &store,
                    prepared_inference_request,
                    |content, request| {
                        python::get_dependencies(content, request.inner.input_file_path.into())
                    },
                )
                .await?;

                let result = Python::with_gil(|py| {
                    externs::unsafe_call(
                        py,
                        core.types.parsed_python_deps_result,
                        &[
                            result.imports.to_object(py).into(),
                            result.string_candidates.to_object(py).into(),
                        ],
                    )
                });

                Ok(result)
            }
        )
        .await
    }
    .boxed()
}

pub(crate) fn parse_javascript_deps(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let core = &context.core;
        let store = core.store();
        let prepared_inference_request =
            PreparedInferenceRequest::prepare(args, &store, "Javascript", javascript::IMPL_HASH)
                .await?;

        in_workunit!(
            "parse_javascript_dependencies",
            Level::Debug,
            desc = Some(format!(
                "Determine Javascript dependencies for {:?}",
                prepared_inference_request.inner.input_file_path
            )),
            |_workunit| async move {
                let result: ParsedJavascriptDependencies = get_or_create_inferred_dependencies(
                    core,
                    &store,
                    prepared_inference_request,
                    |content, request| {
                        if let Some(dependency_inference_request::Metadata::Js(metadata)) =
                            request.inner.metadata
                        {
                            javascript::get_dependencies(
                                content,
                                request.inner.input_file_path.into(),
                                metadata,
                            )
                        } else {
                            Err(format!(
                                "{:?} is not valid metadata for Javascript dependency inference",
                                request.inner.metadata
                            ))
                        }
                    },
                )
                .await?;

                let result = Python::with_gil(|py| {
                    externs::unsafe_call(
                        py,
                        core.types.parsed_javascript_deps_result,
                        &[
                            result.file_imports.to_object(py).into(),
                            result.package_imports.to_object(py).into(),
                        ],
                    )
                });

                Ok(result)
            }
        )
        .await
    }
    .boxed()
}

pub(crate) async fn get_or_create_inferred_dependencies<T, F>(
    core: &Arc<Core>,
    store: &Store,
    request: PreparedInferenceRequest,
    dependencies_parser: F,
) -> NodeResult<T>
where
    T: serde::de::DeserializeOwned + serde::Serialize,
    F: Fn(&str, PreparedInferenceRequest) -> Result<T, String>,
{
    let cache_key = request.cache_key();
    let result =
        if let Some(result) = lookup_inferred_dependencies(&cache_key, core).await? {
            result
        } else {
            let contents = request.read_digest(store).await?;
            let result = dependencies_parser(&contents, request)?;
            core.local_cache
                .store(
                    &cache_key,
                    Bytes::from(serde_json::to_string(&result).map_err(|e| {
                        format!("Failed to serialize dep inference cache result: {e}")
                    })?),
                )
                .await?;
            result
        };
    Ok(result)
}

pub(crate) async fn lookup_inferred_dependencies<T: serde::de::DeserializeOwned>(
    key: &CacheKey,
    core: &Arc<Core>,
) -> NodeResult<Option<T>> {
    let cached_result = core.local_cache.load(key).await?;
    Ok(cached_result
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .flatten())
}
