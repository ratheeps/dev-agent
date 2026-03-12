"""Pydantic models for Figma data structures."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FigmaColor(BaseModel):
    """RGBA colour value."""

    r: float = 0.0
    g: float = 0.0
    b: float = 0.0
    a: float = 1.0


class FigmaStyle(BaseModel):
    """Figma style entry (text, fill, effect, or grid)."""

    key: str = ""
    name: str = ""
    style_type: str = Field("", alias="styleType")
    description: str = ""

    model_config = {"populate_by_name": True}


class FigmaComponent(BaseModel):
    """Figma component metadata."""

    key: str = ""
    name: str = ""
    description: str = ""
    containing_frame: dict[str, Any] = Field(default_factory=dict, alias="containingFrame")

    model_config = {"populate_by_name": True}


class FigmaNode(BaseModel):
    """Generic Figma document node."""

    id: str
    name: str = ""
    type: str = ""
    children: list[FigmaNode] | None = None
    absolute_bounding_box: dict[str, float] | None = Field(
        None, alias="absoluteBoundingBox"
    )
    fills: list[dict[str, Any]] = Field(default_factory=list)
    strokes: list[dict[str, Any]] = Field(default_factory=list)
    style: dict[str, Any] = Field(default_factory=dict)
    characters: str | None = None
    """Text content if the node is a TEXT type."""

    model_config = {"populate_by_name": True}


class FigmaFile(BaseModel):
    """Top-level Figma file representation."""

    name: str = ""
    last_modified: str = Field("", alias="lastModified")
    version: str = ""
    document: FigmaNode | None = None
    components: dict[str, FigmaComponent] = Field(default_factory=dict)
    styles: dict[str, FigmaStyle] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
