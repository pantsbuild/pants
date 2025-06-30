import type { User, ApiResponse } from "@test/common-types";
import { add, multiply } from "./math";

export { add, multiply };
export { Button, UserCard, type ButtonProps } from "./Button";

export function createUser(name: string, email: string): User {
  return {
    id: Math.floor(Math.random() * 1000),
    name,
    email,
  };
}

export function createApiResponse<T>(
  data: T,
  success: boolean = true,
): ApiResponse<T> {
  return {
    data,
    success,
  };
}
