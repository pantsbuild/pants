/*
 * Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.backend.scala.scalapb

import java.util.jar.JarInputStream
import java.io.{File, FileInputStream}
import java.net.URLClassLoader
import protocbridge.{ProtocBridge, ProtocCodeGenerator, ProtocRunner, SandboxedJvmGenerator}
import scalapb.ScalaPbCodeGenerator


// Derived from ScalaPBC under Apache License v2.0.
// Forked from:
// https://github.com/scalapb/ScalaPB/blob/d7e88f3783172f652d63229c7359a1de2e87eac6/scalapbc/src/main/scala/scalapb/ScalaPBC.scala

case class Config(
  protocPath: Option[String] = None,
  throwException: Boolean = false,
  args: Seq[String] = Seq.empty,
  namedGenerators: Seq[(String, ProtocCodeGenerator)] = Seq("scala" -> ScalaPbCodeGenerator),
  executableArtifacts: Seq[String] = Seq.empty,
  jvmPlugins: Seq[(String, String)] = Seq.empty
)

class ScalaPbcException(msg: String) extends RuntimeException(msg)

object ScalaPBShim {
  private val ProtocPathArgument = "--protoc="
  private val JvmPluginArgument = "--jvm-plugin="

  def processArgs(args: Array[String]): Config = {
    case class State(cfg: Config, passThrough: Boolean)

    args
      .foldLeft(State(Config(), false)) { case (state, item) =>
        (state.passThrough, item) match {
          case (false, "--")      => state.copy(passThrough = true)
          case (false, "--throw") => state.copy(cfg = state.cfg.copy(throwException = true))
          case (false, p) if p.startsWith(ProtocPathArgument) =>
            state.copy(
              cfg = state.cfg
                .copy(protocPath = Some(p.substring(ProtocPathArgument.length)))
            )
          case (false, p) if p.startsWith(JvmPluginArgument) =>
            val Array(genName, classpath) = p.substring(JvmPluginArgument.length).split('=')
            state.copy(
              cfg = state.cfg.copy(jvmPlugins = state.cfg.jvmPlugins :+ (genName -> classpath))
            )
          case (_, other) =>
            state.copy(passThrough = true, cfg = state.cfg.copy(args = state.cfg.args :+ other))
        }
      }
      .cfg
  }

  def findMainClass(f: File): Either[String, String] = {
    val jin = new JarInputStream(new FileInputStream(f))
    try {
      val manifest = jin.getManifest()
      Option(manifest.getMainAttributes().getValue("Main-Class"))
        .toRight("Could not find main class for plugin")
        .map(_ + "$")
    } finally {
      jin.close()
    }
  }

  private[scalapb] def runProtoc(config: Config): Int = {
    if (
      config.namedGenerators
        .map(_._1)
        .toSet
        .intersect(config.jvmPlugins.map(_._1).toSet)
        .nonEmpty
    ) {
      throw new RuntimeException(
        s"Plugin name conflict with $JvmPluginArgument"
      )
    }

    def fatalError(err: String): Nothing = {
      if (config.throwException) {
        throw new ScalaPbcException(s"Error: $err")
      } else {
        System.err.println(err)
        sys.exit(1)
      }
    }

    val jvmGenerators = config.jvmPlugins.map({ case (name, classpath) =>
      val files = classpath.split(':').map(f => new File(f))
      val urls = files.map(_.toURI().toURL()).toArray
      val loader = new URLClassLoader(urls, null)
      val mainClass = findMainClass(files.last) match {
        case Right(v)  => v
        case Left(err) => fatalError(err)
      }
      name -> SandboxedJvmGenerator.load(mainClass, loader)
    })

    val protoc = config.protocPath.getOrElse(throw new RuntimeException("--protoc not specified"))

    ProtocBridge.runWithGenerators(
      ProtocRunner(protoc),
      namedGenerators = config.namedGenerators ++ jvmGenerators,
      params = config.args
    )
  }

  def main(args: Array[String]): Unit = {
    val config = processArgs(args)
    val code = runProtoc(config)

    if (!config.throwException) {
      sys.exit(code)
    } else {
      if (code != 0) {
        throw new ScalaPbcException(s"Exit with code $code")
      }
    }
  }
}