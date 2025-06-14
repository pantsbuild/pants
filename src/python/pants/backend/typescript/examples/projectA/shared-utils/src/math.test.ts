import { add, subtract, multiply, divide, clamp, round } from "./math.js";

describe("Math utilities", () => {
  describe("add", () => {
    it("should add two positive numbers", () => {
      expect(add(2, 3)).toBe(5);
    });

    it("should handle negative numbers", () => {
      expect(add(-2, 3)).toBe(1);
      expect(add(-2, -3)).toBe(-5);
    });
  });

  describe("subtract", () => {
    it("should subtract two numbers", () => {
      expect(subtract(5, 3)).toBe(2);
      expect(subtract(3, 5)).toBe(-2);
    });
  });

  describe("multiply", () => {
    it("should multiply two numbers", () => {
      expect(multiply(2, 3)).toBe(6);
      expect(multiply(-2, 3)).toBe(-6);
    });
  });

  describe("divide", () => {
    it("should divide two numbers", () => {
      expect(divide(6, 2)).toBe(3);
      expect(divide(7, 2)).toBe(3.5);
    });

    it("should throw error for division by zero", () => {
      expect(() => divide(5, 0)).toThrow("Division by zero");
    });
  });

  describe("clamp", () => {
    it("should clamp values within range", () => {
      expect(clamp(5, 0, 10)).toBe(5);
      expect(clamp(-5, 0, 10)).toBe(0);
      expect(clamp(15, 0, 10)).toBe(10);
    });
  });

  describe("round", () => {
    it("should round to specified decimal places", () => {
      expect(round(3.14159, 2)).toBe(3.14);
      expect(round(3.14159, 0)).toBe(3);
    });
  });
});
