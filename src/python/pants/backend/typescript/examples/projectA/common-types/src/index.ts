// Common type definitions for the monorepo

export * from "./api.js";

export interface User {
  id: string;
  name: string;
  email: string;
  createdAt: Date;
}

export interface Config {
  apiUrl: string;
  timeout: number;
  retries: number;
}

export type Status = "pending" | "success" | "error";

export interface Result<T> {
  status: Status;
  data?: T;
  error?: string;
}
