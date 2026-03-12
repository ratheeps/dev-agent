# PHP Skill

You are an expert PHP developer. Apply these guidelines for modern, idiomatic PHP 8.x code.
This project uses **PHP 8.3** (Laravel 12 backend + Pimcore PIM service).

## PHP Version Target

- Target **PHP 8.3+** — use all modern features
- Use: named arguments, fibers, enums, readonly properties, readonly classes, match expressions, first-class callables

## Core File Template

Every PHP file must begin with:

```php
<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\User;
use App\Exceptions\NotFoundException;

// ...
```

## PSR Standards

Follow PHP-FIG PSR standards strictly:

- **PSR-1**: Basic coding standard (namespaces, class/method naming)
- **PSR-4**: Autoloading (one class per file, namespace matches directory structure)
- **PSR-12**: Extended coding style (4-space indent, braces on same line for control structures)
- **PSR-7/PSR-15**: HTTP messages and middleware for HTTP-layer code

## Modern PHP 8.x Features

```php
// Enums with backed types (PHP 8.1+)
enum OrderStatus: string
{
    case Pending    = 'pending';
    case Processing = 'processing';
    case Shipped    = 'shipped';
    case Delivered  = 'delivered';
    case Cancelled  = 'cancelled';

    public function label(): string
    {
        return match($this) {
            self::Pending    => 'Awaiting payment',
            self::Processing => 'Being processed',
            self::Shipped    => 'On its way',
            self::Delivered  => 'Delivered',
            self::Cancelled  => 'Cancelled',
        };
    }

    public function isTerminal(): bool
    {
        return in_array($this, [self::Delivered, self::Cancelled], true);
    }
}

// Readonly classes (PHP 8.2+)
readonly class Money
{
    public function __construct(
        public int $amount,       // cents
        public string $currency,  // ISO 4217
    ) {}

    public function add(Money $other): self
    {
        assert($this->currency === $other->currency, 'Currency mismatch');
        return new self($this->amount + $other->amount, $this->currency);
    }
}

// Readonly constructor promotion (PHP 8.1+)
final class UserService
{
    public function __construct(
        private readonly UserRepositoryInterface $users,
        private readonly EventDispatcherInterface $events,
    ) {}
}

// Match expression (PHP 8.0+) — exhaustive, no type coercion
$discount = match(true) {
    $order->amount >= 100_000 => 0.15,
    $order->amount >= 50_000  => 0.10,
    $order->amount >= 10_000  => 0.05,
    default                   => 0.0,
};

// Nullsafe operator (PHP 8.0+)
$city = $user?->getAddress()?->city;

// Named arguments (PHP 8.0+) — improves readability
$user = User::factory()->create(
    name: 'Alice',
    email: 'alice@example.com',
);

// First-class callable syntax (PHP 8.1+)
$lengths  = array_map(strlen(...), $strings);
$filtered = array_filter($users, $this->isActive(...));

// Fibers (PHP 8.1+) — for async-like control flow
$fiber = new Fiber(function (): void {
    $value = Fiber::suspend('ready');
    echo "Resumed with: {$value}";
});
$value = $fiber->start();
$fiber->resume('hello');
```

## Type System

```php
// Full type declarations on all methods
public function findById(string $id): ?User
{
    return User::find($id);
}

// Union types (PHP 8.0+)
public function process(int|string $input): void { ... }

// Intersection types (PHP 8.1+)
public function save(Serializable&Countable $data): void { ... }

// Never return type — function always throws or exits
public function fail(string $message): never
{
    throw new \InvalidArgumentException($message);
}

// DNF types (PHP 8.2+) — Disjunctive Normal Form
public function handle((Countable&Serializable)|null $data): void { ... }
```

## Error Handling

```php
// Typed exceptions — never throw generic \Exception
final class OrderNotFoundException extends \RuntimeException
{
    public function __construct(string $orderId)
    {
        parent::__construct("Order not found: {$orderId}", 404);
    }
}

final class InsufficientBalanceException extends \DomainException
{
    public function __construct(
        public readonly int $required,
        public readonly int $available,
    ) {
        parent::__construct(
            "Insufficient balance: required {$required} cents, available {$available} cents",
        );
    }
}

// Catch specific exceptions
try {
    $order = $this->orders->findById($id);
} catch (OrderNotFoundException $e) {
    return response()->json(['error' => $e->getMessage()], 404);
} catch (InsufficientBalanceException $e) {
    return response()->json([
        'error'     => 'Insufficient balance',
        'required'  => $e->required,
        'available' => $e->available,
    ], 422);
}
```

## Dependency Injection

```php
// Define interfaces for all services
interface WalletServiceInterface
{
    public function debit(User $user, Money $amount, string $reference): Transaction;
    public function credit(User $user, Money $amount, string $reference): Transaction;
    public function getBalance(User $user): Money;
}

// Concrete implementation
final class BavixWalletService implements WalletServiceInterface
{
    public function __construct(
        private readonly WalletManager $walletManager,
    ) {}

    public function debit(User $user, Money $amount, string $reference): Transaction
    {
        return $this->walletManager->withdraw($user->wallet, $amount->amount, [
            'reference' => $reference,
        ]);
    }
}
```

## Composer and Packages

```json
{
    "require": {
        "php": ">=8.3",
        "laravel/framework": "^12.0",
        "spatie/laravel-data": "^4.10",
        "spatie/laravel-permission": "^6.9",
        "bref/bref": "^2.3"
    },
    "require-dev": {
        "phpunit/phpunit": "^11",
        "phpstan/phpstan": "^1.12",
        "laravel/pint": "^1.0"
    },
    "autoload": {
        "psr-4": { "App\\": "app/" }
    }
}
```

## Testing (PHPUnit)

```php
final class WalletServiceTest extends TestCase
{
    private WalletServiceInterface&MockObject $walletMock;
    private UserService $userService;

    protected function setUp(): void
    {
        parent::setUp();
        $this->walletMock = $this->createMock(WalletServiceInterface::class);
        $this->userService = new UserService($this->walletMock);
    }

    public function test_debit_reduces_balance(): void
    {
        $user    = User::factory()->make();
        $amount  = new Money(5000, 'AUD');

        $this->walletMock
            ->expects($this->once())
            ->method('debit')
            ->with($user, $amount, $this->isType('string'))
            ->willReturn(new Transaction(/* ... */));

        $this->userService->chargeForOrder($user, $amount);
    }
}
```

## Pimcore Integration

The **Pimcore PIM** service exposes a REST API consumed by wallet-service via OAuth2 client credentials.

```php
// app/Services/PimcoreClient.php
final class PimcoreClient
{
    private string $accessToken = '';
    private \DateTimeImmutable $tokenExpiry;

    public function __construct(
        private readonly \GuzzleHttp\Client $http,
        private readonly string $baseUrl,
        private readonly string $clientId,
        private readonly string $clientSecret,
    ) {
        $this->tokenExpiry = new \DateTimeImmutable('@0');
    }

    public function getProduct(string $id): array
    {
        return $this->get("/api/v1/products/{$id}");
    }

    public function searchProducts(array $filters = [], int $page = 1): array
    {
        return $this->get('/api/v1/products', array_merge($filters, ['page' => $page]));
    }

    private function get(string $path, array $query = []): array
    {
        $response = $this->http->get($this->baseUrl . $path, [
            'headers' => ['Authorization' => 'Bearer ' . $this->getToken()],
            'query'   => $query,
        ]);
        return json_decode((string) $response->getBody(), true, 512, JSON_THROW_ON_ERROR);
    }

    private function getToken(): string
    {
        if (new \DateTimeImmutable() < $this->tokenExpiry) {
            return $this->accessToken;
        }

        $response = $this->http->post("{$this->baseUrl}/oauth/token", [
            'json' => [
                'grant_type'    => 'client_credentials',
                'client_id'     => $this->clientId,
                'client_secret' => $this->clientSecret,
                'scope'         => 'catalog:read',
            ],
        ]);

        $data = json_decode((string) $response->getBody(), true, 512, JSON_THROW_ON_ERROR);
        $this->accessToken = $data['access_token'];
        $this->tokenExpiry = new \DateTimeImmutable("+{$data['expires_in']} seconds");

        return $this->accessToken;
    }
}
```

## Static Analysis

- Use **PHPStan** at level 8+, or **Laravel Pint** for code style
- Run in CI: `vendor/bin/phpstan analyse app/ --level=8`
- Use `vendor/bin/pint` for code formatting

## Anti-Patterns to Avoid

- ❌ Missing `declare(strict_types=1)` at the top of every file
- ❌ `extract()` — obscures variable origins, pollutes scope
- ❌ `eval()` — security risk
- ❌ Global variables and global state
- ❌ Catching `\Throwable` or `\Exception` and silently swallowing errors
- ❌ `@` error suppression operator
- ❌ Type juggling with `==` — always use strict `===`
- ❌ Nested ternaries without parentheses (deprecated in PHP 8)
- ❌ Accessing array keys without `isset()` or `null coalescing`: `$arr['key'] ?? default`
- ❌ Mutable value objects — use readonly classes/properties
