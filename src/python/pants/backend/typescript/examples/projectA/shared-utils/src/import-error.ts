// Test file with import errors to verify error reporting

// Import error: non-existent module
import { NonExistentFunction } from "./does-not-exist";

// Import error: non-existent named export from existing module
import { UndefinedExport } from "./math";

// Import error: non-existent npm package
import { SomeFunction } from "non-existent-package";

// Import error: trying to import from a file that doesn't export anything
import { SomethingElse } from "./syntax-error"; // This file has syntax errors and no exports

export function useImports(): void {
    // These will fail because imports don't exist
    const result1 = NonExistentFunction();
    const result2 = UndefinedExport();
    const result3 = SomeFunction();
    const result4 = SomethingElse();
    
    console.log(result1, result2, result3, result4);
}