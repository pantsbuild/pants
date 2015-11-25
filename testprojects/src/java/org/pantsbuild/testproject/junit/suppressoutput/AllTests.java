import org.junit.Test;
import static org.junit.Assert.*;

public class AllTests {
  @Test
  public void testFailure() {
    System.out.println("Failure output");
    assertTrue(false);
  }

  @Test
  public void testSuccess() {
    System.out.println("Success output");
    assertTrue(true);
  }
}
