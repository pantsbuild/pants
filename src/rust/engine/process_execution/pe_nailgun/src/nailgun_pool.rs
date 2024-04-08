// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;
use std::ffi::OsString;
use std::io::{self, BufRead, Read};
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::os::unix::process::ExitStatusExt;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_lock::{Mutex, MutexGuardArc};
use futures::future;
use lazy_static::lazy_static;
use log::{debug, info};
use regex::Regex;
use tempfile::TempDir;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

use hashing::Fingerprint;
use store::{ImmutableInputs, Store};
use task_executor::Executor;
use workunit_store::{in_workunit, Level};

use process_execution::local::prepare_workdir;
use process_execution::{NamedCaches, Process, ProcessError};

lazy_static! {
    static ref NAILGUN_PORT_REGEX: Regex = Regex::new(r".*\s+port\s+(\d+)\.$").unwrap();
}

struct PoolEntry {
    fingerprint: NailgunProcessFingerprint,
    last_used: Instant,
    // Because `NailgunProcess` instances are started outside of the NailgunPool's lock, the inner
    // instance is an `Option`. But since they are started eagerly by the task that adds them to the
    // pool, any acquirer that encounters an empty instance here can assume that it died while
    // starting, and re-create it.
    //
    // This uses a `Mutex<Option<_>>` rather than something like `DoubleCheckedCell` because the
    // outer `Mutex` is used to track while the `NailgunProcess` is in use.
    //
    // See also: `NailgunProcessRef`.
    process: Arc<Mutex<Option<NailgunProcess>>>,
}

pub type Port = u16;

///
/// A NailgunPool contains a small Vec of running NailgunProcess instances, fingerprinted with the
/// request used to start them.
///
/// Mutations of the Vec are protected by a Mutex, but each NailgunProcess is also protected by its
/// own Mutex, which is used to track when the process is in use.
///
#[derive(Clone)]
pub struct NailgunPool {
    workdir_base: PathBuf,
    size: usize,
    sema: Arc<Semaphore>,
    store: Store,
    executor: Executor,
    processes: Arc<Mutex<Vec<PoolEntry>>>,
}

impl NailgunPool {
    pub fn new(workdir_base: PathBuf, size: usize, store: Store, executor: Executor) -> Self {
        NailgunPool {
            workdir_base,
            size,
            sema: Arc::new(Semaphore::new(size)),
            store,
            executor,
            processes: Arc::default(),
        }
    }

    pub fn workdir_base(&self) -> &Path {
        &self.workdir_base
    }

    ///
    /// Given a name and a `Process` configuration, return a port of a nailgun server running
    /// under that name and configuration.
    ///
    /// If the server is not running, or if it's running with a different configuration,
    /// this code will start a new server as a side effect.
    ///
    pub async fn acquire(
        &self,
        server_process: Process,
        named_caches: &NamedCaches,
        immutable_inputs: &ImmutableInputs,
    ) -> Result<BorrowedNailgunProcess, ProcessError> {
        let name = server_process.description.clone();
        let requested_fingerprint =
            NailgunProcessFingerprint::new(name.clone(), &server_process, &self.store).await?;
        let semaphore_acquisition = self.sema.clone().acquire_owned();
        let permit = in_workunit!(
            "acquire_nailgun_process",
            // TODO: See also `acquire_command_runner_slot` in `bounded::CommandRunner`.
            // https://github.com/pantsbuild/pants/issues/14680
            Level::Debug,
            |workunit| async move {
                let _blocking_token = workunit.blocking();
                semaphore_acquisition
                    .await
                    .expect("Semaphore should not have been closed.")
            }
        )
        .await;

        let mut process_ref = {
            let mut processes = self.processes.lock().await;

            // Start by seeing whether there are any idle processes with a matching fingerprint.
            if let Some((_idx, process)) =
                Self::find_usable(&mut processes, &requested_fingerprint)?
            {
                return Ok(BorrowedNailgunProcess::new(process, permit));
            }

            // There wasn't a matching, valid, available process. We need to start one.
            if processes.len() >= self.size {
                // Find the oldest idle non-matching process and remove it.
                let idx = Self::find_lru_idle(&mut processes)?.ok_or_else(|| {
                    // NB: We've acquired a semaphore permit, so this should be impossible.
                    "No idle slots in nailgun pool.".to_owned()
                })?;

                processes.swap_remove(idx);
            }

            // Add a new entry for the process, and immediately acquire its mutex, but wait to spawn it
            // until we're outside the pool's mutex.
            let process = Arc::new(Mutex::new(None));
            processes.push(PoolEntry {
                fingerprint: requested_fingerprint.clone(),
                last_used: Instant::now(),
                process: process.clone(),
            });
            process.lock_arc().await
        };

        // Now that we're outside the pool's mutex, spawn and return the process.
        *process_ref = Some(
            NailgunProcess::start_new(
                name.clone(),
                server_process,
                &self.workdir_base,
                &self.store,
                self.executor.clone(),
                named_caches,
                immutable_inputs,
                requested_fingerprint,
            )
            .await?,
        );

        Ok(BorrowedNailgunProcess::new(process_ref, permit))
    }

    ///
    /// Find a usable process in the pool that matches the given fingerprint.
    ///
    fn find_usable(
        pool_entries: &mut Vec<PoolEntry>,
        fingerprint: &NailgunProcessFingerprint,
    ) -> Result<Option<(usize, NailgunProcessRef)>, String> {
        let mut dead_processes = Vec::new();
        for (idx, pool_entry) in pool_entries.iter_mut().enumerate() {
            if &pool_entry.fingerprint != fingerprint {
                continue;
            }

            match Self::try_use(pool_entry)? {
                TryUse::Usable(process) => return Ok(Some((idx, process))),
                TryUse::Dead => dead_processes.push(idx),
                TryUse::Busy => continue,
            }
        }
        // NB: We'll only prune dead processes if we don't find a live match, but that's fine.
        for dead_process_idx in dead_processes.into_iter().rev() {
            pool_entries.swap_remove(dead_process_idx);
        }
        Ok(None)
    }

    ///
    /// Find the least recently used idle (but not necessarily usable) process in the pool.
    ///
    fn find_lru_idle(pool_entries: &mut [PoolEntry]) -> Result<Option<usize>, String> {
        // 24 hours of clock skew would be surprising?
        let mut lru_age = Instant::now() + Duration::from_secs(60 * 60 * 24);
        let mut lru = None;
        for (idx, pool_entry) in pool_entries.iter_mut().enumerate() {
            if pool_entry.process.try_lock_arc().is_some() && pool_entry.last_used < lru_age {
                lru = Some(idx);
                lru_age = pool_entry.last_used;
            }
        }
        Ok(lru)
    }

    fn try_use(pool_entry: &mut PoolEntry) -> Result<TryUse, String> {
        let mut process_guard = if let Some(process_guard) = pool_entry.process.try_lock_arc() {
            process_guard
        } else {
            return Ok(TryUse::Busy);
        };
        let process = if let Some(process) = process_guard.as_mut() {
            process
        } else {
            return Ok(TryUse::Dead);
        };

        pool_entry.last_used = Instant::now();

        debug!(
            "Checking if nailgun server {} is still alive at port {}...",
            process.name, process.port
        );

        // Check if it's alive using the handle.
        let status = process
            .handle
            .try_wait()
            .map_err(|e| format!("Error getting the process status from nailgun: {e}"))?;
        match status {
            None => {
                // Process hasn't exited yet.
                debug!(
                    "Found nailgun process {}, with fingerprint {:?}",
                    process.name, process.fingerprint
                );
                Ok(TryUse::Usable(process_guard))
            }
            Some(status) => {
                // The process has exited with some exit code: restart it.
                if status.signal() != Some(9) {
                    // TODO: BorrowedNailgunProcess cancellation uses `kill` currently, so we avoid warning
                    // for that. In future it would be nice to find a better cancellation strategy.
                    log::warn!(
                        "The nailgun server for {} exited with {}.",
                        process.name,
                        status
                    );
                }
                Ok(TryUse::Dead)
            }
        }
    }
}

/// A borrowed `PoolEntry::process` which has already been validated to be present: see those docs.
///
/// TODO: This Mutex does not have a `map` method to allow converting this into a
/// `MutexGuardArc<NailgunProcess>`, although that would be useful here.
type NailgunProcessRef = MutexGuardArc<Option<NailgunProcess>>;

enum TryUse {
    Usable(NailgunProcessRef),
    Busy,
    Dead,
}

/// Representation of a running nailgun server.
pub struct NailgunProcess {
    pub name: String,
    fingerprint: NailgunProcessFingerprint,
    workdir: TempDir,
    workdir_include_names: HashSet<OsString>,
    port: Port,
    executor: task_executor::Executor,
    handle: std::process::Child,
}

/// Spawn a nailgun process, and read its port from stdout.
///
/// NB: Uses blocking APIs, so should be backgrounded on an executor.
fn spawn_and_read_port(
    process: Process,
    workdir: PathBuf,
) -> Result<(std::process::Child, Port), String> {
    let cmd = process.argv[0].clone();
    // TODO: This is an expensive operation, and thus we info! it.
    //       If it becomes annoying, we can downgrade the logging to just debug!
    info!(
        "Starting new nailgun server with cmd: {:?}, args {:?}, in cwd {}",
        cmd,
        &process.argv[1..],
        workdir.display()
    );

    let mut child = std::process::Command::new(&cmd)
        .args(&process.argv[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env_clear()
        .envs(&process.env)
        .current_dir(&workdir)
        .spawn()
        .map_err(|e| {
            format!(
                "Failed to create child handle for nailgun with cmd: {} options {:#?}: {}",
                &cmd, &process, e
            )
        })?;

    let stdout = child
        .stdout
        .as_mut()
        .ok_or_else(|| "No stdout found!".to_string());
    let port_line = stdout
        .and_then(|stdout| {
            let reader = io::BufReader::new(stdout);
            reader
                .lines()
                .next()
                .ok_or_else(|| "There is no line ready in the child's output".to_string())
        })
        .and_then(|res| res.map_err(|e| format!("Failed to read stdout from nailgun: {e}")));

    // If we failed to read a port line and the child has exited, report that.
    if port_line.is_err() {
        if let Some(exit_status) = child.try_wait().map_err(|e| e.to_string())? {
            let mut stderr = String::new();
            child
                .stderr
                .take()
                .unwrap()
                .read_to_string(&mut stderr)
                .map_err(|e| e.to_string())?;
            return Err(format!(
                "Nailgun failed to start: exited with {exit_status}, stderr:\n{stderr}"
            ));
        }
    }
    let port_line = port_line?;

    let port_str = &NAILGUN_PORT_REGEX
        .captures_iter(&port_line)
        .next()
        .ok_or_else(|| format!("Output for nailgun server was unexpected:\n{port_line:?}"))?[1];
    let port = port_str
        .parse::<Port>()
        .map_err(|e| format!("Error parsing nailgun port {port_str}: {e}"))?;

    Ok((child, port))
}

impl NailgunProcess {
    async fn start_new(
        name: String,
        startup_options: Process,
        workdir_base: &Path,
        store: &Store,
        executor: Executor,
        named_caches: &NamedCaches,
        immutable_inputs: &ImmutableInputs,
        nailgun_server_fingerprint: NailgunProcessFingerprint,
    ) -> Result<NailgunProcess, ProcessError> {
        let workdir = tempfile::Builder::new()
            .prefix("pants-sandbox-")
            .tempdir_in(workdir_base)
            .map_err(|err| format!("Error making tempdir for nailgun server: {err:?}"))?;

        // Prepare the workdir, and then list it to identify the base set of names which should be
        // preserved across runs. TODO: This is less efficient than computing the set of names
        // directly from the Process (or returning them from `prepare_workdir`), but it's also much
        // simpler.
        prepare_workdir(
            workdir.path().to_owned(),
            workdir_base,
            &startup_options,
            startup_options.input_digests.inputs.clone(),
            store,
            named_caches,
            immutable_inputs,
            None,
            None,
        )
        .await?;
        let workdir_include_names = list_workdir(workdir.path()).await?;

        // Spawn the process and read its port from stdout.
        let (child, port) = executor
            .spawn_blocking(
                {
                    let workdir = workdir.path().to_owned();
                    move || spawn_and_read_port(startup_options, workdir)
                },
                |e| Err(format!("Nailgun spawn task failed: {e}")),
            )
            .await?;
        debug!(
            "Created nailgun server process with pid {} and port {}",
            child.id(),
            port
        );

        Ok(NailgunProcess {
            port,
            fingerprint: nailgun_server_fingerprint,
            workdir,
            workdir_include_names,
            name,
            executor,
            handle: child,
        })
    }
}

impl Drop for NailgunProcess {
    fn drop(&mut self) {
        debug!("Exiting nailgun server process {:?}", self.name);
        if self.handle.kill().is_ok() {
            // NB: This is blocking, but should be a short wait in general.
            let _ = self.handle.wait();
        }
    }
}

/// The fingerprint of an nailgun server process.
///
/// This is calculated by hashing together:
///   - The jvm options and classpath used to create the server
///   - The path to the jdk
#[derive(Clone, Hash, PartialEq, Eq, Debug)]
struct NailgunProcessFingerprint {
    pub name: String,
    pub fingerprint: Fingerprint,
}

impl NailgunProcessFingerprint {
    pub async fn new(name: String, nailgun_req: &Process, store: &Store) -> Result<Self, String> {
        let nailgun_req_digest =
            process_execution::get_digest(nailgun_req, None, None, store, None).await;
        Ok(NailgunProcessFingerprint {
            name,
            fingerprint: nailgun_req_digest.hash,
        })
    }
}

///
/// A wrapper around a NailgunProcess checked out from the pool. If `release` is not called, the
/// guard assumes cancellation, and kills the underlying process.
///
pub struct BorrowedNailgunProcess(
    Option<NailgunProcessRef>,
    #[allow(dead_code)] OwnedSemaphorePermit,
);

impl BorrowedNailgunProcess {
    fn new(process: NailgunProcessRef, permit: OwnedSemaphorePermit) -> Self {
        assert!(process.is_some());
        Self(Some(process), permit)
    }

    pub fn name(&self) -> &str {
        &self.0.as_ref().unwrap().as_ref().unwrap().name
    }

    pub fn port(&self) -> u16 {
        self.0.as_ref().unwrap().as_ref().unwrap().port
    }

    pub fn address(&self) -> SocketAddr {
        SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), self.port())
    }

    pub fn workdir_path(&self) -> &Path {
        self.0.as_ref().unwrap().as_ref().unwrap().workdir.path()
    }

    ///
    /// Return the NailgunProcess to the pool.
    ///
    /// Clears the working directory for the process before returning it.
    ///
    pub async fn release(&mut self) -> Result<(), String> {
        let process = self
            .0
            .as_ref()
            .expect("release may only be called once.")
            .as_ref()
            .unwrap();

        clear_workdir(
            &process.executor,
            process.workdir.path(),
            &process.workdir_include_names,
        )
        .await?;

        // Once we've successfully cleaned up, remove the process.
        let _ = self.0.take();
        Ok(())
    }
}

impl Drop for BorrowedNailgunProcess {
    fn drop(&mut self) {
        if let Some(mut process) = self.0.take() {
            // Kill the process, but rely on the pool to notice that it is dead and restart it.
            debug!(
                "Killing nailgun process {:?} due to cancellation.",
                process.as_ref().unwrap().name
            );
            if process.as_mut().unwrap().handle.kill().is_ok() {
                // NB: This is blocking, but should be a short wait in general.
                let _ = process.as_mut().unwrap().handle.wait();
            }
        }
    }
}

async fn clear_workdir(
    executor: &Executor,
    workdir: &Path,
    exclude_names: &HashSet<OsString>,
) -> Result<(), String> {
    // Move all content into a temporary directory.
    let garbage_dir = tempfile::Builder::new()
        .prefix("pants-sandbox-")
        .tempdir_in(workdir.parent().unwrap())
        .map_err(|err| format!("Error making garbage directory for nailgun cleanup: {err:?}"))?;
    let moves = list_workdir(workdir)
        .await?
        .into_iter()
        .filter(|n| !exclude_names.contains(n))
        .map(|name| async {
            tokio::fs::rename(workdir.join(&name), garbage_dir.path().join(&name))
                .await
                .map_err(|e| {
                    format!(
                        "Failed to move {} to garbage: {}",
                        workdir.join(name).display(),
                        e
                    )
                })
        })
        .collect::<Vec<_>>();
    future::try_join_all(moves).await?;

    // And drop it in the background.
    let fut = executor.native_spawn_blocking(move || std::mem::drop(garbage_dir));
    drop(fut);

    Ok(())
}

async fn list_workdir(workdir: &Path) -> Result<HashSet<OsString>, String> {
    let mut dir_entries = tokio::fs::read_dir(workdir)
        .await
        .map_err(|e| format!("Failed to read nailgun process directory: {e}"))?;
    let mut names = HashSet::new();
    while let Some(dir_entry) = dir_entries
        .next_entry()
        .await
        .map_err(|e| format!("Failed to read entry in nailgun process directory: {e}"))?
    {
        names.insert(dir_entry.file_name());
    }
    Ok(names)
}
