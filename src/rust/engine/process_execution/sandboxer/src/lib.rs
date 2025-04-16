// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use ::fs::{DirectoryDigest, Permissions, RelativePath};
use hashing::Digest;
use log::{debug, info, warn};
use protos::gen::pants::sandboxer::{
    MaterializeDirectoryRequest, MaterializeDirectoryResponse,
    sandboxer_grpc_server::{SandboxerGrpc, SandboxerGrpcServer},
};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;
use std::{collections::BTreeSet, io};
use std::{fs, process, thread};
use store::{Store, StoreCliOpt};
use tokio::net::UnixListener;
use tokio_stream::wrappers::UnixListenerStream;
use tonic::transport::Server;
use tonic::{Request, Response, Status};

// The Sandboxer is a solution to the following problem:
//
// For isolation, Pants executes subprocesses in "sandbox directories". Just before executing a
// subprocess Pants creates a sandbox directory for it, and materializes its input files from the
// store into the sandbox.
// In some cases an executable run by the subprocess is also materialized into the sandbox.
// This can lead to an ETXTBSY error in the subprocess:
//
// - While the main process is writing the executable exeA for subprocess A, we fork some other
//   subprocess B.
// - Subprocess B inherits the open file handles of the main process, which in this case
//   includes a write file handle to exeA (subprocess B will close the inherited handles when it
//   execs, but that hasn't happened yet).
// - Subprocess A forks, and tries to exec exeA. This fails with ETXTBSY because subprocess B holds
//   an open write file handle to exeA.
//
// See: https://github.com/golang/go/issues/22315 for an excellent description of this generic
// Unix problem.
//
// The Sandboxer solves the problem via a separate, dedicated process that writes executables into
// sandboxes, and never itself spawns any subprocesses.
//
// The Sandboxer implementation consists of the following units:
// - A server, running in a standalone process, that receives and satisifes file writing requests.
// - A client that sends file writing requests to that server via a Unix domain socket.
// - The SandboxerProcess struct, which encapsulates a server process and a client connection to it.
// - The Sandboxer struct, which manages a SandboxerProcess, respawning it as needed.
//
// We use a Unix domain socket primarily because it's easy to pick a unique socket path per repo.

fn ensure_socket_file_removed(socket_path: &Path) -> Result<(), String> {
    let mut ret = fs::remove_file(socket_path);
    if let Err(ref err) = ret {
        if err.kind() == io::ErrorKind::NotFound {
            ret = Ok(());
        }
    } else {
        debug!("Removed existing socket file {}", &socket_path.display());
    }
    ret.map_err(|e| e.to_string())
}

fn ensure_parent_dir(path: &Path) -> Result<(), String> {
    std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())
}

// The service that the spawned sandboxer process runs.
// The process exits if anything goes wrong, since it's easy and cheap to respawn it.
// It also exits if it's been idle for a while, so that orphaned processes don't pile up.
#[derive(Debug)]
pub struct SandboxerService {
    socket_path: PathBuf,
    store_cli_opt: StoreCliOpt,
}

impl SandboxerService {
    // Note that since we wait one polling interval on startup, increasing
    // this constant will increase our startup time.
    const POLLING_INTERVAL: Duration = Duration::from_millis(50);
    const ALLOWED_IDLE_TIME: Duration = Duration::from_secs(60 * 15);
    // We count idle beats and not actual elapsed idle time, since we don't need to be very
    // precise. The two will have the same effect unless the shutdown thread is unusually starved.
    const ALLOWED_IDLE_BEATS: usize =
        Self::ALLOWED_IDLE_TIME.div_duration_f32(Self::POLLING_INTERVAL) as usize;

    pub fn new(socket_path: PathBuf, store_cli_opt: StoreCliOpt) -> Self {
        Self {
            socket_path,
            store_cli_opt,
        }
    }

    pub async fn serve(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        self.do_serve(true).await
    }

    // Used only in tests, in which case we don't want to run the shutdown thread
    // since it'll exit the test process itself.
    pub async fn serve_in_process(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        self.do_serve(false).await
    }

    pub async fn do_serve(
        &mut self,
        with_shutdown_thread: bool,
    ) -> Result<(), Box<dyn std::error::Error>> {
        // `bind()` expects the socket file not to exist, so we ensure that.
        ensure_socket_file_removed(&self.socket_path)?;
        // Wait a beat, to let any previous sandboxer process notice this removal and exit.
        // There's no great harm in leaving a stray sandboxer process running, it will
        // receive no requests (since the socket file was pulled out from under it) so eventually
        // it'll shut down due to idleness. But it's nicer if we can let it go right away.
        tokio::time::sleep(SandboxerService::POLLING_INTERVAL).await;

        ensure_parent_dir(&self.socket_path)?;
        let listener = UnixListener::bind(&self.socket_path)?;
        // `bind()` creates the socket file, so now we can poll it, in case the
        // user deletes it.
        // NB: We can't easily use the notify crate to watch changes to the socket file,
        //  because on MacOS the FSEvent watches are path-based, not inode-based, and they
        //  are batched. So we may get a spurious notification for the removal above, and not
        //  know if we should act on it. We could use notify's PollWatcher, but it's easier to
        // implement simple polling ourselves, without the overkill of the notify crate.
        let socket_path = self.socket_path.clone();
        let inactivity_counter = Arc::new(AtomicUsize::new(0));
        let inactivity_counter_ref = inactivity_counter.clone();
        if with_shutdown_thread {
            thread::spawn(move || {
                loop {
                    // Note: just a regular thread::sleep() since this is not an async context.
                    thread::sleep(SandboxerService::POLLING_INTERVAL);
                    if !fs::exists(&socket_path).unwrap_or(false) {
                        warn!("Socket file {} deleted. Exiting.", &socket_path.display());
                        process::exit(22);
                    }
                    if inactivity_counter_ref.fetch_add(1, Ordering::Relaxed)
                        > Self::ALLOWED_IDLE_BEATS
                    {
                        warn!("Idle time limit exceeded. Exiting.");
                        process::exit(23);
                    }
                }
            });
        }

        info!(
            "Sandboxer server started on socket path {}",
            self.socket_path.display()
        );
        let store = self
            .store_cli_opt
            .create_store(task_executor::Executor::new())
            .await?;
        let router = Server::builder().add_service(SandboxerGrpcServer::new(SandboxerGrpcImpl {
            store,
            inactivity_counter,
        }));
        router
            .serve_with_incoming(UnixListenerStream::new(listener))
            .await?;
        Ok(())
    }
}

#[derive(Debug)]
pub struct SandboxerGrpcImpl {
    store: Store,

    // We increment this at every poll interval, and reset it on every gRPC call.
    inactivity_counter: Arc<AtomicUsize>,
}

impl SandboxerGrpcImpl {
    async fn do_materialize_directory(
        &self,
        request: Request<MaterializeDirectoryRequest>,
    ) -> Result<Response<MaterializeDirectoryResponse>, String> {
        let r = request.into_inner();
        debug!("Received materialize_directory() request: {:#?}", &r);
        let destination_root: PathBuf = r.destination_root.into();
        let digest: Digest = r.digest.ok_or("No digest provided")?.try_into()?;
        let dir_digest = DirectoryDigest::from_persisted_digest(digest);
        let mutable_paths = BTreeSet::<RelativePath>::from_iter(
            r.mutable_paths
                .iter()
                .map(RelativePath::new)
                .collect::<Result<Vec<_>, _>>()?
                .into_iter(),
        );
        self.store
            .materialize_directory(
                r.destination.into(),
                &destination_root,
                dir_digest,
                false,
                &mutable_paths,
                Permissions::Writable,
            )
            .await
            .map_err(|e| e.to_string())?;
        Ok(Response::new(MaterializeDirectoryResponse {
            confirmation: { "OK".to_string() },
        }))
    }
}

#[tonic::async_trait]
impl SandboxerGrpc for SandboxerGrpcImpl {
    async fn materialize_directory(
        &self,
        request: Request<MaterializeDirectoryRequest>,
    ) -> Result<Response<MaterializeDirectoryResponse>, Status> {
        self.inactivity_counter.store(0, Ordering::Relaxed);
        let ret = self
            .do_materialize_directory(request)
            .await
            .map_err(Status::failed_precondition);
        debug!("materialize_directory() result: {:#?}", ret);
        ret
    }
}
