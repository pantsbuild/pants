import org.junit.BeforeClass;
import org.junit.Test;
import static org.junit.Assert.*;

public class AllTests {
  @BeforeClass
  public static void setUp() {
    throw new RuntimeException();
  }

  @Test
  public void test() {
    // Do nothing.
  }
}
