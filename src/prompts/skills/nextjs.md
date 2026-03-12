# Next.js Skill

You are an expert Next.js developer. Apply these guidelines when implementing Next.js applications.
This project runs **Next.js 14** with the **App Router**, **TypeScript**, **Tailwind CSS**, **shadcn/ui**, and **Axios** for API communication.

## App Router vs Pages Router

- **Default to App Router** (`app/`) for all routes — this project uses App Router exclusively
- Never use `getServerSideProps`, `getStaticProps`, or `getInitialProps` — these are Pages Router only
- Never mix both routers

## App Router File Conventions

```
app/
  layout.tsx           # Root layout (persistent across navigations)
  page.tsx             # Route page component (maps to URL)
  loading.tsx          # Streaming Suspense loading UI
  error.tsx            # Error boundary ('use client' required)
  not-found.tsx        # 404 page
  route.ts             # API route handler (backend endpoint)
  (auth)/              # Route group — no URL segment, shared layout
  (dashboard)/
  [id]/                # Dynamic segment
  [...slug]/           # Catch-all segment
src/
  components/          # Shared components
  components/ui/       # shadcn/ui primitives
  features/            # Domain-specific feature modules
  hooks/               # Custom React hooks
  lib/                 # Utilities and helpers
  services/            # API service layer (Axios)
  store/               # Redux Toolkit store + slices
  types/               # TypeScript type definitions
  validation/          # Zod schemas
  middleware.ts        # Next.js Edge Middleware (auth guards)
```

## Server vs Client Components

- **Server Components** (default): zero JS on client, can `async/await` directly, access env vars
- **Client Components**: add `'use client'` directive; needed for interactivity, hooks, browser APIs, Redux
- Push `'use client'` to the **leaf nodes** — keep layouts and containers as server components

```tsx
// Server Component — fetch data directly, no 'use client'
async function OrderList() {
  const orders = await orderService.listServerSide();
  return (
    <ul>
      {orders.map(o => <OrderCard key={o.id} order={o} />)}
    </ul>
  );
}

// Client Component — interactive, connected to Redux
'use client';
import { useAppSelector } from '@/store/hooks';

function CartButton(): JSX.Element {
  const itemCount = useAppSelector(state => state.cart.items.length);
  return <button>Cart ({itemCount})</button>;
}
```

## Authentication Middleware

The project uses **JWT-based authentication** via the `jose` library in Edge Middleware.

```ts
// src/middleware.ts
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { jwtVerify } from 'jose';

const PUBLIC_PATHS = ['/login', '/register', '/forgot-password', '/api/auth'];

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const { pathname } = request.nextUrl;

  // Allow public paths
  if (PUBLIC_PATHS.some(p => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const token = request.cookies.get('access_token')?.value
    ?? request.headers.get('authorization')?.replace('Bearer ', '');

  if (!token) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  try {
    const secret = new TextEncoder().encode(process.env.NEXT_APP_KEY);
    await jwtVerify(token, secret);
    return NextResponse.next();
  } catch {
    const response = NextResponse.redirect(new URL('/login', request.url));
    response.cookies.delete('access_token');
    return response;
  }
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|public).*)'],
};
```

## Data Fetching

- **Server Components**: call service functions directly (no `fetch` in JSX)
- **Client Components**: use Axios service layer + Redux async thunks or `useAsync` hook
- **Never** use `useEffect` + `fetch` directly — use the service layer

```tsx
// ✅ Server Component — service call
async function DashboardPage() {
  const summary = await dashboardService.getSummary(); // server-side Axios call
  return <DashboardStats data={summary} />;
}

// ✅ Client Component — Redux thunk
'use client';
function TransactionList() {
  const dispatch = useAppDispatch();
  const { items, loading } = useAppSelector(state => state.transactions);

  useEffect(() => {
    dispatch(fetchTransactions());
  }, [dispatch]);

  // ...
}
```

## Route Handlers (API Routes)

```ts
// app/api/v1/webhooks/route.ts
import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = await request.json();
    // Validate and process
    const result = await webhookService.process(body);
    return NextResponse.json({ success: true, data: result }, { status: 200 });
  } catch (error) {
    console.error('Webhook error:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
```

## Server Actions

Use Server Actions for form mutations that don't need a client-side API layer:

```tsx
// app/actions/profileActions.ts
'use server';
import { revalidatePath } from 'next/cache';

export async function updateProfile(formData: FormData): Promise<{ success: boolean; error?: string }> {
  const name = formData.get('name') as string;
  try {
    await profileService.update({ name });
    revalidatePath('/profile');
    return { success: true };
  } catch {
    return { success: false, error: 'Failed to update profile' };
  }
}

// Usage in a Client Component
'use client';
import { updateProfile } from '@/app/actions/profileActions';

function ProfileForm() {
  return (
    <form action={updateProfile}>
      <input name="name" />
      <button type="submit">Save</button>
    </form>
  );
}
```

## Environment Variables

Follow the naming conventions already in `next.config.mjs`:

```
# Server-only (never exposed to client)
NEXT_APP_KEY=...                       # JWT secret
NEXT_AUTH_PASSWORD_CLIENT_ID=...       # Passport password grant client ID
NEXT_AUTH_PASSWORD_CLIENT_SECRET=...   # Passport password grant client secret
NEXT_AUTH_APP_CLIENT_ID=...
NEXT_AUTH_APP_CLIENT_SECRET=...

# Client-accessible (NEXT_PUBLIC_ or exposed via next.config env)
NEXT_APP_API_BASE_URL=https://api.example.com
NEXT_ACCOUNT_PORTAL_URL=https://account.example.com
```

- Access server vars directly: `process.env.NEXT_APP_KEY`
- Access client vars: `process.env.NEXT_APP_API_BASE_URL`
- **Never** put secrets in `NEXT_PUBLIC_*` variables

## Tailwind CSS Conventions

```tsx
// Use Tailwind utility classes — no inline styles, no CSS modules for components
// Use cn() from @/lib/utils for conditional classes (clsx + tailwind-merge)
import { cn } from '@/lib/utils';

function Card({ active, className }: { active: boolean; className?: string }): JSX.Element {
  return (
    <div
      className={cn(
        'rounded-lg border bg-card p-4 shadow-sm transition-all',
        active && 'border-primary ring-1 ring-primary',
        className,
      )}
    />
  );
}

// Use CSS variables for theming (defined in globals.css as --background, --foreground, etc.)
// Prefer semantic classes: bg-background, text-foreground, border-border, text-muted-foreground
```

## Image and Font Optimization

- Always use `next/image` (`<Image>`) — never `<img>` tags
- The project already configures `remotePatterns: [{ protocol: 'https', hostname: '**' }]`
- Set `width` and `height` on `<Image>` or use `fill` with a positioned container
- Use `next/font` for web fonts

## Sentry Integration

Sentry is configured via `@sentry/nextjs`. Wrap custom error boundaries and log critical errors:

```tsx
import * as Sentry from '@sentry/nextjs';

// Capture unexpected errors with context
try {
  await criticalOperation();
} catch (error) {
  Sentry.captureException(error, { tags: { feature: 'checkout' } });
  throw error; // Re-throw so the error boundary handles it
}
```

## Metadata and SEO

```tsx
// Static metadata
export const metadata: Metadata = {
  title: 'GiftBee — Send Gift Cards',
  description: 'The easiest way to send gift cards',
};

// Dynamic metadata per page
export async function generateMetadata({ params }: { params: { id: string } }): Promise<Metadata> {
  const product = await productService.get(params.id);
  return {
    title: `${product.name} — GiftBee`,
    openGraph: { images: [product.imageUrl] },
  };
}
```

## Performance Patterns

- Wrap data-fetching components in `<Suspense>` with a meaningful fallback for streaming SSR
- Use `dynamic()` for heavy client components that don't need SSR:
  ```tsx
  const HeavyChart = dynamic(() => import('@/components/HeavyChart'), { ssr: false });
  ```
- Use `generateStaticParams()` for static generation of dynamic routes
- Avoid importing large libraries at the module level in route handlers

## Anti-Patterns to Avoid

- ❌ `useEffect` + `fetch` in client components — use Redux thunks or service hooks
- ❌ `'use client'` on layouts or container components — forces entire tree to client render
- ❌ `getServerSideProps` / `getStaticProps` — Pages Router only, not App Router
- ❌ Hardcoded `localhost` URLs — use `process.env.NEXT_APP_API_BASE_URL`
- ❌ Secrets in `NEXT_PUBLIC_*` env vars
- ❌ `<img>` instead of `next/image`
- ❌ Blocking the entire page on a slow data fetch — use `<Suspense>` boundaries
- ❌ Storing sensitive tokens in `localStorage` — use HttpOnly cookies
