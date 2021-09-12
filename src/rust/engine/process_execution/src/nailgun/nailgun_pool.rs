// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::io::{self, BufRead};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_lock::{Mutex, MutexGuardArc};
use hashing::{Digest, Fingerprint};
use lazy_static::lazy_static;
use log::{debug, info};
use regex::Regex;
use sha2::{Digest as Sha256Digest, Sha256};
use store::Store;
use tempfile::TempDir;

use crate::Process;

lazy_static! {
  static ref NAILGUN_PORT_REGEX: Regex = Regex::new(r".*\s+port\s+(\d+)\.$").unwrap();
}

struct PoolEntry {
  fingerprint: NailgunProcessFingerprint,
  last_used: Instant,
  process: Arc<Mutex<NailgunProcess>>,
}

pub type Port = usize;

///
/// A NailgunPool contains a small Vec of running NailgunProcess instances, fingerprinted with the
/// request used to start them.
///
/// Mutations of the Vec are protected by a Mutex, but each NailgunProcess is also protected by its
/// own Mutex, which is used to track when the process is in use.
///
/// NB: This pool expects to be used under a semaphore with size equal to the pool size. Because of
/// this, it never actually waits for a pool entry to complete, and can instead assume that at
/// least one pool slot is always idle when `acquire` is entered.
///
#[derive(Clone)]
pub struct NailgunPool {
  workdir_base: PathBuf,
  size: usize,
  processes: Arc<Mutex<Vec<PoolEntry>>>,
}

impl NailgunPool {
  pub fn new(workdir_base: PathBuf, size: usize) -> Self {
    NailgunPool {
      workdir_base,
      size,
      processes: Arc::default(),
    }
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
    name: String,
    startup_options: Process,
    nailgun_req_digest: Digest,
    store: Store,
    input_files: Digest,
  ) -> Result<MutexGuardArc<NailgunProcess>, String> {
    let jdk_path = startup_options.jdk_home.clone().ok_or_else(|| {
      format!(
        "jdk_home is not set for nailgun server startup request {:#?}",
        &startup_options
      )
    })?;
    let requested_fingerprint =
      NailgunProcessFingerprint::new(name.clone(), nailgun_req_digest, jdk_path.clone())?;
    let mut processes = self.processes.lock().await;

    // Start by seeing whether there are any idle processes with a matching fingerprint.
    if let Some((_idx, process)) = Self::find_usable(&mut *processes, &requested_fingerprint)? {
      return Ok(process);
    }

    // There wasn't a matching, valid, available process. We need to start one.
    if processes.len() >= self.size {
      // Find the oldest idle non-matching process and remove it.
      let idx = Self::find_lru_idle(&mut *processes)?.ok_or_else(|| {
        // NB: See the method docs: the pool assumes that it is running under a semaphore, so this
        // should be impossible.
        "No idle slots in nailgun pool.".to_owned()
      })?;

      processes.swap_remove(idx);
    }

    // Start the new process.
    let process = Arc::new(Mutex::new(
      NailgunProcess::start_new(
        name.clone(),
        startup_options,
        &self.workdir_base,
        store,
        requested_fingerprint.clone(),
        input_files,
      )
      .await?,
    ));
    processes.push(PoolEntry {
      fingerprint: requested_fingerprint,
      last_used: Instant::now(),
      process: process.clone(),
    });

    Ok(process.lock_arc().await)
  }

  ///
  /// Find a usable process in the pool that matches the given fingerprint.
  ///
  fn find_usable(
    pool_entries: &mut Vec<PoolEntry>,
    fingerprint: &NailgunProcessFingerprint,
  ) -> Result<Option<(usize, MutexGuardArc<NailgunProcess>)>, String> {
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
  fn find_lru_idle(pool_entries: &mut Vec<PoolEntry>) -> Result<Option<usize>, String> {
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
    let mut process = if let Some(process) = pool_entry.process.try_lock_arc() {
      process
    } else {
      return Ok(TryUse::Busy);
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
      .map_err(|e| format!("Error getting the process status! {}", e))?;
    match status {
      None => {
        // Process hasn't exited yet.
        debug!(
          "Found nailgun process {}, with fingerprint {:?}",
          process.name, process.fingerprint
        );
        Ok(TryUse::Usable(process))
      }
      Some(x) => {
        // The process has exited with some exit code: restart it.
        log::warn!(
          "The nailgun server for {} exited with {}. Restarting process...",
          process.name,
          x
        );
        Ok(TryUse::Dead)
      }
    }
  }
}

enum TryUse {
  Usable(MutexGuardArc<NailgunProcess>),
  Busy,
  Dead,
}

/// Representation of a running nailgun server.
pub struct NailgunProcess {
  pub name: String,
  fingerprint: NailgunProcessFingerprint,
  workdir: TempDir,
  port: Port,
  handle: std::process::Child,
}

fn read_port(child: &mut std::process::Child) -> Result<Port, String> {
  let stdout = child
    .stdout
    .as_mut()
    .ok_or_else(|| "No Stdout found!".to_string());
  stdout.and_then(|stdout| {
    let reader = io::BufReader::new(stdout);
    let line = reader
      .lines()
      .next()
      .ok_or("There is no line ready in the child's output")?
      .map_err(|err| format!("{}", err))?;
    let port = &NAILGUN_PORT_REGEX
      .captures_iter(&line)
      .next()
      .ok_or("Output for nailgun server didn't match the regex!")?[1];
    port
      .parse::<Port>()
      .map_err(|e| format!("Error parsing port {}! {}", &port, e))
  })
}

impl NailgunProcess {
  pub fn address(&self) -> SocketAddr {
    format!("127.0.0.1:{:?}", self.port).parse().unwrap()
  }

  pub fn workdir_path(&self) -> &Path {
    self.workdir.path()
  }

  async fn start_new(
    name: String,
    startup_options: Process,
    workdir_base: &Path,
    store: Store,
    nailgun_server_fingerprint: NailgunProcessFingerprint,
    input_files: Digest,
  ) -> Result<NailgunProcess, String> {
    let workdir = tempfile::Builder::new()
      .prefix("process-execution")
      .tempdir_in(workdir_base)
      .map_err(|err| format!("Error making tempdir for nailgun server: {:?}", err))?;

    // TODO(#8481) This materializes the input files in the client req, which is a superset of the files we need (we only need the classpath, not the input files)
    store
      .materialize_directory(workdir.path().to_owned(), input_files)
      .await?;

    let cmd = startup_options.argv[0].clone();
    // TODO: This is an expensive operation, and thus we info! it.
    //       If it becomes annoying, we can downgrade the logging to just debug!
    info!(
      "Starting new nailgun server with cmd: {:?}, args {:?}, in cwd {:?}",
      cmd,
      &startup_options.argv[1..],
      workdir.path()
    );
    let mut child = std::process::Command::new(&cmd)
      .args(&startup_options.argv[1..])
      .stdout(Stdio::piped())
      .stderr(Stdio::piped())
      .current_dir(&workdir)
      .spawn()
      .map_err(|e| {
        format!(
          "Failed to create child handle with cmd: {} options {:#?}: {}",
          &cmd, &startup_options, e
        )
      })?;

    let port = read_port(&mut child)?;
    debug!(
      "Created nailgun server process with pid {} and port {}",
      child.id(),
      port
    );

    Ok(NailgunProcess {
      port,
      fingerprint: nailgun_server_fingerprint,
      workdir,
      name,
      handle: child,
    })
  }
}

impl Drop for NailgunProcess {
  fn drop(&mut self) {
    debug!("Exiting nailgun server process {:?}", self.name);
    // TODO: Probably needs to `wait` to avoid zombies.
    let _ = self.handle.kill();
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
  pub fn new(
    name: String,
    nailgun_server_req_digest: Digest,
    jdk_path: PathBuf,
  ) -> Result<Self, String> {
    let jdk_realpath = jdk_path
      .canonicalize()
      .map_err(|err| format!("Error getting the realpath of the jdk home: {}", err))?;

    let mut hasher = Sha256::default();
    hasher.update(nailgun_server_req_digest.hash);
    hasher.update(jdk_realpath.to_string_lossy().as_bytes());

    Ok(NailgunProcessFingerprint {
      name,
      fingerprint: Fingerprint::from_bytes(hasher.finalize()),
    })
  }
}
