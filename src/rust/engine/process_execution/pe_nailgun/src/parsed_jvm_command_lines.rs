// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use itertools::Itertools;
use std::slice::Iter;

/// Represents the result of parsing the args of a nailgunnable Process
/// TODO(#8481) We may want to split the classpath by the ":", and store it as a Vec<String>
///         to allow for deep fingerprinting.
#[derive(PartialEq, Eq, Debug)]
pub struct ParsedJVMCommandLines {
    pub nailgun_args: Vec<String>,
    pub client_args: Vec<String>,
    pub client_main_class: String,
}

impl ParsedJVMCommandLines {
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
    pub fn parse_command_lines(args: &[String]) -> Result<ParsedJVMCommandLines, String> {
        let mut args_to_consume = args.iter();

        let nailgun_args_before_classpath = Self::parse_to_classpath(&mut args_to_consume)?;
        let (classpath_flag, classpath_value) = Self::parse_classpath(&mut args_to_consume)?;
        let nailgun_args_after_classpath = Self::parse_jvm_args(&mut args_to_consume)?;
        let main_class = Self::parse_main_class(&mut args_to_consume)?;
        let client_args = Self::parse_to_end(&mut args_to_consume)?;

        if args_to_consume.clone().peekable().peek().is_some() {
            return Err(format!(
                "Malformed command line: There are still arguments to consume: {:?}",
                &args_to_consume
            ));
        }

        let mut nailgun_args = nailgun_args_before_classpath;
        nailgun_args.push(classpath_flag);
        nailgun_args.push(classpath_value);
        nailgun_args.extend(nailgun_args_after_classpath);

        Ok(ParsedJVMCommandLines {
            nailgun_args,
            client_args,
            client_main_class: main_class,
        })
    }

    fn parse_to_classpath(args_to_consume: &mut Iter<String>) -> Result<Vec<String>, String> {
        Ok(args_to_consume
            .take_while_ref(|elem| !ParsedJVMCommandLines::is_classpath_flag(elem))
            .cloned()
            .collect())
    }

    fn parse_classpath(args_to_consume: &mut Iter<String>) -> Result<(String, String), String> {
        let classpath_flag = args_to_consume
            .next()
            .filter(|e| ParsedJVMCommandLines::is_classpath_flag(e))
            .ok_or_else(|| "No classpath flag found.".to_string())
            .map(|e| e.clone())?;

        let classpath_value = args_to_consume
            .next()
            .ok_or_else(|| "No classpath value found!".to_string())
            .and_then(|elem| {
                if ParsedJVMCommandLines::is_flag(elem) {
                    Err(format!("Classpath value has incorrect formatting {elem}."))
                } else {
                    Ok(elem)
                }
            })?
            .clone();

        Ok((classpath_flag, classpath_value))
    }

    fn parse_jvm_args(args_to_consume: &mut Iter<String>) -> Result<Vec<String>, String> {
        Ok(args_to_consume
            .take_while_ref(|elem| ParsedJVMCommandLines::is_flag(elem))
            .cloned()
            .collect())
    }

    fn parse_main_class(args_to_consume: &mut Iter<String>) -> Result<String, String> {
        args_to_consume
            .next()
            .filter(|e| !ParsedJVMCommandLines::is_flag(e))
            .ok_or_else(|| "No main class provided.".to_string())
            .map(|e| e.clone())
    }

    fn parse_to_end(args_to_consume: &mut Iter<String>) -> Result<Vec<String>, String> {
        Ok(args_to_consume.cloned().collect())
    }

    fn is_flag(arg: &str) -> bool {
        arg.starts_with('-') || arg.starts_with('@')
    }

    fn is_classpath_flag(arg: &str) -> bool {
        arg == "-cp" || arg == "-classpath"
    }
}
