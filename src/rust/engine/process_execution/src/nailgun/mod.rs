use std::collections::btree_map::BTreeMap;
use std::collections::btree_set::BTreeSet;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use boxfuture::{try_future, BoxFuture, Boxable};
use futures::future::Future;
use futures::stream::Stream;
use hashing::Digest;
use log::{debug, trace};
use nails::execution::{child_channel, ChildInput, ChildOutput, Command};
use tokio::net::TcpStream;

use crate::local::CapturedWorkdir;
use crate::nailgun::nailgun_pool::{NailgunProcessName, Port};
use crate::{
  Context, ExecuteProcessRequest, ExecuteProcessRequestMetadata, FallibleExecuteProcessResult,
  MultiPlatformExecuteProcessRequest, Platform,
};

#[cfg(test)]
pub mod tests;

pub mod nailgun_pool;

mod parsed_jvm_command_lines;
#[cfg(test)]
mod parsed_jvm_command_lines_tests;

use async_semaphore::AsyncSemaphore;
pub use nailgun_pool::NailgunPool;
use parsed_jvm_command_lines::ParsedJVMCommandLines;
use std::fs::{read_link, remove_file};
use std::net::SocketAddr;
use store::Store;
use workunit_store::WorkUnitStore;

// Hardcoded constants for connecting to nailgun
static NAILGUN_MAIN_CLASS: &str = "com.martiansoftware.nailgun.NGServer";
static ARGS_TO_START_NAILGUN: [&str; 1] = [":0"];

///
/// Constructs the ExecuteProcessRequest that would be used
/// to start the nailgun servers if we needed to.
///
// TODO(#8481) We should calculate the input_files by deeply fingerprinting the classpath.
fn construct_nailgun_server_request(
  nailgun_name: &str,
  args_for_the_jvm: Vec<String>,
  jdk: PathBuf,
  platform: Platform,
) -> ExecuteProcessRequest {
  let mut full_args = args_for_the_jvm;
  full_args.push(NAILGUN_MAIN_CLASS.to_string());
  full_args.extend(ARGS_TO_START_NAILGUN.iter().map(|a| a.to_string()));

  ExecuteProcessRequest {
    argv: full_args,
    env: BTreeMap::new(),
    input_files: hashing::EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Duration::new(1000, 0),
    description: format!("Start a nailgun server for {}", nailgun_name),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: Some(jdk),
    target_platform: platform,
    is_nailgunnable: true,
  }
}

fn construct_nailgun_client_request(
  original_req: ExecuteProcessRequest,
  client_main_class: String,
  mut client_args: Vec<String>,
) -> ExecuteProcessRequest {
  let ExecuteProcessRequest {
    argv: _argv,
    input_files,
    description,
    env: original_request_env,
    output_files,
    output_directories,
    timeout,
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule,
    jdk_home: _jdk_home,
    target_platform,
    is_nailgunnable,
  } = original_req;
  client_args.insert(0, client_main_class);
  ExecuteProcessRequest {
    argv: client_args,
    input_files,
    description,
    env: original_request_env,
    output_files,
    output_directories,
    timeout,
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule,
    jdk_home: None,
    target_platform,
    is_nailgunnable,
  }
}

///
/// A command runner that can run local requests under nailgun.
///
/// It should only be invoked with local requests.
/// It will read a flag marking an `ExecuteProcessRequest` as nailgunnable.
/// If that flag is set, it will connect to a running nailgun server and run the command there.
/// Otherwise, it will just delegate to the regular local runner.
///
pub struct CommandRunner {
  inner: Arc<super::local::CommandRunner>,
  nailgun_pool: NailgunPool,
  async_semaphore: async_semaphore::AsyncSemaphore,
  metadata: ExecuteProcessRequestMetadata,
  workdir_base: PathBuf,
  executor: task_executor::Executor,
}

impl CommandRunner {
  pub fn new(
    runner: crate::local::CommandRunner,
    metadata: ExecuteProcessRequestMetadata,
    workdir_base: PathBuf,
    executor: task_executor::Executor,
  ) -> Self {
    CommandRunner {
      inner: Arc::new(runner),
      nailgun_pool: NailgunPool::new(),
      async_semaphore: AsyncSemaphore::new(1),
      metadata: metadata,
      workdir_base: workdir_base,
      executor: executor,
    }
  }

  // Ensure that the workdir for the given nailgun name exists.
  fn get_nailgun_workdir(&self, nailgun_name: &str) -> Result<PathBuf, String> {
    let workdir = self.workdir_base.clone().join(nailgun_name);
    if workdir.exists() {
      debug!("Nailgun workdir {:?} exits. Reusing that...", &workdir);
      Ok(workdir)
    } else {
      debug!("Creating nailgun workdir at {:?}", &workdir);
      fs::safe_create_dir_all(&workdir)
        .map_err(|err| format!("Error creating the nailgun workdir! {}", err))
        .map(|_| workdir)
    }
  }

  // TODO(#8527) Make this name the name of the task (in v1) or some other more intentional scope (v2).
  //      Using the main class here is fragile, because two tasks might want to run the same main class,
  //      but in different nailgun servers.
  fn calculate_nailgun_name(main_class: &str) -> NailgunProcessName {
    format!("nailgun_server_{}", main_class)
  }

  // TODO(#8481) When we correctly set the input_files field of the nailgun EPR, we won't need to pass it here as an argument.
  // TODO(#8489) We should move this code to NailgunPool. This returns a Future, so this will involve making the struct Futures-aware.
  fn materialize_workdir_for_server(
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
}

impl super::CommandRunner for CommandRunner {
  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let nailgun_pool = self.nailgun_pool.clone();

    let original_request = self.extract_compatible_request(&req).unwrap();
    let original_request2 = original_request.clone();

    if !original_request.is_nailgunnable {
      trace!("The request is not nailgunnable! Short-circuiting to regular process execution");
      return self.inner.run(req, context);
    }
    debug!("Running request under nailgun:\n {:#?}", &original_request);

    // Separate argument lists, to form distinct EPRs for (1) starting the nailgun server and (2) running the client in it.
    let ParsedJVMCommandLines {
      nailgun_args,
      client_args,
      client_main_class,
    } = try_future!(ParsedJVMCommandLines::parse_command_lines(
      &original_request.argv
    ));

    let nailgun_name = CommandRunner::calculate_nailgun_name(&client_main_class);
    let nailgun_name2 = nailgun_name.clone();
    let nailgun_name3 = nailgun_name.clone();

    let jdk_home = try_future!(original_request
      .jdk_home
      .clone()
      .ok_or_else(|| "JDK home must be specified for all nailgunnable requests.".to_string()));
    let nailgun_req = construct_nailgun_server_request(
      &nailgun_name,
      nailgun_args,
      jdk_home.clone(),
      original_request.target_platform,
    );
    trace!("Extracted nailgun request:\n {:#?}", &nailgun_req);

    let nailgun_req_digest = crate::digest(
      MultiPlatformExecuteProcessRequest::from(nailgun_req.clone()),
      &self.metadata,
    );

    let workdir_for_this_nailgun = try_future!(self.get_nailgun_workdir(&nailgun_name));
    let workdir_for_this_nailgun1 = workdir_for_this_nailgun.clone();
    let workdir_for_this_nailgun2 = workdir_for_this_nailgun.clone();
    let executor = self.executor.clone();
    let executor2 = self.executor.clone();
    let build_id = context.build_id.clone();
    let store = self.inner.store.clone();
    let store2 = self.inner.store.clone();
    let workunit_store = context.workunit_store.clone();

    self
      .async_semaphore
      .with_acquired(move || {
        Self::materialize_workdir_for_server(
          store,
          workdir_for_this_nailgun.clone(),
          jdk_home,
          original_request.input_files,
          workunit_store,
        )
        .and_then(move |_metadata| {
          // Connect to a running nailgun.
          executor.spawn_on_io_pool(futures::future::lazy(move || {
            nailgun_pool.connect(
              nailgun_name.clone(),
              nailgun_req,
              &workdir_for_this_nailgun1,
              nailgun_req_digest,
              build_id,
            )
          }))
        })
        .map_err(|e| format!("Failed to connect to nailgun! {}", e))
      })
      .inspect(move |_| debug!("Connected to nailgun instance {}", &nailgun_name3))
      .and_then(move |nailgun_port| {
        // Run the client request in the nailgun we have active.
        debug!("Got nailgun port {} for {}", nailgun_port, nailgun_name2);
        let full_client_req =
          construct_nailgun_client_request(original_request2, client_main_class, client_args);
        trace!("Client request: {:#?}", full_client_req);
        Self::run_and_capture_workdir(
          full_client_req,
          context,
          store2,
          executor2,
          true,
          &workdir_for_this_nailgun2,
          Some(nailgun_port),
        )
      })
      .to_boxed()
  }

  fn extract_compatible_request(
    &self,
    req: &MultiPlatformExecuteProcessRequest,
  ) -> Option<ExecuteProcessRequest> {
    // Request compatibility should be the same as for the local runner, so we just delegate this.
    self.inner.extract_compatible_request(req)
  }
}

impl CapturedWorkdir for CommandRunner {
  fn run_in_workdir(
    workdir_path: &Path,
    req: ExecuteProcessRequest,
    nailgun_port: Option<Port>,
  ) -> Result<Box<dyn Stream<Item = ChildOutput, Error = String> + Send>, String> {
    // A task to render stdout.
    let (stdio_write, stdio_read) = child_channel::<ChildOutput>();
    let (_stdin_write, stdin_read) = child_channel::<ChildInput>();

    let cmd = Command {
      command: req.argv[0].clone(),
      args: req.argv[1..].to_vec(),
      env: req
        .env
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect(),
      working_dir: workdir_path.to_path_buf(),
    };

    let addr: SocketAddr = format!(
      "127.0.0.1:{:?}",
      nailgun_port.ok_or("Must pass a nailgun port to run_nailgun_process")?
    )
    .parse()
    .unwrap();

    debug!("Connecting to server at {}...", addr);
    Ok(Box::new(
      stdio_read.map_err(|()| unreachable!()).select(
        TcpStream::connect(&addr)
          .and_then(move |stream| {
            nails::client_handle_connection(stream, cmd, stdio_write, stdin_read)
          })
          .map_err(|e| format!("Error communicating with server: {}", e))
          .map(ChildOutput::Exit)
          .into_stream(),
      ),
    ))
  }
}
