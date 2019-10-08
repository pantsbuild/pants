/**
  * Copyright (C) 2018 Pants project contributors (see CONTRIBUTORS.md).
  * Licensed under the Apache License, Version 2.0 (see LICENSE).
  */

package org.pantsbuild.zinc.bootstrapper

import java.io.File

import com.martiansoftware.nailgun.NGContext
import sbt.internal.util.ConsoleLogger

import org.pantsbuild.zinc.scalautil.ScalaUtils

object Main {

  def mainImpl(cliArgs: Configuration): Unit = {
    System.out.println(cliArgs);
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

  def main(args: Array[String]): Unit = {
    Cli.CliParser.parse(args, Configuration()) match {
      case Some(cliArgs) => {
        mainImpl(cliArgs)
      }
      case None => System.exit(1)
    }
  }

  def nailMain(context: NGContext): Unit = {
    val startTime = System.currentTimeMillis

    Cli.CliParser.parse(context.getArgs, Configuration()) match {
      case Some(settings) =>
        mainImpl(settings.withAbsolutePaths(new File(context.getWorkingDirectory)))
      case None => {
        context.exit(1)
      }
    }
  }
}
