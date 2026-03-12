# Laravel Skill

You are an expert Laravel developer. Apply these guidelines for idiomatic, maintainable Laravel applications.
This project uses **Laravel 12**, **PHP 8.3**, **Laravel Passport** (OAuth2), **Spatie** packages, **Bref** (AWS Lambda serverless), **SQS** for queues, and **Redis** via Predis.

## Version Target

- Target **Laravel 12** with **PHP 8.3+**
- Follow Laravel 11+ conventions: single `bootstrap/app.php`, minimal service providers
- Use `declare(strict_types=1)` in every PHP file

## Application Structure

```
app/
  Actions/          # Single-responsibility action classes (Spatie Queueable Actions)
  Console/          # Artisan commands
  Events/           # Domain events
  Exceptions/       # Custom exception classes + Handler
  Http/
    Controllers/    # Thin controllers — delegate to Actions/Services
    Middleware/     # Request middleware
    Requests/       # Form Request validation
    Resources/      # API Resources (Spatie Data or JsonResource)
  Jobs/             # Queued jobs (dispatched to SQS)
  Listeners/        # Event listeners
  Mail/             # Mailable classes
  Models/           # Eloquent models (UUID primary keys)
  Notifications/    # Notification classes
  Observers/        # Model observers (with Laravel Auditing)
  Policies/         # Authorization policies
  Rules/            # Custom validation rules
  Services/         # Domain service classes
database/
  factories/        # Model factories
  migrations/       # Schema migrations (ULIDs, timestamps)
  seeders/
config/
  passport.php      # OAuth2 configuration
routes/
  api.php           # Versioned API routes (/api/v1/...)
  web.php           # Web routes (Inertia or minimal)
```

## Eloquent ORM

```php
<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Database\Eloquent\SoftDeletes;
use Illuminate\Database\Eloquent\Builder;
use OwenIt\Auditing\Contracts\Auditable;
use OwenIt\Auditing\Auditable as AuditableTrait;

final class Order extends Model implements Auditable
{
    use HasUuids, SoftDeletes, AuditableTrait;

    protected $fillable = [
        'user_id', 'product_id', 'recipient_email', 'amount', 'currency', 'status',
    ];

    protected $casts = [
        'amount'     => 'integer',     // always in cents
        'metadata'   => 'array',
        'created_at' => 'datetime',
    ];

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function transactions(): HasMany
    {
        return $this->hasMany(Transaction::class);
    }

    // Query scopes
    public function scopePending(Builder $query): Builder
    {
        return $query->where('status', 'pending');
    }
}

// Querying — always eager-load relationships
Order::query()
    ->pending()
    ->with(['user', 'transactions' => fn ($q) => $q->latest()])
    ->orderByDesc('created_at')
    ->paginate(20);
```

## Spatie Data (DTOs)

Use **Spatie Laravel Data** for type-safe DTOs instead of raw arrays.

```php
use Spatie\LaravelData\Data;
use Spatie\LaravelData\Attributes\Validation\Email;
use Spatie\LaravelData\Attributes\Validation\Min;
use Spatie\LaravelData\Attributes\Validation\Max;

final class CreateOrderData extends Data
{
    public function __construct(
        public readonly string $productId,
        #[Email]
        public readonly string $recipientEmail,
        #[Min(1000), Max(1_000_000)]
        public readonly int $amount,       // cents
        public readonly string $currency,
        public readonly ?string $message,
    ) {}
}

// Usage in controller
final class StoreOrderController extends Controller
{
    public function __invoke(CreateOrderData $data, CreateOrder $action): JsonResponse
    {
        $order = $action->execute($data);
        return response()->json(new OrderResource($order), 201);
    }
}
```

## Controllers — Keep Thin

```php
// Single-action controllers with Form Request or Spatie Data
final class StoreOrderController extends Controller
{
    public function __invoke(
        StoreOrderRequest $request,
        CreateOrder $createOrder,
    ): JsonResponse {
        $order = $createOrder->execute($request->toOrderData());
        return response()->json(new OrderResource($order), 201);
    }
}
```

## Form Requests for Validation

```php
final class StoreOrderRequest extends FormRequest
{
    public function authorize(): bool
    {
        return $this->user() !== null;
    }

    public function rules(): array
    {
        return [
            'product_id'      => ['required', 'uuid', 'exists:products,id'],
            'recipient_email' => ['required', 'email', 'max:255'],
            'amount'          => ['required', 'integer', 'min:1000', 'max:1000000'],
            'currency'        => ['required', 'string', 'size:3'],
            'message'         => ['nullable', 'string', 'max:500'],
        ];
    }

    public function toOrderData(): CreateOrderData
    {
        return CreateOrderData::from($this->validated());
    }
}
```

## Spatie Queueable Actions

Use **Spatie Queueable Action** for actions that can run synchronously or be queued.

```php
use Spatie\QueueableAction\QueueableAction;

final class SendGiftCardEmail
{
    use QueueableAction;

    public function execute(Order $order, User $recipient): void
    {
        Mail::to($recipient->email)->send(new GiftCardMailable($order));
    }
}

// Run synchronously
app(SendGiftCardEmail::class)->execute($order, $recipient);

// Dispatch to queue
app(SendGiftCardEmail::class)->onQueue('emails')->execute($order, $recipient);
```

## Laravel Passport (OAuth2)

The project uses **Laravel Passport** with both password grant and client credentials grant.

```php
// routes/api.php
Route::prefix('v1')->group(function () {
    // Public — OAuth token endpoint handled by Passport
    Route::post('/auth/token', [\Laravel\Passport\Http\Controllers\AccessTokenController::class, 'issueToken']);

    // Protected routes
    Route::middleware('auth:api')->group(function () {
        Route::get('/user/profile', [ProfileController::class, 'show']);
        Route::apiResource('orders', OrderController::class);
    });

    // Client credentials — machine-to-machine (e.g. Pimcore service)
    Route::middleware('client')->group(function () {
        Route::get('/catalog/products', [CatalogController::class, 'index']);
    });
});

// Controller — get authenticated user
final class ProfileController extends Controller
{
    public function show(Request $request): JsonResponse
    {
        $user = $request->user();  // typed as User via Passport guard
        return response()->json(new UserResource($user));
    }
}
```

## Spatie Permissions (RBAC)

```php
// Assign roles/permissions
$user->assignRole('corporate_admin');
$user->givePermissionTo('manage:orders');

// Check in controller/policy
$this->authorize('manage:orders');

// In Blade / Inertia
@role('corporate_admin')
  <AdminPanel />
@endrole

// Middleware on routes
Route::middleware(['auth:api', 'role:corporate_admin'])->group(function () {
    Route::apiResource('users', AdminUserController::class);
});
```

## API Resources

```php
final class OrderResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return [
            'id'              => $this->id,
            'status'          => $this->status,
            'recipient_email' => $this->recipient_email,
            'amount'          => $this->amount,       // cents
            'currency'        => $this->currency,
            'created_at'      => $this->created_at->toIso8601String(),
            'user'            => new UserResource($this->whenLoaded('user')),
            'transactions'    => TransactionResource::collection($this->whenLoaded('transactions')),
        ];
    }
}
```

## Migrations (ULIDs / UUIDs)

```php
return new class extends Migration {
    public function up(): void
    {
        Schema::create('orders', function (Blueprint $table): void {
            $table->uuid('id')->primary();
            $table->foreignUuid('user_id')->constrained()->cascadeOnDelete();
            $table->foreignUuid('product_id')->constrained();
            $table->string('recipient_email');
            $table->unsignedBigInteger('amount');    // cents
            $table->string('currency', 3)->default('AUD');
            $table->string('status', 50)->default('pending')->index();
            $table->json('metadata')->nullable();
            $table->timestamps();
            $table->softDeletes();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('orders');
    }
};
```

## Jobs and SQS Queues

```php
// Jobs dispatch to SQS — use QUEUE_CONNECTION=sqs in production
final class ProcessGiftCardOrder implements ShouldQueue
{
    use Dispatchable, InteractsWithQueue, Queueable, SerializesModels;

    public int $tries = 3;
    public int $backoff = 30;
    public int $timeout = 120;

    public function __construct(private readonly Order $order) {}

    public function handle(WalletService $wallet): void
    {
        $wallet->debit($this->order);
        $this->order->update(['status' => 'processing']);
        app(SendGiftCardEmail::class)->execute($this->order, $this->order->user);
    }

    public function failed(\Throwable $e): void
    {
        Log::error('Gift card order failed', [
            'order_id' => $this->order->id,
            'error'    => $e->getMessage(),
        ]);
        $this->order->update(['status' => 'failed']);
    }
}

// Dispatch
ProcessGiftCardOrder::dispatch($order);
ProcessGiftCardOrder::dispatch($order)->onQueue('orders')->delay(now()->addSeconds(5));
```

## Redis with Predis

```php
// config/database.php — Redis uses Predis client
'redis' => [
    'client' => env('REDIS_CLIENT', 'predis'),
    'default' => [
        'url'  => env('REDIS_URL'),
        'host' => env('REDIS_HOST', '127.0.0.1'),
        'port' => env('REDIS_PORT', '6379'),
    ],
],

// Usage
use Illuminate\Support\Facades\Redis;

Redis::set("user:profile:{$userId}", json_encode($profile), 'EX', 3600);
$cached = Redis::get("user:profile:{$userId}");

// Cache facade (preferred for simple caching)
Cache::remember("products:{$categoryId}", now()->addHour(), fn () => Product::where('category_id', $categoryId)->get());
Cache::forget("products:{$categoryId}");
```

## Bref Serverless (AWS Lambda)

The project deploys on **AWS Lambda via Bref**. Keep these constraints in mind:

```php
// In serverless context:
// - No persistent filesystem writes (use S3)
// - No long-running processes
// - Cold starts — keep bootstrap lean
// - SQS handler for async processing

// serverless.yml function handler
// handler: Bref\LaravelBridge\Http\OctaneHandler
// layers: [${bref:layer.php-83-fpm}]

// S3 for file storage — never write to local disk
Storage::disk('s3')->put("receipts/{$order->id}.pdf", $pdfContent);

// Use SQS for all async work
ProcessGiftCardOrder::dispatch($order)->onQueue(config('queue.connections.sqs.queue'));
```

## Authorization (Policies)

```php
final class OrderPolicy
{
    public function view(User $user, Order $order): bool
    {
        return $user->id === $order->user_id || $user->hasRole('corporate_admin');
    }

    public function cancel(User $user, Order $order): bool
    {
        return $user->id === $order->user_id && $order->status === 'pending';
    }
}

// Register in AppServiceProvider (L11+)
Gate::policy(Order::class, OrderPolicy::class);
```

## Testing

```php
final class CreateOrderTest extends TestCase
{
    use RefreshDatabase;

    public function test_authenticated_user_can_create_order(): void
    {
        $user = User::factory()->create();
        $product = Product::factory()->available()->create();

        $response = $this->actingAs($user, 'api')
            ->postJson('/api/v1/orders', [
                'product_id'      => $product->id,
                'recipient_email' => 'friend@example.com',
                'amount'          => 5000,
                'currency'        => 'AUD',
            ]);

        $response->assertCreated()
            ->assertJsonPath('data.status', 'pending')
            ->assertJsonPath('data.recipient_email', 'friend@example.com');

        $this->assertDatabaseHas('orders', [
            'user_id' => $user->id,
            'amount'  => 5000,
        ]);
    }

    public function test_order_creation_dispatches_job(): void
    {
        Queue::fake();
        $user = User::factory()->create();

        $this->actingAs($user, 'api')
            ->postJson('/api/v1/orders', [...]);

        Queue::assertPushed(ProcessGiftCardOrder::class);
    }
}
```

## Service Container and Dependency Injection

```php
// Bind interfaces in AppServiceProvider
$this->app->bind(WalletServiceInterface::class, BavixWalletService::class);
$this->app->singleton(PimcoreClient::class, fn () => new PimcoreClient(config('services.pimcore')));

// Constructor injection — auto-resolved by container
public function __construct(
    private readonly WalletServiceInterface $wallet,
    private readonly PimcoreClient $pimcore,
) {}
```

## Anti-Patterns to Avoid

- ❌ Fat controllers — move logic to Action classes or Services
- ❌ N+1 queries — always eager-load with `with()` or `load()`
- ❌ `$request->all()` — use `$request->validated()` or Spatie Data
- ❌ Business logic in Blade templates or API Resources
- ❌ Writing to local filesystem in Bref/Lambda — use S3
- ❌ Synchronous processing for emails/PDFs/notifications — always queue
- ❌ Hardcoded credentials — use `.env` + `config()` helper
- ❌ Missing database indexes on foreign keys and frequently-queried columns
- ❌ `DB::statement()` for CRUD — use Eloquent or Query Builder
