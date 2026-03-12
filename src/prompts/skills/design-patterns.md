# Design Patterns Skill

You are an expert software engineer who applies established design patterns consistently.
This guide covers the patterns **actively used in the GiftBee codebase**. When implementing new
features, match these patterns — do not introduce new patterns without good reason.

---

## 1. Action / Command Pattern

**Where:** `wallet-service` backend (Laravel), `dev-ai` Python agents

Single-responsibility action classes encapsulate one piece of business logic. Controllers stay thin
by delegating to actions. Actions can optionally be dispatched to a queue (Spatie Queueable Action).

```php
// app/Actions/CreateGiftCardOrder.php
use Spatie\QueueableAction\QueueableAction;

final class CreateGiftCardOrder
{
    use QueueableAction;

    public function __construct(
        private readonly WalletServiceInterface $wallet,
        private readonly NotificationService $notifications,
    ) {}

    public function execute(CreateOrderData $data, User $buyer): Order
    {
        $order = Order::create([
            'user_id'         => $buyer->id,
            'product_id'      => $data->productId,
            'recipient_email' => $data->recipientEmail,
            'amount'          => $data->amount,
            'currency'        => $data->currency,
            'status'          => OrderStatus::Pending,
        ]);

        $this->wallet->hold($buyer, Money::of($data->amount, $data->currency), $order->id);
        $this->notifications->orderCreated($order);

        return $order;
    }
}

// Controller — thin, just validates + delegates
final class StoreOrderController extends Controller
{
    public function __invoke(StoreOrderRequest $request, CreateGiftCardOrder $action): JsonResponse
    {
        $order = $action->execute($request->toOrderData(), $request->user());
        return response()->json(new OrderResource($order), 201);
    }
}

// Queue the action when needed
app(SendGiftCardEmail::class)->onQueue('emails')->execute($order, $recipient);
```

---

## 2. Repository + Interface Pattern

**Where:** `wallet-service` (Laravel), `dev-ai` integration clients

Define an interface for data access. Bind the Eloquent implementation in the service container.
This enables easy testing with mocks and future swapping of implementations.

```php
// app/Repositories/OrderRepositoryInterface.php
interface OrderRepositoryInterface
{
    public function findById(string $id): Order;
    public function findByUser(User $user, int $page = 1): LengthAwarePaginator;
    public function save(Order $order): void;
    public function updateStatus(string $id, OrderStatus $status): void;
}

// app/Repositories/EloquentOrderRepository.php
final class EloquentOrderRepository implements OrderRepositoryInterface
{
    public function findById(string $id): Order
    {
        return Order::findOrFail($id);
    }

    public function findByUser(User $user, int $page = 1): LengthAwarePaginator
    {
        return Order::query()
            ->where('user_id', $user->id)
            ->with(['transactions'])
            ->latest()
            ->paginate(20, page: $page);
    }
}

// Bind in AppServiceProvider
$this->app->bind(OrderRepositoryInterface::class, EloquentOrderRepository::class);
```

**Python equivalent — Protocol for duck typing:**

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class SCMClient(Protocol):
    """Source Control Management client interface."""
    async def create_pull_request(self, title: str, body: str, head: str, base: str) -> str: ...
    async def list_pull_requests(self, state: str = "open") -> list[dict[str, Any]]: ...
    async def add_comment(self, pr_number: int, body: str) -> None: ...
    async def merge_pull_request(self, pr_number: int, method: str = "squash") -> None: ...
```

---

## 3. Adapter Pattern

**Where:** `dev-ai` SCM integrations — wraps MCP clients to implement a protocol

An Adapter translates the interface of an existing class (MCP client) into the interface a client
expects (`SCMClient` protocol). This allows swapping GitHub for Bitbucket with zero changes to consumers.

```python
# src/integrations/scm/github_adapter.py
from src.integrations.scm.protocol import SCMClient

class GitHubSCMAdapter:
    """Adapts the GitHub MCP client to the SCMClient protocol."""

    def __init__(self, github_client: GitHubRepoClient, repo: str, owner: str) -> None:
        self._client = github_client
        self._repo = repo
        self._owner = owner

    async def create_pull_request(self, title: str, body: str, head: str, base: str) -> str:
        result = await self._client._call(  # noqa: SLF001
            "create_pull_request",
            {"owner": self._owner, "repo": self._repo, "title": title,
             "body": body, "head": head, "base": base},
        )
        return result["html_url"]

    async def add_comment(self, pr_number: int, body: str) -> None:
        await self._client._call(  # noqa: SLF001
            "add_issue_comment",
            {"owner": self._owner, "repo": self._repo,
             "issue_number": pr_number, "body": body},
        )

# Same interface — different implementation
class BitbucketSCMAdapter:
    """Adapts the Bitbucket MCP client to the SCMClient protocol."""
    # ... same method signatures, different API calls
```

---

## 4. State Machine Pattern

**Where:** `dev-ai` — `WorkflowPipeline` for the Jira-to-PR pipeline

State is explicit (enum), transitions are declared upfront, and the pipeline
dispatches to state-specific handlers. No `if/elif` chains in the main loop.

```python
# src/workflows/states.py
class WorkflowState(str, enum.Enum):
    TICKET_RECEIVED  = "ticket_received"
    CONTEXT_LOADING  = "context_loading"
    PLANNING         = "planning"
    DELEGATING       = "delegating"
    IMPLEMENTING     = "implementing"
    TESTING          = "testing"
    AWAITING_APPROVAL = "awaiting_approval"
    PR_CREATED       = "pr_created"
    MERGED           = "merged"
    DONE             = "done"
    FAILED           = "failed"

VALID_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.PLANNING: frozenset({
        WorkflowState.DELEGATING,
        WorkflowState.FAILED,
        WorkflowState.RETRYING,
    }),
    # ...
}

# src/workflows/pipeline.py — dispatch table (not if/elif)
class WorkflowPipeline:
    _HANDLERS: dict[WorkflowState, str] = {
        WorkflowState.TICKET_RECEIVED:   "_handle_ticket_received",
        WorkflowState.PLANNING:          "_handle_planning",
        WorkflowState.DELEGATING:        "_handle_delegating",
        WorkflowState.IMPLEMENTING:      "_handle_implementing",
        WorkflowState.TESTING:           "_handle_testing",
        WorkflowState.AWAITING_APPROVAL: "_handle_approval_gate",
        WorkflowState.PR_CREATED:        "_handle_pr_created",
    }

    async def _transition(self, new_state: WorkflowState) -> None:
        allowed = VALID_TRANSITIONS.get(self._context.current_state, frozenset())
        if new_state not in allowed:
            raise InvalidTransitionError(self._context.current_state, new_state)
        self._context = self._context.model_copy(update={"current_state": new_state})
```

---

## 5. Observer Pattern

**Where:** `wallet-service` — Laravel Model Observers with `laravel-auditing`

Observers decouple side effects (cache invalidation, audit logging, notifications) from the model.
The `Auditable` trait auto-records every model change to the `audits` table.

```php
// app/Observers/OrderObserver.php
final class OrderObserver
{
    public function created(Order $order): void
    {
        Cache::forget("user:orders:{$order->user_id}");
        event(new OrderCreated($order));
    }

    public function updated(Order $order): void
    {
        if ($order->isDirty('status')) {
            Cache::forget("user:orders:{$order->user_id}");
            event(new OrderStatusChanged($order, $order->getOriginal('status')));
        }
    }
}

// Register in AppServiceProvider
Order::observe(OrderObserver::class);

// Model implements Auditable — auto-records changes
final class Order extends Model implements Auditable
{
    use AuditableTrait;

    protected array $auditInclude = ['status', 'amount', 'recipient_email'];
}
```

---

## 6. Message Bus Pattern

**Where:** `dev-ai` — inter-agent communication between Orchestrator and Workers

An in-memory async message bus built on `asyncio.Queue`. Each agent has a dedicated mailbox.
The bus routes messages by agent ID, or broadcasts to all with `to_agent='*'`.

```python
# src/agents/communication.py
class MessageBus:
    def __init__(self, maxsize: int = 1000) -> None:
        self._queues: dict[str, asyncio.Queue[AgentMessage]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, agent_id: str) -> None:
        async with self._lock:
            if agent_id not in self._queues:
                self._queues[agent_id] = asyncio.Queue(maxsize=self._maxsize)

    async def publish(self, message: AgentMessage) -> None:
        if message.to_agent == "*":
            for queue in self._queues.values():
                await queue.put(message)
        elif message.to_agent in self._queues:
            await self._queues[message.to_agent].put(message)

    async def receive(self, agent_id: str, timeout: float = 30.0) -> AgentMessage | None:
        try:
            return await asyncio.wait_for(self._queues[agent_id].get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

# Usage — orchestrator sends task to worker
await bus.publish(AgentMessage(
    from_agent=orchestrator.agent_id,
    to_agent=worker.agent_id,
    type=MessageType.TASK_ASSIGNED,
    payload=subtask.model_dump(),
))
```

---

## 7. Circuit Breaker Pattern

**Where:** `dev-ai` — wraps MCP tool calls and external HTTP calls

Prevents cascading failures. Three states: CLOSED (normal), OPEN (rejecting calls), HALF_OPEN (probing).

```python
# src/resilience/circuit_breaker.py
class CircuitState(str, Enum):
    CLOSED    = "closed"     # normal — calls pass through
    OPEN      = "open"       # failing — calls are rejected immediately
    HALF_OPEN = "half_open"  # testing — one call allowed through

class CircuitBreaker:
    def __init__(self, service: str, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:
        self.service = service
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout

    async def call(self, fn: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
        if self._state == CircuitState.OPEN:
            if time.monotonic() < self._next_attempt:
                raise CircuitOpenError(self.service, self._next_attempt - time.monotonic())
            self._state = CircuitState.HALF_OPEN

        try:
            result = await fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._state = CircuitState.OPEN
            self._next_attempt = time.monotonic() + self._recovery_timeout

    def _on_success(self) -> None:
        self._failures = 0
        self._state = CircuitState.CLOSED
```

---

## 8. Strategy Pattern

**Where:** `dev-ai` — skill detection strategies; agent model selection

A family of algorithms (strategies) are interchangeable at runtime.

```python
# SkillDetector uses two strategies: Jira keyword scan and file pattern matching
class SkillDetector:
    def detect_from_jira(self, issue_data: dict[str, object]) -> DetectionResult:
        """Strategy 1: keyword matching in Jira text."""
        ...

    def detect_from_repo(self, file_list: list[str]) -> DetectionResult:
        """Strategy 2: file pattern matching in repo tree."""
        ...

    def merge_results(self, *results: DetectionResult) -> DetectionResult:
        """Combine multiple strategy results."""
        ...

# Model selection strategy — Bedrock vs Claude SDK
if use_bedrock:
    client: LLMClient = BedrockClient(model=config.orchestrator_model)
else:
    client = ClaudeSDKClient(model=config.orchestrator_model)
agent = Orchestrator(claude_sdk_client=client, ...)
```

---

## 9. Page Object Model (POM)

**Where:** `store-front`, `admin-portal` — Playwright E2E tests in `e2e/pages/`

Each page or significant UI section has a class that encapsulates selectors and interactions.
Tests interact with pages through the object, not raw selectors.

```typescript
// e2e/pages/CheckoutPage.ts
import { type Page, type Locator } from '@playwright/test';

export class CheckoutPage {
  readonly recipientEmailInput: Locator;
  readonly amountSelect: Locator;
  readonly messageTextarea: Locator;
  readonly proceedButton: Locator;
  readonly successBanner: Locator;

  constructor(private readonly page: Page) {
    this.recipientEmailInput = page.getByLabel('Recipient email');
    this.amountSelect       = page.getByRole('combobox', { name: 'Amount' });
    this.messageTextarea    = page.getByLabel('Personal message');
    this.proceedButton      = page.getByRole('button', { name: 'Proceed to payment' });
    this.successBanner      = page.getByRole('alert', { name: /order confirmed/i });
  }

  async goto() {
    await this.page.goto('/checkout');
  }

  async fillGiftDetails(email: string, amount: string, message?: string) {
    await this.recipientEmailInput.fill(email);
    await this.amountSelect.selectOption(amount);
    if (message) await this.messageTextarea.fill(message);
  }

  async submitOrder() {
    await this.proceedButton.click();
    await this.successBanner.waitFor();
  }
}
```

---

## 10. Factory Pattern

**Where:** `dev-ai` — `create_webhook_app()`, `get_default_registry()`, Laravel model factories

Factories encapsulate object creation. They are used for:
- Creating configured FastAPI apps with dependencies injected
- Creating registry singletons with lazy caching
- Laravel model factories for test data

```python
# Factory function — creates app with dependencies
def create_webhook_app(
    approval_flow: ApprovalFlow,
    conversation_handler: AgentConversationHandler,
) -> FastAPI:
    app = FastAPI(title="dev-ai webhook server")

    @app.post("/webhooks/teams/approval")
    async def handle_approval(payload: TeamsCardActionPayload) -> dict[str, str]:
        approval_flow.resolve(payload.request_id, payload.approved, payload.responder)
        return {"status": "ok"}

    return app

# Registry singleton with lru_cache
@lru_cache(maxsize=1)
def get_default_registry() -> SkillRegistry:
    return SkillRegistry()
```

```php
// Laravel model factory for tests
final class OrderFactory extends Factory
{
    protected $model = Order::class;

    public function definition(): array
    {
        return [
            'user_id'         => User::factory(),
            'product_id'      => Product::factory(),
            'recipient_email' => $this->faker->safeEmail(),
            'amount'          => $this->faker->numberBetween(1000, 50000),
            'currency'        => 'AUD',
            'status'          => OrderStatus::Pending->value,
        ];
    }

    public function delivered(): static
    {
        return $this->state(['status' => OrderStatus::Delivered->value]);
    }
}

// Usage in tests
$order = Order::factory()->delivered()->create();
```

---

## 11. Dependency Injection

**Where:** Every layer — constructor injection is the default everywhere

Never use `new SomeService()` inside a class body. Declare dependencies in the constructor and let the container resolve them.

```php
// Laravel — constructor injection; container resolves automatically
final class OrderService
{
    public function __construct(
        private readonly OrderRepositoryInterface $orders,
        private readonly WalletServiceInterface   $wallet,
        private readonly EventDispatcherInterface $events,
    ) {}
}
```

```python
# Python — pass dependencies explicitly; use default factories for optional ones
class WorkflowPipeline:
    def __init__(
        self,
        *,
        orchestrator: Orchestrator,
        mcp_manager: MCPManager,
        approval_flow: ApprovalFlow | None = None,
        repo_registry: RepoRegistry | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._mcp = mcp_manager
        self._approval_flow = approval_flow
        self._repo_registry = repo_registry or get_default_repo_registry()
```

---

## Quick Reference

| Pattern | Where used | Purpose |
|---------|-----------|---------|
| Action/Command | Laravel controllers, agents | Encapsulate one business operation |
| Repository | wallet-service, SCM clients | Decouple data access from domain |
| Adapter | SCM clients (GitHub/Bitbucket) | Translate external API to internal interface |
| State Machine | WorkflowPipeline | Explicit state + validated transitions |
| Observer | Laravel model side effects | Decouple events from persistence |
| Message Bus | Orchestrator↔Worker | Async in-process message passing |
| Circuit Breaker | MCP/external calls | Fail fast, prevent cascading failures |
| Strategy | Skill detection, model selection | Swappable algorithms |
| Page Object Model | Playwright E2E tests | Encapsulate UI interactions |
| Factory | App/registry creation | Encapsulate object construction |
| Dependency Injection | Everywhere | Testability, loose coupling |
