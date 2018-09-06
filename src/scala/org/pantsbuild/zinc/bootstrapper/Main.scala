/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.bootstrapper

import org.pantsbuild.zinc.scalautil.ScalaUtils
import java.io.File
import sbt.internal.util.ConsoleLogger

object Main {
  /*
   Assume:
   - args(1): outputPath
   - args(2) compilerInterface
   - args(3): compilerBridgeSource
   - args(4): scalaCompiler
   - args(5): scalaLibrary
   - args(6): scalaReflect (in scalaExtra)
    */
  def main(args: Array[String]): Unit = {
    val outputPath = new File(args(0))
    val compilerInterface = new File(args(1))
    val compilerBridgeSource = new File(args(2))
    val scalaCompiler = new File(args(3))
    val scalaLibrary = new File(args(4))
    val scalaReflect = new File(args(5))
    val scalaExtra = Seq(
      scalaReflect
    )
    val scalaInstance = ScalaUtils.scalaInstance(scalaCompiler, scalaExtra, scalaLibrary)

    val cl = ConsoleLogger.apply()

    BootstrapperUtils.compilerInterface(outputPath, compilerBridgeSource, compilerInterface, scalaInstance, cl)
  }
}
