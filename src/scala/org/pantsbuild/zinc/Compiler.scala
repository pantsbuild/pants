/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.net.URLClassLoader
import sbt.compiler.javac
import sbt.{
  ClasspathOptions,
  CompileOptions,
  Logger,
  LoggerReporter,
  ScalaInstance
}
import sbt.compiler.{
  AnalyzingCompiler,
  CompileOutput,
  CompilerCache,
  IC,
  MixedAnalyzingCompiler
}
import sbt.inc.ZincPrivateAnalysis
import sbt.Path._
import xsbti.compile.{ JavaCompiler, GlobalsCache }

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
  def newScalaCompiler(instance: ScalaInstance, interfaceJar: File): AnalyzingCompiler = {
    IC.newScalaCompiler(instance, interfaceJar, ClasspathOptions.boot)
  }

  /**
   * Create a new java compiler.
   */
  def newJavaCompiler(instance: ScalaInstance, javaHome: Option[File], fork: Boolean): JavaCompiler = {
    val compiler =
      if (fork || javaHome.isDefined) {
        javac.JavaCompiler.fork(javaHome)
      } else {
        Option(javax.tools.ToolProvider.getSystemJavaCompiler).map { jc =>
          // NB: using backported 0.13.10+ JavaCompiler input
          new javac.ZincLocalJavaCompiler(jc)
        }.getOrElse {
          throw new RuntimeException(
            "Unable to locate javac directly. Please ensure that a JDK is on zinc's classpath."
          )
        }
      }

    val options = ClasspathOptions.javac(compiler = false)
    new javac.JavaCompilerAdapter(compiler, instance, options)
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
  def scalaInstance(setup: Setup): ScalaInstance = {
    import setup.{scalaCompiler, scalaExtra, scalaLibrary}
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
   * NB: This usually occurs within the compilerCache entry lock, but in the presence of
   * multiple zinc processes (ie, without nailgun) we need to be more careful not to clobber
   * another compilation attempt.
   */
  def compilerInterface(setup: Setup, scalaInstance: ScalaInstance, log: Logger): File = {
    val dir = setup.cacheDir / interfaceId(scalaInstance.actualVersion)
    val interfaceJar = dir / (CompilerInterfaceId + ".jar")
    if (!interfaceJar.isFile) {
      dir.mkdirs()
      val tempJar = File.createTempFile("interface-", ".jar.tmp", dir)
      try {
        IC.compileInterfaceJar(CompilerInterfaceId, setup.compilerInterfaceSrc, tempJar, setup.sbtInterface, scalaInstance, log)
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

  /**
   * Run a compile. The resulting analysis is pesisted to `inputs.cacheFile`.
   */
  def compile(inputs: Inputs, cwd: Option[File], reporter: xsbti.Reporter, progress: xsbti.compile.CompileProgress)(log: Logger): Unit = {
    import inputs._

    // load the existing analysis
    val targetAnalysisStore = AnalysisMap.cachedStore(cacheFile)
    val (previousAnalysis, previousSetup) =
      targetAnalysisStore.get().map {
        case (a, s) => (a, Some(s))
      } getOrElse {
        (ZincPrivateAnalysis.empty(incOptions.nameHashing), None)
      }

    val result =
      IC.incrementalCompile(
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
        analysisMap = analysisMap.getAnalysis _,
        definesClass = analysisMap.definesClass _,
        reporter,
        compileOrder,
        skip = false,
        incOptions.options
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
