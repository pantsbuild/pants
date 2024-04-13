// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashMap;
use std::convert::TryInto;
use std::pin::Pin;
use std::sync::Arc;

use bytes::{Bytes, BytesMut};
use futures::stream::StreamExt;
use futures::Stream;
use hashing::{Digest, Fingerprint};
use parking_lot::Mutex;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::gen::build::bazel::semver::SemVer;
use protos::gen::google::bytestream::{
    byte_stream_server::ByteStream, QueryWriteStatusRequest, QueryWriteStatusResponse, ReadRequest,
    ReadResponse, WriteRequest, WriteResponse,
};
use remexec::capabilities_server::Capabilities;
use remexec::content_addressable_storage_server::ContentAddressableStorage;
use remexec::{
    BatchReadBlobsRequest, BatchReadBlobsResponse, BatchUpdateBlobsRequest,
    BatchUpdateBlobsResponse, CacheCapabilities, ExecutionCapabilities, FindMissingBlobsRequest,
    FindMissingBlobsResponse, GetCapabilitiesRequest, GetTreeRequest, GetTreeResponse,
    ServerCapabilities,
};
use tonic::metadata::{AsciiMetadataKey, KeyAndValueRef};
use tonic::{Request, Response, Status};

use crate::cas::{RequestCounter, RequestType};

#[derive(Clone, Debug)]
pub(crate) struct StubCASResponder {
    pub chunk_size_bytes: usize,
    pub instance_name: Option<String>,
    pub blobs: Arc<Mutex<HashMap<Fingerprint, Bytes>>>,
    pub always_errors: bool,
    pub required_auth_header: Option<String>,
    pub request_counts: Arc<RequestCounter>,
    pub write_message_sizes: Arc<Mutex<Vec<usize>>>,
}

macro_rules! check_auth {
    ($self:ident, $req:ident) => {
        if let Some(ref required_auth_header) = $self.required_auth_header {
            let auth_header = AsciiMetadataKey::from_static("authorization");
            let authorization_headers: Vec<_> = $req
                .metadata()
                .iter()
                .filter_map(|kv| match kv {
                    KeyAndValueRef::Ascii(key, value) if key == auth_header => Some((key, value)),
                    _ => None,
                })
                .map(|(_key, value)| value)
                .collect();
            if authorization_headers.len() != 1
                || authorization_headers[0] != required_auth_header.as_bytes()
            {
                return Err(Status::unauthenticated(format!(
                    "Bad Authorization header; want {:?} got {:?}",
                    required_auth_header.as_bytes(),
                    authorization_headers
                )));
            }
        }
    };
}

macro_rules! check_instance_name {
    ($self:ident, $req:ident) => {
        if $req.instance_name != $self.instance_name() {
            return Err(Status::not_found(format!(
                "Instance {} does not exist",
                $req.instance_name
            )));
        }
    };
}

#[derive(Debug, Eq, PartialEq)]
struct ParsedWriteResourceName<'a> {
    instance_name: &'a str,
    _uuid: &'a str,
    hash: &'a str,
    size: usize,
}

/// Parses a resource name of the form `{instance_name}/uploads/{uuid}/blobs/{hash}/{size}` into
/// a struct with references to the individual components of the resource name. The
/// `{instance_name}` may be blank (with no leading slash) as per REAPI specification.
fn parse_write_resource_name(resource: &str) -> Result<ParsedWriteResourceName, String> {
    if resource.is_empty() {
        return Err("Missing resource name".to_owned());
    }

    // Parse the resource name into parts separated by slashes (/).
    let parts: Vec<_> = resource.split('/').collect();

    // Search for the `uploads` path component.
    let uploads_index = match parts.iter().position(|p| *p == "uploads") {
        Some(index) => index,
        None => return Err("Malformed resource name: missing `uploads` component".to_owned()),
    };
    let instance_parts = &parts[0..uploads_index];

    if (parts.len() - uploads_index) < 5 {
        return Err(
            "Malformed resource name: not enough path components after `uploads`".to_owned(),
        );
    }

    if parts[uploads_index + 2] != "blobs" {
        return Err("Malformed resource name: expected `blobs` component".to_owned());
    }

    let size = parts[uploads_index + 4]
        .parse::<usize>()
        .map_err(|_| "Malformed resource name: cannot parse size".to_owned())?;

    let instance_name = if instance_parts.is_empty() {
        ""
    } else {
        let last_instance_name_index =
            instance_parts.iter().map(|x| (*x).len()).sum::<usize>() + instance_parts.len() - 1;
        &resource[0..last_instance_name_index]
    };

    Ok(ParsedWriteResourceName {
        instance_name,
        _uuid: parts[uploads_index + 1],
        hash: parts[uploads_index + 3],
        size,
    })
}

#[derive(Debug, Eq, PartialEq)]
struct ParsedReadResourceName<'a> {
    instance_name: &'a str,
    hash: &'a str,
    size: usize,
}

/// `"{instance_name}/blobs/{hash}/{size}"`
fn parse_read_resource_name(resource: &str) -> Result<ParsedReadResourceName, String> {
    if resource.is_empty() {
        return Err("Missing resource name".to_owned());
    }

    // Parse the resource name into parts separated by slashes (/).
    let parts: Vec<_> = resource.split('/').collect();

    // Search for the `blobs` path component.
    let blobs_index = match parts.iter().position(|p| *p == "blobs") {
        Some(index) => index,
        None => return Err("Malformed resource name: missing `blobs` component".to_owned()),
    };
    let instance_parts = &parts[0..blobs_index];

    if (parts.len() - blobs_index) < 3 {
        return Err("Malformed resource name: not enough path components after `blobs`".to_owned());
    }

    let size = parts[blobs_index + 2]
        .parse::<usize>()
        .map_err(|_| "Malformed resource name: cannot parse size".to_owned())?;

    let instance_name = if instance_parts.is_empty() {
        ""
    } else {
        let last_instance_name_index =
            instance_parts.iter().map(|x| (*x).len()).sum::<usize>() + instance_parts.len() - 1;
        &resource[0..last_instance_name_index]
    };

    Ok(ParsedReadResourceName {
        instance_name,
        hash: parts[blobs_index + 1],
        size,
    })
}

impl StubCASResponder {
    fn instance_name(&self) -> String {
        self.instance_name.clone().unwrap_or_default()
    }

    /// Returns an Err to propagate if this CAS responder is configured to always give an error
    fn check_always_errors(&self) -> Result<(), Status> {
        if self.always_errors {
            Err(Status::internal(
                "StubCAS is configured to always fail".to_owned(),
            ))
        } else {
            Ok(())
        }
    }

    fn read_internal(&self, req: &ReadRequest) -> Result<Vec<ReadResponse>, Status> {
        let parsed_resource_name = parse_read_resource_name(&req.resource_name).map_err(|err| {
            Status::invalid_argument(format!("Failed to parse resource name: {err}"))
        })?;

        let digest = parsed_resource_name.hash;
        let fingerprint = Fingerprint::from_hex_string(digest)
            .map_err(|e| Status::invalid_argument(format!("Bad digest {digest}: {e}")))?;
        self.check_always_errors()?;
        let blobs = self.blobs.lock();
        let maybe_bytes = blobs.get(&fingerprint);
        match maybe_bytes {
            Some(bytes) => Ok(bytes
                .chunks(self.chunk_size_bytes)
                .map(|b| ReadResponse {
                    data: bytes.slice_ref(b),
                })
                .collect()),
            None => Err(Status::not_found(format!(
                "Did not find digest {fingerprint}"
            ))),
        }
    }
}

#[tonic::async_trait]
impl ByteStream for StubCASResponder {
    type ReadStream = Pin<Box<dyn Stream<Item = Result<ReadResponse, Status>> + Send + Sync>>;

    async fn read(
        &self,
        request: Request<ReadRequest>,
    ) -> Result<Response<Self::ReadStream>, Status> {
        RequestType::BSRead.record(&self.request_counts);
        check_auth!(self, request);

        let request = request.into_inner();

        let stream_elements = self.read_internal(&request)?;
        let stream = Box::pin(futures::stream::iter(
            stream_elements.into_iter().map(Ok).collect::<Vec<_>>(),
        ));
        Ok(Response::new(stream))
    }

    async fn write(
        &self,
        request: Request<tonic::Streaming<WriteRequest>>,
    ) -> Result<Response<WriteResponse>, Status> {
        RequestType::BSWrite.record(&self.request_counts);
        check_auth!(self, request);

        let write_message_sizes = self.write_message_sizes.clone();
        let blobs = self.blobs.clone();

        let mut stream = request.into_inner();

        let mut maybe_resource_name = None;
        let mut want_next_offset = 0;
        let mut bytes = BytesMut::new();

        while let Some(req_result) = stream.next().await {
            let req = match req_result {
                Ok(r) => r,
                Err(e) => {
                    return Err(Status::invalid_argument(format!(
                        "Client sent an error: {e}"
                    )))
                }
            };

            match maybe_resource_name {
                None => maybe_resource_name = Some(req.resource_name.clone()),
                Some(ref resource_name) => {
                    if *resource_name != req.resource_name {
                        return Err(Status::invalid_argument(format!(
              "All resource names in stream must be the same. Got {} but earlier saw {}",
              req.resource_name, resource_name
            )));
                    }
                }
            }

            if req.write_offset != want_next_offset {
                return Err(Status::invalid_argument(format!(
                    "Missing chunk. Expected next offset {}, got next offset: {}",
                    want_next_offset, req.write_offset
                )));
            }

            want_next_offset += req.data.len() as i64;
            write_message_sizes.lock().push(req.data.len());
            bytes.extend_from_slice(&req.data);
        }

        let bytes = bytes.freeze();

        match maybe_resource_name {
            None => Err(Status::invalid_argument(
                "Stream saw no messages".to_owned(),
            )),
            Some(resource_name) => {
                let parsed_resource_name =
                    parse_write_resource_name(&resource_name).map_err(Status::internal)?;

                if parsed_resource_name.instance_name != self.instance_name().as_str() {
                    return Err(Status::invalid_argument(format!(
                        "Bad instance name in resource name: expected={}, actual={}",
                        self.instance_name(),
                        parsed_resource_name.instance_name
                    )));
                }

                let fingerprint = match Fingerprint::from_hex_string(parsed_resource_name.hash) {
                    Ok(f) => f,
                    Err(err) => {
                        return Err(Status::invalid_argument(format!(
                            "Bad fingerprint in resource name: {}: {}",
                            parsed_resource_name.hash, err
                        )));
                    }
                };
                let size = parsed_resource_name.size;
                if size != bytes.len() {
                    return Err(Status::invalid_argument(format!(
                        "Size was incorrect: resource name said size={} but got {}",
                        size,
                        bytes.len()
                    )));
                }

                self.check_always_errors()?;

                {
                    let mut blobs = blobs.lock();
                    blobs.insert(fingerprint, bytes);
                }

                let response = WriteResponse {
                    committed_size: size as i64,
                };
                Ok(Response::new(response))
            }
        }
    }

    async fn query_write_status(
        &self,
        _: Request<QueryWriteStatusRequest>,
    ) -> Result<Response<QueryWriteStatusResponse>, Status> {
        Err(Status::unimplemented("".to_owned()))
    }
}

#[tonic::async_trait]
impl ContentAddressableStorage for StubCASResponder {
    async fn find_missing_blobs(
        &self,
        request: Request<FindMissingBlobsRequest>,
    ) -> Result<Response<FindMissingBlobsResponse>, Status> {
        RequestType::CASFindMissingBlobs.record(&self.request_counts);
        check_auth!(self, request);

        self.check_always_errors()?;

        let request = request.into_inner();

        check_instance_name!(self, request);

        let blobs = self.blobs.lock();
        let mut response = FindMissingBlobsResponse::default();
        for digest in request.blob_digests {
            let hashing_digest_result: Result<Digest, String> = digest.try_into();
            let hashing_digest = hashing_digest_result.expect("Bad digest");
            if !blobs.contains_key(&hashing_digest.hash) {
                response.missing_blob_digests.push(hashing_digest.into())
            }
        }
        Ok(Response::new(response))
    }

    async fn batch_update_blobs(
        &self,
        request: Request<BatchUpdateBlobsRequest>,
    ) -> Result<Response<BatchUpdateBlobsResponse>, Status> {
        RequestType::CASBatchUpdateBlobs.record(&self.request_counts);
        check_auth!(self, request);

        self.check_always_errors()?;

        let request = request.into_inner();

        check_instance_name!(self, request);

        let mut responses = Vec::new();
        let mut blobs = self.blobs.lock();

        fn write_blob(
            request: remexec::batch_update_blobs_request::Request,
            blobs: &mut HashMap<Fingerprint, Bytes>,
        ) -> Status {
            let digest = match request.digest {
                Some(d) => d,
                None => return Status::invalid_argument("digest not set in batch update request"),
            };

            let fingerprint = match Fingerprint::from_hex_string(&digest.hash) {
                Ok(f) => f,
                Err(err) => {
                    return Status::invalid_argument(format!(
                        "Bad fingerprint: {}: {}",
                        &digest.hash, err
                    ));
                }
            };

            if request.data.len() != digest.size_bytes as usize {
                return Status::invalid_argument(format!(
                    "Size was incorrect: digest size is {} but got {} from data",
                    digest.size_bytes,
                    request.data.len()
                ));
            }

            blobs.insert(fingerprint, request.data);
            Status::ok("")
        }

        for blob_request in request.requests {
            let digest = blob_request.digest.clone();
            self.write_message_sizes
                .lock()
                .push(blob_request.data.len());
            let status = write_blob(blob_request, &mut blobs);
            responses.push(remexec::batch_update_blobs_response::Response {
                digest,
                status: Some(protos::gen::google::rpc::Status {
                    code: status.code() as i32,
                    message: status.message().to_string(),
                    ..protos::gen::google::rpc::Status::default()
                }),
            })
        }

        Ok(Response::new(BatchUpdateBlobsResponse { responses }))
    }

    async fn batch_read_blobs(
        &self,
        request: Request<BatchReadBlobsRequest>,
    ) -> Result<Response<BatchReadBlobsResponse>, Status> {
        RequestType::CASBatchReadBlobs.record(&self.request_counts);
        check_auth!(self, request);

        self.check_always_errors()?;

        let request = request.into_inner();

        check_instance_name!(self, request);

        let mut responses = Vec::new();
        let blobs = self.blobs.lock();

        fn read_blob(
            digest: remexec::Digest,
            blobs: &HashMap<Fingerprint, Bytes>,
        ) -> (Option<Bytes>, Status) {
            let fingerprint = match Fingerprint::from_hex_string(&digest.hash) {
                Ok(f) => f,
                Err(err) => {
                    return (
                        None,
                        Status::invalid_argument(format!(
                            "Bad fingerprint: {}: {}",
                            &digest.hash, err
                        )),
                    );
                }
            };

            match blobs.get(&fingerprint) {
                Some(data) => {
                    if data.len() == digest.size_bytes as usize {
                        (Some(data.clone()), Status::ok(""))
                    } else {
                        (
                            None,
                            Status::invalid_argument(format!(
                                "Size was incorrect: digest size is {} but got {} from data",
                                digest.size_bytes,
                                data.len()
                            )),
                        )
                    }
                }
                None => (None, Status::not_found("")),
            }
        }

        for digest in request.digests {
            let (data_opt, status) = read_blob(digest.clone(), &blobs);
            responses.push(remexec::batch_read_blobs_response::Response {
                digest: Some(digest),
                data: data_opt.unwrap_or_else(Bytes::new),
                status: Some(protos::gen::google::rpc::Status {
                    code: status.code() as i32,
                    message: status.message().to_string(),
                    ..protos::gen::google::rpc::Status::default()
                }),
                compressor: remexec::compressor::Value::Identity as i32,
            });
        }

        Ok(Response::new(remexec::BatchReadBlobsResponse { responses }))
    }

    type GetTreeStream = tonic::codec::Streaming<GetTreeResponse>;

    async fn get_tree(
        &self,
        _: Request<GetTreeRequest>,
    ) -> Result<Response<Self::GetTreeStream>, Status> {
        Err(Status::unimplemented("".to_owned()))
    }
}

#[tonic::async_trait]
impl Capabilities for StubCASResponder {
    async fn get_capabilities(
        &self,
        request: Request<GetCapabilitiesRequest>,
    ) -> Result<Response<ServerCapabilities>, Status> {
        let request = request.into_inner();
        check_instance_name!(self, request);

        let response = ServerCapabilities {
            cache_capabilities: Some(CacheCapabilities {
                digest_functions: vec![remexec::digest_function::Value::Sha256 as i32],
                max_batch_total_size_bytes: 0,
                ..CacheCapabilities::default()
            }),
            execution_capabilities: Some(ExecutionCapabilities {
                digest_function: remexec::digest_function::Value::Sha256 as i32,
                exec_enabled: true,
                ..ExecutionCapabilities::default()
            }),
            high_api_version: Some(SemVer {
                major: 2,
                minor: 999,
                ..SemVer::default()
            }),
            ..ServerCapabilities::default()
        };

        Ok(Response::new(response))
    }
}

#[cfg(test)]
mod tests {
    use super::{
        parse_read_resource_name, parse_write_resource_name, ParsedReadResourceName,
        ParsedWriteResourceName,
    };

    #[test]
    fn parse_write_resource_name_correctly() {
        let result = parse_write_resource_name("main/uploads/uuid-12345/blobs/abc123/12").unwrap();
        assert_eq!(
            result,
            ParsedWriteResourceName {
                instance_name: "main",
                _uuid: "uuid-12345",
                hash: "abc123",
                size: 12,
            }
        );

        let result = parse_write_resource_name("uploads/uuid-12345/blobs/abc123/12").unwrap();
        assert_eq!(
            result,
            ParsedWriteResourceName {
                instance_name: "",
                _uuid: "uuid-12345",
                hash: "abc123",
                size: 12,
            }
        );

        let result = parse_write_resource_name("a/b/c/uploads/uuid-12345/blobs/abc123/12").unwrap();
        assert_eq!(
            result,
            ParsedWriteResourceName {
                instance_name: "a/b/c",
                _uuid: "uuid-12345",
                hash: "abc123",
                size: 12,
            }
        );

        // extra components after the size are accepted
        let result =
            parse_write_resource_name("a/b/c/uploads/uuid-12345/blobs/abc123/12/extra/stuff")
                .unwrap();
        assert_eq!(
            result,
            ParsedWriteResourceName {
                instance_name: "a/b/c",
                _uuid: "uuid-12345",
                hash: "abc123",
                size: 12,
            }
        );
    }

    #[test]
    fn parse_write_resource_name_errors_as_expected() {
        //
        let err = parse_write_resource_name("").unwrap_err();
        assert_eq!(err, "Missing resource name");

        let err = parse_write_resource_name("main/uuid-12345/blobs/abc123/12").unwrap_err();
        assert_eq!(err, "Malformed resource name: missing `uploads` component");

        let err = parse_write_resource_name("main/uploads/uuid-12345/abc123/12").unwrap_err();
        assert_eq!(
            err,
            "Malformed resource name: not enough path components after `uploads`"
        );

        let err = parse_write_resource_name("main/uploads/uuid-12345/abc123/12/foo").unwrap_err();
        assert_eq!(err, "Malformed resource name: expected `blobs` component");

        // negative size should be rejected
        let err =
            parse_write_resource_name("main/uploads/uuid-12345/blobs/abc123/-12").unwrap_err();
        assert_eq!(err, "Malformed resource name: cannot parse size");
    }

    #[test]
    fn parse_read_resource_name_correctly() {
        let result = parse_read_resource_name("main/blobs/abc123/12").unwrap();
        assert_eq!(
            result,
            ParsedReadResourceName {
                instance_name: "main",
                hash: "abc123",
                size: 12,
            }
        );

        let result = parse_read_resource_name("blobs/abc123/12").unwrap();
        assert_eq!(
            result,
            ParsedReadResourceName {
                instance_name: "",
                hash: "abc123",
                size: 12,
            }
        );

        let result = parse_read_resource_name("a/b/c/blobs/abc123/12").unwrap();
        assert_eq!(
            result,
            ParsedReadResourceName {
                instance_name: "a/b/c",
                hash: "abc123",
                size: 12,
            }
        );
    }

    #[test]
    fn parse_read_resource_name_errors_as_expected() {
        let err = parse_read_resource_name("").unwrap_err();
        assert_eq!(err, "Missing resource name");

        let err = parse_read_resource_name("main/abc123/12").unwrap_err();
        assert_eq!(err, "Malformed resource name: missing `blobs` component");

        let err = parse_read_resource_name("main/blobs/12").unwrap_err();
        assert_eq!(
            err,
            "Malformed resource name: not enough path components after `blobs`"
        );

        // negative size should be rejected
        let err = parse_read_resource_name("main/blobs/abc123/-12").unwrap_err();
        assert_eq!(err, "Malformed resource name: cannot parse size");
    }
}
