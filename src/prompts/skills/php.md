# PHP Skill

You are an expert PHP developer. Apply these guidelines for modern, idiomatic PHP 8.x code.

## PHP Version Target

- Target **PHP 8.2+** unless the project specifies otherwise
- Use the latest language features: named arguments, fibers, enums, readonly properties, match expressions

## PSR Standards

Follow PHP-FIG PSR standards strictly:
- **PSR-1**: Basic coding standard (namespaces, class/method naming)
- **PSR-4**: Autoloading (one class per file, namespace matches directory structure)
- **PSR-12**: Extended coding style guide
- **PSR-7/15**: HTTP message interfaces and middleware (for HTTP applications)

## Namespace and Autoloading

```php
<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\User;
use App\Repositories\UserRepositoryInterface;
use App\Exceptions\UserNotFoundException;

class UserService
{
    public function __construct(
        private readonly UserRepositoryInterface $userRepository,
    ) {}
}
```

- Always declare `declare(strict_types=1);` at the top of every file
- Use `use` statements for full class names — never use global namespace inside namespaced code

## Modern PHP 8.x Features

```php
// Enums (PHP 8.1+)
enum Status: string
{
    case Active = 'active';
    case Inactive = 'inactive';
    case Pending = 'pending';
}

// Readonly properties (PHP 8.1+)
class User
{
    public function __construct(
        public readonly string $id,
        public readonly string $email,
        public string $name,
    ) {}
}

// Match expression (PHP 8.0+)
$result = match($status) {
    Status::Active => 'User is active',
    Status::Inactive => 'User is inactive',
    default => 'Unknown status',
};

// Named arguments (PHP 8.0+)
$user = new User(id: '123', email: 'test@example.com', name: 'Alice');

// Nullsafe operator (PHP 8.0+)
$city = $user?->getAddress()?->getCity();

// First-class callable syntax (PHP 8.1+)
$fn = strlen(...);
$lengths = array_map(strlen(...), $strings);
```

## Type System

```php
// Always use type declarations
function getUserById(string $id): ?User
{
    // ...
}

// Union types (PHP 8.0+)
function process(int|string $input): void { ... }

// Intersection types (PHP 8.1+)
function save(Serializable&Countable $data): void { ... }

// Return never for functions that always throw or exit
function fail(string $message): never
{
    throw new \InvalidArgumentException($message);
}
```

## Error Handling

```php
// Use typed exceptions
class UserNotFoundException extends \RuntimeException
{
    public function __construct(string $userId)
    {
        parent::__construct("User not found: {$userId}");
    }
}

// Don't use @ error suppression
// Don't catch \Exception broadly — catch specific exceptions
try {
    $user = $this->userRepository->findById($id);
} catch (UserNotFoundException $e) {
    // handle specifically
} finally {
    // cleanup
}
```

## Dependency Injection

- Use **constructor injection** as the default (not property or setter injection)
- Define **interfaces** for services that may have multiple implementations
- Use a **DI container** (Symfony, PHP-DI, or Laravel's service container)

```php
interface UserRepositoryInterface
{
    public function findById(string $id): User;
    public function save(User $user): void;
    public function delete(string $id): void;
}
```

## Composer and Packages

```json
{
    "require": {
        "php": ">=8.2",
        "psr/http-message": "^2.0",
        "psr/container": "^2.0"
    },
    "require-dev": {
        "phpunit/phpunit": "^11",
        "phpstan/phpstan": "^1.10",
        "squizlabs/php_codesniffer": "^3.8"
    },
    "autoload": {
        "psr-4": { "App\\": "src/" }
    }
}
```

## Testing (PHPUnit)

```php
final class UserServiceTest extends TestCase
{
    private UserRepositoryInterface&MockObject $repositoryMock;
    private UserService $userService;

    protected function setUp(): void
    {
        $this->repositoryMock = $this->createMock(UserRepositoryInterface::class);
        $this->userService = new UserService($this->repositoryMock);
    }

    public function testFindUserById(): void
    {
        $expected = new User(id: '1', email: 'a@b.com', name: 'Alice');
        $this->repositoryMock
            ->expects($this->once())
            ->method('findById')
            ->with('1')
            ->willReturn($expected);

        $result = $this->userService->findById('1');
        $this->assertSame($expected, $result);
    }
}
```

## Static Analysis

- Use **PHPStan** at level 8 or max, or **Psalm** at level 1
- Run static analysis in CI: `vendor/bin/phpstan analyse src/ --level=8`

## Anti-Patterns to Avoid

- ❌ `extract()` — obscures variable origins and pollutes scope
- ❌ `eval()` — security risk and debugging nightmare
- ❌ Global variables and global state
- ❌ Catching `\Throwable` or `\Exception` and silently swallowing errors
- ❌ `mysql_*` functions — use PDO or a query builder
- ❌ Nested ternaries without parentheses (deprecated in PHP 8)
- ❌ Type juggling with `==` — always use strict comparison `===`
