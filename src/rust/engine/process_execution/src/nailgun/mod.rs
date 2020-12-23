use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::time::Duration;

use async_trait::async_trait;
use futures::future::{FutureExt, TryFutureExt};
use futures::stream::{BoxStream, StreamExt};
use log::{debug, trace};
use nails::execution::{self, child_channel, ChildInput, Command};
use tokio::net::TcpStream;

use crate::local::{CapturedWorkdir, ChildOutput};
use crate::nailgun::nailgun_pool::NailgunProcessName;
use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, NamedCaches, Platform, Process,
  ProcessCacheScope, ProcessMetadata,
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
use std::net::SocketAddr;

// Hardcoded constants for connecting to nailgun
static NAILGUN_MAIN_CLASS: &str = "com.martiansoftware.nailgun.NGServer";
static ARGS_TO_START_NAILGUN: [&str; 1] = [":0"];

///
/// Constructs the Process that would be used
/// to start the nailgun servers if we needed to.
///
// TODO(#8481) We should calculate the input_files by deeply fingerprinting the classpath.
fn construct_nailgun_server_request(
  nailgun_name: &str,
  args_for_the_jvm: Vec<String>,
  jdk: PathBuf,
  platform_constraint: Option<Platform>,
) -> Process {
  let mut full_args = args_for_the_jvm;
  full_args.push(NAILGUN_MAIN_CLASS.to_string());
  full_args.extend(ARGS_TO_START_NAILGUN.iter().map(|&a| a.to_string()));

  Process {
    argv: full_args,
    env: BTreeMap::new(),
    working_directory: None,
    input_files: hashing::EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Some(Duration::new(1000, 0)),
    description: format!("Start a nailgun server for {}", nailgun_name),
    level: log::Level::Info,
    append_only_caches: BTreeMap::new(),
    jdk_home: Some(jdk),
    platform_constraint,
    is_nailgunnable: true,
    execution_slot_variable: None,
    cache_scope: ProcessCacheScope::Never,
  }
}

fn construct_nailgun_client_request(
  original_req: Process,
  client_main_class: String,
  mut client_args: Vec<String>,
) -> Process {
  client_args.insert(0, client_main_class);
  Process {
    argv: client_args,
    jdk_home: None,
    ..original_req
  }
}

///
/// A command runner that can run local requests under nailgun.
///
/// It should only be invoked with local requests.
/// It will read a flag marking an `Process` as nailgunnable.
/// If that flag is set, it will connect to a running nailgun server and run the command there.
/// Otherwise, it will just delegate to the regular local runner.
///
pub struct CommandRunner {
  inner: super::local::CommandRunner,
  nailgun_pool: NailgunPool,
  async_semaphore: async_semaphore::AsyncSemaphore,
  metadata: ProcessMetadata,
  workdir_base: PathBuf,
  executor: task_executor::Executor,
}

impl CommandRunner {
  pub fn new(
    runner: crate::local::CommandRunner,
    metadata: ProcessMetadata,
    workdir_base: PathBuf,
    executor: task_executor::Executor,
  ) -> Self {
    CommandRunner {
      inner: runner,
      nailgun_pool: NailgunPool::new(),
      async_semaphore: AsyncSemaphore::new(1),
      metadata,
      workdir_base,
      executor,
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

#[async_trait]
impl super::CommandRunner for CommandRunner {
  async fn run(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    let original_request = self.extract_compatible_request(&req).unwrap();

    if !original_request.is_nailgunnable {
      trace!("The request is not nailgunnable! Short-circuiting to regular process execution");
      return self.inner.run(req, context).await;
    }
    debug!("Running request under nailgun:\n {:#?}", &original_request);

    let executor = self.executor.clone();
    let store = self.inner.store.clone();
    let ParsedJVMCommandLines {
      client_main_class, ..
    } = ParsedJVMCommandLines::parse_command_lines(&original_request.argv)?;
    let nailgun_name = CommandRunner::calculate_nailgun_name(&client_main_class);
    let workdir_for_this_nailgun = self.get_nailgun_workdir(&nailgun_name)?;

    self
      .run_and_capture_workdir(
        original_request,
        context,
        store,
        executor,
        true,
        &workdir_for_this_nailgun,
        Platform::current().unwrap(),
      )
      .await
  }

  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    // Request compatibility should be the same as for the local runner, so we just delegate this.
    self.inner.extract_compatible_request(req)
  }
}

#[async_trait]
impl CapturedWorkdir for CommandRunner {
  fn named_caches(&self) -> &NamedCaches {
    self.inner.named_caches()
  }

  async fn run_in_workdir<'a, 'b, 'c>(
    &'a self,
    workdir_path: &'b Path,
    req: Process,
    context: Context,
    _exclusive_spawn: bool,
  ) -> Result<BoxStream<'c, Result<ChildOutput, String>>, String> {
    // Separate argument lists, to form distinct EPRs for (1) starting the nailgun server and (2) running the client in it.
    let ParsedJVMCommandLines {
      nailgun_args,
      client_args,
      client_main_class,
    } = ParsedJVMCommandLines::parse_command_lines(&req.argv)?;

    let nailgun_name = CommandRunner::calculate_nailgun_name(&client_main_class);
    let nailgun_name2 = nailgun_name.clone();
    let nailgun_name3 = nailgun_name.clone();
    let client_workdir = if let Some(working_directory) = &req.working_directory {
      workdir_path.join(working_directory)
    } else {
      workdir_path.to_path_buf()
    };

    let jdk_home = req
      .jdk_home
      .clone()
      .ok_or("JDK home must be specified for all nailgunnable requests.")?;
    let nailgun_req = construct_nailgun_server_request(
      &nailgun_name,
      nailgun_args,
      jdk_home,
      req.platform_constraint,
    );
    trace!("Extracted nailgun request:\n {:#?}", &nailgun_req);

    let nailgun_req_digest = crate::digest(
      MultiPlatformProcess::from(nailgun_req.clone()),
      &self.metadata,
    );

    let nailgun_pool = self.nailgun_pool.clone();
    let req2 = req.clone();
    let workdir_for_this_nailgun = self.get_nailgun_workdir(&nailgun_name)?;
    let build_id = context.build_id;
    let store = self.inner.store.clone();

    let mut child = self
      .async_semaphore
      .clone()
      .with_acquired(move |_id| {
        // Get the port of a running nailgun server (or a new nailgun server if it doesn't exist)
        nailgun_pool.connect(
          nailgun_name.clone(),
          nailgun_req,
          workdir_for_this_nailgun,
          nailgun_req_digest,
          build_id,
          store,
          req.input_files,
        )
      })
      .map_err(|e| format!("Failed to connect to nailgun! {}", e))
      .inspect(move |_| debug!("Connected to nailgun instance {}", &nailgun_name3))
      .and_then(move |nailgun_port| {
        // Run the client request in the nailgun we have active.
        debug!("Got nailgun port {} for {}", nailgun_port, nailgun_name2);
        let client_req = construct_nailgun_client_request(req2, client_main_class, client_args);
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
        TcpStream::connect(addr)
          .and_then(move |stream| {
            nails::client::handle_connection(nails::Config::default(), stream, cmd, async {
              let (_stdin_write, stdin_read) = child_channel::<ChildInput>();
              stdin_read
            })
          })
          .map_err(|e| format!("Error communicating with server: {}", e))
      })
      .await?;

    let output_stream = child
      .output_stream
      .take()
      .unwrap()
      .map(|output| match output {
        execution::ChildOutput::Stdout(bytes) => Ok(ChildOutput::Stdout(bytes)),
        execution::ChildOutput::Stderr(bytes) => Ok(ChildOutput::Stderr(bytes)),
      });
    let exit_code = child
      .wait()
      .map_ok(ChildOutput::Exit)
      .map_err(|e| format!("Error communicating with server: {}", e));

    Ok(futures::stream::select(output_stream, exit_code.into_stream()).boxed())
  }
}
