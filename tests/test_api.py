import pytest
from fastapi.testclient import TestClient

from app.main import TaskStore, create_app


@pytest.fixture
def client():
    return TestClient(create_app(TaskStore()))


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_version(client):
    assert "version" in client.get("/version").json()


def test_create_and_get_task(client):
    created = client.post("/tasks", json={"title": "Write README"}).json()
    assert created["id"] == 1
    assert created["status"] == "todo"
    assert client.get("/tasks/1").json()["title"] == "Write README"


def test_list_filters_by_status(client):
    client.post("/tasks", json={"title": "a"})
    client.post("/tasks", json={"title": "b", "status": "done"})
    done = client.get("/tasks", params={"status": "done"}).json()
    assert [t["title"] for t in done] == ["b"]
    assert len(client.get("/tasks").json()) == 2


def test_update_task(client):
    client.post("/tasks", json={"title": "draft"})
    updated = client.put("/tasks/1", json={"title": "final", "status": "in_progress"}).json()
    assert updated["title"] == "final"
    assert updated["status"] == "in_progress"


def test_delete_task(client):
    client.post("/tasks", json={"title": "temp"})
    assert client.delete("/tasks/1").status_code == 204
    assert client.get("/tasks/1").status_code == 404


@pytest.mark.parametrize("method,path", [("get", "/tasks/99"), ("delete", "/tasks/99")])
def test_missing_task_returns_404(client, method, path):
    assert getattr(client, method)(path).status_code == 404


def test_update_missing_task_returns_404(client):
    assert client.put("/tasks/99", json={"title": "x"}).status_code == 404


@pytest.mark.parametrize(
    "payload", [{}, {"title": ""}, {"title": "x" * 121}, {"title": "x", "status": "blocked"}]
)
def test_validation_errors(client, payload):
    assert client.post("/tasks", json=payload).status_code == 422


def test_metrics_exposed(client):
    client.get("/healthz")
    assert "http_requests_total" in client.get("/metrics").text
