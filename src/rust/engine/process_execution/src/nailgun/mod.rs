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

pub use nailgun_pool::NailgunPool;
use workunit_store::WorkUnitStore;

// Hardcoded constants for connecting to nailgun
static NAILGUN_MAIN_CLASS: &str = "com.martiansoftware.nailgun.NGServer";
static ARGS_TO_START_NAILGUN: [&str; 1] = [":0"];

// We can hardcode this because we mix it into the digest in the EPR.
static NG_CLIENT_PATH: &str = "bin/ng/1.0.0/ng";

/// Represents the result of parsing the args of a nailgunnable ExecuteProcessRequest
/// TODO(8481) We may want to split the classpath by the ":", and store it as a Vec<String>
///         to allow for deep fingerprinting.
struct ParsedJVMCommandLines {
    nailgun_args: Vec<String>,
    client_args: Vec<String>,
    main_class: String,
}

///
/// Given a list of args that one would likely pass to a java call,
/// we automatically split it to generate two argument lists:
///  - nailgun arguments: The list of arguments needed to start the nailgun server.
///    These arguments include everything in the arg list up to (but not including) the main class.
///    These arguments represent roughly JVM options (-Xmx...), and the classpath (-cp ...).
///
///  - client arguments: The list of arguments that will be used to run the jvm program under nailgun.
///    These arguments can be thought of as "passthrough args" that are sent to the jvm via the nailgun client.
///    These arguments include everything starting from the main class.
///
/// We assume that:
///  - Every args list has a main class.
///  - There is exactly one argument that doesn't begin with a `-` in the command line before the main class,
///    and it's the value of the classpath (i.e. `-cp scala-library.jar`).
///
/// We think these assumptions are valid as per: https://github.com/pantsbuild/pants/issues/8387
///
fn split_args(args: &Vec<String>) -> ParsedJVMCommandLines {
    let mut nailgun_args = vec![];
    let mut client_args = vec![];
    let mut main_class = "".to_string();
    let mut have_seen_classpath = false;
    let mut have_processed_classpath = false;
    let mut have_seen_main_class = false;
    for arg in args {
        if have_seen_main_class {
            // Arguments to pass to the client request
            client_args.push(arg.clone());
        } else if (arg == "-cp" || arg == "-classpath") && !have_seen_classpath {
            // Process the -cp flag itself
            have_seen_classpath = true;
            nailgun_args.push(arg.clone());
        } else if have_seen_classpath && !have_processed_classpath {
            // Process the classpath string
            nailgun_args.push(arg.clone());
            have_processed_classpath = true;
        } else if have_processed_classpath && !arg.starts_with("-") {
            // Process the main class:
            // I have already seen the value of the -cp classpath, and this is not a flag.
            main_class = arg.clone();
            have_seen_main_class = true;
        } else {
            // Process the rest (jvm options to pass to nailgun)
            nailgun_args.push(arg.clone());
        }
    }
    ParsedJVMCommandLines {
        nailgun_args: nailgun_args,
        client_args: client_args,
        main_class: main_class,
    }
}

// TODO(8481) The input_files arg should be calculated from deeply fingerprinting the classpath.
fn get_nailgun_request(args: Vec<String>, _input_files: Digest, jdk: Option<PathBuf>, platform: Platform) -> ExecuteProcessRequest {
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
    pub fn new(runner: super::local::CommandRunner, metadata: ExecuteProcessRequestMetadata, python_distribution_absolute_path: PathBuf) -> Self {
        NailgunCommandRunner {
            inner: Arc::new(runner),
            nailgun_pool: NailgunPool::new(),
            metadata: metadata,
            workdir_base: std::env::temp_dir(),
            python_distribution_absolute_path: python_distribution_absolute_path,
        }
    }

    // Ensure that the workdir for the given nailgun name exists.
    fn get_nailguns_workdir(&self, nailgun_name: &NailgunProcessName) -> Result<PathBuf, String> {
        let workdir = self.workdir_base.clone().join(nailgun_name);
        if self.workdir_base.exists() {
            debug!("Creating nailgun workdir at {:?}", self.workdir_base);
            std::fs::create_dir_all(workdir.clone())
                .map_err(|err| format!("Error creating the nailgun workdir! {}", err))
                .map(|_| workdir)
        } else {
            debug!("nailgun workdir {:?} exits. Reusing that...", self.workdir_base);
            Ok(workdir)
        }
    }

    fn calculate_nailgun_name(main_class: &String, digest: &Digest) -> String {
        format!("{}_{}", main_class, digest.0)
    }

    // TODO(8481) When we correctly set the input_files field of the nailgun EPR, we won't need to pass it here as an argument.
    // TODO(8489) We should move this code to NailgunPool. This returns a Future, so this will involve making the struct Futures-aware.
    fn materialize_workdir_for_server(&self, nailgun_workdir: &PathBuf, nailgun_request: &ExecuteProcessRequest, input_files: Digest, workunit_store: WorkUnitStore) -> BoxFuture<(), String> {
        let maybe_jdk_home = nailgun_request.jdk_home.clone();
        // Materialize the directory for running the nailgun server, if we need to.
        let nailgun_workdir_path2 = nailgun_workdir.clone();
        let nailgun_workdir_path3 = nailgun_workdir.clone();
        let nailgun_workdir_path4 = nailgun_workdir.clone();
        self.inner
            .store
            // TODO(8481) This materializes the input files in the client req, which is a superset of the files we need (we only need the classpath, not the input files)
            .materialize_directory(nailgun_workdir.clone(), input_files, workunit_store)
            .and_then(move |_metadata| {
                maybe_jdk_home.map_or(Ok(()), |jdk_home_relpath| {
                    let jdk_home_in_workdir = nailgun_workdir_path2.clone().join(".jdk");
                    if !jdk_home_in_workdir.exists() {
                        symlink(jdk_home_relpath, jdk_home_in_workdir)
                            .map_err(|err| format!("Error making symlink for local execution in workdir {:?}: {:?}", &nailgun_workdir_path2, err))
                    } else {
                        debug!("JDK home for Nailgun already exists in {:?}. Using that one.", &nailgun_workdir_path4);
                        Ok(())
                    }
                })?;
                Ok(())
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

        let mut client_req = self.extract_compatible_request(&req).unwrap();

        if !client_req.is_nailgunnable {
            trace!("The request is not nailgunnable! Short-circuiting to regular process execution");
            return self.inner.run(req, context)
        }
        debug!("Running request under nailgun:\n {:#?}", &client_req);

        // Separate argument lists, to form distinct EPRs for (1) starting the nailgun server and (2) running the client in it.
        let ParsedJVMCommandLines {nailgun_args, client_args, main_class } = split_args(&client_req.argv);
        let nailgun_req = get_nailgun_request(nailgun_args, client_req.input_files, client_req.jdk_home.clone(), client_req.target_platform);
        trace!("Extracted nailgun request:\n {:#?}", &nailgun_req);

        let nailgun_req_digest = crate::digest(MultiPlatformExecuteProcessRequest::from(nailgun_req.clone()), &self.metadata);

        let nailgun_name = NailgunCommandRunner::calculate_nailgun_name(&main_class, &nailgun_req_digest);
        let nailgun_name2 = nailgun_name.clone();
        let nailgun_name3 = nailgun_name.clone();
        let nailgun_pool = self.nailgun_pool.clone();
        let inner = self.inner.clone();
        let python_distribution = self.get_python_distribution();

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
                        client_req.argv.push(main_class);
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
