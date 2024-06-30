// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
#![allow(unused)]

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fs::File;
use std::path::{Path, PathBuf};
use std::str;
use std::sync::Arc;
use std::time::Duration;

use maplit::hashset;
use shell_quote::bash;
use tempfile::TempDir;

use fs::EMPTY_DIRECTORY_DIGEST;
use store::{ImmutableInputs, Store};
use testutil::data::{TestData, TestDirectory};
use testutil::path::{find_bash, which};
use testutil::{owned_string_vec, relative_paths};
use tokio::sync::RwLock;
use workunit_store::{RunningWorkunit, WorkunitStore};

use crate::local_tests::named_caches_and_immutable_inputs;
use crate::{
    workspace, CacheName, CommandRunner as CommandRunnerTrait, Context,
    FallibleProcessResultWithPlatform, InputDigests, NamedCaches, Process, ProcessError,
    RelativePath,
};

#[derive(PartialEq, Debug)]
struct TestResult {
    original: FallibleProcessResultWithPlatform,
    stdout_bytes: Vec<u8>,
    stderr_bytes: Vec<u8>,
}

async fn run_command(req: Process, workspace_dir: &Path) -> Result<TestResult, ProcessError> {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();
    let work_dir = TempDir::new().unwrap();

    run_command_with_workdir(
        req,
        workspace_dir,
        work_dir.path(),
        &mut workunit,
        None,
        None,
    )
    .await
}

async fn run_command_with_workdir(
    mut req: Process,
    workspace_dir: &Path,
    work_dir: &Path,
    workunit: &mut RunningWorkunit,
    store: Option<Store>,
    executor: Option<task_executor::Executor>,
) -> Result<TestResult, ProcessError> {
    let store_dir = TempDir::new().unwrap();

    let executor = executor.unwrap_or_else(task_executor::Executor::new);

    let store = store.unwrap_or_else(|| Store::local_only(executor.clone(), &store_dir).unwrap());

    let (_caches_dir, named_caches, immutable_inputs) =
        named_caches_and_immutable_inputs(store.clone());

    let runner = crate::workspace::CommandRunner::new(
        store.clone(),
        executor.clone(),
        workspace_dir.to_path_buf(),
        work_dir.to_path_buf(),
        named_caches,
        immutable_inputs,
        Arc::new(RwLock::new(())),
    );

    let original = runner.run(Context::default(), workunit, req).await?;
    let stdout_bytes = store
        .load_file_bytes_with(original.stdout_digest, |bytes| bytes.to_vec())
        .await?;
    let stderr_bytes = store
        .load_file_bytes_with(original.stderr_digest, |bytes| bytes.to_vec())
        .await?;

    Ok(TestResult {
        original,
        stdout_bytes,
        stderr_bytes,
    })
}

#[tokio::test]
#[cfg(unix)]
async fn stdout() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(owned_string_vec(&["/bin/echo", "-n", "foo"])),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "foo".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
#[cfg(unix)]
async fn stdout_and_stderr_and_exit_code() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(owned_string_vec(&[
            "/bin/bash",
            "-c",
            "echo -n foo ; echo >&2 -n bar ; exit 1",
        ])),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "foo".as_bytes());
    assert_eq!(result.stderr_bytes, "bar".as_bytes());
    assert_eq!(result.original.exit_code, 1);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
#[cfg(unix)]
async fn capture_exit_code_signal() {
    // Launch a process that kills itself with a signal.
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(owned_string_vec(&["/bin/bash", "-c", "kill $$"])),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, -15);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
#[cfg(unix)]
async fn env() {
    let mut env: BTreeMap<String, String> = BTreeMap::new();
    env.insert("FOO".to_string(), "foo".to_string());
    env.insert("BAR".to_string(), "not foo".to_string());

    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(owned_string_vec(&["/usr/bin/env"])).env(env.clone()),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    let stdout = String::from_utf8(result.stdout_bytes.to_vec()).unwrap();
    let got_env: BTreeMap<String, String> = stdout
        .split('\n')
        .filter(|line| !line.is_empty())
        .map(|line| line.splitn(2, '='))
        .map(|mut parts| {
            (
                parts.next().unwrap().to_string(),
                parts.next().unwrap_or("").to_string(),
            )
        })
        .filter(|x| x.0 != "PATH")
        .collect();

    assert_eq!(env, got_env);
}

#[tokio::test]
#[cfg(unix)]
async fn env_is_deterministic() {
    fn make_request() -> Process {
        let mut env = BTreeMap::new();
        env.insert("FOO".to_string(), "foo".to_string());
        env.insert("BAR".to_string(), "not foo".to_string());
        Process::new(owned_string_vec(&["/usr/bin/env"])).env(env)
    }

    let workspace_dir = TempDir::new().unwrap();
    let result1 = run_command(make_request(), workspace_dir.path()).await;
    let result2 = run_command(make_request(), workspace_dir.path()).await;

    assert_eq!(result1.unwrap(), result2.unwrap());
}

#[tokio::test]
async fn binary_not_found() {
    let workspace_dir = TempDir::new().unwrap();
    let err_string = run_command(
        Process::new(owned_string_vec(&["./xyzzy"])),
        workspace_dir.path(),
    )
    .await
    .expect_err("Want Err");
    assert!(err_string.to_string().contains("Failed to execute"));
    assert!(err_string.to_string().contains("xyzzy"));
}

#[tokio::test]
async fn output_files_none() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(owned_string_vec(&[&find_bash(), "-c", "exit 0"])),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
async fn output_files_one() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(vec![
            find_bash(),
            "-c".to_owned(),
            format!(
                "echo -n {} > {{chroot}}/roland.ext",
                TestData::roland().string()
            ),
        ])
        .output_files(relative_paths(&["roland.ext"]).collect()),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::containing_roland().directory_digest()
    );
}

#[tokio::test]
async fn output_dirs() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(vec![
            find_bash(),
            "-c".to_owned(),
            format!(
                "/bin/mkdir {{chroot}}/cats && echo -n {} > {{chroot}}/cats/roland.ext ; echo -n {} > {{chroot}}/treats.ext",
                TestData::roland().string(),
                TestData::catnip().string()
            ),
        ])
        .output_files(relative_paths(&["treats.ext"]).collect())
        .output_directories(relative_paths(&["cats"]).collect()), workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::recursive().directory_digest()
    );
}

#[tokio::test]
async fn output_files_many() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(vec![
            find_bash(),
            "-c".to_owned(),
            format!(
                "mkdir -p {{chroot}}/cats && echo -n {} > {{chroot}}/cats/roland.ext ; echo -n {} > {{chroot}}/treats.ext",
                TestData::roland().string(),
                TestData::catnip().string()
            ),
        ])
        .output_files(relative_paths(&["cats/roland.ext", "treats.ext"]).collect()),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::recursive().directory_digest()
    );
}

#[tokio::test]
async fn output_files_execution_failure() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(vec![
            find_bash(),
            "-c".to_owned(),
            format!(
                "echo -n {} > {{chroot}}/roland.ext ; exit 1",
                TestData::roland().string()
            ),
        ])
        .output_files(relative_paths(&["roland.ext"]).collect()),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 1);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::containing_roland().directory_digest()
    );
}

#[tokio::test]
async fn output_files_partial_output() {
    let workspace_dir = TempDir::new().unwrap();

    // Write a file to the workspace. The invoked process will verify it exists but will not capture it since it
    // is not in the sandbox.
    let file_path = workspace_dir.path().join("xyzzy");
    drop(File::create(&file_path).unwrap());

    let result = run_command(
        Process::new(vec![
            find_bash(),
            "-c".to_owned(),
            format!(
                "echo -n {} > {{chroot}}/roland.ext && [ -f ./xyzzy ]",
                TestData::roland().string()
            ),
        ])
        .output_files(relative_paths(&["roland.ext", "xyzzy"]).collect()),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::containing_roland().directory_digest()
    );
}

#[tokio::test]
async fn output_overlapping_file_and_dir() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(vec![
            find_bash(),
            "-c".to_owned(),
            format!(
                "mkdir -p {{chroot}}/cats && echo -n {} > {{chroot}}/cats/roland.ext",
                TestData::roland().string()
            ),
        ])
        .output_files(relative_paths(&["cats/roland.ext"]).collect())
        .output_directories(relative_paths(&["cats"]).collect()),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::nested().directory_digest()
    );
}

#[tokio::test]
async fn append_only_cache_created() {
    let workspace_dir = TempDir::new().unwrap();

    let name = "geo";
    let dest_base = ".cache";
    let cache_name = CacheName::new(name.to_owned()).unwrap();
    let cache_dest = RelativePath::new(format!("{dest_base}/{name}")).unwrap();
    let result = run_command(
        Process::new(vec![
            "/bin/ls".to_owned(),
            format!("{{chroot}}/{}", dest_base),
        ])
        .append_only_caches(vec![(cache_name, cache_dest)].into_iter().collect()),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, format!("{name}\n").as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
async fn test_chroot_placeholder() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();
    let mut env: BTreeMap<String, String> = BTreeMap::new();
    env.insert("PATH".to_string(), "/usr/bin:{chroot}/bin".to_string());

    let work_dir = TempDir::new().unwrap();
    let workspace_dir = TempDir::new().unwrap();

    let result = run_command_with_workdir(
        Process::new(vec!["/usr/bin/env".to_owned()]).env(env.clone()),
        workspace_dir.path(),
        work_dir.path(),
        &mut workunit,
        None,
        None,
    )
    .await
    .unwrap();

    let stdout = String::from_utf8(result.stdout_bytes.to_vec()).unwrap();
    let got_env: BTreeMap<String, String> = stdout
        .split('\n')
        .filter(|line| !line.is_empty())
        .map(|line| line.splitn(2, '='))
        .map(|mut parts| {
            (
                parts.next().unwrap().to_string(),
                parts.next().unwrap_or("").to_string(),
            )
        })
        .collect();

    let path = format!("/usr/bin:{}", work_dir.path().to_str().unwrap());
    assert!(got_env.get(&"PATH".to_string()).unwrap().starts_with(&path));
    assert!(got_env.get(&"PATH".to_string()).unwrap().ends_with("/bin"));
}

#[tokio::test]
async fn test_input_digests_in_sandbox() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let work_dir = TempDir::new().unwrap();

    let store_dir = TempDir::new().unwrap();
    let executor = task_executor::Executor::new();
    let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

    // Prepare the store to contain /cats/roland.ext, because the EPR needs to materialize it and then run
    // from the ./cats directory.
    store
        .store_file_bytes(TestData::roland().bytes(), false)
        .await
        .expect("Error saving file bytes");
    store
        .record_directory(&TestDirectory::containing_roland().directory(), true)
        .await
        .expect("Error saving directory");
    store
        .record_directory(&TestDirectory::nested().directory(), true)
        .await
        .expect("Error saving directory");

    let cp = which("cp").expect("No cp on $PATH.");
    let bash_contents = format!(
        "echo $PWD && {} {{chroot}}/cats/roland.ext ./roland.ext",
        cp.display()
    );

    let mut process = Process::new(vec![find_bash(), "-c".to_owned(), bash_contents.to_owned()]);
    process.input_digests =
        InputDigests::with_input_files(TestDirectory::nested().directory_digest());

    let workspace_dir = TempDir::new().unwrap();
    let result = run_command_with_workdir(
        process,
        workspace_dir.path(),
        work_dir.path(),
        &mut workunit,
        Some(store),
        Some(executor),
    )
    .await
    .unwrap();

    std::fs::metadata(workspace_dir.path().join("roland.ext"))
        .expect("roland.ext copied to workspace");
}

#[tokio::test]
async fn all_containing_directories_for_outputs_are_created() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(vec![
            find_bash(),
            "-c".to_owned(),
            format!(
                // mkdir would normally fail, since birds/ doesn't yet exist, as would echo, since cats/
                // does not exist, but we create the containing directories for all outputs before the
                // process executes.
                "/bin/mkdir {{chroot}}/birds/falcons && echo -n {} > {{chroot}}/cats/roland.ext",
                TestData::roland().string()
            ),
        ])
        .output_files(relative_paths(&["cats/roland.ext"]).collect())
        .output_directories(relative_paths(&["birds/falcons"]).collect()),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, "".as_bytes());
    assert_eq!(String::from_utf8(result.stderr_bytes).unwrap(), "");
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::nested_dir_and_file().directory_digest()
    );
}

#[tokio::test]
async fn output_empty_dir() {
    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(
        Process::new(vec![
            find_bash(),
            "-c".to_owned(),
            "/bin/mkdir {chroot}/falcons".to_string(),
        ])
        .output_directories(relative_paths(&["falcons"]).collect()),
        workspace_dir.path(),
    )
    .await
    .unwrap();

    assert_eq!(String::from_utf8(result.stdout_bytes).unwrap(), "");
    assert_eq!(String::from_utf8(result.stderr_bytes).unwrap(), "");
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::containing_falcons_dir().directory_digest()
    );
}

#[tokio::test]
async fn timeout() {
    let argv = vec![
        find_bash(),
        "-c".to_owned(),
        "/bin/echo -n 'Calculating...'; /bin/sleep 0.5; /bin/echo -n 'European Burmese'"
            .to_string(),
    ];

    let mut process = Process::new(argv);
    process.timeout = Some(Duration::from_millis(100));
    process.description = "sleepy-cat".to_string();

    let workspace_dir = TempDir::new().unwrap();
    let result = run_command(process, workspace_dir.path()).await.unwrap();

    assert_eq!(result.original.exit_code, -15);
    let stdout = String::from_utf8(result.stdout_bytes.to_vec()).unwrap();
    let stderr = String::from_utf8(result.stderr_bytes.to_vec()).unwrap();
    assert!(&stdout.contains("Calculating..."));
    assert!(&stderr.contains("Exceeded timeout"));
    assert!(&stderr.contains("sleepy-cat"));
}

#[tokio::test]
async fn working_directory() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let workspace_dir = TempDir::new().unwrap();

    // Create a directory in the workspace to act as the working directory.
    let subdir_path = workspace_dir.path().join("subdir");
    std::fs::create_dir_all(&subdir_path).unwrap();

    let store_dir = TempDir::new().unwrap();
    let executor = task_executor::Executor::new();
    let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

    // Prepare the store to contain /cats/roland.ext, because the EPR needs to materialize it and
    // then copy from the `cats`` directory in the sandbox.
    store
        .store_file_bytes(TestData::roland().bytes(), false)
        .await
        .expect("Error saving file bytes");
    store
        .record_directory(&TestDirectory::containing_roland().directory(), true)
        .await
        .expect("Error saving directory");
    store
        .record_directory(&TestDirectory::nested().directory(), true)
        .await
        .expect("Error saving directory");

    let work_dir = TempDir::new().unwrap();

    let mut process = Process::new(vec![
        find_bash(),
        "-c".to_owned(),
        "cp {chroot}/cats/roland.ext .".to_owned(),
    ]);
    process.working_directory = Some(RelativePath::new("subdir").unwrap());
    process.input_digests =
        InputDigests::with_input_files(TestDirectory::nested().directory_digest());
    process.timeout = Some(Duration::from_secs(1));

    let result = run_command_with_workdir(
        process,
        workspace_dir.path(),
        work_dir.path(),
        &mut workunit,
        Some(store),
        Some(executor),
    )
    .await
    .unwrap();

    assert_eq!(String::from_utf8(result.stdout_bytes).unwrap(), "");
    assert_eq!(String::from_utf8(result.stderr_bytes).unwrap(), "");
    assert_eq!(result.original.exit_code, 0);

    std::fs::metadata(subdir_path.join("roland.ext")).expect("roland.ext copied to workspace");
}

#[tokio::test]
async fn immutable_inputs() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let store_dir = TempDir::new().unwrap();
    let executor = task_executor::Executor::new();
    let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

    store
        .store_file_bytes(TestData::roland().bytes(), false)
        .await
        .expect("Error saving file bytes");
    store
        .record_directory(&TestDirectory::containing_roland().directory(), true)
        .await
        .expect("Error saving directory");
    store
        .record_directory(&TestDirectory::containing_falcons_dir().directory(), true)
        .await
        .expect("Error saving directory");

    let work_dir = TempDir::new().unwrap();
    let workspace_dir = TempDir::new().unwrap();

    let mut process = Process::new(vec![
        find_bash(),
        "-c".to_owned(),
        "/bin/ls {chroot}".to_string(),
    ]);
    process.input_digests = InputDigests::new(
        &store,
        TestDirectory::containing_falcons_dir().directory_digest(),
        {
            let mut map = BTreeMap::new();
            map.insert(
                RelativePath::new("cats").unwrap(),
                TestDirectory::containing_roland().directory_digest(),
            );
            map
        },
        BTreeSet::default(),
    )
    .await
    .unwrap();
    process.timeout = Some(Duration::from_secs(1));
    process.description = "confused-cat".to_string();

    let result = run_command_with_workdir(
        process,
        workspace_dir.path(),
        work_dir.path(),
        &mut workunit,
        Some(store),
        Some(executor),
    )
    .await
    .unwrap();

    let stdout_lines = str::from_utf8(&result.stdout_bytes)
        .unwrap()
        .lines()
        .collect::<HashSet<_>>();
    assert_eq!(stdout_lines, hashset! {"falcons", "cats"});
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
}
