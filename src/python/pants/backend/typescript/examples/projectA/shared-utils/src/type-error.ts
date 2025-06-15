// Test file with type mismatch errors to verify error reporting

export interface Product {
    id: number;
    name: string;
    price: number;
    inStock: boolean;
}

export function createProduct(name: string, price: number): Product {
    return {
        id: "invalid-id", // Type error: should be number, not string
        name: name,
        price: price.toString(), // Type error: should be number, not string
        inStock: "yes" // Type error: should be boolean, not string
    };
}

export function processProducts(products: Product[]): string[] {
    // Type error: map callback should return string, but we return number
    return products.map((product) => {
        return product.id; // Should return string, but returning number
    });
}

export function calculateDiscount(price: number, discount: string): number {
    // Type error: cannot perform arithmetic on string
    return price - discount; // Should convert string to number first
}

export function validateProduct(product: Product): boolean {
    // Type error: comparing number to string
    if (product.id === "123") {
        return true;
    }
    
    // Type error: calling string method on number
    if (product.price.toLowerCase() === "free") {
        return false;
    }
    
    return product.inStock;
}