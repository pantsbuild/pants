/**
  * Copyright (C) 2018 Pants project contributors (see CONTRIBUTORS.md).
  * Licensed under the Apache License, Version 2.0 (see LICENSE).
  */

package org.pantsbuild.zinc.bootstrapper

import org.pantsbuild.zinc.scalautil.ScalaUtils
import sbt.internal.util.ConsoleLogger

object Main {
  def main(args: Array[String]): Unit = {
    Cli.CliParser.parse(args, Configuration()) match {
      case Some(cliArgs) => {
        val scalaInstance = ScalaUtils
          .scalaInstance(cliArgs.scalaCompiler,
                         Seq(cliArgs.scalaReflect),
                         cliArgs.scalaLibrary)

        // As per https://github.com/pantsbuild/pants/issues/6160, this is a workaround
        // so we can run zinc without $PATH (as needed in remoting).
        System.setProperty("sbt.log.format", "true")

        val cl = ConsoleLogger.apply()

        BootstrapperUtils
          .compilerInterface(cliArgs.outputPath,
                             cliArgs.compilerBridgeSource,
                             cliArgs.compilerInterface,
                             scalaInstance,
                             cl)
      }
      case None => System.exit(1)
    }
  }
}
