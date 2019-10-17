
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

        let nailgun_args_before_classpath = Self::parse_jvm_args_that_are_not_classpath(&mut args_to_consume)?;
        let (classpath_flag, classpath_value) = Self::parse_classpath(&mut args_to_consume)?;
        let nailgun_args_after_classpath = Self::parse_jvm_args_that_are_not_classpath(&mut args_to_consume)?;
        let main_class = Self::parse_main_class(&mut args_to_consume)?;
        let client_args = Self::parse_to_end(&mut args_to_consume)?;

        let mut nailgun_args = nailgun_args_before_classpath;
        nailgun_args.push(classpath_flag);
        nailgun_args.push(classpath_value);
        nailgun_args.extend(nailgun_args_after_classpath);

        Ok(ParsedJVMCommandLines{
            nailgun_args: nailgun_args,
            client_args: client_args,
            client_main_class: main_class,
        })
    }

    fn parse_jvm_args_that_are_not_classpath(_args_to_consume: &mut dyn Iterator<Item=&String>) -> Result<Vec<String>, String> {
        unimplemented!()
    }

    fn parse_classpath(_args_to_consume: &mut dyn Iterator<Item=&String>) -> Result<(String, String), String> {
        unimplemented!()
    }

    fn parse_main_class(_args_to_consume: &mut dyn Iterator<Item=&String>) -> Result<String, String> {
        unimplemented!()
    }

    fn parse_to_end(_args_to_consume: &mut dyn Iterator<Item=&String>) -> Result<Vec<String>, String> {
        unimplemented!()
    }
}

#[cfg(test)]
mod tests {
    use crate::nailgun::parsed_jvm_command_lines::ParsedJVMCommandLines;

    struct CLIBuilder {
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
                args_before_classpath: self.args_before_classpath.clone(),
                classpath_flag: self.classpath_flag.clone(),
                classpath_value: self.classpath_value.clone(),
                args_after_classpath: self.args_after_classpath.clone(),
                main_class: self.main_class.clone(),
                client_args: self.client_args.clone(),
            }
        }

        pub fn with_nailgun_args(&mut self) -> &mut CLIBuilder {
            self.args_before_classpath = vec!["-Xmx4g".to_string()];
            self.args_after_classpath = vec!["-Xmx4g".to_string()];
            self
        }

        pub fn with_classpath(&mut self) -> &mut CLIBuilder {
            self.classpath_flag = Some("-cp".to_string());
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
                .with_nailgun_args()
                .with_classpath()
                .with_main_class()
                .with_client_args()
                .build()            
        }

        pub fn render_to_full_cli(&self) -> Vec<String> {
            let mut cli = vec![];
            cli.extend(self.args_before_classpath.clone());
            cli.extend(self.classpath_flag.clone());
            cli.extend(self.classpath_value.clone());
            cli.extend(self.args_after_classpath.clone());
            cli.extend(self.main_class.clone());
            cli.extend(self.client_args.clone());
            cli
        }

        pub fn render_to_parsed_args(&self) -> ParsedJVMCommandLines {
            let mut nailgun_args: Vec<String> = self.args_before_classpath.clone();
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
}

