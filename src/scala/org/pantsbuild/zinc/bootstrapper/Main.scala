/**
  * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
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
