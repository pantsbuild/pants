package org.pantsbuild.contrib.scrooge.scrooge_gen

class UseGoodThrift extends all.your.base.thriftscala.MyService.MethodPerEndpoint {
  def getNumber(x: Int): com.twitter.util.Future[Int] = {
    com.twitter.util.Future[Int](1)
  }
}
