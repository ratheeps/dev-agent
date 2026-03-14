# Architectural & Operational Improvements for "mason"

To improve the quality, efficiency, and cost-effectiveness of this multi-agent system, several architectural and operational enhancements can be implemented:

### 1. Leverage LLM Prompt Caching (Massive Cost/Speed Improvement)
Anthropic and AWS Bedrock support **Prompt Caching**. Since your agents likely share massive amounts of context (e.g., system prompts, architectural guidelines from DynamoDB, large API schemas, or the full file tree), you can cache these prefixes.
* **How to implement:** Ensure your `claude_sdk_client.py` and `bedrock_client.py` structure the API calls to place static context (like `orchestrator_system.md` and repository guidelines) at the beginning of the prompt and mark them as cacheable.
* **Impact:** This can reduce input token costs by up to 90% and significantly decrease time-to-first-token (TTFT) for recurring tasks.

### 2. Introduce a "Router" or "Triage" Agent (Cost Optimization)
Currently, it seems Claude Opus (expensive) acts as the lead architect for breaking down *every* ticket. Not all tasks require Opus-level reasoning.
* **How to implement:** Introduce a fast, cheap model (like Claude 3.5 Haiku) in `src/agents/router.py` to triage incoming webhooks/tickets.
  * If it's a simple bug fix (e.g., "Fix typo in button"), Haiku assigns it directly to a Sonnet worker.
  * If it's a complex epic (e.g., "Implement new RBAC system"), Haiku routes it to Opus for architectural breakdown.
* **Impact:** Saves Opus calls for tasks that actually need deep architectural reasoning.

### 3. Agentic Sandboxing & Local Verification (Output Quality)
Currently, if an agent pushes a PR and waits for human feedback or a CI pipeline failure, the feedback loop is slow.
* **How to implement:** Give the Sonnet worker agents access to a secure execution sandbox (e.g., using Docker or a service like E2B). Provide tools that allow the agent to run `ruff check`, `mypy`, and `pytest` *before* creating the Pull Request.
* **Impact:** The agent can self-correct syntax errors, type errors, and failing tests autonomously. The PRs submitted will be much higher quality and require less human intervention.

### 4. Upgrade Memory from DynamoDB to a Vector Database
The `contex.md` mentions DynamoDB for episodic and semantic memory. While DynamoDB is great for Key-Value retrieval, it is poor for semantic search (e.g., "Have we fixed a bug similar to this database deadlock before?").
* **How to implement:** Integrate a Vector Database (like Qdrant, Pinecone, or AWS OpenSearch with vector support) alongside or instead of DynamoDB for `src/memory/semantic.py` and `src/memory/episodic.py`.
* **Impact:** Agents can dynamically retrieve only the most relevant past PRs, bug fixes, and architectural rules based on the *meaning* of the current task, keeping the context window small (efficiency) and highly relevant (quality).

### 5. Abstract Syntax Tree (AST) & Codebase Mapping Tools
When a codebase grows, having an agent read entire files or search via naive grep can eat up context tokens rapidly and lead to hallucinations.
* **How to implement:** Create MCP tools that allow the agent to query the codebase at a structural level (e.g., using Tree-sitter).
  * `get_function_signature(function_name)`
  * `find_usages(class_name)`
  * `get_file_outline(file_path)`
* **Impact:** The agent only reads the specific chunks of code it needs to modify, drastically reducing input tokens and improving the accuracy of edits.

### 6. Implement a "Critic" Phase (Self-Reflection)
Before Opus finalizes a plan or Sonnet finalizes a PR, implement an automated review step.
* **How to implement:** Add a `review_loop.py` step where a separate Sonnet agent is given the original Jira ticket, the generated code diff, and a rubric (e.g., "Are there tests? Does it handle edge cases?"). The Critic agent outputs a pass/fail. If it fails, the Worker must revise.
* **Impact:** Acts as an automated code reviewer, catching logic gaps before a human ever sees the PR.

### 7. Circuit Breakers for Token/Cost Limits
Autonomous agents can occasionally get stuck in loops (e.g., repeatedly failing to fix a test and retrying 50 times), which can burn through your API budget.
* **How to implement:** Utilize your existing `src/resilience/circuit_breaker.py` to monitor token usage and retry counts per task. If a task exceeds a specific budget or attempt threshold, pause execution, save the state to memory, and send a Slack/Teams message asking a human to unblock it.
