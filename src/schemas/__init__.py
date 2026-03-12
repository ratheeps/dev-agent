"""Public schema re-exports."""

from src.schemas.atlassian import (
    ConfluencePage,
    ConfluencePageBody,
    ConfluenceSearchResult,
    ConfluenceUser,
    JiraComment,
    JiraCreateIssueRequest,
    JiraCreateIssueResponse,
    JiraIssue,
    JiraIssueFields,
    JiraIssueType,
    JiraPriority,
    JiraSearchResult,
    JiraStatus,
    JiraTransition,
    JiraUser,
)
from src.schemas.figma import (
    FigmaColor,
    FigmaComponent,
    FigmaFile,
    FigmaNode,
    FigmaStyle,
)
from src.schemas.github import (
    GitHubBranch,
    GitHubCreatePullRequestRequest,
    GitHubFileContent,
    GitHubPullRequest,
    GitHubPullRequestComment,
    GitHubPushFileRequest,
    GitHubRepo,
    GitHubUser,
)
from src.schemas.teams import (
    TeamsApprovalRequest,
    TeamsApprovalResponse,
    TeamsMessageResponse,
)

__all__ = [
    # Atlassian / Jira
    "ConfluencePage",
    "ConfluencePageBody",
    "ConfluenceSearchResult",
    "ConfluenceUser",
    "JiraComment",
    "JiraCreateIssueRequest",
    "JiraCreateIssueResponse",
    "JiraIssue",
    "JiraIssueFields",
    "JiraIssueType",
    "JiraPriority",
    "JiraSearchResult",
    "JiraStatus",
    "JiraTransition",
    "JiraUser",
    # Figma
    "FigmaColor",
    "FigmaComponent",
    "FigmaFile",
    "FigmaNode",
    "FigmaStyle",
    # GitHub
    "GitHubBranch",
    "GitHubCreatePullRequestRequest",
    "GitHubFileContent",
    "GitHubPullRequest",
    "GitHubPullRequestComment",
    "GitHubPushFileRequest",
    "GitHubRepo",
    "GitHubUser",
    # Teams
    "TeamsApprovalRequest",
    "TeamsApprovalResponse",
    "TeamsMessageResponse",
]
