// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::ManagedChild;
use hyper_util::rt::TokioIo;
use log::{info, warn};
use protos::gen::pants::sandboxer::{
    sandboxer_grpc_client::SandboxerGrpcClient,
    sandboxer_grpc_server::{SandboxerGrpc, SandboxerGrpcServer},
    CopyLocalFileRequest, CopyLocalFileResponse,
};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;
use std::{fs, process, thread};
use tokio::net::{UnixListener, UnixStream};
use tokio::process::Command;
use tokio_stream::wrappers::UnixListenerStream;
use tonic::transport::{Channel, Endpoint, Server, Uri};
use tonic::{Request, Response, Status};
use tower::service_fn;

// The Sandboxer is a solution to the following problem:
//
// For isolation, Pants executes subprocesses in "sandbox directories". Just before executing a
// subprocess Pants creates a sandbox directory for it, and materializes its input files from the
// store into the sandbox.
// In some cases the subprocess's executable is also materialized into the sandbox. This can lead
// to an ETXTBSY error in the subprocess:
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
// The Sandboxer code consists of the following units:
// - A server, running in a standalone process, that receives and satisifes file writing requests.
// - A client that sends file writing requests to that server via a Unix domain socket.
// - The SandboxerProcess struct, which encapsulates a server process and a client connection to it.
// - The Sandboxer struct, which manages a SandboxerProcess, respawning it as needed.
//
// We use a Unix domain socket primarily because it's easy to pick a unique socket path per repo.
// The lower latency is a bonus.

fn ensure_socket_file_removed(socket_path: &Path) -> Result<(), String> {
    let mut ret = fs::remove_file(socket_path);
    if let Err(ref err) = ret {
        if err.kind() == io::ErrorKind::NotFound {
            ret = Ok(());
        }
    } else {
        info!("Removed existing socket file {}", &socket_path.display());
    }
    ret.map_err(|e| e.to_string())
}

// The service that the spawned sandboxer process runs.
// The process exits if anything goes wrong, since it's easy and cheap to respawn it.
// It also exits if it's been idle for a while, so that orphaned processes don't pile up.
#[derive(Debug)]
pub struct SandboxerService {
    socket_path: PathBuf,
}

impl SandboxerService {
    const POLLING_INTERVAL: Duration = Duration::from_millis(500);
    const ALLOWED_IDLE_TIME: Duration = Duration::from_secs(60 * 15);
    const ALLOWED_IDLE_BEATS: usize =
        Self::ALLOWED_IDLE_TIME.div_duration_f32(Self::POLLING_INTERVAL) as usize;

    pub fn new(socket_path: PathBuf) -> Self {
        Self { socket_path }
    }

    fn ensure_socket_file_removed(&mut self) -> Result<(), String> {
        ensure_socket_file_removed(&self.socket_path)
    }

    pub async fn serve(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        // `bind()` expects the socket file not to exist, so we ensure that.
        self.ensure_socket_file_removed()?;
        let listener = UnixListener::bind(&self.socket_path)?;
        // `bind()` creates the socket file, so now we can poll it, in case the
        // user deletes it.
        // NB: We can't easily use the notify crate to watch changes to the socket file,
        //  because on MacOS the FSEvent watches are path-based, not inode-based, and they
        //  are batched. So we may get a spurious notification for the removal above, and not
        //  know if we should act on it. We could use notify's PollWatcher, but it's easier to
        // implement simple polling ourselves, without the overkill of the notify crate.
        let socket_path = self.socket_path.clone();
        let idle_beats = Arc::new(AtomicUsize::new(0));

        let idle_beats_ref = idle_beats.clone();
        thread::spawn(move || loop {
            thread::sleep(SandboxerService::POLLING_INTERVAL);
            if !fs::exists(&socket_path).unwrap_or(false) {
                warn!("Socket file {} deleted. Exiting.", &socket_path.display());
                process::exit(22);
            }
            if idle_beats_ref.fetch_add(1, Ordering::Relaxed) > Self::ALLOWED_IDLE_BEATS {
                warn!("Idle time limit exceeded. Exiting.");
                process::exit(23);
            }
        });

        info!(
            "Starting sandboxer server on socket path {}",
            self.socket_path.display()
        );
        Server::builder()
            .add_service(SandboxerGrpcServer::new(SandboxerGrpcImpl {
                inactivity_counter: idle_beats,
            }))
            .serve_with_incoming(UnixListenerStream::new(listener))
            .await?;
        Ok(())
    }
}

#[derive(Debug)]
pub struct SandboxerGrpcImpl {
    // We increment this at every poll interval, and reset it on every gRPC call.
    inactivity_counter: Arc<AtomicUsize>,
}

#[tonic::async_trait]
impl SandboxerGrpc for SandboxerGrpcImpl {
    async fn copy_local_file(
        &self,
        request: Request<CopyLocalFileRequest>,
    ) -> Result<Response<CopyLocalFileResponse>, Status> {
        self.inactivity_counter.store(0, Ordering::Relaxed);
        let r = request.into_inner();
        // NB: It's important that we actually copy, rather than move, the file, as
        // we must create a new inode. We copy first to a tmp destination and then
        // rename atomically, so that the final path is never in a half-copied state.
        // We reasonably assume that the tmp destination is not occupied: The suffix
        // is obscure, and only one sandboxer should ever be writing into a given sandbox.
        let tmp_dst = format!("{}._sandboxer.dst.tmp", &r.dst);
        let nbytes = fs::copy(&r.src, &tmp_dst).map_err(|e| {
            let err_msg = e.to_string();
            warn!("Error copying {} to {}: {}", &r.src, &tmp_dst, err_msg);
            Status::failed_precondition(err_msg)
        })?;
        fs::rename(&tmp_dst, &r.dst).map_err(|e| {
            let err_msg = e.to_string();
            warn!("Error remaning {} to {}: {}", &tmp_dst, &r.dst, err_msg);
            Status::failed_precondition(err_msg)
        })?;

        let confirmation = format!("Copied {} bytes from {} to {}", nbytes, &r.src, &r.dst);
        info!("{}", confirmation);
        Ok(Response::new(CopyLocalFileResponse {
            confirmation: { confirmation },
        }))
    }
}

// The client that sends requests to the sandboxer service.
pub struct SandboxerClient {
    grpc_client: SandboxerGrpcClient<Channel>,
}

impl SandboxerClient {
    pub async fn connect(socket_path: &Path) -> Result<Self, String> {
        let socket_path_buf = socket_path.to_path_buf();
        let channel = Endpoint::try_from("http://[::]:50051")
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

    pub async fn copy_local_file(&mut self, src: &Path, dst: &Path) -> Result<String, String> {
        let src_str = src
            .to_str()
            .ok_or(format!("Invalid UTF8 in src: {}", src.to_string_lossy()))?
            .to_string();
        let dst_str = dst
            .to_str()
            .ok_or(format!("Invalid UTF8 in dst: {}", dst.to_string_lossy()))?
            .to_string();
        let request = tonic::Request::new(CopyLocalFileRequest {
            src: src_str,
            dst: dst_str,
        });
        self.grpc_client
            .copy_local_file(request)
            .await
            .map(|res| res.into_inner().confirmation)
            .map_err(|e| e.to_string())
    }
}

// The spawned sandboxer process and a connection to it.
pub struct SandboxerProcess {
    process: ManagedChild,
    client: SandboxerClient,
}

// Manages the spawned sandboxer process and communicates with it.
pub struct Sandboxer {
    sandboxer_exe: PathBuf,
    socket_path: PathBuf,
    process: Option<SandboxerProcess>,
}

impl Sandboxer {
    pub async fn new(sandboxer_exe: PathBuf, socket_path: PathBuf) -> Result<Self, String> {
        Ok(Self {
            sandboxer_exe,
            socket_path,
            process: None,
        })
    }

    pub async fn spawn(&mut self) -> Result<(), String> {
        let mut cmd = Command::new(&self.sandboxer_exe);
        let cmd = cmd.arg(&self.socket_path);
        self.process = Some(SandboxerProcess {
            process: ManagedChild::spawn(cmd, Some(Duration::from_millis(100)))
                .map_err(|e| e.to_string())?,
            client: SandboxerClient::connect(&self.socket_path).await?,
        });
        Ok(())
    }

    fn kill(&mut self) -> Result<(), String> {
        if let Some(ref mut proc) = self.process {
            proc.process.attempt_shutdown_sync()?;
        }
        self.process = None;
        self.ensure_socket_file_removed()
    }

    async fn respawn(&mut self) -> Result<(), String> {
        self.kill()?;
        self.spawn().await
    }

    fn ensure_socket_file_removed(&mut self) -> Result<(), String> {
        ensure_socket_file_removed(&self.socket_path)
    }

    fn client(&mut self) -> Result<&mut SandboxerClient, String> {
        match &mut self.process {
            Some(proc) => Ok(&mut proc.client),
            _ => Err("Sandboxer process not running".to_string()),
        }
    }

    #[allow(dead_code)]
    async fn copy_local_file(&mut self, src: &Path, dst: &Path) -> Result<String, String> {
        let ret = self.client()?.copy_local_file(src, dst).await;
        if ret.is_err() {
            // The server might be down for some reason (e.g., it has not been initially started
            // yet, or the socket file was deleted by the user). If this happens, retry once.
            self.respawn().await?;
            return self.client()?.copy_local_file(src, dst).await;
        }
        ret
    }
}

impl Drop for Sandboxer {
    fn drop(&mut self) {
        let _ = self.kill();
    }
}
