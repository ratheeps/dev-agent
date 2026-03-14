# Application Architecture Skill

You are an expert in the GiftBee multi-service application architecture.
Apply this knowledge when implementing features, adding new services, or modifying cross-service contracts.

---

## Repository Overview

GiftBee is a **gift card e-commerce platform** composed of 5 repositories, all in the parent
`giftbee/` directory:

| Repo | Stack | Role |
|------|-------|------|
| `local-infra` | Docker Compose | Dev environment orchestration (all services + databases) |
| `store-front` | Next.js 14 + TypeScript | Customer-facing storefront (send/receive gift cards) |
| `admin-portal` | Next.js 14 + TypeScript | Corporate/admin backoffice (manage orders, users, catalog) |
| `wallet-service` | Laravel 12 + PHP 8.3 | Core API — wallet, orders, auth, payments |
| `pim` | Pimcore | Product catalog management — product data consumed by wallet-service |

---

## Service Responsibility Boundaries

```
┌─────────────────────┐    ┌─────────────────────┐
│     store-front      │    │    admin-portal      │
│  (customer portal)   │    │  (backoffice portal) │
│  Next.js 14 + React  │    │  Next.js 14 + React  │
│  Port: 3000 (local)  │    │  Port: 3001 (local)  │
└────────┬────────────┘    └────────┬─────────────┘
         │  REST /api/v1             │  REST /api/v1
         │  Bearer token (Passport)  │  Bearer token (Passport)
         └─────────────┬─────────────┘
                       ▼
            ┌──────────────────────┐
            │    wallet-service     │
            │  Laravel 12 + PHP 8.3 │
            │  REST API + OAuth2    │
            │  Port: 8000 (local)  │
            └──────────┬───────────┘
                       │  client_credentials grant
                       │  REST /api/v1/catalog
                       ▼
            ┌──────────────────────┐
            │         pim           │
            │  Pimcore 11+ + PHP   │
            │  Product catalog CMS  │
            │  Port: 8080 (local)  │
            └──────────────────────┘
```

---

## Authentication Architecture

### User Authentication — Password Grant (OAuth2)

The frontends authenticate users via Laravel Passport's password grant flow:

```
1. User enters email + password on store-front or admin-portal
2. Frontend POSTs to wallet-service /oauth/token:
   {
     "grant_type": "password",
     "client_id": NEXT_AUTH_PASSWORD_CLIENT_ID,
     "client_secret": NEXT_AUTH_PASSWORD_CLIENT_SECRET,
     "username": "user@example.com",
     "password": "secret",
     "scope": ""
   }
3. wallet-service returns { access_token, refresh_token, expires_in }
4. Frontend stores access_token in HttpOnly cookie (not localStorage)
5. All subsequent API calls include: Authorization: Bearer {access_token}
6. Next.js middleware (jose jwtVerify) validates token on every request
```

```typescript
// src/services/authService.ts (store-front / admin-portal)
export const authService = {
  async login(email: string, password: string): Promise<TokenResponse> {
    const { data } = await axios.post<TokenResponse>(
      `${process.env.NEXT_APP_API_BASE_URL}/oauth/token`,
      {
        grant_type: 'password',
        client_id: process.env.NEXT_AUTH_PASSWORD_CLIENT_ID,
        client_secret: process.env.NEXT_AUTH_PASSWORD_CLIENT_SECRET,
        username: email,
        password,
        scope: '',
      },
    );
    return data;
  },
};
```

### Service-to-Service — Client Credentials Grant (OAuth2)

Wallet-service authenticates to pim using client credentials (machine-to-machine):

```php
// Pimcore API call from wallet-service
// Uses OAuth2 client_credentials grant — no user context
$token = $this->pimcore->getClientCredentialsToken(
    clientId: config('services.pimcore.client_id'),
    clientSecret: config('services.pimcore.client_secret'),
    scope: 'catalog:read',
);
$product = $this->pimcore->getProduct($productId);
```

---

## Frontend Application Structure (store-front & admin-portal)

Both frontends follow the same **feature-slice** directory structure inside `src/`:

```
src/
  app/                      # Next.js App Router — file-based routing
    (auth)/                 # Route group: login, register, forgot-password
    (dashboard)/            # Route group: authenticated pages
      layout.tsx            # Dashboard shell with sidebar/nav
      page.tsx              # Dashboard home
    api/                    # Next.js Route Handlers (API proxy endpoints)
    layout.tsx              # Root layout (fonts, providers)
    globals.css             # Tailwind base styles + CSS variables
  components/               # Shared UI components
    ui/                     # shadcn/ui primitives (Button, Input, Dialog, etc.)
    layout/                 # Header, Sidebar, Footer, PageWrapper
    forms/                  # Reusable form components
  features/                 # Domain-specific feature modules
    <domain>/               # e.g. orders/, recipients/, products/
      components/           # Domain components
      hooks/                # Custom hooks (useOrders, useOrderMutations)
      services/             # Domain service layer (Axios calls)
      types/                # Domain TypeScript interfaces
      store/                # Redux slice for this domain
      validation/           # Zod schemas for forms
  hooks/                    # Global custom hooks (useAuth, useDebounce)
  lib/                      # Utilities: cn(), formatCurrency(), dateUtils
  providers/                # React context providers (Redux, ThemeProvider)
  services/                 # Global API services: api.ts (Axios instance), authService.ts
  store/                    # Redux Toolkit store, root reducer, hooks (useAppSelector)
  types/                    # Global TypeScript types (ApiResponse, PaginationMeta)
  validation/               # Global Zod schemas
  config/                   # App configuration (routes, constants)
  enums/                    # TypeScript enums and const objects
  middleware.ts             # Next.js Edge Middleware (JWT auth guard)
```

### Feature Slice Pattern

When adding a new feature domain (e.g. "vouchers"):

```
src/features/vouchers/
  components/
    VoucherCard.tsx
    VoucherList.tsx
    CreateVoucherDialog.tsx
  hooks/
    useVouchers.ts          # useAsync hook + API calls
    useVoucherMutation.ts   # create/update/delete + Redux dispatch
  services/
    voucherService.ts       # Axios calls to wallet-service /api/v1/vouchers
  store/
    voucherSlice.ts         # Redux slice: state, thunks, selectors
  types/
    index.ts                # Voucher, CreateVoucherPayload, VoucherStatus
  validation/
    voucherSchema.ts        # Zod schema for voucher forms
```

---

## Backend API Architecture (wallet-service)

### API Versioning

All API routes are prefixed with `/api/v1/`:

```php
// routes/api.php
Route::prefix('v1')->group(function (): void {
    // Public auth
    Route::post('/auth/register', [RegisterController::class, 'store']);
    Route::post('/auth/profile', [ProfileController::class, 'show']);  // Passport handles /oauth/token

    // Authenticated user routes
    Route::middleware('auth:api')->group(function (): void {
        Route::get('/user/profile', [ProfileController::class, 'show']);
        Route::apiResource('/orders', OrderController::class);
        Route::apiResource('/recipients', RecipientController::class);
        Route::get('/wallet/balance', [WalletController::class, 'balance']);
    });

    // Admin routes
    Route::middleware(['auth:api', 'role:admin,corporate_admin'])->prefix('admin')->group(function (): void {
        Route::apiResource('/users', AdminUserController::class);
        Route::apiResource('/orders', AdminOrderController::class);
    });

    // Service-to-service (client credentials)
    Route::middleware('client')->prefix('catalog')->group(function (): void {
        Route::get('/products', [CatalogController::class, 'index']);
        Route::get('/products/{id}', [CatalogController::class, 'show']);
    });
});
```

### JSON Response Envelope

All API responses wrap data in a consistent envelope:

```json
// Success (single resource)
{
  "data": { "id": "...", "status": "pending", ... }
}

// Success (collection)
{
  "data": [ ... ],
  "meta": {
    "current_page": 1,
    "last_page": 5,
    "per_page": 20,
    "total": 94
  }
}

// Error
{
  "message": "The given data was invalid.",
  "errors": {
    "recipient_email": ["The recipient email field is required."],
    "amount": ["The amount must be at least 1000."]
  }
}
```

```php
// API Resource enforces this structure
final class OrderResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return [
            'id'              => $this->id,
            'status'          => $this->status,
            'recipient_email' => $this->recipient_email,
            'amount'          => $this->amount,
            'currency'        => $this->currency,
            'created_at'      => $this->created_at->toIso8601String(),
        ];
    }
}
```

---

## State Management (store-front & admin-portal)

**Redux Toolkit** manages global state. The store is structured by feature domain:

```
store/
  index.ts               # configureStore, RootState, AppDispatch
  hooks.ts               # typed useAppSelector, useAppDispatch
  slices/
    authSlice.ts         # user session, tokens
    cartSlice.ts         # checkout cart state
    notificationSlice.ts # toasts and alerts
  features/
    ordersSlice.ts       # orders list + status
    recipientsSlice.ts   # saved recipients
```

**What goes in Redux vs local state:**

| Type | Use Redux | Use useState |
|------|-----------|-------------|
| Authenticated user | ✅ | |
| Auth token | ✅ | |
| Cart/checkout flow | ✅ | |
| Persistent list data (orders) | ✅ | |
| Dialog open/close | | ✅ |
| Form field values | | ✅ (react-hook-form) |
| Hover/focus states | | ✅ |
| Derived data | | ✅ (useMemo) |

---

## Cross-Service API Contracts

TypeScript interface types live in `src/types/` on frontends and must match the Laravel API Resources.
Any change to an API Resource in wallet-service **requires** updating the corresponding TypeScript type.

```typescript
// src/types/order.ts (store-front / admin-portal)
export interface Order {
  id: string;
  status: 'pending' | 'processing' | 'shipped' | 'delivered' | 'cancelled';
  recipientEmail: string;
  amount: number;       // cents
  currency: string;     // ISO 4217, e.g. "AUD"
  createdAt: string;    // ISO 8601
}

export interface OrderMeta {
  currentPage: number;
  lastPage: number;
  perPage: number;
  total: number;
}

export interface OrderListResponse {
  data: Order[];
  meta: OrderMeta;
}
```

---

## File Upload Architecture

Files (receipts, images) are stored in **AWS S3**, never on the server filesystem.

```php
// wallet-service — generate presigned upload URL
public function getUploadUrl(string $filename): array
{
    $key = "uploads/{$filename}";
    $command = $this->s3->getCommand('PutObject', [
        'Bucket' => config('filesystems.disks.s3.bucket'),
        'Key'    => $key,
    ]);
    $url = (string) $this->s3->createPresignedRequest($command, '+15 minutes')->getUri();
    return ['upload_url' => $url, 'key' => $key];
}

// Frontend — direct upload to S3 with presigned URL (no server roundtrip)
const uploadFile = async (file: File) => {
  const { upload_url, key } = await fileService.getUploadUrl(file.name);
  await axios.put(upload_url, file, { headers: { 'Content-Type': file.type } });
  return key;
};
```

---

## Adding a New Feature (Checklist)

When implementing a new domain feature (e.g. "Scheduled Gifts"):

### Backend (wallet-service)
1. Create migration: `php artisan make:migration create_scheduled_gifts_table`
2. Create Model: `app/Models/ScheduledGift.php` with `HasUuids`, `Auditable`
3. Create FormRequest: `app/Http/Requests/StoreScheduledGiftRequest.php`
4. Create Spatie Data DTO: `app/Data/ScheduledGiftData.php`
5. Create Action: `app/Actions/CreateScheduledGift.php`
6. Create Resource: `app/Http/Resources/ScheduledGiftResource.php`
7. Create Controller: `app/Http/Controllers/ScheduledGiftController.php` (single-action or resource)
8. Add routes to `routes/api.php` under `v1` prefix with correct middleware
9. Create Factory + Feature test in `tests/Feature/`

### Frontend (store-front or admin-portal)
1. Create feature slice: `src/features/scheduled-gifts/`
2. Define types: `src/features/scheduled-gifts/types/index.ts`
3. Create Zod schema: `src/features/scheduled-gifts/validation/scheduledGiftSchema.ts`
4. Create service: `src/features/scheduled-gifts/services/scheduledGiftService.ts`
5. Create Redux slice: `src/features/scheduled-gifts/store/scheduledGiftSlice.ts`
6. Create components: form, list, detail
7. Add page: `src/app/(dashboard)/scheduled-gifts/page.tsx`
8. Add E2E test: `e2e/scheduled-gifts.spec.ts`

---

## Adding a New Microservice (Checklist)

When introducing a new service/repo (e.g. "notification-service"):

1. **Create repo** in Bitbucket under the GiftBee workspace
2. **Add to local-infra** `docker-compose.yml`:
   - New service container
   - Assign to appropriate Docker network (`giftbee_backend_network`)
   - Add Nginx reverse proxy config in `nginx/`
3. **Define OAuth2 client** in wallet-service for service-to-service auth
4. **Add API contract types** in consuming frontends/services
5. **Add `Dockerfile`** in the new repo for local + production
6. **Register in mason config** (`config/repositories.yaml` — add repo entry with stack, URLs)
7. **Add Bitbucket Pipeline** (`bitbucket-pipelines.yml`)
8. **Add OpenTofu module** (if needs AWS resources)

---

## Local Development Ports (Quick Reference)

| Service | Port | URL |
|---------|------|-----|
| store-front | 3000 | http://localhost:3000 |
| admin-portal | 3001 | http://localhost:3001 |
| wallet-service | 8000 | http://localhost:8000 |
| pim | 8080 | http://localhost:8080 |
| MySQL | 3306 | mysql://localhost:3306 |
| Redis | 6379 | redis://localhost:6379 |
| Mailpit UI | 8025 | http://localhost:8025 |
| PHPMyAdmin | 8090 | http://localhost:8090 |
| RedisInsight | 5540 | http://localhost:5540 |
| Nginx | 80/443 | http://localhost |
