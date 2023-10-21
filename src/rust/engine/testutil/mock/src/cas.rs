// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use futures::FutureExt;
use grpc_util::hyper_util::AddrIncomingWithStream;
use hashing::Fingerprint;
use parking_lot::Mutex;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::gen::google::bytestream::byte_stream_server::ByteStreamServer;
use remexec::action_cache_server::ActionCacheServer;
use remexec::capabilities_server::CapabilitiesServer;
use remexec::content_addressable_storage_server::ContentAddressableStorageServer;
use testutil::data::{TestData, TestDirectory, TestTree};
use tonic::transport::Server;

use crate::action_cache_service::{ActionCacheHandle, ActionCacheResponder};
use crate::cas_service::StubCASResponder;

///
/// Implements the:
/// * ContentAddressableStorage
/// * ActionCache
/// * Capabilities
/// ...gRPC APIs.
///
/// NB: You might expect that these services could be generically composed, but the
/// `tonic::{Server, Router}` builder pattern changes its type with each call to `add_service`,
/// making it very challenging to wrap. Instead, we statically compose them.
///
pub struct StubCAS {
    // CAS fields.
    // TODO: These are inlined (rather than namespaced) for backwards compatibility.
    pub request_counts: Arc<RequestCounter>,
    pub write_message_sizes: Arc<Mutex<Vec<usize>>>,
    pub blobs: Arc<Mutex<HashMap<Fingerprint, Bytes>>>,
    // AC fields.
    pub action_cache: ActionCacheHandle,
    // Generic server fields.
    local_addr: SocketAddr,
    shutdown_sender: Option<tokio::sync::oneshot::Sender<()>>,
}

pub type RequestCounter = Mutex<HashMap<RequestType, usize>>;

#[derive(PartialEq, Eq, Hash, Debug, Copy, Clone)]
pub enum RequestType {
    // ByteStream
    BSRead,
    BSWrite,
    // ContentAddressableStorage
    CASFindMissingBlobs,
    CASBatchUpdateBlobs,
    CASBatchReadBlobs,
    // add others of interest as required
}

impl RequestType {
    pub fn record(self, request_counts: &RequestCounter) {
        *request_counts.lock().entry(self).or_insert(0) += 1;
    }
}

impl Drop for StubCAS {
    fn drop(&mut self) {
        if let Some(s) = self.shutdown_sender.take() {
            let _ = s.send(());
        }
    }
}

pub struct StubCASBuilder {
    ac_always_errors: bool,
    cas_always_errors: bool,
    chunk_size_bytes: Option<usize>,
    content: HashMap<Fingerprint, Bytes>,
    port: Option<u16>,
    instance_name: Option<String>,
    required_auth_token: Option<String>,
    ac_read_delay: Duration,
    ac_write_delay: Duration,
}

impl StubCASBuilder {
    pub fn new() -> Self {
        StubCASBuilder {
            ac_always_errors: false,
            cas_always_errors: false,
            chunk_size_bytes: None,
            content: HashMap::new(),
            port: None,
            instance_name: None,
            required_auth_token: None,
            ac_read_delay: Duration::from_millis(0),
            ac_write_delay: Duration::from_millis(0),
        }
    }
}

impl StubCASBuilder {
    pub fn chunk_size_bytes(mut self, chunk_size_bytes: usize) -> Self {
        if self.chunk_size_bytes.is_some() {
            panic!("Can't set chunk_size_bytes twice");
        }
        self.chunk_size_bytes = Some(chunk_size_bytes);
        self
    }

    pub fn port(mut self, port: u16) -> Self {
        if self.port.is_some() {
            panic!("Can't set port twice");
        }
        self.port = Some(port);
        self
    }

    pub fn file(mut self, file: &TestData) -> Self {
        self.content.insert(file.fingerprint(), file.bytes());
        self
    }

    pub fn directory(mut self, directory: &TestDirectory) -> Self {
        self.content
            .insert(directory.fingerprint(), directory.bytes());
        self
    }

    pub fn tree(mut self, tree: &TestTree) -> Self {
        self.content.insert(tree.fingerprint(), tree.bytes());
        self
    }

    pub fn unverified_content(mut self, fingerprint: Fingerprint, content: Bytes) -> Self {
        self.content.insert(fingerprint, content);
        self
    }

    pub fn ac_always_errors(mut self) -> Self {
        self.ac_always_errors = true;
        self
    }

    pub fn cas_always_errors(mut self) -> Self {
        self.cas_always_errors = true;
        self
    }

    pub fn ac_read_delay(mut self, duration: Duration) -> Self {
        self.ac_read_delay = duration;
        self
    }

    pub fn ac_write_delay(mut self, duration: Duration) -> Self {
        self.ac_write_delay = duration;
        self
    }

    pub fn instance_name(mut self, instance_name: String) -> Self {
        if self.instance_name.is_some() {
            panic!("Can't set instance_name twice");
        }
        self.instance_name = Some(instance_name);
        self
    }

    pub fn required_auth_token(mut self, required_auth_token: String) -> Self {
        if self.required_auth_token.is_some() {
            panic!("Can't set required_auth_token twice");
        }
        self.required_auth_token = Some(required_auth_token);
        self
    }

    pub fn build(self) -> StubCAS {
        let request_counts = Arc::new(Mutex::new(HashMap::new()));
        let write_message_sizes = Arc::new(Mutex::new(Vec::new()));
        let blobs = Arc::new(Mutex::new(self.content));
        let cas_responder = StubCASResponder {
            chunk_size_bytes: self.chunk_size_bytes.unwrap_or(1024),
            instance_name: self.instance_name,
            blobs: blobs.clone(),
            always_errors: self.cas_always_errors,
            request_counts: request_counts.clone(),
            write_message_sizes: write_message_sizes.clone(),
            required_auth_header: self.required_auth_token.map(|t| format!("Bearer {t}")),
        };

        let action_map = Arc::new(Mutex::new(HashMap::new()));
        let ac_always_errors = Arc::new(AtomicBool::new(self.ac_always_errors));
        let ac_responder = ActionCacheResponder {
            action_map: action_map.clone(),
            always_errors: ac_always_errors.clone(),
            read_delay: self.ac_read_delay,
            write_delay: self.ac_write_delay,
        };

        let addr = format!("127.0.0.1:{}", self.port.unwrap_or(0))
            .parse()
            .expect("failed to parse IP address");
        let incoming = hyper::server::conn::AddrIncoming::bind(&addr).expect("failed to bind port");
        let local_addr = incoming.local_addr();
        let incoming = AddrIncomingWithStream(incoming);

        let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel();

        tokio::spawn(async move {
            let mut server = Server::builder();
            let router = server
                .add_service(ActionCacheServer::new(ac_responder.clone()))
                .add_service(ByteStreamServer::new(cas_responder.clone()))
                .add_service(ContentAddressableStorageServer::new(cas_responder.clone()))
                .add_service(CapabilitiesServer::new(cas_responder));

            router
                .serve_with_incoming_shutdown(incoming, shutdown_receiver.map(drop))
                .await
                .unwrap();
        });

        StubCAS {
            request_counts,
            write_message_sizes,
            blobs,
            action_cache: ActionCacheHandle {
                action_map,
                always_errors: ac_always_errors,
            },
            local_addr,
            shutdown_sender: Some(shutdown_sender),
        }
    }
}

impl StubCAS {
    pub fn builder() -> StubCASBuilder {
        StubCASBuilder::new()
    }

    pub fn empty() -> StubCAS {
        StubCAS::builder().build()
    }

    pub fn cas_always_errors() -> StubCAS {
        StubCAS::builder().cas_always_errors().build()
    }

    ///
    /// The address on which this server is listening over insecure HTTP transport.
    ///
    pub fn address(&self) -> String {
        format!("http://{}", self.local_addr)
    }

    pub fn request_count(&self, request_type: RequestType) -> usize {
        *self.request_counts.lock().get(&request_type).unwrap_or(&0)
    }

    pub fn remove(&self, fingerprint: Fingerprint) -> bool {
        self.blobs.lock().remove(&fingerprint).is_some()
    }
}
