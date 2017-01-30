/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.net.URLClassLoader
import sbt.internal.inc.{
  AnalyzingCompiler,
  CompileOutput,
  CompilerCache,
  CompilerBridgeProvider,
  IncrementalCompilerImpl,
  RawCompiler,
  ScalaInstance,
  javac
}
import sbt.io.Path
import sbt.io.syntax._
import sbt.util.Logger
import xsbti.compile.{
  GlobalsCache,
  JavaCompiler,
  ScalaInstance => XScalaInstance
}

import org.pantsbuild.zinc.cache.Cache
import org.pantsbuild.zinc.cache.Cache.Implicits

object Compiler {
  val CompilerInterfaceId = "compiler-interface"
  val JavaClassVersion = System.getProperty("java.class.version")

  /**
   * Static cache for zinc compilers.
   */
  private val compilerCache = Cache[Setup, Compiler](Setup.Defaults.compilerCacheLimit)

  /**
   * Static cache for resident scala compilers.
   */
  private val residentCache: GlobalsCache = createResidentCache(Setup.Defaults.residentCacheLimit)

  /**
   * Get or create a zinc compiler based on compiler setup.
   */
  def apply(setup: Setup, log: Logger): Compiler =
    compilerCache.getOrElseUpdate(setup) {
      create(setup, log)
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
    val scalac       = newScalaCompiler(instance, interfaceJar)
    val javac        = newJavaCompiler(instance, setup.javaHome, setup.forkJava)
    new Compiler(scalac, javac, setup)
  }

  /**
   * Create a new scala compiler.
   */
  def newScalaCompiler(instance: XScalaInstance, interfaceJar: File): AnalyzingCompiler =
    new AnalyzingCompiler(
      instance,
      CompilerBridgeProvider.constant(interfaceJar),
      sbt.internal.inc.ClasspathOptionsUtil.auto,
      _ => (), None
    )

  /**
   * Create a new java compiler.
   */
  def newJavaCompiler(instance: XScalaInstance, javaHome: Option[File], fork: Boolean): JavaCompiler =
    if (fork || javaHome.isDefined) {
      javac.JavaCompiler.fork(javaHome)
    } else {
      javac.JavaCompiler.local.getOrElse {
        throw new RuntimeException(
          "Unable to locate javac directly. Please ensure that a JDK is on zinc's classpath."
        )
      }
    }

  /**
   * Create new globals cache.
   */
  def createResidentCache(maxCompilers: Int): GlobalsCache = {
    if (maxCompilers <= 0) CompilerCache.fresh else CompilerCache(maxCompilers)
  }

  /**
   * Create the scala instance for the compiler. Includes creating the classloader.
   */
  def scalaInstance(setup: Setup): XScalaInstance = {
    import setup.{scalaCompiler, scalaExtra, scalaLibrary}
    val allJars = scalaLibrary +: scalaCompiler +: scalaExtra
    val loader = scalaLoader(allJars)
    val version = scalaVersion(loader)
    new ScalaInstance(version.getOrElse("unknown"), loader, scalaLibrary, scalaCompiler, allJars.toArray, version)
  }

  /**
   * Create a new classloader with the root loader as parent (to avoid zinc itself being included).
   */
  def scalaLoader(jars: Seq[File]) =
    new URLClassLoader(
      Path.toURLs(jars),
      sbt.internal.inc.classpath.ClasspathUtilities.rootLoader
    )

  /**
   * Get the actual scala version from the compiler.properties in a classloader.
   * The classloader should only contain one version of scala.
   */
  def scalaVersion(scalaLoader: ClassLoader): Option[String] = {
    Util.propertyFromResource("compiler.properties", "version.number", scalaLoader)
  }

  /**
   * Get the compiler interface for this compiler setup. Compile it if not already cached.
   * NB: This usually occurs within the compilerCache entry lock, but in the presence of
   * multiple zinc processes (ie, without nailgun) we need to be more careful not to clobber
   * another compilation attempt.
   */
  def compilerInterface(setup: Setup, scalaInstance: XScalaInstance, log: Logger): File = {
    def compile(targetJar: File): Unit =
      AnalyzingCompiler.compileSources(
        Seq(setup.compilerBridgeSrc),
        targetJar,
        Seq(setup.compilerInterface),
        CompilerInterfaceId,
        new RawCompiler(scalaInstance, sbt.internal.inc.ClasspathOptionsUtil.auto, log),
        log
      )
    val dir = setup.cacheDir / interfaceId(scalaInstance.actualVersion)
    val interfaceJar = dir / (CompilerInterfaceId + ".jar")
    if (!interfaceJar.isFile) {
      dir.mkdirs()
      val tempJar = File.createTempFile("interface-", ".jar.tmp", dir)
      try {
        compile(tempJar)
        tempJar.renameTo(interfaceJar)
      } finally {
        tempJar.delete()
      }
    }
    interfaceJar
  }

  def interfaceId(scalaVersion: String) = CompilerInterfaceId + "-" + scalaVersion + "-" + JavaClassVersion
}

/**
 * A zinc compiler for incremental recompilation.
 */
class Compiler(scalac: AnalyzingCompiler, javac: JavaCompiler, setup: Setup) {

  private[this] val compiler = new IncrementalCompilerImpl()

  /**
   * Run a compile. The resulting analysis is pesisted to `inputs.cacheFile`.
   */
  def compile(inputs: Inputs, cwd: Option[File], reporter: xsbti.Reporter, progress: xsbti.compile.CompileProgress)(log: Logger): Unit = {
    import inputs._

    // load the existing analysis
    val targetAnalysisStore = AnalysisMap.cachedStore(cacheFile)
    val (previousAnalysis, previousSetup) =
      targetAnalysisStore.get().map {
        case (a, s) => (Some(a), Some(s))
      } getOrElse {
        (None, None)
       }

    val result =
       compiler.incrementalCompile(
         scalac,
         javac,
         sources,
         classpath = autoClasspath(classesDirectory, scalac.scalaInstance.allJars, javaOnly, classpath),
         output = CompileOutput(classesDirectory),
         cache = Compiler.residentCache,
         Some(progress),
         options = scalacOptions,
         javacOptions,
         previousAnalysis,
         previousSetup,
         perClasspathEntryLookup = analysisMap.getPCELookup,
         reporter,
         compileOrder,
         skip = false,
         incOptions.options(log),
         extra = Nil
       )(log)

    // if the compile resulted in modified analysis, persist it
    if (result.hasModified) {
      targetAnalysisStore.set(result.analysis, result.setup)
     }
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
