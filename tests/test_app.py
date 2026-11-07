"""Exercise the local HTTP API and persistence without loading an AI model."""
from copy import deepcopy
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config
from app.advisor import AnalysisUnavailable
from app.main import create_app


PREDICTIONS = [
    {"label": "Tomato___Early_blight", "score": 0.91, "kind": "disease", "model": "test-classifier"}
]


def report(category="disease", needs_expert=False):
    return {
        "plant": "Tomato",
        "issue": "Possible early blight",
        "category": category,
        "summary": "Lower leaves show dark patches.",
        "observations": ["Dark patches on a leaf"],
        "possible_causes": ["Early blight"],
        "immediate_actions": ["Check other leaves."],
        "treatment": ["Water at the base."],
        "prevention": ["Provide airflow."],
        "uncertainty": "A photograph does not confirm the cause.",
        "needs_expert": needs_expert,
        "sources": [],
    }


class FakeVision:
    def __init__(self):
        self.calls = []
        self.closed = False

    def status(self):
        return {"available": True, "models": [{"name": "test-classifier", "kind": "disease"}]}

    def classify(self, path):
        # Verify the analyzer receives a decodable server-side image.
        with Image.open(path) as image:
            assert image.format == "JPEG"
            assert image.mode == "RGB"
        self.calls.append(path)
        return deepcopy(PREDICTIONS)

    def close(self):
        self.closed = True


class FakeAdvisor:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else report()
        self.error = error
        self.calls = []
        self.closed = False

    async def status(self):
        return {"available": True, "model": "test-text", "vision_model": "test-vision", "models": ["test-vision"]}

    async def analyze(self, path, predictions, crop, notes):
        self.calls.append({"path": path, "predictions": predictions, "crop": crop, "notes": notes})
        if self.error:
            raise self.error
        return deepcopy(self.result), "MediaPipe + Ollama vision", "test-vision"

    async def close(self):
        self.closed = True


def image_bytes(size=(960, 640), image_format="PNG"):
    output = BytesIO()
    image = Image.new("RGB", size, color=(62, 140, 68))
    image.save(output, format=image_format)
    return output.getvalue()


def upload(client, image=None, **kwargs):
    return client.post(
        "/api/scans",
        files={"file": ("leaf.png", image if image is not None else image_bytes(), "image/png")},
        **kwargs,
    )


@pytest.fixture
def session(tmp_path):
    vision = FakeVision()
    advisor = FakeAdvisor()
    app = create_app(tmp_path, vision=vision, advisor=advisor)
    with TestClient(app) as client:
        yield client, vision, advisor, tmp_path
    assert vision.closed
    assert advisor.closed


def test_upload_persists_report_and_normalized_images(session):
    client, vision, advisor, directory = session
    response = upload(client, data={"crop": "  Tomato  ", "notes": "  Spots appeared yesterday.  "})
    assert response.status_code == 201
    scan = response.json()
    assert scan["status"] == "complete"
    assert scan["crop"] == "Tomato"
    assert scan["notes"] == "Spots appeared yesterday."
    assert scan["report"] == report()
    assert scan["predictions"] == PREDICTIONS
    assert scan["model"] == "test-vision"
    assert scan["created_at"]
    assert advisor.calls[0]["crop"] == "Tomato"
    assert len(vision.calls) == 1
    assert (directory / "history.sqlite3").is_file()

    for key, max_dimension in (("image_url", 1800), ("thumbnail_url", 480)):
        image_response = client.get(scan[key])
        assert image_response.status_code == 200
        assert image_response.headers["content-type"] == "image/jpeg"
        with Image.open(BytesIO(image_response.content)) as image:
            assert image.format == "JPEG"
            assert max(image.size) <= max_dimension
            assert image.width > image.height
    assert client.get("/api/scans").json() == {"items": [scan], "total": 1}
    assert client.get(f"/api/scans/{scan['id']}").json() == scan


@pytest.mark.parametrize(
    "invalid_image",
    [b"not an image", image_bytes(size=(12, 64)), image_bytes(image_format="GIF"), image_bytes()[:30]],
    ids=["non-image", "too-small", "unsupported-format", "truncated"],
)
def test_bad_uploads_never_create_history_or_call_models(session, invalid_image):
    client, vision, advisor, directory = session
    response = upload(client, invalid_image)
    assert response.status_code == 422
    assert client.get("/api/scans").json() == {"items": [], "total": 0}
    assert list((directory / "uploads").iterdir()) == []
    assert not vision.calls
    assert not advisor.calls


@pytest.mark.parametrize("request_size", [2049, 70_000], ids=["file-limit", "request-limit"])
def test_oversize_uploads_leave_no_records(session, monkeypatch, request_size):
    client, vision, advisor, directory = session
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 2048)
    response = upload(client, b"x" * request_size)
    assert response.status_code == 413
    assert client.get("/api/scans").json()["total"] == 0
    assert list((directory / "uploads").iterdir()) == []
    assert not vision.calls
    assert not advisor.calls


def test_history_and_image_survive_a_server_restart(tmp_path):
    with TestClient(create_app(tmp_path, FakeVision(), FakeAdvisor())) as client:
        original = upload(client).json()
        saved_photo = client.get(original["image_url"]).content

    # Construct a fresh application, storage object, and model adapters.
    with TestClient(create_app(tmp_path, FakeVision(), FakeAdvisor())) as restarted:
        assert restarted.get("/api/scans").json() == {"items": [original], "total": 1}
        assert restarted.get(original["image_url"]).content == saved_photo
        assert restarted.get(f"/api/scans/{original['id']}").json()["report"] == report()


def test_failed_analysis_is_saved_and_can_be_retried(session):
    client, _, advisor, directory = session
    advisor.error = AnalysisUnavailable("Ollama is unavailable for this test.")
    response = upload(client)
    assert response.status_code == 201
    failed = response.json()
    assert failed["status"] == "error"
    assert failed["error"] == "Ollama is unavailable for this test."
    assert failed["report"] is None
    assert client.get(failed["image_url"]).status_code == 200

    advisor.error = None
    retried = client.post(f"/api/scans/{failed['id']}/retry")
    assert retried.status_code == 200
    scan = retried.json()
    assert scan["id"] == failed["id"]
    assert scan["created_at"] == failed["created_at"]
    assert scan["status"] == "complete"
    assert scan["error"] is None
    assert scan["report"] == report()
    assert client.get("/api/scans").json()["total"] == 1
    assert len(list((directory / "uploads").glob("*.jpg"))) == 2


def test_unexpected_model_error_keeps_image_and_hides_internal_detail(session):
    client, _, advisor, _ = session
    advisor.error = RuntimeError("internal secret debug detail")
    response = upload(client)
    assert response.status_code == 201
    failed = response.json()
    assert failed["status"] == "error"
    assert "internal secret" not in failed["error"]
    assert client.get(failed["thumbnail_url"]).status_code == 200


def test_specialist_failure_still_uses_working_vision_advisor(session, monkeypatch):
    client, vision, advisor, _ = session

    def broken_classifier(path):
        raise RuntimeError("Specialist model could not evaluate this image")

    monkeypatch.setattr(vision, "classify", broken_classifier)
    response = upload(client)
    assert response.status_code == 201
    scan = response.json()
    assert scan["status"] == "complete"
    assert scan["error"] is None
    assert scan["predictions"] == []
    assert scan["report"] == report()
    assert len(advisor.calls) == 1
    assert advisor.calls[0]["predictions"] == []
    assert client.get(f"/api/scans/{scan['id']}").json() == scan


def test_delete_removes_history_and_both_image_files(session):
    client, _, _, directory = session
    scan = upload(client).json()
    response = client.delete(f"/api/scans/{scan['id']}")
    assert response.status_code == 204
    assert not response.content
    assert client.get("/api/scans").json()["total"] == 0
    assert list((directory / "uploads").iterdir()) == []
    for url in (f"/api/scans/{scan['id']}", scan["image_url"], scan["thumbnail_url"]):
        assert client.get(url).status_code == 404
    assert client.delete(f"/api/scans/{scan['id']}").status_code == 404


def test_non_plant_result_discards_closed_set_leaf_predictions(session):
    client, _, advisor, _ = session
    advisor.result = report(category="not_plant")
    scan = upload(client).json()
    # Candidates did reach the advisor, but must not be shown as plant evidence.
    assert advisor.calls[0]["predictions"] == PREDICTIONS
    assert scan["predictions"] == []
    assert client.get(f"/api/scans/{scan['id']}").json()["predictions"] == []


@pytest.mark.parametrize(
    "category, needs_expert", [("uncertain", False), ("disease", True)]
)
def test_uncertain_findings_are_marked_for_review(session, category, needs_expert):
    client, _, advisor, _ = session
    advisor.result = report(category=category, needs_expert=needs_expert)
    assert upload(client).json()["status"] == "needs_review"


def test_cross_origin_browser_cannot_create_retry_or_delete_scans(session):
    client, _, advisor, _ = session
    foreign = {"Origin": "https://unrelated.example"}
    assert upload(client, headers=foreign).status_code == 403
    assert client.get("/api/scans").json()["total"] == 0
    assert not advisor.calls

    scan = upload(client, headers={"Origin": "http://testserver"}).json()
    assert client.post(f"/api/scans/{scan['id']}/retry", headers=foreign).status_code == 403
    assert client.delete(f"/api/scans/{scan['id']}", headers=foreign).status_code == 403
    assert client.get("/api/scans").json()["total"] == 1
    assert len(advisor.calls) == 1


def test_interrupted_scan_is_retryable_after_restart(tmp_path):
    app = create_app(tmp_path, FakeVision(), FakeAdvisor())
    with TestClient(app) as client:
        scan = upload(client).json()
        app.state.store.update(scan["id"], status="processing")

    with TestClient(create_app(tmp_path, FakeVision(), FakeAdvisor())) as restarted:
        interrupted = restarted.get(f"/api/scans/{scan['id']}").json()
        assert interrupted["status"] == "error"
        assert "server stopped" in interrupted["error"]
        assert restarted.post(f"/api/scans/{scan['id']}/retry").json()["status"] == "complete"


def test_health_and_history_validation(session):
    client, _, _, _ = session
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert health.headers["cache-control"] == "no-store"
    for query in ("limit=0", "limit=501", "offset=-1"):
        assert client.get("/api/scans?" + query).status_code == 422
