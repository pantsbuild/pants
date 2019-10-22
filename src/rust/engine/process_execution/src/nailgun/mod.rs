use std::collections::btree_map::BTreeMap;
use std::collections::btree_set::BTreeSet;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use futures::future::Future;
use log::{debug, trace};

use boxfuture::{try_future, BoxFuture, Boxable};
use hashing::Digest;

use crate::nailgun::nailgun_pool::{NailgunProcessName, Port};
use crate::{
  Context, ExecuteProcessRequest, ExecuteProcessRequestMetadata, FallibleExecuteProcessResult,
  MultiPlatformExecuteProcessRequest, Platform,
};

pub mod nailgun_pool;
mod parsed_jvm_command_lines;

pub use nailgun_pool::NailgunPool;
use parsed_jvm_command_lines::ParsedJVMCommandLines;
use std::fs::{read_link, remove_file};
use workunit_store::WorkUnitStore;

// Hardcoded constants for connecting to nailgun
static NAILGUN_MAIN_CLASS: &str = "com.martiansoftware.nailgun.NGServer";
static ARGS_TO_START_NAILGUN: [&str; 1] = [":0"];

static NAILGUN_PORT_ENV_VAR_FOR_CLIENT: &str = "NAILGUN_PORT";

// We can hardcode this because we mix it into the digest in the EPR.
// TODO(#8480) This hardcoded path can go away
//              when we port the fetching of the clients and servers to the rust stack,
//              or when we switch to a different client.
static NG_CLIENT_PATH: &str = "bin/ng/1.0.0/ng";

///
/// Constructs the ExecuteProcessRequest that would be used
/// to start the nailgun servers if we needed to.
///
// TODO(8481) We should calculate the input_files by deeply fingerprinting the classpath.
fn construct_nailgun_server_request(
  args: Vec<String>,
  jdk: Option<PathBuf>,
  platform: Platform,
) -> ExecuteProcessRequest {
  let mut full_args = args;
  full_args.push(NAILGUN_MAIN_CLASS.to_string());
  full_args.extend(ARGS_TO_START_NAILGUN.iter().map(|a| a.to_string()));

  ExecuteProcessRequest {
    argv: full_args,
    env: BTreeMap::new(),
    input_files: hashing::EMPTY_DIGEST,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Duration::new(1000, 0),
    description: String::from("ExecuteProcessRequest to start a nailgun"),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: jdk,
    target_platform: platform,
    is_nailgunnable: true,
  }
}

fn construct_nailgun_client_request(
  original_req: ExecuteProcessRequest,
  python_distribution: String,
  client_main_class: String,
  client_args: Vec<String>,
  nailgun_port: Port,
) -> ExecuteProcessRequest {
  let ExecuteProcessRequest {
    argv: argv,
    input_files: input_files,
    description: description,
    env: env,
    output_files: output_files,
    output_directories: output_directories,
    timeout: timeout,
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: unsafe_files,
    jdk_home: jdk_home,
    target_platform: target_platform,
    is_nailgunnable: is_nailgunnable,
  } = original_req;
  let mut client_argv = vec![
    python_distribution,
    NG_CLIENT_PATH.to_string(),
    "--".to_string(),
    client_main_class,
  ]
  .into_iter()
  .chain(argv.into_iter())
  .collect();
  let mut client_env = env;
  client_env.insert(
    NAILGUN_PORT_ENV_VAR_FOR_CLIENT.into(),
    nailgun_port.to_string(),
  );
  ExecuteProcessRequest {
    argv: client_argv,
    input_files,
    description,
    env: client_env,
    output_files,
    output_directories,
    timeout,
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: unsafe_files,
    jdk_home: None,
    target_platform,
    is_nailgunnable
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
  metadata: ExecuteProcessRequestMetadata,
  workdir_base: PathBuf,
  python_distribution_absolute_path: PathBuf,
}

impl CommandRunner {
  pub fn new(
    runner: crate::local::CommandRunner,
    metadata: ExecuteProcessRequestMetadata,
    python_distribution_absolute_path: PathBuf,
    workdir_base: PathBuf,
  ) -> Self {
    CommandRunner {
      inner: Arc::new(runner),
      nailgun_pool: NailgunPool::new(),
      metadata: metadata,
      workdir_base: workdir_base,
      python_distribution_absolute_path: python_distribution_absolute_path,
    }
  }

  // Ensure that the workdir for the given nailgun name exists.
  fn get_nailgun_workdir(&self, nailgun_name: &NailgunProcessName) -> Result<PathBuf, String> {
    let workdir = self.workdir_base.clone().join(nailgun_name);
    if !workdir.exists() {
      debug!("Creating nailgun workdir at {:?}", &workdir);
      fs::safe_create_dir_all(&workdir)
        .map_err(|err| format!("Error creating the nailgun workdir! {}", err))
        .map(|_| workdir)
    } else {
      debug!("nailgun workdir {:?} exits. Reusing that...", &workdir);
      Ok(workdir)
    }
  }

  fn calculate_nailgun_name(main_class: &String) -> NailgunProcessName {
    format!("nailgun_server_{}", main_class)
  }

  // TODO(8481) When we correctly set the input_files field of the nailgun EPR, we won't need to pass it here as an argument.
  // TODO(8489) We should move this code to NailgunPool. This returns a Future, so this will involve making the struct Futures-aware.
  fn materialize_workdir_for_server(
    &self,
    workdir_for_server: PathBuf,
    requested_jdk_home: Option<PathBuf>,
    input_files: Digest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<(), String> {
    if requested_jdk_home.is_none() {
      return futures::future::err(format!(
        "No JDK specified when materializing the server directory"
      ))
      .to_boxed();
    }
    let requested_jdk_home = requested_jdk_home.unwrap();
    // Materialize the directory for running the nailgun server, if we need to.
    let workdir_for_server2 = workdir_for_server.clone();
    let workdir_for_server3 = workdir_for_server.clone();
    let workdir_for_server4 = workdir_for_server.clone();

    self.inner
            .store
            // TODO(8481) This materializes the input files in the client req, which is a superset of the files we need (we only need the classpath, not the input files)
            .materialize_directory(workdir_for_server.clone(), input_files, workunit_store)
            .and_then(move |_metadata| {
                let jdk_home_in_workdir = workdir_for_server2.clone().join(".jdk");
                let jdk_home_in_workdir2 = jdk_home_in_workdir.clone();
                let jdk_home_in_workdir3 = jdk_home_in_workdir.clone();
                if !jdk_home_in_workdir.exists() {
                    futures::future::result(
                        symlink(requested_jdk_home, jdk_home_in_workdir)
                            .map_err(|err| format!("Error making new symlink for local execution in workdir {:?}: {:?}", &workdir_for_server2, err))
                    )
                } else {
                    let maybe_existing_jdk = read_link(jdk_home_in_workdir).map_err(|e| format!("{}", e));
                    let maybe_existing_jdk2 = maybe_existing_jdk.clone();
                    if maybe_existing_jdk.is_err() || (maybe_existing_jdk.is_ok() && maybe_existing_jdk.unwrap() != requested_jdk_home) {
                        let res = remove_file(jdk_home_in_workdir2)
                            .map_err(|err| format!(
                                "Error removing existing (but incorrect) jdk symlink. We wanted it to point to {:?}, but it pointed to {:?}. {}",
                                &requested_jdk_home, &maybe_existing_jdk2, err
                            ))
                            .and_then(|_| {
                                symlink(requested_jdk_home, jdk_home_in_workdir3)
                                    .map_err(|err| format!("Error overwriting symlink for local execution in workdir {:?}: {:?}", &workdir_for_server2, err))
                            });
                        futures::future::result(res)
                    } else {
                        debug!("JDK home for Nailgun already exists in {:?}. Using that one.", &workdir_for_server4);
                        futures::future::ok(())
                    }
                }
        })
        .inspect(move |_| debug!("Materialized directory {:?} before connecting to nailgun server.", &workdir_for_server3))
        .to_boxed()
  }

  fn get_python_distribution_path(&self) -> String {
    format!("{}", self.python_distribution_absolute_path.display())
  }
}

impl super::CommandRunner for CommandRunner {
  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let nailgun_pool = self.nailgun_pool.clone();
    let inner = self.inner.clone();
    let python_distribution = self.get_python_distribution_path();

    let client_req = self.extract_compatible_request(&req).unwrap();

    if !client_req.is_nailgunnable {
      trace!("The request is not nailgunnable! Short-circuiting to regular process execution");
      return self.inner.run(req, context);
    }
    debug!("Running request under nailgun:\n {:#?}", &client_req);

    // Separate argument lists, to form distinct EPRs for (1) starting the nailgun server and (2) running the client in it.
    let ParsedJVMCommandLines {
      nailgun_args,
      client_args,
      client_main_class,
    } = ParsedJVMCommandLines::parse_command_lines(&client_req.argv)
      .expect("Error parsing command lines!!");
    let nailgun_req = construct_nailgun_server_request(
      nailgun_args,
      client_req.jdk_home.clone(),
      client_req.target_platform,
    );
    trace!("Extracted nailgun request:\n {:#?}", &nailgun_req);

    let nailgun_req_digest = crate::digest(
      MultiPlatformExecuteProcessRequest::from(nailgun_req.clone()),
      &self.metadata,
    );

    let nailgun_name = CommandRunner::calculate_nailgun_name(&client_main_class);
    let nailgun_name2 = nailgun_name.clone();
    let nailgun_name3 = nailgun_name.clone();

    let workdir_for_this_nailgun = try_future!(self.get_nailgun_workdir(&nailgun_name));
    let workdir_for_this_nailgun1 = workdir_for_this_nailgun.clone();

    self
      .materialize_workdir_for_server(
        workdir_for_this_nailgun.clone(),
        nailgun_req.jdk_home.clone(),
        client_req.input_files,
        context.workunit_store.clone(),
      )
      .and_then(move |_metadata| {
        // Connect to a running nailgun.
        nailgun_pool.connect(
          nailgun_name.clone(),
          nailgun_req,
          &workdir_for_this_nailgun1,
          nailgun_req_digest,
        )
      })
      .map_err(|e| format!("Failed to connect to nailgun! {}", e))
      .and_then(move |nailgun_port| {
        // Run the client request in the nailgun we have active.
        debug!("Got nailgun port {:#?}", nailgun_port);
        let full_client_req = construct_nailgun_client_request(
          client_req,
          python_distribution,
          client_main_class,
          client_args,
          nailgun_port,
        );
        debug!("Running client request on nailgun {}", &nailgun_name2);
        trace!("Client request: {:#?}", full_client_req);
        inner.run(
          MultiPlatformExecuteProcessRequest::from(full_client_req),
          context,
        )
      })
      .inspect(move |_| debug!("Connected to nailgun instance {}", &nailgun_name3))
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

#[cfg(test)]
mod tests {
  use crate::nailgun::{
    CommandRunner, ARGS_TO_START_NAILGUN, NAILGUN_MAIN_CLASS, NAILGUN_PORT_ENV_VAR_FOR_CLIENT,
  };
  use crate::{ExecuteProcessRequest, ExecuteProcessRequestMetadata, Platform};
  use hashing::EMPTY_DIGEST;
  use std::fs::read_link;
  use std::os::unix::fs::symlink;
  use std::path::PathBuf;
  use store::Store;
  use tempfile::TempDir;
  use workunit_store::WorkUnitStore;

  fn mock_nailgun_runner(workdir_base: Option<PathBuf>) -> CommandRunner {
    let store_dir = TempDir::new().unwrap();
    let executor = task_executor::Executor::new();
    let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();
    let local_runner =
      crate::local::CommandRunner::new(store, executor.clone(), std::env::temp_dir(), true);
    let metadata = ExecuteProcessRequestMetadata {
      instance_name: None,
      cache_key_gen_version: None,
      platform_properties: vec![],
    };
    let python_distribution = PathBuf::from("/usr/bin/python");
    let workdir_base = workdir_base.unwrap_or(std::env::temp_dir());

    CommandRunner::new(local_runner, metadata, python_distribution, workdir_base)
  }

  fn unique_temp_dir(base_dir: PathBuf, prefix: Option<String>) -> TempDir {
    tempfile::Builder::new()
      .prefix(&(prefix.unwrap_or("".to_string())))
      .tempdir_in(&base_dir)
      .expect("Error making tempdir for local process execution: {:?}")
  }

  fn mock_nailgunnable_request(jdk_home: Option<PathBuf>) -> ExecuteProcessRequest {
    ExecuteProcessRequest {
      argv: vec![],
      env: Default::default(),
      input_files: EMPTY_DIGEST,
      output_files: Default::default(),
      output_directories: Default::default(),
      timeout: Default::default(),
      description: "".to_string(),
      unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: EMPTY_DIGEST,
      jdk_home: jdk_home,
      target_platform: Platform::Darwin,
      is_nailgunnable: true,
    }
  }

  #[test]
  fn get_workdir_creates_directory_if_it_doesnt_exist() {
    let mock_workdir_base = unique_temp_dir(std::env::temp_dir(), None)
      .path()
      .to_owned();
    let mock_nailgun_name = "mock_non_existing_workdir".to_string();
    let runner = mock_nailgun_runner(Some(mock_workdir_base.clone()));

    let target_workdir = mock_workdir_base.join(mock_nailgun_name.clone());
    assert!(!target_workdir.exists());
    let res = runner.get_nailgun_workdir(&mock_nailgun_name);
    assert_eq!(res, Ok(target_workdir.clone()));
    assert!(target_workdir.exists());
  }

  #[test]
  fn get_workdir_returns_the_workdir_when_it_exists() {
    let mock_workdir_base = unique_temp_dir(std::env::temp_dir(), None)
      .path()
      .to_owned();
    let mock_nailgun_name = "mock_existing_workdir".to_string();
    let runner = mock_nailgun_runner(Some(mock_workdir_base.clone()));

    let target_workdir = mock_workdir_base.join(mock_nailgun_name.clone());
    assert!(!target_workdir.exists());
    let creation_res = fs::safe_create_dir_all(&target_workdir);
    assert!(creation_res.is_ok());
    assert!(target_workdir.exists());

    let res = runner.get_nailgun_workdir(&mock_nailgun_name);
    assert_eq!(res, Ok(target_workdir.clone()));
    assert!(target_workdir.exists());
  }

  #[test]
  fn creating_nailgun_server_request_updates_the_cli() {
    let req = super::construct_nailgun_server_request(Vec::new(), None, Platform::None);
    assert_eq!(req.argv[0], NAILGUN_MAIN_CLASS);
    assert_eq!(req.argv[1..], ARGS_TO_START_NAILGUN);
  }

  #[test]
  fn creating_nailgun_client_request_inserts_port_as_an_env_var() {
    let original_req = mock_nailgunnable_request(None);
    let req = super::construct_nailgun_client_request(
      original_req,
      "".to_string(),
      "".to_string(),
      vec![],
      1234,
    );
    assert_eq!(
      req.env.get(NAILGUN_PORT_ENV_VAR_FOR_CLIENT),
      Some(&String::from("1234"))
    );
  }

  #[test]
  fn creating_nailgun_client_request_removes_jdk_home() {
    let original_req = mock_nailgunnable_request(Some(PathBuf::from("some/path")));
    let req = super::construct_nailgun_client_request(
      original_req,
      "".to_string(),
      "".to_string(),
      vec![],
      1234,
    );
    assert_eq!(req.jdk_home, None);
  }

  #[test]
  fn nailgun_name_is_the_main_class() {
    let main_class = "my.main.class".to_string();
    let name = super::CommandRunner::calculate_nailgun_name(&main_class);
    assert_eq!(name, format!("nailgun_server_{}", main_class));
  }

  fn materialize_with_jdk(
    runner: &CommandRunner,
    dir: PathBuf,
    jdk_path: PathBuf,
  ) -> Result<(), String> {
    let executor = task_executor::Executor::new();
    let materializer = runner.materialize_workdir_for_server(
      dir,
      Some(jdk_path),
      EMPTY_DIGEST,
      WorkUnitStore::new(),
    );
    executor.block_on(materializer)
  }

  #[test]
  fn materializing_workdir_for_server_creates_a_link_for_the_jdk() {
    let workdir_base_tempdir = unique_temp_dir(std::env::temp_dir(), None);
    let workdir_base = workdir_base_tempdir.path().to_owned();
    let mock_jdk_dir = unique_temp_dir(std::env::temp_dir(), None);
    let mock_jdk_path = mock_jdk_dir.path().to_owned();
    let runner = mock_nailgun_runner(Some(workdir_base));
    let nailgun_name = "mock_server".to_string();

    let workdir_for_server = runner
      .get_nailgun_workdir(&nailgun_name)
      .expect("Error creating workdir for nailgun server");
    println!("Workdir for server {:?}", &workdir_for_server);

    // Assert that the materialization was successful
    let materialization_result =
      materialize_with_jdk(&runner, workdir_for_server.clone(), mock_jdk_path.clone());
    assert_eq!(materialization_result, Ok(()));

    // Assert that the symlink points to the requested jdk
    let materialized_jdk_path = workdir_for_server.join(".jdk");
    let materialized_jdk = read_link(materialized_jdk_path);
    assert!(materialized_jdk.is_ok());
    assert_eq!(materialized_jdk.unwrap(), mock_jdk_path);
  }

  #[test]
  fn materializing_workdir_for_server_replaces_jdk_link_if_a_different_one_is_requested() {
    let workdir_base_tempdir = unique_temp_dir(std::env::temp_dir(), None);
    let workdir_base = workdir_base_tempdir.path().to_owned();

    let _ = workdir_base_tempdir.into_path();

    let runner = mock_nailgun_runner(Some(workdir_base));
    let nailgun_name = "mock_server".to_string();

    let original_mock_jdk_dir = unique_temp_dir(std::env::temp_dir(), None);
    let original_mock_jdk_path = original_mock_jdk_dir.path().to_owned();
    let requested_mock_jdk_dir = unique_temp_dir(std::env::temp_dir(), None);
    let requested_mock_jdk_path = requested_mock_jdk_dir.path().to_owned();

    let workdir_for_server = runner
      .get_nailgun_workdir(&nailgun_name)
      .expect("Error creating workdir for nailgun server");
    let materialized_jdk_path = workdir_for_server.join(".jdk");

    // Manually create a symlink to one of the jdk files
    let symlink_res = symlink(original_mock_jdk_path, materialized_jdk_path.clone());
    assert!(symlink_res.is_ok());

    // Trigger materialization of the nailgun server workdir
    let materialization_result =
      materialize_with_jdk(&runner, workdir_for_server, requested_mock_jdk_path.clone());
    assert!(materialization_result.is_ok());

    // Assert that the symlink points to the requested jdk, and not the original one
    let materialized_jdk = read_link(materialized_jdk_path);
    assert!(materialized_jdk.is_ok());
    assert_eq!(materialized_jdk.unwrap(), requested_mock_jdk_path);
  }
}
