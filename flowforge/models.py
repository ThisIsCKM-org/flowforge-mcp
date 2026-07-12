from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Priority = Literal["low", "medium", "high"]
WorkUnitType = Literal["feature", "milestone", "deliverable", "initiative"]


class CreateProject(BaseModel):
    name: str
    key: str | None = None
    description: str | None = None
    template_id: int | None = None


class UpdateProject(BaseModel):
    name: str | None = None
    key: str | None = None
    description: str | None = None


class CreateProjectTemplate(BaseModel):
    name: str
    description: str | None = None
    statuses: list[dict] = Field(default_factory=list)
    starter_tasks: list[dict] = Field(default_factory=list)


class CreateWorkUnit(BaseModel):
    project_id: int
    title: str
    key: str | None = None
    description: str | None = None
    type: WorkUnitType = "feature"
    status: str | None = None
    priority: Priority = "medium"
    start_date: str | None = None
    target_date: str | None = None
    tags: list[str] = Field(default_factory=list)


class UpdateWorkUnit(BaseModel):
    title: str | None = None
    key: str | None = None
    description: str | None = None
    type: WorkUnitType | None = None
    status: str | None = None
    priority: Priority | None = None
    start_date: str | None = None
    target_date: str | None = None
    tags: list[str] | None = None


class CreateTask(BaseModel):
    project_id: int
    title: str
    key: str | None = None
    description: str | None = None
    work_unit_id: int | None = None
    status: str = "Todo"
    helpdesk_ref_id: str | None = None
    priority: Priority = "medium"
    assignee: str | None = None
    due_date: str | None = None
    position: int | None = None
    tags: list[str] = Field(default_factory=list)


class UpdateTask(BaseModel):
    title: str | None = None
    key: str | None = None
    description: str | None = None
    work_unit_id: int | None = None
    status: str | None = None
    helpdesk_ref_id: str | None = None
    priority: Priority | None = None
    assignee: str | None = None
    due_date: str | None = None
    position: int | None = None
    tags: list[str] | None = None


class CreateComment(BaseModel):
    task_id: int
    content: str
    author: str | None = None


class UpdateComment(BaseModel):
    content: str

class CreateAttachment(BaseModel):
    task_id: int | None = None
    comment_id: int | None = None
    filename: str
    content_type: str
    data_base64: str
    alt_text: str | None = None
