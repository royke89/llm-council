from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_review_preview_lists_files(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "x.js").write_text("x", encoding="utf-8")

    resp = client.post("/api/review/preview", json={"path": str(tmp_path)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["file_count"] == 1
    assert "main.py" in data["files"]
    assert not any(f.startswith("node_modules") for f in data["files"])
    assert data["est_tokens"] > 0
    assert isinstance(data["est_cost"], (int, float))


def test_review_preview_bad_path():
    resp = client.post("/api/review/preview",
                       json={"path": "Z:/no/such/dir/xyz123"})
    assert resp.status_code == 200
    assert "error" in resp.json()
