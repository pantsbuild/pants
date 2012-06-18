/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import java.io.File
import java.net.URLClassLoader
import sbt.{ ClasspathOptions, ScalaInstance }
import sbt.compiler.{ AggressiveCompile, AnalyzingCompiler, CompilerCache, IC }
import sbt.inc.Analysis
import sbt.Logger
import sbt.Path._
import xsbti.compile.{ JavaCompiler, GlobalsCache }

object Compiler {
  val CompilerInterfaceId = "compiler-interface"
  val JavaClassVersion = System.getProperty("java.class.version")

  /**
   * Static cache for compile results.
   */
  val analysisCache = Cache[File, Analysis](Setup.Defaults.analysisCacheLimit)

  /**
   * Create a new inkling compiler based on compiler setup.
   */
  def apply(setup: Setup, log: Logger): Compiler = {
    val compilerCache = if (setup.maxCompilers <= 0) CompilerCache.fresh else CompilerCache(setup.maxCompilers)
    val instance = scalaInstance(setup)
    val interfaceJar = compilerInterface(setup, instance, log)
    val scalac = IC.newScalaCompiler(instance, interfaceJar, ClasspathOptions.boot, log)
    val javac = AggressiveCompile.directOrFork(instance, ClasspathOptions.javac(false), setup.javaHome)
    new Compiler(scalac, javac, compilerCache, log)
  }

  /**
   * Create the scala instance for the compiler. Includes creating the classloader.
   */
  def scalaInstance(setup: Setup): ScalaInstance = {
    import setup.{ scalaCompiler, scalaLibrary, scalaExtra}
    val loader = scalaLoader(scalaLibrary +: scalaCompiler +: scalaExtra)
    val version = scalaVersion(loader)
    new ScalaInstance(version.getOrElse("unknown"), loader, scalaLibrary, scalaCompiler, scalaExtra, version)
  }

  /**
   * Create a new classloader with the root loader as parent (to avoid inkling itself being included).
   */
  def scalaLoader(jars: Seq[File]) = new URLClassLoader(toURLs(jars), sbt.classpath.ClasspathUtilities.rootLoader)

  /**
   * Get the actual scala version from the compiler.properties in a classloader.
   * The classloader should only contain one version of scala.
   */
  def scalaVersion(scalaLoader: ClassLoader): Option[String] = {
    Util.propertyFromResource("compiler.properties", "version.number", scalaLoader)
  }

  /**
   * Get the compiler interface for this compiler setup. Compile it if not already cached.
   */
  def compilerInterface(setup: Setup, scalaInstance: ScalaInstance, log: Logger): File = {
    val dir = setup.cacheDir / interfaceId(scalaInstance.actualVersion)
    val interfaceJar = dir / (CompilerInterfaceId + ".jar")
    if (!interfaceJar.exists) {
      dir.mkdirs()
      IC.compileInterfaceJar(CompilerInterfaceId, setup.compilerInterfaceSrc, interfaceJar, setup.sbtInterface, scalaInstance, log)
    }
    interfaceJar
  }

  def interfaceId(scalaVersion: String) = CompilerInterfaceId + "-" + scalaVersion + "-" + JavaClassVersion
}

/**
 * An inkling compiler for incremental recompilation.
 */
class Compiler(scalac: AnalyzingCompiler, javac: JavaCompiler, cache: GlobalsCache, log: Logger) {

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   */
  def compile(inputs: Inputs): Analysis = {
    import inputs._
    val doCompile = new AggressiveCompile(cacheFile)
    val cp = autoClasspath(classesDirectory, scalac.scalaInstance.libraryJar, javaOnly, classpath)
    val getAnalysis: File => Option[Analysis] = analysisMap.get _
    val analysis = doCompile(scalac, javac, sources, cp, classesDirectory, cache, scalacOptions, javacOptions, getAnalysis, definesClass, 100, compileOrder, false)(log)
    Compiler.analysisCache.put(cacheFile, analysis)
    analysis
  }

  /**
   * Automatically add the output directory and scala library to the classpath.
   */
  def autoClasspath(classesDirectory: File, scalaLibrary: File, javaOnly: Boolean, classpath: Seq[File]): Seq[File] = {
    if (javaOnly) classesDirectory +: classpath
    else classesDirectory +: scalaLibrary +: classpath
  }

  override def toString = "Compiler(Scala %s)" format scalac.scalaInstance.actualVersion
}
