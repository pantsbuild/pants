// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use ::fs::{DirectoryDigest, Permissions, RelativePath};
use children::ManagedChild;
use hashing::Digest;
use hyper_util::rt::TokioIo;
use log::{debug, info, warn};
use logging::logger::PANTS_LOGGER;
use protos::pb::pants::sandboxer::{
    MaterializeDirectoryRequest, MaterializeDirectoryResponse,
    sandboxer_grpc_client::SandboxerGrpcClient,
    sandboxer_grpc_server::{SandboxerGrpc, SandboxerGrpcServer},
};
use std::process::Stdio;
use std::{
    env,
    os::unix::{ffi::OsStrExt, net::SocketAddr},
    path::{Path, PathBuf},
};

use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;
use std::{collections::BTreeSet, io};
use std::{fs, thread};
use store::{Store, StoreCliOpt};
use tokio::fs::OpenOptions;
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::RwLock;
use tokio::sync::oneshot;
use tokio::{process::Command, sync::RwLockWriteGuard};
use tokio_stream::wrappers::UnixListenerStream;
use tonic::transport::{Channel, Endpoint, Server, Uri};
use tonic::{Request, Response, Status};
use tower::service_fn;

#[cfg(test)]
mod tests;

#[cfg(test)]
mod test_util;

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
    pub const POLLING_INTERVAL: Duration = Duration::from_millis(50);
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
        // receive no new connections (since the socket file was pulled out from under it)
        // so eventually it'll shut down due to idleness. But it's nicer if we can let it
        // go right away.
        tokio::time::sleep(SandboxerService::POLLING_INTERVAL).await;

        ensure_parent_dir(&self.socket_path)?;
        let listener = UnixListener::bind(&self.socket_path)?;
        // `bind()` creates the socket file, so now we can poll it to check if it has
        // been deleted by the user. If it has, existing connections will continue to
        // work (via the underlying inode) but new connections will not be possible,
        // so we exit the process and let the caller respawn it.
        //
        // NB: We can't easily use the notify crate to watch changes to the socket file,
        //  because on MacOS the FSEvent watches are path-based, not inode-based, and they
        //  are batched. So we may get a spurious notification for the removal above, and not
        //  know if we should act on it. We could use notify's PollWatcher, but it's easier to
        // implement simple polling ourselves, without the overkill of the notify crate.
        let socket_path = self.socket_path.clone();
        let inactivity_counter = Arc::new(AtomicUsize::new(0));
        let inactivity_counter_ref = inactivity_counter.clone();
        let (graceful_shutdown_tx, graceful_shutdown_rx) = oneshot::channel();
        let (abrupt_shutdown_tx, abrupt_shutdown_rx) = oneshot::channel();

        thread::spawn(move || {
            loop {
                // Note: just a regular thread::sleep() since this is not an async context.
                thread::sleep(SandboxerService::POLLING_INTERVAL);
                if !fs::exists(&socket_path).unwrap_or(false) {
                    warn!("Socket file {} deleted. Exiting.", &socket_path.display());
                    let _ = graceful_shutdown_tx.send(());
                    break;
                }
                if inactivity_counter_ref.fetch_add(1, Ordering::Relaxed) > Self::ALLOWED_IDLE_BEATS
                {
                    warn!("Idle time limit exceeded. Exiting.");
                    let _ = graceful_shutdown_tx.send(());
                    break;
                }
            }
            // The server has no graceful shutdown timeout and so can block indeterminately if a
            // client doesn't respond to a shutdown notice. So we implement a timeout here.
            // If the server does perform a graceful shutdown in time then the main thread will
            // exit and this thread will not send its signal. Otherwise we'll send the signal
            // and trigger an abrupt shutdown.
            // See https://github.com/hyperium/tonic/issues/1820.
            thread::sleep(SandboxerService::POLLING_INTERVAL);
            let _ = abrupt_shutdown_tx.send(());
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

        tokio::select! {
            _ = router
            .serve_with_incoming_shutdown(UnixListenerStream::new(listener), async {
                drop(graceful_shutdown_rx.await);
            }) => {}
            _ = abrupt_shutdown_rx => {
                std::process::exit(22);
            }
        }
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
            debug!("Waited {slept:?} to connect to sandboxer at {socket_path:?}");
            maybe_client = SandboxerClient::connect(socket_path).await;
            if maybe_client.is_ok() {
                debug!("Connected to sandboxer at {socket_path:?}");
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

// The spawned sandboxer process and a connection to it.
pub struct SandboxerProcess {
    process: ManagedChild,
    client: SandboxerClient,
}

// Manages the spawned sandboxer process and communicates with it.
#[derive(Clone)]
pub struct Sandboxer {
    sandboxer_bin: PathBuf,
    socket_path: PathBuf,
    log_path: PathBuf,
    store_cli_opt: StoreCliOpt,
    process: Arc<RwLock<Option<SandboxerProcess>>>,
}

type WriteLockedSandboxerProcess<'a> = RwLockWriteGuard<'a, Option<SandboxerProcess>>;

impl Sandboxer {
    pub async fn new(
        sandboxer_bin: PathBuf,
        pants_workdir: PathBuf,
        store_cli_opt: StoreCliOpt,
    ) -> Result<Self, String> {
        let workdir_hash = format!(
            "{:x}",
            Digest::of_bytes(pants_workdir.as_os_str().as_bytes())
                .hash
                .prefix_hash()
        );

        let try_socket_path = |base: PathBuf| -> Option<PathBuf> {
            let run_dir = if base.starts_with(&pants_workdir) {
                base
            } else {
                base.join(&workdir_hash)
            };
            let socket_path = run_dir.join("sandboxer.sock");
            debug!("Trying sandboxer socket path {}", socket_path.display());

            match SocketAddr::from_pathname(&socket_path) {
                Ok(_) => (),
                Err(e) => {
                    warn!(
                        "Invalid sandboxer socket path {}: {}",
                        socket_path.display(),
                        e
                    );
                    return None;
                }
            }

            let res = fs::create_dir_all(&run_dir);
            if res.is_err() {
                debug!(
                    "Failed to create dir for sandboxer socket at {}",
                    socket_path.display()
                );
                None
            } else {
                info!("Using sandboxer socket path {}", socket_path.display());
                Some(socket_path)
            }
        };

        // UNIX domain socket creation can fail with "transport error" if the path is too long.
        // We have no control over the repo root path length, so we try to create the socket
        // in some standard short path locations, falling back to the repo dir as a last resort.
        // See https://refspecs.linuxfoundation.org/FHS_3.0/fhs/ch03s15.html and
        // https://specifications.freedesktop.org/basedir-spec/latest/ for why these paths.
        let socket_path = env::var_os("XDG_RUNTIME_DIR")
            .and_then(|path| try_socket_path(PathBuf::from(path).join("pants")))
            .or_else(|| try_socket_path(PathBuf::from("/run/pants")))
            .or_else(|| try_socket_path(PathBuf::from("/var/run/pants")))
            .or_else(|| try_socket_path(env::temp_dir().join("run/pants")))
            .or_else(|| try_socket_path(pants_workdir.join("sandboxer")))
            .ok_or("Failed to find a working socket path".to_owned())?;

        Ok(Self {
            sandboxer_bin,
            socket_path,
            log_path: pants_workdir.join("sandboxer").join("sandboxer.log"),
            store_cli_opt,
            process: Arc::new(RwLock::new(None)),
        })
    }

    pub fn socket_path(&self) -> &Path {
        self.socket_path.as_ref()
    }

    pub async fn is_alive(&self) -> Result<bool, String> {
        let mut locked_proc = self.process.write().await;
        if let Some(proc) = locked_proc.as_mut() {
            proc.process.check_child_has_exited().map(|b| !b)
        } else {
            Ok(false)
        }
    }

    pub async fn spawn(&self) -> Result<(), String> {
        let mut locked_proc = self.process.write().await;
        self.do_spawn(&mut locked_proc).await
    }

    async fn do_spawn(
        &self,
        locked_proc: &mut WriteLockedSandboxerProcess<'_>,
    ) -> Result<(), String> {
        ensure_parent_dir(&self.log_path)?;
        let logfile = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log_path)
            .await
            .map_err(|e| e.to_string())?;
        let mut cmd = Command::new(&self.sandboxer_bin);
        cmd.arg("--socket-path");
        cmd.arg(self.socket_path.as_os_str());
        cmd.args(self.store_cli_opt.to_cli_args());
        // Pass the calling code's global log level to the sandboxer process.
        // TODO: Check for a relevant per-target log level?
        cmd.env("RUST_LOG", PANTS_LOGGER.global_level().as_str());
        cmd.stderr(Stdio::from(logfile.into_std().await));

        debug!(
            "Spawning sandboxer with cmd: {} {}",
            &self.sandboxer_bin.to_string_lossy(),
            cmd.as_std()
                .get_args()
                .map(|a| a.to_string_lossy())
                .collect::<Vec<_>>()
                .join(" ")
        );

        if locked_proc.is_none() {
            let process = ManagedChild::spawn(&mut cmd, Some(Duration::from_millis(1000)))
                .map_err(|e| e.to_string())?;
            debug!("Spawned sandboxer process {:?}", process.id());
            let client = SandboxerClient::connect_with_retries(&self.socket_path).await?;
            let _ = locked_proc.insert(SandboxerProcess { process, client });
        }
        Ok(())
    }

    async fn kill(&self) {
        let mut locked_proc = self.process.write().await;
        self.do_kill(&mut locked_proc).await
    }

    async fn do_kill(&self, locked_proc: &mut RwLockWriteGuard<'_, Option<SandboxerProcess>>) {
        // Note that we don't want to remove the socket file here, as it may no longer
        // be under the control of the sandboxer process we're killing.
        if let Some(ref mut proc) = **locked_proc {
            // Best effort to shut down, ignoring any errors (which would
            // typically be due to the process already being dead).
            let _ = proc.process.attempt_shutdown_sync();
        }
        locked_proc.take();
    }

    async fn client(&self) -> Result<SandboxerClient, String> {
        {
            let proc = self.process.read().await;
            if let Some(proc) = proc.as_ref() {
                return Ok(proc.client.clone());
            }
        }
        // We've released the read lock, so now we can acquire the write lock.
        let mut locked_proc = self.process.write().await;
        Ok(if let Some(proc) = locked_proc.as_mut() {
            // Some other concurrent task spawned the process while we were
            // waiting for the write lock, so nothing to do.
            proc.client.clone()
        } else {
            self.do_spawn(&mut locked_proc).await?;
            locked_proc.as_ref().unwrap().client.clone()
        })
    }

    pub async fn materialize_directory(
        &self,
        destination: &Path,
        destination_root: &Path,
        dir_digest: &DirectoryDigest,
        mutable_paths: &BTreeSet<RelativePath>,
    ) -> Result<(), String> {
        let mutable_paths: Vec<String> = mutable_paths
            .iter()
            .map(|rp| {
                rp.to_str()
                    .map(str::to_string)
                    .ok_or_else(|| format!("Path is not valid string: {rp:?}"))
            })
            .collect::<Result<Vec<_>, _>>()?;
        let ret = self
            .client()
            .await?
            .materialize_directory(destination, destination_root, dir_digest, &mutable_paths)
            .await;
        if ret.is_err() {
            // The server might be down for some reason (e.g., it has not been initially started
            // yet, or the socket file was deleted by the user). If this happens, ensure the
            // server is properly killed, and retry once.
            self.kill().await;
            return self
                .client()
                .await?
                .materialize_directory(destination, destination_root, dir_digest, &mutable_paths)
                .await;
        }
        ret
    }
}

// Note that we do NOT want to terminate the process in a Drop implementation.
// There would be two ways to do this:  One is to kill() the process. But that is async,
// and so not easily callable in drop(). The other is to delete the socket file. But that
// might pull the rug out from under another Sandboxer that has preempted the dropped one.
// However we do set kill_on_drop for the sandboxer process on creation, so tokio will
// attempt to kill it asynchronously for us. This may leave a zombie process, as tokio doesn't
// guarantee timely reaping. But since we expect the Sandboxer to be dropped only when pantsd
// (or any other controlling process) is about to exit, at which point any of its child zombies
// will be reaped by the system, this should be fine.
