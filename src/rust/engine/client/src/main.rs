// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::convert::{AsRef, Infallible};
use std::env;
use std::ffi::{CString, OsString};
use std::os::unix::ffi::OsStringExt;
use std::path::PathBuf;
use std::str::FromStr;
use std::time::SystemTime;

use nix::unistd::execv;
use strum::VariantNames;
use strum_macros::{AsRefStr, EnumString, EnumVariantNames};

use options::{option_id, render_choice, Args, BuildRoot, Env, OptionParser};
use pantsd::find_pantsd;

// TODO(John Sirois): Maybe consolidate with PythonLogLevel in src/rust/engine/logging/src/lib.rs.
#[derive(AsRefStr, EnumString, EnumVariantNames)]
#[strum(serialize_all = "snake_case")]
enum PythonLogLevel {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
}

async fn execute(start: SystemTime) -> Result<i32, String> {
    let build_root = BuildRoot::find()?;
    let (env, dropped) = Env::capture_lossy();
    let env_items = (&env).into();
    let argv = env::args().collect::<Vec<_>>();
    let options_parser = OptionParser::new(env, Args::argv())?;

    let use_pantsd = options_parser.parse_bool(&option_id!("pantsd"), true)?;
    if !use_pantsd.value {
        return Err(format!(
            "Pantsd has been turned off via {option_source:?}.",
            option_source = use_pantsd.source
        ));
    }

    let concurrent = options_parser.parse_bool(&option_id!("concurrent"), false)?;
    if concurrent.value {
        return Err("Pantsd is being turned off since --concurrent is true.".to_owned());
    }

    let level_option = option_id!(-'l', "level");
    let log_level_option_value =
        options_parser.parse_string(&level_option, PythonLogLevel::Info.as_ref())?;
    let level = PythonLogLevel::from_str(&log_level_option_value.value).map_err(|_| {
        format!(
            "Not a valid log level {level} from {option_source:?}. Should be one of {levels}.",
            level = log_level_option_value.value,
            option_source = log_level_option_value.source,
            levels = render_choice(PythonLogLevel::VARIANTS)
                .expect("We know there is at least one PythonLogLevel enum variant."),
        )
    })?;
    env_logger::init_from_env(env_logger::Env::new().filter_or("__PANTS_LEVEL__", level.as_ref()));

    // Now that the logger has been set up, we can retroactively log any dropped env vars.
    let mut keys_with_non_utf8_values = dropped.keys_with_non_utf8_values;
    keys_with_non_utf8_values.sort();
    for name in keys_with_non_utf8_values {
        log::warn!("Environment variable with non-UTF-8 value ignored: {name}");
    }
    let mut non_utf8_keys = dropped.non_utf8_keys;
    non_utf8_keys.sort();
    for name in non_utf8_keys {
        log::warn!(
            "Environment variable with non-UTF-8 name ignored: {}",
            name.to_string_lossy()
        );
    }
    let pantsd_settings = find_pantsd(&build_root, &options_parser)?;
    client::execute_command(start, pantsd_settings, env_items, argv).await
}

fn try_execv_fallback_client(pants_server: OsString) -> Result<Infallible, i32> {
    let exe = PathBuf::from(pants_server.clone());
    let c_exe = CString::new(exe.into_os_string().into_vec())
        .expect("Failed to convert executable to a C string.");

    let mut c_args = vec![c_exe.clone()];
    c_args.extend(env::args_os().skip(1).map(|arg| {
        CString::new(arg.into_vec()).expect("Failed to convert argument to a C string.")
    }));

    execv(&c_exe, &c_args).map_err(|errno| {
        eprintln!("Failed to exec pants at {pants_server:?}: {}", errno.desc());
        1
    })
}

fn execv_fallback_client(pants_server: OsString) -> Infallible {
    if let Err(exit_code) = try_execv_fallback_client(pants_server) {
        std::process::exit(exit_code);
    }
    unreachable!()
}

// The value is taken from this C precedent:
// ```
// $ grep 75 /usr/include/sysexits.h
// #define EX_TEMPFAIL	75	/* temp failure; user is invited to retry */
// ```
const EX_TEMPFAIL: i32 = 75;

// An environment variable which if set, points to a non-native entrypoint to fall back to if
// `pantsd` is not already running with the appropriate fingerprint.
//
// This environment variable constitutes a public API used by `scie-pants` and the `pants` script.
// But in future, the native client may become the only client for `pantsd` (by directly handling
// forking the `pantsd` process and then connecting to it).
const PANTS_SERVER_EXE: &str = "_PANTS_SERVER_EXE";
// An end-user-settable environment variable to skip attempting to use the native client, and
// immediately delegate to the legacy client.
const PANTS_NO_NATIVE_CLIENT: &str = "PANTS_NO_NATIVE_CLIENT";

#[tokio::main]
async fn main() {
    let start = SystemTime::now();
    let no_native_client =
        matches!(env::var_os(PANTS_NO_NATIVE_CLIENT), Some(value) if !value.is_empty());
    let pants_server = env::var_os(PANTS_SERVER_EXE);

    match &pants_server {
        Some(pants_server) if no_native_client => {
            // The user requested that the native client not be used. Immediately fall back to the legacy
            // client.
            execv_fallback_client(pants_server.clone());
            return;
        }
        _ => {}
    }

    match (execute(start).await, pants_server) {
        (Err(_), Some(pants_server)) => {
            // We failed to connect to `pantsd`, but a server variable was provided. Fall back
            // to `execv`'ing the legacy Python client, which will handle spawning `pantsd`.
            execv_fallback_client(pants_server);
        }
        (Err(err), None) => {
            eprintln!("{err}");
            // We use this exit code to indicate an error running pants via the nailgun protocol to
            // differentiate from a successful nailgun protocol session.
            std::process::exit(EX_TEMPFAIL);
        }
        (Ok(exit_code), _) => std::process::exit(exit_code),
    }
}
