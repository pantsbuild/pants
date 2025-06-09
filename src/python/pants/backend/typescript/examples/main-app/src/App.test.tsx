import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { App } from "./App.js";
import type { Config } from "@pants-example/common-types";

const mockConfig: Config = {
  apiUrl: "https://test.example.com",
  timeout: 1000,
  retries: 1,
};

describe("App", () => {
  it("renders the application title", () => {
    render(<App config={mockConfig} />);
    expect(screen.getByText("TypeScript Monorepo Example")).toBeInTheDocument();
  });

  it("displays configuration values", () => {
    render(<App config={mockConfig} />);
    expect(
      screen.getByText("API URL: https://test.example.com"),
    ).toBeInTheDocument();
    expect(screen.getByText("Timeout: 1000ms")).toBeInTheDocument();
  });

  it("increments counter when button is clicked", () => {
    render(<App config={mockConfig} />);

    const incrementButton = screen.getByText("Increment");
    expect(screen.getByText("Count: 0")).toBeInTheDocument();

    fireEvent.click(incrementButton);
    expect(screen.getByText("Count: 1")).toBeInTheDocument();

    fireEvent.click(incrementButton);
    expect(screen.getByText("Count: 2")).toBeInTheDocument();
  });

  it("validates email input", () => {
    render(<App config={mockConfig} />);

    const emailInput = screen.getByPlaceholderText("Enter your email");
    const submitButton = screen.getByText("Submit");

    // Initially disabled
    expect(submitButton).toBeDisabled();

    // Invalid email
    fireEvent.change(emailInput, { target: { value: "invalid-email" } });
    expect(submitButton).toBeDisabled();
    expect(emailInput).toHaveStyle("border: 2px solid red");

    // Valid email
    fireEvent.change(emailInput, { target: { value: "test@example.com" } });
    expect(submitButton).not.toBeDisabled();
    expect(emailInput).toHaveStyle("border: 2px solid green");
  });

  it("displays user data", () => {
    render(<App config={mockConfig} />);

    expect(screen.getByText("Name: Demo User")).toBeInTheDocument();
    expect(screen.getByText("Email: demo@example.com")).toBeInTheDocument();
    expect(screen.getByText("ID: 1")).toBeInTheDocument();
  });
});
