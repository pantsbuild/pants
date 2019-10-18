use std::collections::btree_map::BTreeMap;
use std::collections::btree_set::BTreeSet;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use futures::future::Future;
use log::{debug, trace};

use boxfuture::{Boxable, BoxFuture, try_future};
use hashing::Digest;

use crate::{ExecuteProcessRequest, ExecuteProcessRequestMetadata, FallibleExecuteProcessResult, MultiPlatformExecuteProcessRequest, Platform, Context};
use crate::nailgun::nailgun_pool::NailgunProcessName;

pub mod nailgun_pool;
mod parsed_jvm_command_lines;

pub use nailgun_pool::NailgunPool;
use workunit_store::WorkUnitStore;
use parsed_jvm_command_lines::ParsedJVMCommandLines;
use std::fs::{read_link, remove_dir_all, remove_file};

// Hardcoded constants for connecting to nailgun
static NAILGUN_MAIN_CLASS: &str = "com.martiansoftware.nailgun.NGServer";
static ARGS_TO_START_NAILGUN: [&str; 1] = [":0"];

// We can hardcode this because we mix it into the digest in the EPR.
// TODO(8480) This can go away when we port the fetching of the clients and servers to the rust stack.
static NG_CLIENT_PATH: &str = "bin/ng/1.0.0/ng";

///
/// Constructs the ExecuteProcessRequest that would be used
/// to start the nailgun servers if we needed to.
///
// TODO(8481) We should calculate the input_files by deeply fingerprinting the classpath.
fn construct_nailgun_server_request(args: Vec<String>, jdk: Option<PathBuf>, platform: Platform) -> ExecuteProcessRequest {
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
        unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: hashing::EMPTY_DIGEST,
        jdk_home: jdk,
        target_platform: platform,
        is_nailgunnable: true,
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
pub struct NailgunCommandRunner {
    inner: Arc<super::local::CommandRunner>,
    nailgun_pool: NailgunPool,
    metadata: ExecuteProcessRequestMetadata,
    workdir_base: PathBuf,
    python_distribution_absolute_path: PathBuf,
}

impl NailgunCommandRunner {
    pub fn new(runner: crate::local::CommandRunner, metadata: ExecuteProcessRequestMetadata, python_distribution_absolute_path: PathBuf, workdir_base: PathBuf) -> Self {
        NailgunCommandRunner {
            inner: Arc::new(runner),
            nailgun_pool: NailgunPool::new(),
            metadata: metadata,
            workdir_base: workdir_base,
            python_distribution_absolute_path: python_distribution_absolute_path,
        }
    }

    // Ensure that the workdir for the given nailgun name exists.
    fn get_nailguns_workdir(&self, nailgun_name: &NailgunProcessName) -> Result<PathBuf, String> {
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

    fn calculate_nailgun_name(main_class: &String, digest: &Digest) -> String {
        format!("{}_{}", main_class, digest.0)
    }

    // TODO(8481) When we correctly set the input_files field of the nailgun EPR, we won't need to pass it here as an argument.
    // TODO(8489) We should move this code to NailgunPool. This returns a Future, so this will involve making the struct Futures-aware.
    fn materialize_workdir_for_server(
        &self,
        nailgun_workdir: &PathBuf,
        nailgun_request: &ExecuteProcessRequest,
        input_files: Digest,
        workunit_store: WorkUnitStore
    ) -> BoxFuture<(), String> {
        let requested_jdk_home = nailgun_request.jdk_home
            .clone()
            .expect("No JDK home specified.");
        // Materialize the directory for running the nailgun server, if we need to.
        let nailgun_workdir_path2 = nailgun_workdir.clone();
        let nailgun_workdir_path3 = nailgun_workdir.clone();
        let nailgun_workdir_path4 = nailgun_workdir.clone();
        self.inner
            .store
            // TODO(8481) This materializes the input files in the client req, which is a superset of the files we need (we only need the classpath, not the input files)
            .materialize_directory(nailgun_workdir.clone(), input_files, workunit_store)
            .and_then(move |_metadata| {
                let jdk_home_in_workdir = nailgun_workdir_path2.clone().join(".jdk");
                let jdk_home_in_workdir2 = jdk_home_in_workdir.clone();
                let jdk_home_in_workdir3 = jdk_home_in_workdir.clone();
                let jdk_home_in_workdir4 = jdk_home_in_workdir.clone();
                if !jdk_home_in_workdir.exists() {
                    futures::future::result(
                        symlink(requested_jdk_home, jdk_home_in_workdir)
                            .map_err(|err| format!("Error making symlink for local execution in workdir {:?}: {:?}", &nailgun_workdir_path2, err))
                    )
                } else {
                    let maybe_existing_jdk = read_link(jdk_home_in_workdir).map_err(|e| format!("{}", e));
                    let maybe_existing_jdk2 = maybe_existing_jdk.clone();
                    if maybe_existing_jdk.is_err() || (maybe_existing_jdk.is_ok() && maybe_existing_jdk.unwrap() != requested_jdk_home) {
                        let res = remove_file(jdk_home_in_workdir2)
                            .map_err(|e| format!(
                                "Error removing existing (but incorrect) jdk symlink. We wanted it to point to {:?}, but it pointed to {:?}",
                                &requested_jdk_home, &maybe_existing_jdk2
                            ))
                            .and_then(|_| {
                                symlink(requested_jdk_home, jdk_home_in_workdir4)
                                    .map_err(|err| format!("Error making symlink for local execution in workdir {:?}: {:?}", &nailgun_workdir_path2, err))
                            });
                        futures::future::result(res)
                    } else {
                        debug!("JDK home for Nailgun already exists in {:?}. Using that one.", &nailgun_workdir_path4);
                        futures::future::ok(())
                    }
                }
            })
            .inspect(move |_| debug!("Materialized directory {:?} before connecting to nailgun server.", &nailgun_workdir_path3))
            .to_boxed()
    }

    fn get_python_distribution(&self) -> String {
        self.python_distribution_absolute_path
            .clone()
            .into_os_string()
            .into_string()
            .expect("The path of your python distribution is not UTF-8!")
    }
}

impl super::CommandRunner for NailgunCommandRunner {
    fn run(
        &self,
        req: MultiPlatformExecuteProcessRequest,
        context: Context) -> BoxFuture<FallibleExecuteProcessResult, String> {

        let nailgun_pool = self.nailgun_pool.clone();
        let inner = self.inner.clone();
        let python_distribution = self.get_python_distribution();

        let mut client_req = self.extract_compatible_request(&req).unwrap();

        if !client_req.is_nailgunnable {
            trace!("The request is not nailgunnable! Short-circuiting to regular process execution");
            return self.inner.run(req, context)
        }
        debug!("Running request under nailgun:\n {:#?}", &client_req);

        // Separate argument lists, to form distinct EPRs for (1) starting the nailgun server and (2) running the client in it.
        let ParsedJVMCommandLines { nailgun_args, client_args, client_main_class } = ParsedJVMCommandLines::parse_command_lines(&client_req.argv).expect("Error parsing command lines!!");
        let nailgun_req = construct_nailgun_server_request(nailgun_args, client_req.jdk_home.clone(), client_req.target_platform);
        trace!("Extracted nailgun request:\n {:#?}", &nailgun_req);

        let nailgun_req_digest = crate::digest(MultiPlatformExecuteProcessRequest::from(nailgun_req.clone()), &self.metadata);

        let nailgun_name = NailgunCommandRunner::calculate_nailgun_name(&client_main_class, &nailgun_req_digest);
        let nailgun_name2 = nailgun_name.clone();
        let nailgun_name3 = nailgun_name.clone();

        let workdir_for_this_nailgun = try_future!(self.get_nailguns_workdir(&nailgun_name));
        let workdir_for_this_nailgun1 = workdir_for_this_nailgun.clone();

        self.materialize_workdir_for_server(&workdir_for_this_nailgun, &nailgun_req, client_req.input_files, context.workunit_store.clone())
            .and_then(move |_metadata| {
                // Connect to a running nailgun, starting one appropriate one up.
                nailgun_pool.connect(nailgun_name.clone(), nailgun_req, &workdir_for_this_nailgun1, nailgun_req_digest)
            })
            .map_err(|e| format!("Failed to connect to nailgun! {}", e))
            .and_then(move |nailgun_port| {
                // Run the client request in the nailgun we have active.
                debug!("Got nailgun port {:#?}", nailgun_port);
                let full_client_req =
                    {
                        client_req.argv = vec![
                            python_distribution,
                            NG_CLIENT_PATH.to_string(),
                            "--".to_string(),
                        ];
                        client_req.argv.push(client_main_class);
                        client_req.argv.extend(client_args);
                        client_req.jdk_home = None;
                        client_req.env.insert("NAILGUN_PORT".into(), nailgun_port.to_string());
                        client_req
                    };
                debug!("Running client request on nailgun {}", &nailgun_name2);
                trace!("Client request: {:#?}", full_client_req);
                inner.run(MultiPlatformExecuteProcessRequest::from(full_client_req), context)
            })
            .inspect(move |_| debug!("Connected to nailgun instance {}", &nailgun_name3))
            .to_boxed()
    }

    fn extract_compatible_request(&self, req: &MultiPlatformExecuteProcessRequest) -> Option<ExecuteProcessRequest> {
        // Request compatibility should be the same as for the local runner, so we just delegate this.
        self.inner.extract_compatible_request(req)
    }
}

#[cfg(test)]
mod tests {
    use crate::nailgun::NailgunCommandRunner;
    use store::Store;
    use tempfile::TempDir;
    use crate::ExecuteProcessRequestMetadata;
    use std::path::PathBuf;

    fn mock_nailgun_runner(workdir_base: Option<PathBuf>) -> NailgunCommandRunner {
        let store_dir = TempDir::new().unwrap();
        let executor = task_executor::Executor::new();
        let store =  Store::local_only(executor.clone(), store_dir.path()).unwrap();
        let local_runner = crate::local::CommandRunner::new(
            store,
            executor.clone(),
            std::env::temp_dir(),
            true,
        );
        let metadata = ExecuteProcessRequestMetadata {
            instance_name: None,
            cache_key_gen_version: None,
            platform_properties: vec![]
        };
        let python_distribution = PathBuf::from("/usr/bin/python");
        let workdir_base = workdir_base.unwrap_or(std::env::temp_dir());

        NailgunCommandRunner::new(
            local_runner,
            metadata,
            python_distribution,
            workdir_base,
        )

    }

    fn unique_temp_dir(base_dir: PathBuf, prefix: Option<String>) -> TempDir {
        tempfile::Builder::new()
            .prefix(&(prefix.unwrap_or("".to_string())))
            .tempdir_in(&base_dir)
            .expect("Error making tempdir for local process execution: {:?}")
    }

    #[test]
    fn get_workdir_creates_directory_if_it_doesnt_exist() {
        let mock_workdir_base = unique_temp_dir(std::env::temp_dir(), None).into_path();
        let mock_nailgun_name = "mock_non_existing_workdir".to_string();
        let runner = mock_nailgun_runner(Some(mock_workdir_base.clone()));

        let target_workdir = mock_workdir_base.join(mock_nailgun_name.clone());
        assert!(!target_workdir.exists());
        let res = runner.get_nailguns_workdir(&mock_nailgun_name);
        assert_eq!(res, Ok(target_workdir.clone()));
        assert!(target_workdir.exists());
    }

    #[test]
    fn get_workdir_returns_the_workdir_when_it_exists() {
        let mock_workdir_base = unique_temp_dir(std::env::temp_dir(), None).into_path();
        let mock_nailgun_name = "mock_existing_workdir".to_string();
        let runner = mock_nailgun_runner(Some(mock_workdir_base.clone()));

        let target_workdir = mock_workdir_base.join(mock_nailgun_name.clone());
        assert!(!target_workdir.exists());
        let creation_res = fs::safe_create_dir_all(&target_workdir);
        assert!(creation_res.is_ok());
        assert!(target_workdir.exists());

        let res = runner.get_nailguns_workdir(&mock_nailgun_name);
        assert_eq!(res, Ok(target_workdir.clone()));
        assert!(target_workdir.exists());
    }
}
