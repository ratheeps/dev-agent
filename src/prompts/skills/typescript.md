# TypeScript Skill

You are an expert TypeScript developer. Apply these guidelines for strict, type-safe TypeScript code.
This project uses **TypeScript** with `strict: true`, path aliases (`@/`), and **Zod** for runtime validation.

## Compiler Configuration

```json
// tsconfig.json — key settings
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "moduleResolution": "bundler",
    "paths": { "@/*": ["./src/*"] },
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }]
  }
}
```

- Always use `strict: true` (enables `strictNullChecks`, `noImplicitAny`, etc.)
- Use `@/` path alias for all internal imports: `import { Button } from '@/components/ui/button'`
- Use `noUncheckedIndexedAccess` — always guard array/object access

## Type Annotations

```ts
// ✅ Explicit parameter and return types on all public functions
function getUserById(id: string): Promise<User | null> { ... }

// ✅ Generic functions with constraints
function sortBy<T, K extends keyof T>(items: T[], key: K): T[] {
  return [...items].sort((a, b) => (a[key] > b[key] ? 1 : -1));
}

// ✅ Const assertions for string literal unions
const ORDER_STATUSES = ['pending', 'processing', 'shipped', 'delivered', 'cancelled'] as const;
type OrderStatus = typeof ORDER_STATUSES[number];

// ✅ Template literal types for string patterns
type ApiRoute = `/api/v1/${string}`;
type EventName = `on${Capitalize<string>}`;
```

## Interfaces vs Types

- Use **`interface`** for object shapes (extendable, implements-able)
- Use **`type`** for unions, intersections, mapped types, utility type aliases
- Never use `any` — use `unknown` for truly unknown input, then narrow with type guards

```ts
// Interface for domain entities
interface User {
  id: string;
  email: string;
  name: string;
  createdAt: Date;
}

interface AdminUser extends User {
  permissions: string[];
  lastLoginAt: Date | null;
}

// Type for computed/union types
type ID = string;
type UserRole = 'admin' | 'manager' | 'viewer';
type Nullable<T> = T | null;
type ApiResponse<T> = { data: T; meta?: PaginationMeta };
```

## Zod for Runtime Validation

Use **Zod** for all runtime schema validation — API response parsing, form validation, env vars.

```ts
import { z } from 'zod';

// Define schema
const userSchema = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  name: z.string().min(1).max(255),
  role: z.enum(['admin', 'manager', 'viewer']),
  createdAt: z.string().datetime(),
});

// Infer TypeScript type from schema
type User = z.infer<typeof userSchema>;

// Parse API response (throws ZodError on failure)
const user = userSchema.parse(apiResponse.data);

// Safe parse (returns { success, data } | { success: false, error })
const result = userSchema.safeParse(apiResponse.data);
if (!result.success) {
  console.error('Invalid user data:', result.error.flatten());
  return null;
}

// Schemas in src/validation/ — co-located with feature
export const createOrderSchema = z.object({
  recipientEmail: z.string().email('Invalid recipient email'),
  amount: z.number().int().min(1000).max(1000000), // cents
  message: z.string().max(500).optional(),
  productId: z.string().uuid(),
});

export type CreateOrderInput = z.infer<typeof createOrderSchema>;
```

## Utility Types

```ts
Partial<T>          // All properties optional
Required<T>         // All properties required
Readonly<T>         // All properties readonly
Pick<T, K>          // Select subset of properties
Omit<T, K>          // Exclude subset of properties
Record<K, V>        // Typed dictionary/map
ReturnType<F>       // Return type of a function
Parameters<F>       // Parameters tuple of a function
NonNullable<T>      // Exclude null and undefined
Awaited<T>          // Unwrap Promise type
Extract<T, U>       // Extract union members assignable to U
Exclude<T, U>       // Exclude union members assignable to U
```

## Discriminated Unions

```ts
// Use discriminated unions for exhaustive type-safe branching
type ApiState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: T }
  | { status: 'error'; error: string; code?: number };

function renderState<T>(state: ApiState<T>): React.ReactNode {
  switch (state.status) {
    case 'idle': return null;
    case 'loading': return <Spinner />;
    case 'success': return <DataView data={state.data} />;
    case 'error': return <ErrorMessage message={state.error} />;
    // TypeScript ensures all cases are handled
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
    'email' in value &&
    typeof (value as User).id === 'string'
  );
}

// Assertion function for invariants
function assertDefined<T>(value: T | null | undefined, msg: string): asserts value is T {
  if (value == null) throw new Error(`Assertion failed: ${msg}`);
}

// Type predicate with Array filter
const users: Array<User | null> = [...];
const validUsers: User[] = users.filter((u): u is User => u !== null);
```

## API Contract Types

Define API contract types in `src/types/` to share between services and components:

```ts
// src/types/api.ts — Shared API response envelope
export interface ApiSuccessResponse<T> {
  data: T;
  message?: string;
  meta?: {
    current_page: number;
    last_page: number;
    per_page: number;
    total: number;
  };
}

export interface ApiErrorResponse {
  message: string;
  errors?: Record<string, string[]>;
  code?: string;
}

// src/types/order.ts
export interface Order {
  id: string;
  status: OrderStatus;
  recipientEmail: string;
  amount: number;        // always in cents
  currency: string;      // ISO 4217
  createdAt: string;     // ISO 8601
}

export interface CreateOrderPayload {
  productId: string;
  recipientEmail: string;
  amount: number;
  message?: string;
}
```

## Generics

```ts
// Constrained generics
function pick<T extends object, K extends keyof T>(obj: T, keys: K[]): Pick<T, K> {
  return keys.reduce((acc, key) => ({ ...acc, [key]: obj[key] }), {} as Pick<T, K>);
}

// Conditional types
type IsArray<T> = T extends unknown[] ? true : false;
type Unwrap<T> = T extends Promise<infer U> ? U : T;

// Mapped types
type Optional<T> = { [K in keyof T]?: T[K] };
type DeepReadonly<T> = { readonly [K in keyof T]: T[K] extends object ? DeepReadonly<T[K]> : T[K] };
```

## Async / Promises

```ts
// Always type async return values
async function fetchOrder(id: string): Promise<Order> { ... }

// Promise.all with typed destructuring
const [user, orders]: [User, Order[]] = await Promise.all([
  fetchUser(id),
  fetchOrders(id),
]);

// Typed error handling
class ApiError extends Error {
  constructor(
    public readonly statusCode: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  static isApiError(error: unknown): error is ApiError {
    return error instanceof ApiError;
  }
}
```

## Enums

- Prefer **const objects** or **union types** over `enum` (avoids extra JS emission)

```ts
// ✅ Const object — readable, tree-shakeable
const OrderStatus = {
  Pending: 'pending',
  Processing: 'processing',
  Shipped: 'shipped',
  Delivered: 'delivered',
  Cancelled: 'cancelled',
} as const;
type OrderStatus = typeof OrderStatus[keyof typeof OrderStatus];

// ✅ String union — simplest for small sets
type UserRole = 'admin' | 'manager' | 'viewer';

// ❌ Avoid regular enums — emit IIFE, numeric by default
enum Direction { North, South } // generates extra JS
```

## Module Patterns

```ts
// Named exports (preferred for tree-shaking)
export { UserService } from './user.service';
export type { User, CreateUserInput } from './types';

// Use @/ alias for all imports — never relative ../../
import { apiClient } from '@/services/api';
import { Button } from '@/components/ui/button';
import { createOrderSchema } from '@/validation/orderSchema';
```

## Anti-Patterns to Avoid

- ❌ Using `any` — use `unknown` and narrow it
- ❌ Type assertions (`as T`) without prior validation — use type guards
- ❌ `@ts-ignore` without an explanatory comment
- ❌ Relative imports `../../..` — use `@/` alias
- ❌ Not validating API responses at runtime — use Zod `.parse()`
- ❌ Over-engineering types — readability matters; `string` beats `DeepPartialReadonly<T>` in most cases
- ❌ `Function` type — use explicit function signatures
- ❌ Ignoring `undefined` in array access — use optional chaining `arr[0]?.property`
- ❌ `Object` / `{}` as a catch-all type — be specific
