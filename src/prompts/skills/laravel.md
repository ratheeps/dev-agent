# Laravel Skill

You are an expert Laravel developer. Apply these guidelines for idiomatic, maintainable Laravel applications.

## Version Target

- Target **Laravel 11+** unless the project specifies otherwise
- Follow the Laravel release conventions (single `bootstrap/app.php`, minimal service providers)

## Application Structure

```
app/
  Actions/          # Single-responsibility action classes
  Console/          # Artisan commands
  Events/           # Domain events
  Exceptions/       # Custom exception classes
  Http/
    Controllers/    # Thin controllers — delegate to Actions/Services
    Middleware/     # Request middleware
    Requests/       # Form Request validation classes
    Resources/      # API Resources (transformers)
  Jobs/             # Queued jobs
  Listeners/        # Event listeners
  Mail/             # Mailable classes
  Models/           # Eloquent models
  Notifications/    # Notification classes
  Observers/        # Model observers
  Policies/         # Authorization policies
  Providers/        # Service providers (minimal in L11)
  Rules/            # Custom validation rules
  Services/         # Domain service classes
database/
  factories/        # Model factories
  migrations/       # Schema migrations
  seeders/          # Database seeders
```

## Eloquent ORM

```php
// Model conventions
final class User extends Authenticatable
{
    // Always declare fillable or guarded
    protected $fillable = ['name', 'email', 'password'];

    // Cast types explicitly
    protected $casts = [
        'email_verified_at' => 'datetime',
        'settings' => 'array',
        'is_admin' => 'boolean',
    ];

    // Relationships
    public function posts(): HasMany
    {
        return $this->hasMany(Post::class);
    }

    public function role(): BelongsTo
    {
        return $this->belongsTo(Role::class);
    }

    // Scopes
    public function scopeActive(Builder $query): Builder
    {
        return $query->where('active', true);
    }
}

// Querying
User::query()
    ->where('active', true)
    ->with(['role', 'posts' => fn ($q) => $q->latest()->limit(5)])
    ->orderBy('created_at', 'desc')
    ->paginate(20);
```

## Controllers — Keep Thin

```php
// Single-action controllers for clarity
final class StoreUserController extends Controller
{
    public function __invoke(StoreUserRequest $request, CreateUser $createUser): JsonResponse
    {
        $user = $createUser->handle($request->validated());
        return response()->json(new UserResource($user), 201);
    }
}
```

## Form Requests for Validation

```php
final class StoreUserRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true; // or gate check
    }

    public function rules(): array
    {
        return [
            'name' => ['required', 'string', 'max:255'],
            'email' => ['required', 'email', 'unique:users,email'],
            'password' => ['required', 'min:8', 'confirmed'],
        ];
    }
}
```

## API Resources

```php
final class UserResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return [
            'id' => $this->id,
            'name' => $this->name,
            'email' => $this->email,
            'created_at' => $this->created_at->toIso8601String(),
            'posts' => PostResource::collection($this->whenLoaded('posts')),
        ];
    }
}
```

## Migrations

```php
return new class extends Migration {
    public function up(): void
    {
        Schema::create('users', function (Blueprint $table) {
            $table->ulid('id')->primary();
            $table->string('name');
            $table->string('email')->unique();
            $table->timestamp('email_verified_at')->nullable();
            $table->string('password');
            $table->timestamps();
            $table->softDeletes();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('users');
    }
};
```

## Jobs and Queues

```php
final class SendWelcomeEmail implements ShouldQueue
{
    use Dispatchable, InteractsWithQueue, Queueable, SerializesModels;

    public int $tries = 3;
    public int $backoff = 60;

    public function __construct(private readonly User $user) {}

    public function handle(Mailer $mailer): void
    {
        $mailer->to($this->user)->send(new WelcomeMail($this->user));
    }

    public function failed(\Throwable $e): void
    {
        Log::error('Welcome email failed', ['user' => $this->user->id, 'error' => $e->getMessage()]);
    }
}

// Dispatch
SendWelcomeEmail::dispatch($user);
SendWelcomeEmail::dispatch($user)->delay(now()->addMinutes(5));
```

## Authorization (Gates and Policies)

```php
// Policy
final class PostPolicy
{
    public function update(User $user, Post $post): bool
    {
        return $user->id === $post->user_id;
    }
}

// Usage in controller
$this->authorize('update', $post);
// or in Blade
@can('update', $post) ... @endcan
```

## Testing

```php
// Feature tests (HTTP)
final class UserRegistrationTest extends TestCase
{
    use RefreshDatabase;

    public function test_user_can_register(): void
    {
        $response = $this->postJson('/api/users', [
            'name' => 'Alice',
            'email' => 'alice@example.com',
            'password' => 'password',
            'password_confirmation' => 'password',
        ]);

        $response->assertCreated()
            ->assertJsonPath('data.email', 'alice@example.com');
        $this->assertDatabaseHas('users', ['email' => 'alice@example.com']);
    }
}
```

## Service Container and Dependency Injection

```php
// In AppServiceProvider or a dedicated provider
$this->app->bind(UserRepositoryInterface::class, EloquentUserRepository::class);

// Constructor injection in controllers and services (auto-resolved)
public function __construct(private readonly UserRepositoryInterface $users) {}
```

## Anti-Patterns to Avoid

- ❌ Fat controllers — move logic to Action classes or Services
- ❌ DB::statement or raw queries for CRUD — use Eloquent or Query Builder
- ❌ N+1 queries — always eager-load relationships with `with()`
- ❌ Business logic in Blade templates
- ❌ Using `$request->all()` — use `$request->validated()` from Form Requests
- ❌ Hardcoded credentials — use `.env` and `config()` helper
- ❌ Skipping database indexes on frequently-queried columns
- ❌ Not using queues for time-consuming tasks (emails, notifications, API calls)
