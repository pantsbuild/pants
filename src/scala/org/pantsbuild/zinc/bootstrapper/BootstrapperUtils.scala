/**
 * Copyright (C) 2018 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.bootstrapper

import org.pantsbuild.buck.util.zip.ZipScrubber
import java.io.File
import xsbti.compile.{
  ClasspathOptionsUtil,
  ScalaInstance => XScalaInstance
}
import sbt.internal.inc.{AnalyzingCompiler, RawCompiler}
import sbt.util.Logger

object BootstrapperUtils {
  val CompilerInterfaceId = "compiler-interface"
  val JavaClassVersion = System.getProperty("java.class.version")

  def compilerInterface(output: File, compilerBridgeSrc: File, compilerInterface: File, scalaInstance: XScalaInstance, log: Logger): Unit = {
    def compile(targetJar: File): Unit =
      AnalyzingCompiler.compileSources(
        Seq(compilerBridgeSrc),
        targetJar,
        Seq(compilerInterface),
        CompilerInterfaceId,
        new RawCompiler(scalaInstance, ClasspathOptionsUtil.auto, log),
        log
      )

    val dir = output.getParentFile
    dir.mkdirs()
    val tempJar = File.createTempFile("interface-", ".jar.tmp", dir)
    try {
      compile(tempJar)
      ZipScrubber.scrubZip(tempJar.toPath)
      tempJar.renameTo(output)
    } finally {
      tempJar.delete()
    }
  }
}
