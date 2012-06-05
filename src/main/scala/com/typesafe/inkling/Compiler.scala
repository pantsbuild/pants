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

  def apply(setup: Setup): Compiler = {
    val compilerCache = if (setup.maxCompilers <= 0) CompilerCache.fresh else CompilerCache(setup.maxCompilers)
    val instance = scalaInstance(setup)
    val interfaceJar = compilerInterface(setup, instance)
    val scalac = IC.newScalaCompiler(instance, interfaceJar, ClasspathOptions.boot, setup.log)
    val javac = AggressiveCompile.directOrFork(instance, ClasspathOptions.javac(false), setup.javaHome)
    new Compiler(scalac, javac, compilerCache, setup.log)
  }

  def scalaInstance(setup: Setup): ScalaInstance = {
    val loader = scalaLoader(Seq(setup.scalaLibrary, setup.scalaCompiler))
    val version = scalaVersion(loader)
    new ScalaInstance(version.getOrElse("unknown"), loader, setup.scalaLibrary, setup.scalaCompiler, Seq.empty, version)
  }

  def scalaLoader(jars: Seq[File]) = new URLClassLoader(toURLs(jars), sbt.classpath.ClasspathUtilities.rootLoader)

  def scalaVersion(scalaLoader: ClassLoader): Option[String] = {
    Util.propertyFromResource("compiler.properties", "version.number", scalaLoader)
  }

  def compilerInterface(setup: Setup, scalaInstance: ScalaInstance): File = {
    val dir = setup.cacheDir / interfaceId(scalaInstance.actualVersion)
    val interfaceJar = dir / (CompilerInterfaceId + ".jar")
    if (!interfaceJar.exists()) {
      dir.mkdirs()
      IC.compileInterfaceJar(CompilerInterfaceId, setup.compilerInterfaceSrc, interfaceJar, setup.sbtInterface, scalaInstance, setup.log)
    }
    interfaceJar
  }

  def interfaceId(scalaVersion: String) = CompilerInterfaceId + "-" + scalaVersion + "-" + JavaClassVersion
}

class Compiler(scalac: AnalyzingCompiler, javac: JavaCompiler, cache: GlobalsCache, log: Logger) {
  def compile(inputs: Inputs): Analysis = {
    import inputs._
    val doCompile = new AggressiveCompile(cacheFile)
    val cp = autoClasspath(classesDirectory, scalac.scalaInstance.libraryJar, javaOnly, classpath)
    val getAnalysis: File => Option[Analysis] = analysisMap.get _
    val analysis = doCompile(scalac, javac, sources, cp, classesDirectory, cache, scalacOptions, javacOptions, getAnalysis, definesClass, 100, compileOrder, false)(log)
    AnalysisCache.put(cacheFile, analysis)
  }

  def autoClasspath(classesDirectory: File, scalaLibrary: File, javaOnly: Boolean, classpath: Seq[File]): Seq[File] = {
    if (javaOnly) classesDirectory +: classpath
    else classesDirectory +: scalaLibrary +: classpath
  }

  override def toString = "Compiler(Scala %s)" format scalac.scalaInstance.actualVersion
}
