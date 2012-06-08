/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import com.martiansoftware.nailgun.{ Alias, AliasManager, NGContext, NGServer }
import java.io.File

class Nailgun // for classOf

object Nailgun {
  val DefaultPort = 4655

  def main(args: Array[String]): Unit = {
    val port = try args(0).toInt catch { case _: Exception => DefaultPort }
    start(port)
  }

  def start(port: Int): Unit = {
    val server = new NGServer(null, port)
    val am = server.getAliasManager
    am.addAlias(new Alias("inkling", "scala incremental compiler", classOf[Nailgun]))
    am.addAlias(new Alias("status", "status of nailgun server", classOf[Nailgun]))
    am.addAlias(new Alias("shutdown", "shutdown the nailgun server", classOf[Nailgun]))
    val thread = new Thread(server)
    thread.setName("InklingNailgun(" + port + ")")
    thread.start()
    Runtime.getRuntime().addShutdownHook(new ShutdownHook(server))
  }

  def nailMain(context: NGContext): Unit = {
    context.getCommand match {
      case "inkling"  => inkling(context)
      case "status"   => status(context)
      case "shutdown" => shutdown(context)
      case cmd        => context.err.println("Unknown command: " + cmd)
    }
  }

  def inkling(context: NGContext): Unit = {
    Main.run(context.getArgs, Some(new File(context.getWorkingDirectory)))
  }

  def status(context: NGContext): Unit = {
    val entries = Main.compilerCache.entries
    context.out.println("Nailgun server running with %s cached compilers" format entries.size)
    entries foreach {
      case (setup, compiler) =>
        context.out.println("")
        context.out.println("%s [%s]" format (compiler, compiler.hashCode.toHexString))
        Setup.show(setup, context.out.println)
    }
  }

  def shutdown(context: NGContext): Unit = {
    context.getNGServer.shutdown(true)
  }

  class ShutdownHook(server: NGServer) extends Thread {
    override def run(): Unit = {
      server.shutdown(false)
      // give some time to shutdown
      var count = 0
      while (server.isRunning && (count < 50)) {
        try { Thread.sleep(100) } catch { case _: InterruptedException => }
        count += 1
      }
    }
  }
}
