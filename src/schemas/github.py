"""Pydantic models for GitHub data structures."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GitHubUser(BaseModel):
    """GitHub user / actor."""

    login: str
    id: int = 0
    avatar_url: str = Field("", alias="avatar_url")
    html_url: str = Field("", alias="html_url")

    model_config = {"populate_by_name": True}


class GitHubRepo(BaseModel):
    """GitHub repository metadata."""

    id: int
    name: str
    full_name: str = Field("", alias="full_name")
    private: bool = False
    default_branch: str = Field("main", alias="default_branch")
    html_url: str = Field("", alias="html_url")
    clone_url: str = Field("", alias="clone_url")
    description: str | None = None

    model_config = {"populate_by_name": True}


class GitHubBranch(BaseModel):
    """GitHub branch reference."""

    ref: str
    sha: str
    url: str = ""


class GitHubPullRequest(BaseModel):
    """GitHub pull request."""

    id: int
    number: int
    title: str
    body: str | None = None
    state: str = "open"
    html_url: str = Field("", alias="html_url")
    head: GitHubBranch | None = None
    base: GitHubBranch | None = None
    user: GitHubUser | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    merged_at: datetime | None = None

    model_config = {"populate_by_name": True}


class GitHubPullRequestComment(BaseModel):
    """Comment on a GitHub pull request."""

    id: int
    body: str = ""
    user: GitHubUser | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    path: str | None = None
    position: int | None = None

    model_config = {"populate_by_name": True}


class GitHubFileContent(BaseModel):
    """Response from creating/updating a file via the Contents API."""

    sha: str = ""
    path: str = ""
    html_url: str = Field("", alias="html_url")

    model_config = {"populate_by_name": True}


class GitHubCreatePullRequestRequest(BaseModel):
    """Payload for creating a pull request."""

    owner: str
    repo: str
    title: str
    body: str = ""
    head: str
    base: str = "main"


class GitHubPushFileRequest(BaseModel):
    """Payload for creating or updating a file in a repo."""

    owner: str
    repo: str
    path: str
    content: str
    message: str
    branch: str = "main"
    sha: str | None = None
    """SHA of the existing file blob when updating; omit for new files."""
