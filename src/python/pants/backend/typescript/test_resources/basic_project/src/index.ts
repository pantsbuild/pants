import { add, multiply } from './math';

export function calculate(): number {
    return add(5, multiply(2, 3));
}

export function main() {
    const result = calculate();
    console.log('Calculation result:', result);
    return result;
}