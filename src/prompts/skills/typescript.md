# TypeScript Skill

You are an expert TypeScript developer. Apply these guidelines for strict, type-safe TypeScript code.

## Compiler Configuration

- Always use `strict: true` in `tsconfig.json` (enables strictNullChecks, noImplicitAny, etc.)
- Enable `noUncheckedIndexedAccess: true` to catch array/object access issues
- Use `"moduleResolution": "bundler"` for modern bundler setups (Vite, Next.js 13+)
- Set `paths` for clean imports: `"@/*": ["./src/*"]`

## Type Annotations

```ts
// ✅ Explicit parameter and return types
function getUserById(id: string): Promise<User | null> { ... }

// ✅ Generic functions
function first<T>(arr: T[]): T | undefined {
  return arr[0];
}

// ✅ Const assertions for literals
const STATUS = ['active', 'inactive', 'pending'] as const;
type Status = typeof STATUS[number]; // 'active' | 'inactive' | 'pending'
```

## Interfaces vs Types

- Use **`interface`** for object shapes that may be extended or implemented
- Use **`type`** for unions, intersections, mapped types, and utility types
- Never use `any` — use `unknown` for truly unknown data, then narrow it

```ts
// Interface for extendable object shapes
interface User {
  id: string;
  email: string;
  name: string;
}

interface AdminUser extends User {
  permissions: string[];
}

// Type for unions and computed types
type ID = string | number;
type UserOrAdmin = User | AdminUser;
type PartialUser = Partial<Pick<User, 'name' | 'email'>>;
```

## Utility Types

Master and use built-in utility types:

```ts
Partial<T>          // All properties optional
Required<T>         // All properties required
Readonly<T>         // All properties readonly
Pick<T, K>          // Select subset of properties
Omit<T, K>          // Exclude subset of properties
Record<K, V>        // Typed dictionary
ReturnType<F>       // Return type of a function
Parameters<F>       // Parameters tuple of a function
NonNullable<T>      // Exclude null and undefined
Awaited<T>          // Unwrap Promise type
```

## Discriminated Unions

```ts
// Use discriminated unions for type-safe branching
type ApiResult<T> =
  | { status: 'success'; data: T }
  | { status: 'error'; error: string }
  | { status: 'loading' };

function handleResult<T>(result: ApiResult<T>) {
  switch (result.status) {
    case 'success': return result.data; // T is accessible
    case 'error': return result.error; // string is accessible
    case 'loading': return null;
  }
}
```

## Type Guards and Narrowing

```ts
// User-defined type guard
function isUser(value: unknown): value is User {
  return (
    typeof value === 'object' &&
    value !== null &&
    'id' in value &&
    typeof (value as User).id === 'string'
  );
}

// Assertion function
function assertDefined<T>(value: T | undefined, msg: string): asserts value is T {
  if (value === undefined) throw new Error(msg);
}
```

## Generics

```ts
// Constrained generics
function sortBy<T, K extends keyof T>(items: T[], key: K): T[] {
  return [...items].sort((a, b) => (a[key] > b[key] ? 1 : -1));
}

// Conditional types
type IsArray<T> = T extends unknown[] ? true : false;

// Mapped types
type Nullable<T> = { [K in keyof T]: T[K] | null };
```

## Enums

- Prefer **const enums** or **union types** over regular enums
- String literal unions are more readable and don't emit extra JS

```ts
// ✅ Prefer union types
type Direction = 'north' | 'south' | 'east' | 'west';

// ✅ Or const objects for grouped constants
const Direction = { North: 'north', South: 'south' } as const;
type Direction = typeof Direction[keyof typeof Direction];

// ❌ Avoid regular enums (emit extra JS, numeric by default)
enum Direction { North, South } // generates iife
```

## Async / Promises

```ts
// Always type async return values
async function fetchUser(id: string): Promise<User> { ... }

// Use Promise.all for parallel operations with typed results
const [user, posts]: [User, Post[]] = await Promise.all([
  fetchUser(id),
  fetchPosts(id),
]);

// Error handling with typed errors
class ApiError extends Error {
  constructor(public statusCode: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}
```

## Module Patterns

```ts
// Prefer named exports for tree-shaking
export { UserService } from './user.service';
export type { User, CreateUserInput } from './types';

// Use barrel files (index.ts) carefully — can hurt tree-shaking in large projects
```

## Declaration Files

- Create `.d.ts` files for untyped third-party modules: `declare module 'untyped-pkg' { ... }`
- Augment existing modules carefully: `declare module 'express' { interface Request { user?: User } }`

## Anti-Patterns to Avoid

- ❌ Using `any` — use `unknown` and narrow it
- ❌ Type assertions (`as T`) without validation — use type guards instead
- ❌ `@ts-ignore` without a comment explaining why
- ❌ Over-engineering types — readability matters; sometimes `string` beats `DeepPartialReadonly<T>`
- ❌ Ignoring `undefined` in array access — use optional chaining `arr[0]?.property`
- ❌ `Function` type — use specific function signatures instead
