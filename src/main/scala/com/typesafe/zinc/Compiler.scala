/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.zinc

import java.io.File
import java.net.URLClassLoader
import sbt.{ ClasspathOptions, CompileOptions, CompileSetup, LoggerReporter, ScalaInstance }
import sbt.compiler.{ AggressiveCompile, AnalyzingCompiler, CompilerCache, CompileOutput, IC }
import sbt.inc.{ Analysis, AnalysisStore, FileBasedStore, IncOptions }
import sbt.Path._
import xsbti.compile.{ JavaCompiler, GlobalsCache }
import xsbti.Logger

object Compiler {
  val CompilerInterfaceId = "compiler-interface"
  val JavaClassVersion = System.getProperty("java.class.version")

  /**
   * Static cache for zinc compilers.
   */
  val compilerCache = Cache[Setup, Compiler](Setup.Defaults.compilerCacheLimit)

  /**
   * Static cache for resident scala compilers.
   */
  val residentCache: GlobalsCache = createResidentCache(Setup.Defaults.residentCacheLimit)

  /**
   * Static cache for compile analyses.
   */
  val analysisCache = Cache[File, AnalysisStore](Setup.Defaults.analysisCacheLimit)

  /**
   * Get or create a zinc compiler based on compiler setup.
   */
  def apply(setup: Setup, log: Logger): Compiler = {
    compilerCache.get(setup)(create(setup, log))
  }

  /**
   * Java API for creating compiler.
   */
  def getOrCreate(setup: Setup, log: Logger): Compiler = apply(setup, log)

  /**
   * Create a new zinc compiler based on compiler setup.
   */
  def create(setup: Setup, log: Logger): Compiler = {
    val instance     = scalaInstance(setup)
    val interfaceJar = compilerInterface(setup, instance, log)
    val scalac       = IC.newScalaCompiler(instance, interfaceJar, ClasspathOptions.boot, log)
    val javac        = AggressiveCompile.directOrFork(instance, ClasspathOptions.javac(false), setup.javaHome)
    new Compiler(scalac, javac)
  }

  /**
   * Create new globals cache.
   */
  def createResidentCache(maxCompilers: Int): GlobalsCache = {
    if (maxCompilers <= 0) CompilerCache.fresh else CompilerCache(maxCompilers)
  }

  /**
   * Get or create an analysis store.
   */
  def analysisStore(cacheFile: File): AnalysisStore = {
    analysisCache.get(cacheFile)(createAnalysisStore(cacheFile))
  }

  /**
   * Create a new analysis store based on a cache file.
   */
  def createAnalysisStore(cacheFile: File): AnalysisStore = {
    import sbinary.DefaultProtocol.{immutableMapFormat, immutableSetFormat, StringFormat, tuple2Format}
    import sbt.inc.AnalysisFormats._
    AnalysisStore.sync(AnalysisStore.cached(FileBasedStore(cacheFile)))
  }

  /**
   * Get an analysis, lookup by cache file.
   */
  def analysis(cacheFile: File): Analysis = {
    analysisStore(cacheFile).get map (_._1) getOrElse Analysis.Empty
  }

  /**
   * Check whether an analysis is empty.
   */
  def analysisIsEmpty(cacheFile: File): Boolean = {
    analysis(cacheFile) eq Analysis.Empty
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
   * Create a new classloader with the root loader as parent (to avoid zinc itself being included).
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
 * A zinc compiler for incremental recompilation.
 */
class Compiler(scalac: AnalyzingCompiler, javac: JavaCompiler) {

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   */
  def compile(inputs: Inputs)(log: Logger): Analysis = compile(inputs, None)(log)

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   */
  def compile(inputs: Inputs, cwd: Option[File])(log: Logger): Analysis = {
    import inputs._
    if (forceClean && Compiler.analysisIsEmpty(cacheFile)) Util.cleanAllClasses(classesDirectory)
    val getAnalysis: File => Option[Analysis] = analysisMap.get _
    val aggressive    = new AggressiveCompile(cacheFile)
    val cp            = autoClasspath(classesDirectory, scalac.scalaInstance.allJars, javaOnly, classpath)
    val compileOutput = CompileOutput(classesDirectory)
    val globalsCache  = Compiler.residentCache
    val progress      = None
    val maxErrors     = 100
    val reporter      = new LoggerReporter(maxErrors, log, identity)
    val skip          = false
    val compileSetup  = new CompileSetup(compileOutput, new CompileOptions(scalacOptions, javacOptions), scalac.scalaInstance.actualVersion, compileOrder)
    val analysisStore = Compiler.analysisStore(cacheFile)
    val incOptions    = IncOptions.Default
    val analysis      = aggressive.compile1(sources, cp, compileSetup, progress, analysisStore, getAnalysis, definesClass, scalac, javac, reporter, skip, globalsCache, incOptions)(log)
    if (mirrorAnalysis) {
      SbtAnalysis.printRelations(analysis, Some(new File(cacheFile.getPath() + ".relations")), cwd)
    }
    SbtAnalysis.printOutputs(analysis, outputRelations, outputProducts, cwd, classesDirectory)
    analysis
  }

  /**
   * Automatically add the output directory and scala library to the classpath.
   */
  def autoClasspath(classesDirectory: File, allScalaJars: Seq[File], javaOnly: Boolean, classpath: Seq[File]): Seq[File] = {
    if (javaOnly) classesDirectory +: classpath
    else Setup.splitScala(allScalaJars) match {
      case Some(scalaJars) => classesDirectory +: scalaJars.library +: classpath
      case None            => classesDirectory +: classpath
    }
  }

  override def toString = "Compiler(Scala %s)" format scalac.scalaInstance.actualVersion
}
