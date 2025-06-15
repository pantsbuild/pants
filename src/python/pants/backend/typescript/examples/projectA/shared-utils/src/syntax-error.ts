// Test file with syntax errors to verify error reporting - FIXED VERSION

export interface User {
    id: number;
    name: string;
    email: string;
} // Fixed: added semicolon

export function processUser(user: User): string {
    // Fixed: added proper closing braces
    if (user.id > 0) {
        return `Processing user: ${user.name}`;
    }
    
    // Fixed: added proper closing brace for object
    const userInfo = {
        id: user.id,
        displayName: user.name,
        contact: user.email
    };
    
    return userInfo.displayName;
}

export function calculateTotal(items: number[]): number {
    let total = 0;
    for (const item of items) {
        total += item;
    }
    return total;
} // This function should now compile without syntax errors