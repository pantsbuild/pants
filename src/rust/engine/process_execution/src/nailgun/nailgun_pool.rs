// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::fs::{read_link, remove_file};
use std::io::BufReader;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use boxfuture::{try_future, BoxFuture, Boxable};
use futures::future::{self, Future, Loop};
use futures::stream::Stream;
use futures_locks::{self, Mutex, MutexGuard};
use log::{debug, info};
use parking_lot;
use regex::Regex;

use hashing::{Digest, Fingerprint};
use lazy_static::lazy_static;

use crate::ExecuteProcessRequest;
use digest::Digest as DigestTrait;
use sha2::Sha256;
use store::Store;
use workunit_store::WorkUnitStore;

use tokio::fs;
use tokio::io::lines;
use tokio_timer::sleep;

lazy_static! {
  static ref NAILGUN_PORT_REGEX: Regex = Regex::new(r".*\s+port\s+(\d+)\.$").unwrap();
}

static MAX_PROCESS_OUTPUT_POLLS: usize = 10;

pub type NailgunProcessName = String;
type NailgunProcessMap = HashMap<NailgunProcessName, Mutex<NailgunProcess>>;
pub type Port = usize;

#[derive(Clone)]
pub struct NailgunPool {
  processes: Mutex<NailgunProcessMap>,
}

impl NailgunPool {
  pub fn new() -> Self {
    NailgunPool {
      processes: Mutex::new(NailgunProcessMap::new()),
    }
  }

  // TODO(#8481) When we correctly set the input_files field of the nailgun EPR, we won't need to pass it here as an argument.
  pub fn materialize_workdir_for_server(
    store: Store,
    workdir_for_server: PathBuf,
    requested_jdk_home: PathBuf,
    input_files: Digest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<(), String> {
    // Materialize the directory for running the nailgun server, if we need to.
    let workdir_for_server2 = workdir_for_server.clone();

    // TODO(#8481) This materializes the input files in the client req, which is a superset of the files we need (we only need the classpath, not the input files)
    store.materialize_directory(workdir_for_server.clone(), input_files, workunit_store)
    .and_then(move |_metadata| {
      let jdk_home_in_workdir = &workdir_for_server.clone().join(".jdk");
      let jdk_home_in_workdir2 = jdk_home_in_workdir.clone();
      let jdk_home_in_workdir3 = jdk_home_in_workdir.clone();
      if jdk_home_in_workdir.exists() {
        let maybe_existing_jdk = read_link(jdk_home_in_workdir).map_err(|e| format!("{}", e));
        let maybe_existing_jdk2 = maybe_existing_jdk.clone();
        if maybe_existing_jdk.is_err() || (maybe_existing_jdk.is_ok() && maybe_existing_jdk.unwrap() != requested_jdk_home) {
          remove_file(jdk_home_in_workdir2)
              .map_err(|err| format!(
                "Error removing existing (but incorrect) jdk symlink. We wanted it to point to {:?}, but it pointed to {:?}. {}",
                &requested_jdk_home, &maybe_existing_jdk2, err
              ))
              .and_then(|_| {
                symlink(requested_jdk_home, jdk_home_in_workdir3)
                    .map_err(|err| format!("Error overwriting symlink for local execution in workdir {:?}: {:?}", &workdir_for_server, err))
              })
        } else {
          debug!("JDK home for Nailgun already exists in {:?}. Using that one.", &workdir_for_server);
          Ok(())
        }
      } else {
        symlink(requested_jdk_home, jdk_home_in_workdir)
            .map_err(|err| format!("Error making new symlink for local execution in workdir {:?}: {:?}", &workdir_for_server, err))
      }
    })
    .inspect(move |_| debug!("Materialized directory {:?} before connecting to nailgun server.", &workdir_for_server2))
    .to_boxed()
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
    workdir_path: PathBuf,
    nailgun_req_digest: Digest,
    build_id_requesting_connection: String,
    store: Store,
    input_files: Digest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<(Port, futures_locks::MutexGuard<NailgunProcess>), String> {
    let jdk_path = try_future!(startup_options.jdk_home.clone().ok_or_else(|| {
      format!(
        "jdk_home is not set for nailgun server startup request {:#?}",
        &startup_options
      )
    }));
    let requested_server_fingerprint = try_future!(NailgunProcessFingerprint::new(
      nailgun_req_digest,
      jdk_path.clone()
    ));

    let processes = self.processes.clone();
    processes.lock()
      .map_err(|e| format!("Failed to lock processes Mutex: {:?}", e))
      .and_then(move |mut processes| {
        let connection_result = if let Some(process) = processes.get_mut(&name) {
          // Clone some fields that we need for later
          process.lock()
            .map_err(|e| format!("Failed to lock NailgunProcess Mutex: {:?}", e))
            .and_then(move |process| {
            let (process_name, process_fingerprint, process_port, build_id_that_started_the_server) = (
              process.name.clone(),
              process.fingerprint.clone(),
              process.port,
              process.build_id.clone(),
            );

            debug!(
              "Checking if nailgun server {} is still alive at port {}...",
              &process_name, process_port
            );

            // If the process is in the map, check if it's alive using the handle.
            let status = process
                .handle
                .lock()
                .try_wait()
                .map_err(|e| format!("Error getting the process status: {}", e))
                .clone();
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
                  future::ok((process_port, process)).to_boxed()
                } else {
                  // The running process doesn't coincide with the options we want.
                  if build_id_that_started_the_server == build_id_requesting_connection {
                    future::err(format!(
                      "Trying to change the JVM options for a running nailgun server that was started this run, with name {}.\
                        There is exactly one nailgun server per task, so it shouldn't be possible to change the options of a nailgun server mid-run.\
                        This might be a problem with how we calculate the keys of nailgun servers (https://github.com/pantsbuild/pants/issues/8527).",
                      &name)
                    ).to_boxed()
                  } else {
                    // Restart it.
                    // Since the stored server was started in a different pants run,
                    // no client will be running on that server.
                    debug!(
                      "The options for server process {} are different to the startup_options, \
                      and the original process was started in a different pants run.\n\
                      Startup Options: {:?}\n Process Cmd: {:?}",
                      &process_name, startup_options, process_fingerprint
                    );
                    debug!("Restarting the server...");
                    Self::start_new_nailgun(
                      processes,
                      name,
                      startup_options,
                      workdir_path,
                      requested_server_fingerprint,
                      build_id_requesting_connection,
                      store,
                      input_files,
                      workunit_store,
                      jdk_path,
                    ).to_boxed()
                  }
                }
              }
              Ok(_) => {
                // The process has exited with some exit code
                debug!("The requested nailgun server was not running anymore. Restarting process...");
                Self::start_new_nailgun(
                  processes,
                  name,
                  startup_options,
                  workdir_path,
                  requested_server_fingerprint,
                  build_id_requesting_connection,
                  store,
                  input_files,
                  workunit_store,
                  jdk_path,
                ).to_boxed()
              }
              Err(e) => future::err(e).to_boxed(),
            }
          }).to_boxed()
        } else {
          // We don't have a running nailgun registered in the map.
          debug!(
            "No nailgun server is running with name {}. Starting one...",
            &name
          );
          Self::start_new_nailgun(
            processes,
            name,
            startup_options,
            workdir_path,
            requested_server_fingerprint,
            build_id_requesting_connection,
            store,
            input_files,
            workunit_store,
            jdk_path,
          ).to_boxed()
        };
        debug!("Unlocking nailgun process pool.");
        connection_result
    }).to_boxed()
  }

  fn start_new_nailgun(
    mut processes: MutexGuard<NailgunProcessMap>,
    name: String,
    startup_options: ExecuteProcessRequest,
    workdir_path: PathBuf,
    nailgun_server_fingerprint: NailgunProcessFingerprint,
    build_id: String,
    store: Store,
    input_files: Digest,
    workunit_store: WorkUnitStore,
    jdk_path: PathBuf,
  ) -> BoxFuture<(Port, MutexGuard<NailgunProcess>), String> {
    debug!(
      "Starting new nailgun server for {}, with options {:?}",
      &name, &startup_options
    );
    // TODO materialize workdir for server here.
    Self::materialize_workdir_for_server(
      store,
      workdir_path.clone(),
      jdk_path,
      input_files,
      workunit_store,
    )
    .and_then({
      let name = name.clone();
      |_| {
        NailgunProcess::start_new(
          name,
          startup_options,
          workdir_path,
          nailgun_server_fingerprint,
          build_id,
        )
      }
    })
    .map({
      let name = name.clone();
      move |process| {
        let port = process.port;
        let new_nailgun = Mutex::new(process);
        let nailgun_guard = new_nailgun
          .try_lock()
          .expect("We just created this nailgun, no one else can have locked it");
        processes.insert(name, new_nailgun);
        (port, nailgun_guard)
      }
    })
    .to_boxed()
  }
}

/// Representation of a running nailgun server.
#[derive(Debug)]
pub struct NailgunProcess {
  pub name: NailgunProcessName,
  pub fingerprint: NailgunProcessFingerprint,
  pub build_id: String,
  pub port: Port,
  pub handle: Arc<parking_lot::Mutex<std::process::Child>>,
}

fn read_port(stdout: PathBuf) -> BoxFuture<Port, String> {
  future::loop_fn(MAX_PROCESS_OUTPUT_POLLS, move |mut loops| {
    let stdout = stdout.clone();
    let wait_period = Duration::from_millis(100);
    sleep(wait_period)
      .map_err(|e| format!("sleep while waiting for nailgun stdout failed: {:?}", e))
      .and_then(move |_| {
        fs::File::open(stdout.clone()).map_err(move |_| format!("Could not open file {:?}", stdout))
      })
      .and_then(|log| {
        lines(BufReader::new(log))
          .take(1)
          .into_future()
          .map_err(|(err, _s)| format!("Error getting file line in read port {}", err))
      })
      .and_then(move |(line, _)| {
        if let Some(s) = line {
          debug!("Nailgun process startup output is: `{:?}`", s);
          Ok(Loop::Break(Ok(s)))
        } else {
          loops -= 1;
          if loops == 0 {
            Ok(Loop::Break(Err(
              "Couldn't read a line from nailgun".to_string(),
            )))
          } else {
            Ok(Loop::Continue(loops))
          }
        }
      })
  })
  .and_then(|line| {
    info!("DEBUG_NAILGUN start output is {:?}", line);
    match line {
      Ok(s) => {
        let port = &NAILGUN_PORT_REGEX.captures_iter(s.trim()).next();
        match port {
          Some(port) => port[1]
            .parse::<Port>()
            .map_err(|e| format!("Error parsing port {}! {}", &port[1], e)),
          None => Err("Output for nailgun server didn't match the regex!".to_string()),
        }
      }
      Err(e) => Err(format!("Error reading nailgun startup stdout: {:?}.", e)),
    }
  })
  .to_boxed()
}

impl NailgunProcess {
  fn create_output_file(server_workdir: PathBuf, name: String) -> BoxFuture<fs::File, String> {
    let fname = Self::process_output_path(server_workdir, name);
    tokio::fs::File::create(fname.clone())
      .map_err(move |e| format!("Failed to open file {:?} for reading {:?}", fname, e))
      .to_boxed()
  }

  fn process_output_path(server_workdir: PathBuf, name: String) -> PathBuf {
    server_workdir.clone().join(name)
  }

  fn start_new(
    name: NailgunProcessName,
    startup_options: ExecuteProcessRequest,
    workdir_path: PathBuf,
    nailgun_server_fingerprint: NailgunProcessFingerprint,
    build_id: String,
  ) -> BoxFuture<NailgunProcess, String> {
    let cmd = startup_options.argv[0].clone();
    // TODO: This is an expensive operation, and thus we info! it.
    //       If it becomes annoying, we can downgrade the logging to just debug!
    info!(
      "Starting new nailgun server with cmd: {:?}, args {:?}, in cwd {:?}",
      cmd,
      &startup_options.argv[1..],
      &workdir_path
    );
    Self::create_output_file(workdir_path.clone(), "stdout.log".to_string())
      .join(Self::create_output_file(
        workdir_path.clone(),
        "stderr.log".to_string(),
      ))
      .and_then({
        let workdir_path = workdir_path.clone();
        move |(stdout, stderr)| {
          let handle = std::process::Command::new(&cmd)
            .args(&startup_options.argv[1..])
            .stdout(stdout.into_std())
            .stderr(stderr.into_std())
            .current_dir(workdir_path)
            .spawn();
          handle.map_err(|e| {
            format!(
              "Failed to create child handle with cmd: {} options {:#?}: {}",
              &cmd, &startup_options, e
            )
          })
        }
      })
      .and_then(move |child| {
        let stdout_file_path =
          Self::process_output_path(workdir_path.clone(), "stdout.log".to_string());
        read_port(stdout_file_path).map(|port| (child, port))
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
          handle: Arc::new(parking_lot::Mutex::new(child)),
          build_id: build_id,
        })
      })
      .to_boxed()
  }
}

impl Drop for NailgunProcess {
  fn drop(&mut self) {
    let _ = self.handle.lock().kill();
  }
}

/// The fingerprint of an nailgun server process.
///
/// This is calculated by hashing together:
///   - The jvm options and classpath used to create the server
///   - The path to the jdk
#[derive(Clone, Hash, PartialEq, Eq, Debug)]
pub struct NailgunProcessFingerprint(pub Fingerprint);

impl NailgunProcessFingerprint {
  pub fn new(nailgun_server_req_digest: Digest, jdk_path: PathBuf) -> Result<Self, String> {
    let jdk_realpath = jdk_path
      .canonicalize()
      .map_err(|err| format!("Error getting the realpath of the jdk home: {}", err))?;

    let mut hasher = Sha256::default();
    hasher.input(nailgun_server_req_digest.0);
    hasher.input(jdk_realpath.to_string_lossy().as_bytes());
    Ok(NailgunProcessFingerprint(Fingerprint::from_bytes_unsafe(
      &hasher.result(),
    )))
  }
}
