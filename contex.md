Here is a summary of the core concepts and architecture for building this multi-agent system using Claude Code and AWS:

**1. Agent Orchestration (Claude 4.6 Opus & Sonnet)**
To achieve high reasoning without burning through your budget, the system utilizes the "Agent Teams" feature within Claude Code. You can set Claude 4.6 Opus as the lead architect to ingest the project context and break down the Jira tickets into a phased implementation plan. Opus then spawns multiple Claude 4.6 Sonnet instances as parallel "teammates" to execute the code. Sonnet 4.6 is ideal for implementation because it matches Opus in daily coding tasks but operates much faster and at a significantly lower cost.

**2. Low-Cost Infrastructure & Persistent Memory**
To make the system 100% production-ready and cost-effective, the agents are hosted on Amazon Bedrock AgentCore Runtime. Unlike AWS Lambda (which has execution time limits) or persistent ECS instances (which charge you even when idle), AgentCore only bills for active CPU consumption. When the agent is waiting on an API response from GitHub or Jira, you aren't charged for the compute time.

To ensure the agents retain your "golden rules" and project context, the architecture uses Bedrock AgentCore Memory backed by Amazon DynamoDB. This provides short-term memory for active tasks, episodic memory to remember how past bugs were fixed, and long-term semantic memory to permanently store your coding preferences and architectural guidelines.

**3. Universal Tool Integration (MCP)**
Instead of writing custom API wrappers, the system relies on the Model Context Protocol (MCP) to standardize how agents interact with your enterprise stack :

* **Jira & Confluence:** The project management agent uses the Atlassian Rovo MCP server to analyze Confluence requirement pages and automatically generate structured Jira epics, sub-tasks, and timelines.


* **Figma:** The Figma MCP server allows the dev agents to ingest design components, read exact spacing/color variables, and map them directly to your codebase's UI components.


* **Bitbucket & GitHub:** The source control MCPs enable the agents to clone repositories, read massive code diffs, execute commits, and automatically open pull requests.


* **User Creation:** For provisioning users in Jira, GitHub, or Bitbucket for the agents themselves, you can utilize the respective platforms' SCIM provisioning APIs or Admin REST APIs to programmatically create and permission the agent accounts.



**4. Automated PR Loops & Chat Integration**
Once the Sonnet agents implement the code and create a Pull Request, human developers can review the work. If you leave a comment on the PR, you can use Claude Code's `/loop` command to have the agent run continuously in the background; it will automatically read your PR comment, rewrite the code, fix any failing tests, and push the new commit.

To minimize human interaction while maintaining safety, the system integrates the Slack or Microsoft Teams MCP servers. If the agent is unsure about a design choice or needs permission to merge a PR, it will pause execution and send a direct message to a human engineer via Slack/Teams to request approval before proceeding.
