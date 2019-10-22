// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::io;
use std::io::BufRead;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;

use log::{debug, info, trace};
use parking_lot::Mutex;
use regex::Regex;

use hashing::{Digest, Fingerprint};
use lazy_static::lazy_static;

use crate::ExecuteProcessRequest;
use digest::Digest as DigestTrait;
use sha2::Sha256;

lazy_static! {
  static ref NAILGUN_PORT_REGEX: Regex = Regex::new(r".*\s+port\s+(\d+)\.$").unwrap();
}

pub type NailgunProcessName = String;
type NailgunProcessMap = HashMap<NailgunProcessName, NailgunProcess>;
pub type Port = usize;

#[derive(Clone)]
pub struct NailgunPool {
  processes: Arc<Mutex<NailgunProcessMap>>,
}

impl NailgunPool {
  pub fn new() -> Self {
    NailgunPool {
      processes: Arc::new(Mutex::new(NailgunProcessMap::new())),
    }
  }

  ///
  /// Given a `NailgunProcessName` and a `ExecuteProcessRequest` configuration,
  /// return a port of a nailgun server running under that name and configuration.
  ///
  /// If the server is not running, or if it's running with a different configuration,
  /// this code will start a new server as a side effect.
  ///
  pub fn connect(
    &self,
    name: NailgunProcessName,
    startup_options: ExecuteProcessRequest,
    workdir_path: &PathBuf,
    nailgun_req_digest: Digest,
  ) -> Result<Port, String> {
    trace!("Locking nailgun process pool so that only one can be connecting at a time.");
    let mut processes = self.processes.lock();

    let jdk_path = startup_options.jdk_home.clone().ok_or(format!(
      "jdk_home is not set for nailgun server startup request {:#?}",
      &startup_options
    ))?;
    let requested_server_fingerprint =
      NailgunProcessFingerprint::new(nailgun_req_digest, jdk_path)?;

    let maybe_process = processes.get_mut(&name);
    let connection_result = if let Some(process) = maybe_process {
      // Clone some fields that we need for later
      let (process_name, process_fingerprint, process_port) = (
        process.name.clone(),
        process.fingerprint.clone(),
        process.port,
      );

      debug!(
        "Checking if nailgun server {} is still alive at port {}...",
        &process_name, process_port
      );

      // If the process is in the map, check if it's alive using the handle.
      let status = {
        process
          .handle
          .lock()
          .try_wait()
          .map_err(|e| format!("Error getting the process status! {}", e))
          .clone()
      };
      match status {
        Ok(None) => {
          // Process hasn't exited yet
          debug!(
            "Found nailgun process {}, with fingerprint {:?}",
            &name, process_fingerprint
          );
          if requested_server_fingerprint == process_fingerprint {
            debug!("The fingerprint of the running nailgun {:?} matches the requested fingerprint {:?}. Connecting to existing server.",
                   requested_server_fingerprint, process_fingerprint);
            Ok(process_port)
          } else {
            // The running process doesn't coincide with the options we want.
            // Restart it.
            debug!("The options for process {} are different to the startup_options! \n Startup Options: {:?}\n Process Cmd: {:?}",
                               &process_name, startup_options, process_fingerprint
                        );
            self.start_new_nailgun(
              &mut *processes,
              name,
              startup_options,
              workdir_path,
              requested_server_fingerprint,
            )
          }
        }
        Ok(_) => {
          // The process has exited with some exit code
          debug!("The requested nailgun server was not running anymore. Restarting process...");
          self.start_new_nailgun(
            &mut *processes,
            name,
            startup_options,
            workdir_path,
            requested_server_fingerprint,
          )
        }
        Err(e) => Err(e),
      }
    } else {
      // We don't have a running nailgun registered in the map.
      debug!(
        "No nailgun server is running with name {}. Starting one...",
        &name
      );
      self.start_new_nailgun(
        &mut *processes,
        name,
        startup_options,
        workdir_path,
        requested_server_fingerprint,
      )
    };
    trace!("Unlocking nailgun process pool.");
    connection_result
  }

  fn start_new_nailgun(
    &self,
    processes: &mut NailgunProcessMap,
    name: String,
    startup_options: ExecuteProcessRequest,
    workdir_path: &PathBuf,
    nailgun_server_fingerprint: NailgunProcessFingerprint,
  ) -> Result<Port, String> {
    debug!(
      "Starting new nailgun server for {}, with options {:?}",
      &name, &startup_options
    );
    NailgunProcess::start_new(
      name.clone(),
      startup_options,
      workdir_path,
      nailgun_server_fingerprint,
    )
    .and_then(move |process| {
      let port = process.port;
      processes.insert(name.clone(), process);
      Ok(port)
    })
  }
}

/// Representation of a running nailgun server.
#[derive(Debug)]
pub struct NailgunProcess {
  pub name: NailgunProcessName,
  pub fingerprint: NailgunProcessFingerprint,
  pub port: Port,
  pub handle: Arc<Mutex<std::process::Child>>,
}

fn read_port(child: &mut std::process::Child) -> Result<Port, String> {
  let stdout = child.stdout.as_mut().ok_or(format!("No Stdout found!"));
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
  fn start_new(
    name: NailgunProcessName,
    startup_options: ExecuteProcessRequest,
    workdir_path: &PathBuf,
    nailgun_server_fingerprint: NailgunProcessFingerprint,
  ) -> Result<NailgunProcess, String> {
    let cmd = startup_options.argv[0].clone();
    // TODO: This is an expensive operation, and thus we info! it.
    //       If it becomes annoying, we can downgrade the logging to just debug!
    info!(
      "Starting new nailgun server with cmd: {:?}, args {:?}, in cwd {:?}",
      cmd,
      &startup_options.argv[1..],
      &workdir_path
    );
    let handle = std::process::Command::new(&cmd)
      .args(&startup_options.argv[1..])
      .stdout(Stdio::piped())
      .stderr(Stdio::piped())
      .current_dir(&workdir_path)
      .spawn();
    handle
      .map_err(|e| {
        format!(
          "Failed to create child handle with cmd: {} options {:#?}: {}",
          &cmd, &startup_options, e
        )
      })
      .and_then(|mut child| {
        let port = read_port(&mut child);
        port.map(|port| (child, port))
      })
      .and_then(|(child, port)| {
        debug!(
          "Created nailgun server process with pid {} and port {}",
          child.id(),
          port
        );
        Ok(NailgunProcess {
          port: port,
          fingerprint: nailgun_server_fingerprint,
          name: name,
          handle: Arc::new(Mutex::new(child)),
        })
      })
  }
}

impl Drop for NailgunProcess {
  fn drop(&mut self) {
    debug!("Exiting nailgun server process {:?}", self);
    let _ = self.handle.lock().kill();
  }
}

#[derive(Clone, Hash, PartialEq, Eq, Debug)]
pub struct NailgunProcessFingerprint(pub Fingerprint);

impl NailgunProcessFingerprint {
  pub fn new(nailgun_server_req_digest: Digest, jdk_path: PathBuf) -> Result<Self, String> {
    let jdk_version_output = std::process::Command::new(jdk_path.join("bin").join("java"))
      .arg("-version")
      .output()
      .map_err(|err| {
        format!(
          "Failed to get version of the jdk for fingerprinting {}",
          err
        )
      })?;

    let mut hasher = Sha256::default();
    hasher.input(nailgun_server_req_digest.0);
    hasher.input(jdk_path.to_string_lossy().as_bytes());
    hasher.input(jdk_version_output.stdout);
    Ok(NailgunProcessFingerprint(Fingerprint::from_bytes_unsafe(
      &hasher.result(),
    )))
  }
}
