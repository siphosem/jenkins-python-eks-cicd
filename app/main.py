"""TaskFlow API: a small task-tracking REST service used to demonstrate CI/CD to EKS."""

import os
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock

from fastapi import FastAPI, HTTPException, Response, status
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

APP_VERSION = os.getenv("APP_VERSION", "dev")


class Status(StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    status: Status = Status.todo


class Task(TaskIn):
    id: int
    created_at: datetime


class TaskStore:
    """Thread-safe in-memory store. Swap for a database without touching the routes."""

    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._next_id = 1
        self._lock = Lock()

    def list(self, status_filter: Status | None = None) -> list[Task]:
        tasks = list(self._tasks.values())
        if status_filter:
            tasks = [t for t in tasks if t.status == status_filter]
        return tasks

    def get(self, task_id: int) -> Task | None:
        return self._tasks.get(task_id)

    def create(self, data: TaskIn) -> Task:
        with self._lock:
            task = Task(id=self._next_id, created_at=datetime.now(UTC), **data.model_dump())
            self._tasks[task.id] = task
            self._next_id += 1
            return task

    def update(self, task_id: int, data: TaskIn) -> Task | None:
        with self._lock:
            existing = self._tasks.get(task_id)
            if existing is None:
                return None
            updated = existing.model_copy(update=data.model_dump())
            self._tasks[task_id] = updated
            return updated

    def delete(self, task_id: int) -> bool:
        with self._lock:
            return self._tasks.pop(task_id, None) is not None


def create_app(store: TaskStore | None = None) -> FastAPI:
    app = FastAPI(title="TaskFlow API", version=APP_VERSION)
    tasks = store or TaskStore()
    Instrumentator().instrument(app).expose(app, include_in_schema=False)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/version")
    def version() -> dict:
        return {"version": APP_VERSION}

    @app.get("/tasks", response_model=list[Task])
    def list_tasks(status: Status | None = None) -> list[Task]:
        return tasks.list(status)

    @app.post("/tasks", response_model=Task, status_code=201)
    def create_task(data: TaskIn) -> Task:
        return tasks.create(data)

    @app.get("/tasks/{task_id}", response_model=Task)
    def get_task(task_id: int) -> Task:
        task = tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.put("/tasks/{task_id}", response_model=Task)
    def update_task(task_id: int, data: TaskIn) -> Task:
        task = tasks.update(task_id, data)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.delete("/tasks/{task_id}", status_code=204)
    def delete_task(task_id: int) -> Response:
        if not tasks.delete(task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


app = create_app()
