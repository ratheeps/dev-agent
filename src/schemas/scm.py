"""SCM-agnostic pull request and branch models."""

from __future__ import annotations

from pydantic import BaseModel


class SCMBranch(BaseModel):
    name: str
    sha: str
    repo: str


class SCMPullRequest(BaseModel):
    number: int
    url: str
    title: str
    body: str
    head_branch: str
    base_branch: str
    repo: str
    state: str = "open"
    reviewers: list[str] = []
