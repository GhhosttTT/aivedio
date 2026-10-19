import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image

from src.services.comfyui_service import ComfyUIError, ComfyUIService, ComfyUIWaitTimeout


@pytest.fixture
def service(monkeypatch):
    instance = ComfyUIService(max_retries=2)
    monkeypatch.setattr("src.services.comfyui_service.time.sleep", lambda _delay: None)
    yield instance
    instance.client.close()


def transport(service, handler):
    service.client.close()
    service.client = httpx.Client(transport=httpx.MockTransport(handler))


def test_connection_failure_can_retry_before_request_is_accepted(service):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("not connected", request=request)
        return httpx.Response(200, json={"prompt_id": "accepted"})

    transport(service, handler)
    assert service._submit_workflow({}) == "accepted"
    assert len(calls) == 2
    assert json.loads(calls[0].content)["client_id"] == json.loads(calls[1].content)["client_id"]


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ReadError, httpx.WriteError])
def test_unknown_submission_outcome_must_not_be_submitted_twice(service, error_type):
    calls = []

    def handler(request):
        calls.append(request)
        raise error_type("connection lost after send", request=request)

    transport(service, handler)
    with pytest.raises(ComfyUIWaitTimeout, match="outcome is unknown") as caught:
        service._submit_workflow({})
    assert len(calls) == 1
    assert caught.value.client_id == json.loads(calls[0].content)["client_id"]


@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(200, json={}), httpx.Response(200, content=b"invalid json")])
def test_ambiguous_submission_response_needs_inspection(service, response):
    request = Mock(return_value=response)
    transport(service, request)
    with pytest.raises(ComfyUIWaitTimeout, match="inspect"):
        service._submit_workflow({})
    request.assert_called_once()


def test_explicit_rejection_is_not_a_live_job(service):
    request = Mock(return_value=httpx.Response(400, json={"error": "invalid node"}))
    transport(service, request)
    with pytest.raises(ComfyUIError, match="HTTP 400") as caught:
        service._submit_workflow({})
    assert not isinstance(caught.value, ComfyUIWaitTimeout)
    request.assert_called_once()


def test_artifact_download_retry_reuses_the_completed_gpu_job(service, monkeypatch, tmp_path):
    submit, wait = Mock(return_value="job-123"), Mock(return_value={"outputs": {}})
    monkeypatch.setattr(service, "_submit_workflow", submit)
    monkeypatch.setattr(service, "_wait_for_completion", wait)
    output = tmp_path / "candidate.png"
    download = Mock(side_effect=[ComfyUIError("temporary download failure"), str(output)])
    assert service._run_submitted_job({}, str(output), "image", "9", download) == str(output)
    submit.assert_called_once()
    wait.assert_called_once_with("job-123")
    assert download.call_count == 2
    job = json.loads(output.with_suffix(".job.json").read_text())
    assert job["status"] == "completed"
    assert job["prompt_id"] == "job-123" and job["output_node"] == "9"


def test_observation_timeout_keeps_recoverable_prompt_id(service, monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_submit_workflow", Mock(return_value="pending-123"))
    monkeypatch.setattr(service, "_wait_for_completion", Mock(side_effect=ComfyUIWaitTimeout("still running", prompt_id="pending-123")))
    output = tmp_path / "candidate.png"
    download = Mock()
    with pytest.raises(ComfyUIWaitTimeout):
        service._run_submitted_job({}, str(output), "image", "9", download)
    download.assert_not_called()
    job = json.loads(output.with_suffix(".job.json").read_text())
    assert job["status"] == "observation_required"
    assert job["prompt_id"] == "pending-123"


def test_recoverable_job_resumes_without_resubmitting(service, monkeypatch, tmp_path):
    output = tmp_path / "candidate.png"
    workflow = {"9": {"class_type": "SaveImage", "inputs": {}}}
    from src.services.generation_review import fingerprint
    output.with_suffix(".job.json").write_text(json.dumps({
        "status": "observation_required",
        "kind": "image",
        "server": service.base_url,
        "workflow_sha256": fingerprint(workflow),
        "prompt_id": "pending-456",
    }), encoding="utf-8")
    submit = Mock(side_effect=AssertionError("recovery must not submit a duplicate job"))
    monkeypatch.setattr(service, "_submit_workflow", submit)
    monkeypatch.setattr(service, "_wait_for_completion", Mock(return_value={"outputs": {}}))
    download = Mock(return_value=str(output))

    assert service._run_submitted_job(workflow, str(output), "image", "9", download) == str(output)
    submit.assert_not_called()
    download.assert_called_once_with({"outputs": {}})
    job = json.loads(output.with_suffix(".job.json").read_text())
    assert job["status"] == "completed"
    assert job["prompt_id"] == "pending-456"


def test_stale_job_state_is_not_resumed(service, monkeypatch, tmp_path):
    output = tmp_path / "candidate.png"
    output.with_suffix(".job.json").write_text(json.dumps({
        "status": "observation_required",
        "kind": "image",
        "server": service.base_url,
        "workflow_sha256": "stale",
        "prompt_id": "old-job",
    }), encoding="utf-8")
    submit = Mock(return_value="new-job")
    monkeypatch.setattr(service, "_submit_workflow", submit)
    monkeypatch.setattr(service, "_wait_for_completion", Mock(return_value={"outputs": {}}))
    download = Mock(return_value=str(output))
    workflow = {"9": {"class_type": "SaveImage", "inputs": {}}}

    service._run_submitted_job(workflow, str(output), "image", "9", download)

    submit.assert_called_once_with(workflow)


def test_bad_download_cannot_replace_previously_accepted_pixels(tmp_path):
    path = tmp_path / "accepted.png"
    original = b"accepted file content"
    path.write_bytes(original)
    with pytest.raises(Exception):
        ComfyUIService._save_download(b"invalid image", path, verify_image=True)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.download"))


def test_verified_image_download_replaces_atomically(tmp_path):
    data = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(data, format="PNG")
    path = tmp_path / "output.png"
    ComfyUIService._save_download(data.getvalue(), path, verify_image=True)
    assert path.read_bytes() == data.getvalue()
    assert not list(tmp_path.glob("*.download"))


def test_empty_video_download_cannot_replace_an_existing_clip(tmp_path):
    path = tmp_path / "output.mp4"
    path.write_bytes(b"accepted clip")
    with pytest.raises(ComfyUIError, match="empty"):
        ComfyUIService._save_download(b"", path)
    assert path.read_bytes() == b"accepted clip"


def test_batch_generation_stops_on_a_potentially_running_job(service, monkeypatch):
    generate = Mock(side_effect=ComfyUIWaitTimeout("inspect the pending job"))
    monkeypatch.setattr(service, "generate_image", generate)
    with pytest.raises(ComfyUIWaitTimeout):
        service.generate_batch(["first actor", "second actor"])
    generate.assert_called_once()


def test_execution_failure_does_not_resubmit_the_same_image(service, monkeypatch):
    monkeypatch.setattr(service, "preflight", Mock())
    submit = Mock(side_effect=ComfyUIError("Out of memory"))
    monkeypatch.setattr(service, "_submit_and_wait", submit)
    with pytest.raises(ComfyUIError, match="Out of memory"):
        service.generate_image("an actor")
    submit.assert_called_once()
