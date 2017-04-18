// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.scalac.plugin

import tools.nsc.{Global, Phase}
import tools.nsc.plugins.{Plugin, PluginComponent}

/**
 * Another very simple plugin that just logs its existence in the pipeline.
 * Useful for testing that a plugin can be compiled using another plugin.
 *
 * @param global The compiler instance this plugin is installed in.
 */
class OtherSimpleScalacPlugin(val global: Global) extends Plugin {
  // Required Plugin boilerplate.
  val name = "other_simple_scalac_plugin"
  val description = "Logs a greeting."
  val components = List[PluginComponent](Component)

  var pluginOpts: List[String] = Nil

  override def processOptions(options: List[String], error: String => Unit) = {
    pluginOpts = options
  }

  private[this] object Component extends PluginComponent {
    // Required PluginComponent boilerplate.
    val global: OtherSimpleScalacPlugin.this.global.type = OtherSimpleScalacPlugin.this.global
    val runsAfter = List[String]("parser")
    val phaseName = OtherSimpleScalacPlugin.this.name

    def newPhase(prev: Phase): Phase = new SayHello(prev)

    private[this] class SayHello(prev: Phase) extends StdPhase(prev) {
      override def apply(unit: global.CompilationUnit) {
        var pluginOptsStr = pluginOpts.mkString(" ")
        global.inform(s"Hello ${unit.source}! OtherSimpleScalacPlugin ran with " +
          s"${pluginOpts.length} args: ${pluginOptsStr}")
      }
    }
  }
}
