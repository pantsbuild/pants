/**
 * Copyright (C) 2018 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.bootstrapper

import org.pantsbuild.tools.jar.JarBuilder
import com.facebook.buck.util.zip.{ZipConstants, ZipScrubber}
import com.google.common.base.Optional
import java.io.File
import java.net.URLClassLoader
import java.util.ArrayList
import java.util.regex.Pattern
import sbt.io.Path
import xsbti.compile.{
  ClasspathOptionsUtil,
  ScalaInstance => XScalaInstance
}
import sbt.internal.inc.{
  AnalyzingCompiler,
  RawCompiler,
  ScalaInstance
}
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
      makeReproducible(tempJar, output)
    } finally {
      tempJar.delete()
    }
  }

  def makeReproducible(tempJar: File, output: File): Unit = {
    new JarBuilder(tempJar).addJar(tempJar).write(
      false,
      JarBuilder.DuplicateHandler.always(JarBuilder.DuplicateAction.SKIP),
      new ArrayList[Pattern](),
      Optional.of[java.lang.Long](ZipConstants.getFakeTime)
    )
    ZipScrubber.scrubZip(tempJar.toPath)
    tempJar.renameTo(output)
  }
}
