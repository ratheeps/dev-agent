# Next.js Skill

You are an expert Next.js developer. Apply these guidelines when implementing Next.js applications.

## App Router vs Pages Router

- **Default to App Router** (`app/`) for all new Next.js 13+ projects
- Use Pages Router (`pages/`) only when working in an existing codebase that hasn't migrated
- Never mix both routers for the same routes

## App Router File Conventions

```
app/
  layout.tsx           # Root layout (persistent across navigations)
  page.tsx             # Route page component (maps to URL)
  loading.tsx          # Suspense loading UI
  error.tsx            # Error boundary UI ('use client' required)
  not-found.tsx        # 404 UI
  route.ts             # API route handler
  (group)/             # Route group (doesn't affect URL)
  [param]/             # Dynamic segment
  [...slug]/           # Catch-all segment
  [[...slug]]/         # Optional catch-all
```

## Server vs Client Components

- **Server Components** (default): zero JS sent to client, can `async/await` directly, access server resources
- **Client Components**: add `'use client'` directive at the top; needed for interactivity, hooks, browser APIs
- Keep the tree as **server-heavy as possible** — push `'use client'` to leaf components
- Never import server-only modules in client components

```tsx
// Server Component — can fetch data directly
async function ProductList() {
  const products = await db.query('SELECT * FROM products');
  return <ul>{products.map(p => <ProductItem key={p.id} product={p} />)}</ul>;
}

// Client Component — interactive
'use client';
import { useState } from 'react';
function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(c => c + 1)}>{count}</button>;
}
```

## Data Fetching

- In Server Components: `fetch()` with Next.js caching extensions or ORM/DB calls directly
- Use `cache: 'force-cache'` for static data, `cache: 'no-store'` for dynamic data
- Use `revalidate` option for ISR: `fetch(url, { next: { revalidate: 3600 } })`
- For client-side fetching: React Query or SWR (not `useEffect` + `fetch`)

```tsx
// Static generation (default)
const data = await fetch('https://api.example.com/data');

// ISR — revalidate every hour
const data = await fetch('https://api.example.com/data', { next: { revalidate: 3600 } });

// Dynamic — always fresh
const data = await fetch('https://api.example.com/data', { cache: 'no-store' });
```

## Route Handlers (API Routes)

```ts
// app/api/users/route.ts
import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get('id');
  const user = await getUserById(id);
  return NextResponse.json(user);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  // validate, process
  return NextResponse.json({ created: true }, { status: 201 });
}
```

## Middleware

```ts
// middleware.ts (root level)
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  // Auth check, redirects, header injection
  const token = request.cookies.get('auth-token');
  if (!token) return NextResponse.redirect(new URL('/login', request.url));
  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/api/protected/:path*'],
};
```

## Metadata and SEO

```tsx
// Static metadata
export const metadata: Metadata = {
  title: 'Page Title',
  description: 'Page description',
};

// Dynamic metadata
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const product = await getProduct(params.id);
  return { title: product.name };
}
```

## Image and Font Optimization

- Always use `next/image` (`<Image>`) instead of `<img>` for automatic optimization
- Use `next/font` for web fonts — eliminates layout shift and external font requests
- Set `width` and `height` on `<Image>` or use `fill` with a positioned container

## Environment Variables

- Server-only: `VARIABLE_NAME` (never exposed to client)
- Client-accessible: `NEXT_PUBLIC_VARIABLE_NAME`
- Never put secrets in `NEXT_PUBLIC_*` variables

## Performance Patterns

- Use `<Suspense>` to wrap data-fetching components for streaming SSR
- Use `dynamic()` for heavy client components that don't need SSR
- Use `generateStaticParams()` for static generation of dynamic routes
- Enable `output: 'standalone'` in `next.config.ts` for containerized deployments

## Anti-Patterns to Avoid

- ❌ Fetching data in `useEffect` when a Server Component could do it
- ❌ Adding `'use client'` to layout files — this forces entire subtree to be client-rendered
- ❌ Using `getServerSideProps` in App Router (Pages Router only)
- ❌ Importing large libraries in route handlers without tree-shaking
- ❌ Hardcoding `localhost` URLs — use relative paths or `NEXT_PUBLIC_API_URL`
