package org.pantsbuild.tools.junit.impl.security;

import java.util.concurrent.CountDownLatch;

import static org.hamcrest.CoreMatchers.*;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.*;
import static org.junit.Assert.fail;
import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.*;

public class JunitSecurityContextLookupAndErrorCollectionTest {

  private final CountDownLatch latch = new CountDownLatch(1);
  static class AssertableThread extends Thread {
    Throwable thrown;

    AssertableThread(ThreadGroup threadGroup, Runnable runnable) {
      super(threadGroup, runnable);
      setUncaughtExceptionHandler(new UncaughtExceptionHandler() {
        @Override
        public void uncaughtException(Thread t, Throwable e) {
          thrown = e;
        }
      });
    }

    void joinOrRaise() throws Throwable {
      join();
      if (thrown!= null) {
        throw thrown;
      }
    }
  }

  @Test
  public void disallowsDanglingThreadsForSuiteIfSuiteDisallowed() {
    JunitSecurityManagerConfig config = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.disallowLeakingTestSuiteThreads,
        NetworkHandling.allowAll);
    JunitSecurityContextLookupAndErrorCollection lookupAndErrorCollection;
    lookupAndErrorCollection = new JunitSecurityContextLookupAndErrorCollection(config);
    assertThat(
        lookupAndErrorCollection.disallowsThreadsFor(TestSecurityContext.newSuiteContext("foo")),
        is(true));
  }

  @Test
  public void allowAllIncludesSuites() {
    JunitSecurityManagerConfig config = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.allowAll,
        NetworkHandling.allowAll);
    JunitSecurityContextLookupAndErrorCollection lookupAndErrorCollection;
    lookupAndErrorCollection = new JunitSecurityContextLookupAndErrorCollection(config);
    assertThat(
        lookupAndErrorCollection.disallowsThreadsFor(TestSecurityContext.newSuiteContext("foo")),
        is(false));
  }

  @Test
  public void createSuiteIfMissing() {
    JunitSecurityManagerConfig config = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.allowAll,
        NetworkHandling.allowAll);
    JunitSecurityContextLookupAndErrorCollection lookupAndErrorCollection;
    lookupAndErrorCollection = new JunitSecurityContextLookupAndErrorCollection(config);

    ContextKey testKey = new ContextKey("org.foo.Foo", "test");

    lookupAndErrorCollection.startTest(testKey);
    ContextKey suiteKey = new ContextKey("org.foo.Foo");
    assertThat(lookupAndErrorCollection.getContext(suiteKey), notNullValue());
    assertThat(
        lookupAndErrorCollection.getContext(suiteKey).getThreadGroup(),
        is(lookupAndErrorCollection.getContext(testKey).getThreadGroup().getParent()));
  }

  @Test
  public void suiteThenTest() throws InterruptedException {
    JunitSecurityManagerConfig config = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.allowAll,
        NetworkHandling.allowAll);
    JunitSecurityContextLookupAndErrorCollection lookupAndErrorCollection;
    lookupAndErrorCollection = new JunitSecurityContextLookupAndErrorCollection(config);

    ContextKey suiteKey = new ContextKey("org.foo.Foo");
    lookupAndErrorCollection.startSuite(suiteKey);
    TestSecurityContext suiteContext = lookupAndErrorCollection.getContext(suiteKey);

    ContextKey testKey = new ContextKey("org.foo.Foo", "test");
    lookupAndErrorCollection.startTest(testKey);

    TestSecurityContext testContext = lookupAndErrorCollection.getContext(testKey);

    assertFalse(lookupAndErrorCollection.anyHasRunningThreads());
    assertFalse(suiteContext.hasActiveThreads());

    runThreadAwaitingLatch(testContext);

    assertTrue(lookupAndErrorCollection.anyHasRunningThreads());
    assertTrue(suiteContext.hasActiveThreads());
    assertTrue(testContext.hasActiveThreads());

    latch.countDown();
    Thread.sleep(1);

    assertFalse(lookupAndErrorCollection.anyHasRunningThreads());
    assertFalse(suiteContext.hasActiveThreads());
    assertFalse(testContext.hasActiveThreads());

    lookupAndErrorCollection.endTest();
  }

  @Test
  public void looksUpContextCorrectlyFromThreadGroup() throws Throwable {
    JunitSecurityManagerConfig config = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.allowAll,
        NetworkHandling.allowAll);
    final JunitSecurityContextLookupAndErrorCollection lookupAndErrorCollection;
    lookupAndErrorCollection = new JunitSecurityContextLookupAndErrorCollection(config);

    ContextKey suiteKey = new ContextKey("org.foo.Foo");
    lookupAndErrorCollection.startSuite(suiteKey);
    final TestSecurityContext suiteContext = lookupAndErrorCollection.getContext(suiteKey);

    ContextKey testKey = new ContextKey("org.foo.Foo", "test");
    lookupAndErrorCollection.startTest(testKey);

    final TestSecurityContext testContext = lookupAndErrorCollection.getContext(testKey);

    assertFalse(lookupAndErrorCollection.anyHasRunningThreads());
    assertFalse(suiteContext.hasActiveThreads());

    AssertableThread thread = new AssertableThread(testContext.getThreadGroup(), new Runnable() {
      @Override
      public void run() {
        assertThat(lookupAndErrorCollection.lookupContextByThreadGroup(), is(testContext));
      }
    });
    thread.start();
    thread.joinOrRaise();


    thread = new AssertableThread(suiteContext.getThreadGroup(), new Runnable() {
      @Override
      public void run() {
        assertThat(
            Thread.currentThread().getThreadGroup().getName(),
            containsString("⁓m⁓null⁓Threads"));
        assertThat(lookupAndErrorCollection.lookupContextByThreadGroup(), is(suiteContext));
      }
    });
    thread.start();
    thread.joinOrRaise();
  }

  @Test
  public void innerAndOuterThreads() throws InterruptedException {
    JunitSecurityManagerConfig config = new JunitSecurityManagerConfig(
        SystemExitHandling.disallow,
        ThreadHandling.allowAll, NetworkHandling.allowAll);
    JunitSecurityContextLookupAndErrorCollection lookupAndErrorCollection;
    lookupAndErrorCollection = new JunitSecurityContextLookupAndErrorCollection(config);

    ContextKey suiteKey = new ContextKey("org.foo.Foo");
    lookupAndErrorCollection.startSuite(suiteKey);
    TestSecurityContext suiteContext = lookupAndErrorCollection.getContext(suiteKey);

    ContextKey testKey = new ContextKey("org.foo.Foo", "test");
    lookupAndErrorCollection.startTest(testKey);

    TestSecurityContext testContext = lookupAndErrorCollection.getContext(testKey);

    assertFalse(lookupAndErrorCollection.anyHasRunningThreads());
    assertFalse(suiteContext.hasActiveThreads());

    runThreadAwaitingLatch(suiteContext);

    assertTrue(lookupAndErrorCollection.anyHasRunningThreads());
    assertTrue("suite "+suiteContext, suiteContext.hasActiveThreads());
    assertFalse("test "+testContext, testContext.hasActiveThreads());


    runThreadAwaitingLatch(testContext);

    assertTrue(lookupAndErrorCollection.anyHasRunningThreads());
    assertTrue(suiteContext.hasActiveThreads());
    assertTrue(testContext.hasActiveThreads());

    latch.countDown();
    Thread.sleep(1);

    assertFalse(lookupAndErrorCollection.anyHasRunningThreads());
    assertFalse(suiteContext.hasActiveThreads());
    assertFalse(testContext.hasActiveThreads());

    lookupAndErrorCollection.endTest();
  }

  @Test
  public void contextKefForThreadGroupSetupOutsideJunitSecurityContextIsNull() {
    assertNull(ContextKey.parseFromThreadGroupName("main"));
  }

  private void runThreadAwaitingLatch(TestSecurityContext testContext) {
    Thread thread = new Thread(testContext.getThreadGroup(), new Runnable() {
      @Override
      public void run() {
        try {
          latch.await();
        } catch (InterruptedException e) {
          e.printStackTrace();
        }
      }
    });
    thread.start();
  }
}
