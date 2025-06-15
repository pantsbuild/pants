// Test file with cross-package errors to verify error reporting

// Valid imports from other packages in the workspace
import { add, multiply } from "./math";
import { Button } from "../../shared-components/src/Button";
import { ApiResponse } from "../../common-types/src/api";

// Cross-package type error: using wrong types from other packages
export function processApiData(data: ApiResponse<string>): number {
    // Type error: ApiResponse<string> data property is string, not number
    return data.data * 2; // Cannot multiply string by number
}

export function createInvalidButton(): Button {
    // Type error: Button expects specific props, but we're providing wrong types
    return new Button({
        label: 123, // Should be string, not number
        onClick: "not-a-function", // Should be function, not string
        disabled: "false" // Should be boolean, not string
    });
}

export function useMathFunctions(): string {
    const num1 = "5"; // string instead of number
    const num2 = "10"; // string instead of number
    
    // Type error: add expects numbers, but we're passing strings
    const sum = add(num1, num2);
    
    // Type error: multiply expects numbers, but we're passing strings  
    const product = multiply(num1, num2);
    
    // Type error: trying to call string method on number
    return sum.toUpperCase() + product.toLowerCase();
}

// Cross-package interface mismatch
export function processUserData(user: any): ApiResponse<any> {
    return {
        data: user,
        success: "true", // Type error: should be boolean, not string
        message: 404, // Type error: should be string, not number
        timestamp: "not-a-date" // This might be okay depending on ApiResponse definition
    };
}