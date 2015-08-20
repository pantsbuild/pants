/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.net.URLClassLoader
import sbt.compiler.javac
import sbt.{ ClasspathOptions, CompileOptions, CompileSetup, Logger, LoggerReporter, ScalaInstance }
import sbt.compiler.{ AnalyzingCompiler, CompilerCache, CompileOutput, MixedAnalyzingCompiler, IC }
import sbt.inc.{ Analysis, AnalysisStore, FileBasedStore, ZincPrivateAnalysis }
import sbt.Path._
import xsbti.compile.{ JavaCompiler, GlobalsCache }

import org.pantsbuild.zinc.Cache.Implicits

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
   * Static cache for compile analyses.  Values must be Options because in get() we don't yet know if, on
   * a cache miss, the underlying file will yield a valid Analysis.
   */
  val analysisCache = Cache[FileFPrint, Option[(Analysis, CompileSetup)]](Setup.Defaults.analysisCacheLimit)

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
      if (fork || javaHome.isDefined)
        javac.JavaCompiler.fork(javaHome)
      else
        javac.JavaCompiler.local.getOrElse(javac.JavaCompiler.fork(None))

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
   * Create an analysis store backed by analysisCache.
   *
   * TODO: for all but the "output" analysis, the synchronization is overkill; everything upstream is immutable
   */
  def cachedAnalysisStore(cacheFile: File): AnalysisStore = {
    val fileStore = AnalysisStore.cached(FileBasedStore(cacheFile))

    val fprintStore = new AnalysisStore {
      def set(analysis: Analysis, setup: CompileSetup) {
        fileStore.set(analysis, setup)
        FileFPrint.fprint(cacheFile) foreach { analysisCache.put(_, Some((analysis, setup))) }
      }
      def get(): Option[(Analysis, CompileSetup)] = {
        FileFPrint.fprint(cacheFile) flatMap { fprint =>
          analysisCache.getOrElseUpdate(fprint) {
            fileStore.get
          }
        }
      }
    }

    AnalysisStore.sync(AnalysisStore.cached(fprintStore))
  }

  /**
   * Analysis for the given file if it is already cached.
   */
  def analysisOptionFor(cacheFile: File): Option[Analysis] =
    cachedAnalysisStore(cacheFile).get map (_._1)

  /**
   * Check whether an analysis is empty.
   */
  def analysisIsEmpty(cacheFile: File): Boolean =
    analysisOptionFor(cacheFile).isEmpty

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
class Compiler(scalac: AnalyzingCompiler, javac: JavaCompiler, setup: Setup) {

  /**
   * Run a compile. The resulting analysis is pesisted to `inputs.cacheFile`.
   */
  def compile(inputs: Inputs, cwd: Option[File], reporter: xsbti.Reporter, progress: xsbti.compile.CompileProgress)(log: Logger): Unit = {
    import inputs._
    if (forceClean && Compiler.analysisIsEmpty(cacheFile)) {
      Util.cleanAllClasses(classesDirectory)
    }

    // load the existing analysis
    // TODO: differentiate output analysis from input analysis
    val targetAnalysisStore = Compiler.cachedAnalysisStore(cacheFile)
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
        analysisMap = analysisMap.get,
        definesClass,
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
