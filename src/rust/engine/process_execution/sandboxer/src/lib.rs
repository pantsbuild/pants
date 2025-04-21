// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use ::fs::{DirectoryDigest, Permissions, RelativePath};
use hashing::Digest;
use hyper_util::rt::TokioIo;
use log::{debug, info, warn};
use protos::gen::pants::sandboxer::{
    MaterializeDirectoryRequest, MaterializeDirectoryResponse,
    sandboxer_grpc_client::SandboxerGrpcClient,
    sandboxer_grpc_server::{SandboxerGrpc, SandboxerGrpcServer},
};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;
use std::{collections::BTreeSet, io};
use std::{fs, thread};
use store::{Store, StoreCliOpt};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::oneshot;
use tokio_stream::wrappers::UnixListenerStream;
use tonic::transport::{Channel, Endpoint, Server, Uri};
use tonic::{Request, Response, Status};
use tower::service_fn;

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
        let (shutdown_tx, shutdown_rx) = oneshot::channel();

        thread::spawn(move || {
            loop {
                // Note: just a regular thread::sleep() since this is not an async context.
                thread::sleep(SandboxerService::POLLING_INTERVAL);
                if !fs::exists(&socket_path).unwrap_or(false) {
                    warn!("Socket file {} deleted. Exiting.", &socket_path.display());
                    let _ = shutdown_tx.send(());
                    break;
                }
                if inactivity_counter_ref.fetch_add(1, Ordering::Relaxed) > Self::ALLOWED_IDLE_BEATS
                {
                    warn!("Idle time limit exceeded. Exiting.");
                    let _ = shutdown_tx.send(());
                    break;
                }
            }
        });

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
            .serve_with_incoming_shutdown(UnixListenerStream::new(listener), async {
                drop(shutdown_rx.await)
            })
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
        let mutable_paths = r
            .mutable_paths
            .into_iter()
            .map(RelativePath::new)
            .collect::<Result<BTreeSet<_>, _>>()?;
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
        Ok(Response::new(MaterializeDirectoryResponse {}))
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

// The client that sends requests to the sandboxer service.
#[derive(Clone, Debug)]
pub struct SandboxerClient {
    grpc_client: SandboxerGrpcClient<Channel>,
}

impl SandboxerClient {
    pub async fn connect(socket_path: &Path) -> Result<Self, String> {
        let socket_path_buf = socket_path.to_path_buf();
        // This needs to be some valid URI, but is not actually used. See example at:
        // https://github.com/hyperium/tonic/blob/50253f1cb236feca3061488d542e37cf60ba4f65/examples/src/uds/client_with_connector.rs#L21
        let channel = Endpoint::try_from("http://[::]")
            .map_err(|e| e.to_string())?
            .connect_with_connector(service_fn(move |_: Uri| {
                let socket_path_buf = socket_path_buf.clone();
                async {
                    Ok::<_, std::io::Error>(TokioIo::new(
                        UnixStream::connect(socket_path_buf).await?,
                    ))
                }
            }))
            .await
            .map_err(|e| e.to_string())?;
        Ok(SandboxerClient {
            grpc_client: SandboxerGrpcClient::new(channel),
        })
    }

    pub async fn connect_with_retries(socket_path: &Path) -> Result<Self, String> {
        // TODO: POLLING_INTERVAL seems to be a good time quantum to use when waiting
        //  for server startup (since we know the server sleeps that long on startup)
        //  but this is somewhat arbitrary and could be tuned further.
        let sleep_time = SandboxerService::POLLING_INTERVAL;
        let mut slept = Duration::ZERO;
        let mut maybe_client: Result<Self, String> = Err("Not connected yet".to_string());

        for _ in 0..20 {
            tokio::time::sleep(sleep_time).await;
            slept += sleep_time;
            debug!(
                "Waited {:?} to connect to sandboxer at {:?}",
                slept, socket_path
            );
            maybe_client = SandboxerClient::connect(socket_path).await;
            if maybe_client.is_ok() {
                debug!("Connected to sandboxer at {:?}", socket_path);
                break;
            }
        }
        maybe_client
    }

    pub async fn materialize_directory(
        &mut self,
        destination: &Path,
        destination_root: &Path,
        dir_digest: &DirectoryDigest,
        mutable_paths: &[String],
    ) -> Result<(), String> {
        let request = tonic::Request::new(MaterializeDirectoryRequest {
            destination: destination
                .to_str()
                .ok_or(format!(
                    "workdir_path is not a valid str: {}",
                    destination.display()
                ))?
                .to_string(),
            destination_root: destination_root
                .to_str()
                .ok_or(format!(
                    "workdir_root_path is not a valid str: {}",
                    destination_root.display()
                ))?
                .to_string(),
            digest: Some(dir_digest.as_digest().into()),
            mutable_paths: mutable_paths.to_vec(),
        });

        self.grpc_client
            .materialize_directory(request)
            .await
            .map(|_| ())
            .map_err(|e| e.to_string())
    }
}
