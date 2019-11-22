use std::collections::btree_map::BTreeMap;
use std::collections::btree_set::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use boxfuture::BoxFuture;
use futures::future::Future;
use futures::stream::Stream;
use log::{debug, trace};
use nails::execution::{child_channel, ChildInput, ChildOutput, Command};
use tokio::net::TcpStream;
use tempfile;

use crate::local::CapturedWorkdir;
use crate::nailgun::nailgun_pool::NailgunProcessName;
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

pub use nailgun_pool::NailgunPool;
use parsed_jvm_command_lines::ParsedJVMCommandLines;
use std::net::SocketAddr;

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
  client_workdir: PathBuf,
) -> Result<ExecuteProcessRequest, String> {
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
  // arg file is only materialized to the client workdir but java is running in the
  // nailgun dir so we have to adjust the path to point to the correct spot, which is in the
  // client workdir.
  let maybe_arg_file = client_args.last().unwrap();
  if maybe_arg_file.starts_with('@') {
    if let Ok(arg_file_path) = maybe_arg_file[1..].parse::<PathBuf>() {
      client_args.pop();
      let mut full_arg_file_path = client_workdir
        .as_path()
        .join(arg_file_path)
        .into_os_string()
        .into_string()
        .map_err(|_| {
          "Couldn't convert path into String, does it contain valid unicode?".to_string()
        })?;
      // turn the path back into a java arguments file.
      full_arg_file_path.insert(0, '@');
      client_args.push(full_arg_file_path);
    }
  }
  Ok(ExecuteProcessRequest {
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
  })
}

///
/// A command runner that can run local requests under nailgun.
///
/// It should only be invoked with local requests.
/// It will read a flag marking an `ExecuteProcessRequest` as nailgunnable.
/// If that flag is set, it will connect to a running nailgun server and run the command there.
/// Otherwise, it will just delegate to the regular local runner.
///
#[derive(Clone)]
pub struct CommandRunner {
  inner: Arc<super::local::CommandRunner>,
  nailgun_pool: NailgunPool,
  metadata: ExecuteProcessRequestMetadata,
  workdir_base: PathBuf,
  executor: task_executor::Executor,
  client_workdir: PathBuf,
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
      metadata: metadata,
      workdir_base: workdir_base.clone(),
      executor: executor,
      client_workdir: tempfile::Builder::new()
        .prefix("process-execution")
        .tempdir_in(workdir_base)
        .expect("Error making client tempdir for process execution")
        .into_path()
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
}

impl super::CommandRunner for CommandRunner {
  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let original_request = self.extract_compatible_request(&req).unwrap();

    if !original_request.is_nailgunnable {
      trace!("The request is not nailgunnable! Short-circuiting to regular process execution");
      return self.inner.run(req, context);
    }
    debug!("Running request under nailgun:\n {:#?}", &original_request);

    let executor = self.executor.clone();
    let store = self.inner.store.clone();
    self.run_and_capture_workdir(
      original_request,
      context,
      store,
      executor,
      true,
      &self.workdir_base,
      Some(self.client_workdir.clone())
    )
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
    &self,
    workdir_path: &Path,
    req: ExecuteProcessRequest,
    context: Context,
  ) -> Result<Box<dyn Stream<Item = ChildOutput, Error = String> + Send>, String> {
    // Separate argument lists, to form distinct EPRs for (1) starting the nailgun server and (2) running the client in it.
    let ParsedJVMCommandLines {
      nailgun_args,
      client_args,
      client_main_class,
    } = ParsedJVMCommandLines::parse_command_lines(&req.argv)?;

    let nailgun_name = CommandRunner::calculate_nailgun_name(&client_main_class);
    let nailgun_name2 = nailgun_name.clone();
    let nailgun_name3 = nailgun_name.clone();
    let client_workdir = workdir_path.to_path_buf();

    let jdk_home = req
      .jdk_home
      .clone()
      .ok_or("JDK home must be specified for all nailgunnable requests.")?;
    let nailgun_req = construct_nailgun_server_request(
      &nailgun_name,
      nailgun_args,
      jdk_home.clone(),
      req.target_platform,
    );
    trace!("Extracted nailgun request:\n {:#?}", &nailgun_req);

    let nailgun_req_digest = crate::digest(
      MultiPlatformExecuteProcessRequest::from(nailgun_req.clone()),
      &self.metadata,
    );

    let nailgun_pool = self.nailgun_pool.clone();
    let req2 = req.clone();
    let workdir_for_this_nailgun = self.get_nailgun_workdir(&nailgun_name)?;
    let workdir_for_this_nailgun1 = workdir_for_this_nailgun.clone();
    let build_id = context.build_id.clone();
    let store = self.inner.store.clone();
    let workunit_store = context.workunit_store.clone();

    // Streams to read child output from
    let (stdio_write, stdio_read) = child_channel::<ChildOutput>();
    let (_stdin_write, stdin_read) = child_channel::<ChildInput>();
    let client_req = construct_nailgun_client_request(
      req2,
      client_main_class,
      client_args,
      client_workdir.clone(),
    )?;

    // Get the port of a running nailgun server (or a new nailgun server if it doesn't exist)
    let nails_command = nailgun_pool
      .connect(
        nailgun_name.clone(),
        nailgun_req,
        workdir_for_this_nailgun1,
        nailgun_req_digest,
        build_id,
        store,
        req.input_files,
        workunit_store,
      )
      .map_err(|e| format!("Failed to connect to nailgun! {}", e))
      .inspect(move |_| debug!("Connected to nailgun instance {}", &nailgun_name3))
      .and_then(move |(nailgun_port, nailgun_guard)| {
        // Run the client request in the nailgun we have active.
        debug!("Got nailgun port {} for {}", nailgun_port, nailgun_name2);
        let cmd = Command {
          command: client_req.argv[0].clone(),
          args: client_req.argv[1..].to_vec(),
          env: client_req
            .env
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect(),
          working_dir: client_workdir,
        };
        trace!("Client request: {:#?}", client_req);
        let addr: SocketAddr = format!("127.0.0.1:{:?}", nailgun_port).parse().unwrap();
        debug!("Connecting to server at {}...", addr);
        TcpStream::connect(&addr)
          .and_then(move |stream| {
            nails::client_handle_connection(stream, cmd, stdio_write, stdin_read)
          })
          .map_err(|e| format!("Error communicating with server: {}", e))
          .map(ChildOutput::Exit)
          .map(move |exit| {
            drop(nailgun_guard);
            exit
          })
      });

    Ok(Box::new(
      stdio_read
        .map_err(|()| unreachable!())
        .select(nails_command.into_stream()),
    ))
  }
}
