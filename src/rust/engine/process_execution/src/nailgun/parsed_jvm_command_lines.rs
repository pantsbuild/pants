use itertools::Itertools;
use std::slice::Iter;

/// Represents the result of parsing the args of a nailgunnable ExecuteProcessRequest
/// TODO(8481) We may want to split the classpath by the ":", and store it as a Vec<String>
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
    pub fn parse_command_lines(args: &Vec<String>) -> Result<ParsedJVMCommandLines, String> {
        let mut args_to_consume = args.iter();

        let jdk = Self::parse_jdk(&mut args_to_consume)?;
        let nailgun_args_before_classpath = Self::parse_jvm_args_that_are_not_classpath(&mut args_to_consume)?;
        let (classpath_flag, classpath_value) = Self::parse_classpath(&mut args_to_consume)?;
        let nailgun_args_after_classpath = Self::parse_jvm_args_that_are_not_classpath(&mut args_to_consume)?;
        let main_class = Self::parse_main_class(&mut args_to_consume)?;
        let client_args = Self::parse_to_end(&mut args_to_consume)?;

        if args_to_consume.clone().peekable().peek().is_some() {
            return Err(
                format!("Malformed command line: There are still arguments to consume: {:?}", &args_to_consume)
            )
        }

        let mut nailgun_args = vec![jdk];
        nailgun_args.extend(nailgun_args_before_classpath);
        nailgun_args.push(classpath_flag);
        nailgun_args.push(classpath_value);
        nailgun_args.extend(nailgun_args_after_classpath);

        Ok(ParsedJVMCommandLines{
            nailgun_args: nailgun_args,
            client_args: client_args,
            client_main_class: main_class,
        })
    }

    fn parse_jdk(args_to_consume: &mut Iter<String>) -> Result<String, String> {
        args_to_consume
            .next()
            .filter(|&e| e == &".jdk/bin/java".to_string())
            .ok_or(format!("Every command line must start with a call to the jdk."))
            .map(|e| e.clone())
    }

    fn parse_jvm_args_that_are_not_classpath(args_to_consume: &mut Iter<String>) -> Result<Vec<String>, String> {
        Ok(args_to_consume
            .take_while_ref(|elem|
                ParsedJVMCommandLines::is_flag(elem) && !ParsedJVMCommandLines::is_classpath_flag(elem)
            )
            .map(|e| e.clone())
            .collect())
    }

    fn parse_classpath(args_to_consume: &mut Iter<String>) -> Result<(String, String), String> {
        let classpath_flag = args_to_consume
            .next()
            .filter(|e| ParsedJVMCommandLines::is_classpath_flag(&e))
            .ok_or_else(|| format!("No classpath flag found."))
            .map(|e| e.clone())?;

        let classpath_value = args_to_consume
            .next()
            .ok_or(format!("No classpath value found!"))
            .and_then(|elem|
                if ParsedJVMCommandLines::is_flag(elem) {
                    Err(format!("Classpath value has incorrect formatting {}.", elem))
                } else {
                    Ok(elem)
                }
            )?
            .clone();

        Ok((classpath_flag, classpath_value))
    }

    fn parse_main_class(args_to_consume: &mut Iter<String>) -> Result<String, String> {
        args_to_consume
            .next()
            .filter(|e| !ParsedJVMCommandLines::is_flag(e))
            .ok_or("No main class provided.".to_string())
            .map(|e| e.clone())
    }

    fn parse_to_end(args_to_consume: &mut Iter<String>) -> Result<Vec<String>, String> {
        Ok(args_to_consume.map(|e| e.clone()).collect())
    }

    fn is_flag(arg: &String) -> bool {
        arg.starts_with("-") || arg.starts_with("@")
    }

    fn is_classpath_flag(arg: &String) -> bool {
        arg == "-cp" || arg == "-classpath"
    }
}

#[cfg(test)]
mod tests {
    use crate::nailgun::parsed_jvm_command_lines::ParsedJVMCommandLines;

    #[derive(Debug)]
    struct CLIBuilder {
        jdk: Option<String>,
        args_before_classpath: Vec<String>,
        classpath_flag: Option<String>,
        classpath_value: Option<String>,
        args_after_classpath: Vec<String>,
        main_class: Option<String>,
        client_args: Vec<String>,
    }

    impl CLIBuilder {
        pub fn empty() -> CLIBuilder {
            CLIBuilder {
                jdk: None,
                args_before_classpath: vec![],
                classpath_flag: None,
                classpath_value: None,
                args_after_classpath: vec![],
                main_class: None,
                client_args: vec![],
            }
        }
        
        pub fn build(&self) -> CLIBuilder {
            CLIBuilder {
                jdk: self.jdk.clone(),
                args_before_classpath: self.args_before_classpath.clone(),
                classpath_flag: self.classpath_flag.clone(),
                classpath_value: self.classpath_value.clone(),
                args_after_classpath: self.args_after_classpath.clone(),
                main_class: self.main_class.clone(),
                client_args: self.client_args.clone(),
            }
        }

        pub fn with_jdk(&mut self) -> &mut CLIBuilder {
            self.jdk = Some(".jdk/bin/java".to_string());
            self
        }

        pub fn with_nailgun_args(&mut self) -> &mut CLIBuilder {
            self.args_before_classpath = vec!["-Xmx4g".to_string()];
            self.args_after_classpath = vec!["-Xmx4g".to_string()];
            self
        }

        pub fn with_classpath(&mut self) -> &mut CLIBuilder {
            self.with_classpath_flag().with_classpath_value()
        }

        pub fn with_classpath_flag(&mut self) -> &mut CLIBuilder {
            self.classpath_flag = Some("-cp".to_string());
            self
        }

        pub fn with_classpath_value(&mut self) -> &mut CLIBuilder {
            self.classpath_value = Some("scala-compiler.jar:scala-library.jar".to_string());
            self
        }

        pub fn with_main_class(&mut self) -> &mut CLIBuilder {
            self.main_class = Some("org.pantsbuild.zinc.compiler.Main".to_string());
            self
        }

        pub fn with_client_args(&mut self) -> &mut CLIBuilder {
            self.client_args = vec!["-some-arg-for-zinc".to_string(), "@argfile".to_string()];
            self
        }

        pub fn with_everything() -> CLIBuilder {
            CLIBuilder::empty()
                .with_jdk()
                .with_nailgun_args()
                .with_classpath()
                .with_main_class()
                .with_client_args()
                .build()            
        }

        pub fn render_to_full_cli(&self) -> Vec<String> {
            let mut cli = vec![];
            cli.extend(self.jdk.clone());
            cli.extend(self.args_before_classpath.clone());
            cli.extend(self.classpath_flag.clone());
            cli.extend(self.classpath_value.clone());
            cli.extend(self.args_after_classpath.clone());
            cli.extend(self.main_class.clone());
            cli.extend(self.client_args.clone());
            cli
        }

        pub fn render_to_parsed_args(&self) -> ParsedJVMCommandLines {
            let mut nailgun_args: Vec<String> = self.jdk.iter().map(|e| e.clone()).collect();
            nailgun_args.extend(self.args_before_classpath.clone());
            nailgun_args.extend(self.classpath_flag.clone());
            nailgun_args.extend(self.classpath_value.clone());
            nailgun_args.extend(self.args_after_classpath.clone());
            ParsedJVMCommandLines {
                nailgun_args: nailgun_args,
                client_args: self.client_args.clone(),
                client_main_class: self.main_class.clone().unwrap(),
            }
        }
    }

    #[test]
    fn parses_correctly_formatted_cli() {
        let correctly_formatted_cli = CLIBuilder::with_everything();

        let parse_result =
            ParsedJVMCommandLines::parse_command_lines(&correctly_formatted_cli.render_to_full_cli());

        assert_eq!(
            parse_result,
            Ok(correctly_formatted_cli.render_to_parsed_args())
        )
    }

    #[test]
    fn parses_cli_without_jvm_args() {
        let cli_without_jvm_args =
            CLIBuilder::empty().with_jdk().with_classpath().with_main_class().with_client_args().build();

        let parse_result =
            ParsedJVMCommandLines::parse_command_lines(&cli_without_jvm_args.render_to_full_cli());

        assert_eq!(
            parse_result,
            Ok(cli_without_jvm_args.render_to_parsed_args())
        )
    }

    #[test]
    fn fails_to_parse_cli_without_jdk() {
        let cli_without_jdk =
            CLIBuilder::empty().with_nailgun_args().with_main_class().build();

        let parse_result =
            ParsedJVMCommandLines::parse_command_lines(&cli_without_jdk.render_to_full_cli());

        assert_eq!(
            parse_result,
            Err("Every command line must start with a call to the jdk.".to_string())
        )
    }

    #[test]
    fn fails_to_parse_cli_without_main_class() {
        let cli_without_main_class =
            CLIBuilder::empty().with_jdk().with_classpath().with_client_args().build();

        let parse_result =
            ParsedJVMCommandLines::parse_command_lines(&cli_without_main_class.render_to_full_cli());

        assert_eq!(
            parse_result,
            Err("No main class provided.".to_string())
        )
    }

    #[test]
    fn fails_to_parse_cli_without_classpath() {
        let cli_without_classpath =
            CLIBuilder::empty().with_jdk().with_nailgun_args().with_main_class().with_client_args().build();

        let parse_result =
            ParsedJVMCommandLines::parse_command_lines(&cli_without_classpath.render_to_full_cli());

        assert_eq!(
            parse_result,
            Err("No classpath flag found.".to_string())
        )
    }

    #[test]
    fn fails_to_parse_cli_without_classpath_value() {
        let cli_without_classpath_value =
            CLIBuilder::empty().with_jdk().with_classpath_flag().with_nailgun_args().with_main_class().build();

        let parse_result =
            ParsedJVMCommandLines::parse_command_lines(&cli_without_classpath_value.render_to_full_cli());

        assert_eq!(
            parse_result,
            Err("Classpath value has incorrect formatting -Xmx4g.".to_string())
        )
    }
}

