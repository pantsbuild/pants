/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.extractor

import java.io.File

import scala.compat.java8.OptionConverters._

import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.module.scala.DefaultScalaModule
import com.fasterxml.jackson.module.scala.experimental.ScalaObjectMapper

import org.pantsbuild.zinc.analysis.{AnalysisMap, PortableAnalysisMappers}
import org.pantsbuild.zinc.options.Parsed

/**
 * Command-line main class for analysis extraction.
 */
object Main {
  val Command = "zinc-extractor"

  private val om = {
    val mapper = new ObjectMapper with ScalaObjectMapper
    mapper.registerModule(DefaultScalaModule)
    mapper
  }

  def main(args: Array[String]): Unit = {
    val Parsed(settings, residual, errors) = Settings.parse(args)

    // bail out on any command-line option errors
    if (errors.nonEmpty) {
      for (error <- errors) System.err.println(error)
      System.err.println("See %s -help for information about options" format Command)
      sys.exit(1)
    }

    if (settings.help) {
      Settings.printUsage(Command)
      return
    }

    val summaryJson =
      settings.summaryJson.getOrElse {
        throw new RuntimeException(s"An output file is required.")
      }

    // Load relevant analysis.
    val analysisMap = AnalysisMap.create(settings.analysis)
    val analysis =
      analysisMap.cachedStore(settings.analysis.cache)
        .get()
        .asScala
        .getOrElse {
          throw new RuntimeException(s"Failed to load analysis from ${settings.analysis.cache}")
        }
        .getAnalysis

    // Extract products and dependencies.
    val extractor = new Extractor(settings.classpath, analysis, analysisMap)

    om.writeValue(
      summaryJson,
      Summary(
        extractor.products,
        extractor.dependencies
      )
    )
  }
}

case class Summary(
  products: collection.Map[File, collection.Set[File]],
  dependencies: collection.Map[File, collection.Set[File]]
)
