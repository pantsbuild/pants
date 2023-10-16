// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
    clippy::unseparated_literal_suffix,
    clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
    clippy::len_without_is_empty,
    clippy::redundant_field_names,
    clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use std::convert::AsRef;
use std::env;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::time::SystemTime;

use log::debug;
use strum::VariantNames;
use strum_macros::{AsRefStr, EnumString, EnumVariantNames};

use client::pantsd;
use options::{option_id, render_choice, OptionParser};

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
    let options_parser = OptionParser::new()?;

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

    let working_dir = env::current_dir()
        .map_err(|e| format!("Could not detect current working directory: {err}", err = e))?;
    let pantsd_settings = find_pantsd(&working_dir, &options_parser)?;
    let env = env::vars().collect::<Vec<(_, _)>>();
    let argv = env::args().collect::<Vec<_>>();
    client::execute_command(start, pantsd_settings, env, argv).await
}

fn find_pantsd(
    working_dir: &Path,
    options_parser: &OptionParser,
) -> Result<client::ConnectionSettings, String> {
    let pants_subprocessdir = option_id!("pants", "subprocessdir");
    let option_value = options_parser.parse_string(&pants_subprocessdir, ".pids")?;
    let metadata_dir = {
        let path = PathBuf::from(&option_value.value);
        if path.is_absolute() {
            path
        } else {
            match working_dir.join(&path) {
                p if p.is_absolute() => p,
                p => p.canonicalize().map_err(|e| {
                    format!(
            "Failed to resolve relative pants subprocessdir specified via {:?} as {}: {}",
            option_value,
            path.display(),
            e
          )
                })?,
            }
        }
    };
    debug!(
        "\
    Looking for pantsd metadata in {metadata_dir} as specified by {option} = {value} via \
    {source:?}.\
    ",
        metadata_dir = metadata_dir.display(),
        option = pants_subprocessdir,
        value = option_value.value,
        source = option_value.source
    );
    let port = pantsd::probe(working_dir, &metadata_dir)?;
    let mut pantsd_settings = client::ConnectionSettings::new(port);
    pantsd_settings.timeout_limit = options_parser
        .parse_float(
            &option_id!("pantsd", "timeout", "when", "multiple", "invocations"),
            pantsd_settings.timeout_limit,
        )?
        .value;
    pantsd_settings.dynamic_ui = options_parser
        .parse_bool(&option_id!("dynamic", "ui"), pantsd_settings.dynamic_ui)?
        .value;
    Ok(pantsd_settings)
}

// The value is taken from this C precedent:
// ```
// $ grep 75 /usr/include/sysexits.h
// #define EX_TEMPFAIL	75	/* temp failure; user is invited to retry */
// ```
const EX_TEMPFAIL: i32 = 75;

#[tokio::main]
async fn main() {
    let start = SystemTime::now();
    match execute(start).await {
        Err(err) => {
            eprintln!("{}", err);
            // We use this exit code to indicate an error running pants via the nailgun protocol to
            // differentiate from a successful nailgun protocol session.
            std::process::exit(EX_TEMPFAIL);
        }
        Ok(exit_code) => std::process::exit(exit_code),
    }
}
