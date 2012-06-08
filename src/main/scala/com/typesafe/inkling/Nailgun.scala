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
    am.addAlias(new Alias("shutdown", "shutdown the nailgun server", classOf[Nailgun]))
    val thread = new Thread(server)
    thread.setName("InklingNailgun(" + port + ")")
    thread.start()
    Runtime.getRuntime().addShutdownHook(new ShutdownHook(server))
  }

  def nailMain(context: NGContext): Unit = {
    context.getCommand match {
      case "inkling"  => Main.run(context.getArgs, Some(new File(context.getWorkingDirectory)))
      case "shutdown" => context.getNGServer.shutdown(true)
      case cmd        => context.err.println("Unknown command: " + cmd)
    }
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
