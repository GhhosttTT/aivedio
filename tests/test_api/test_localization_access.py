from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.api.dependencies import require_localization_job_access


def _request(job_id: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": f"/api/localization/jobs/{job_id}",
        "path_params": {"job_id": job_id},
        "headers": [],
        "query_string": b"",
        "server": ("test", 80),
        "scheme": "http",
        "client": ("test", 1),
    })


def test_localization_job_access_accepts_owned_job():
    query = SimpleNamespace(
        join=lambda *args: query,
        filter=lambda *args: query,
        first=lambda: SimpleNamespace(id=7),
    )
    db = SimpleNamespace(query=lambda *_args: query)

    result = require_localization_job_access(_request("7"), SimpleNamespace(id=3), db)

    assert result is None


def test_localization_job_access_hides_unowned_job():
    query = SimpleNamespace(
        join=lambda *args: query,
        filter=lambda *args: query,
        first=lambda: None,
    )
    db = SimpleNamespace(query=lambda *_args: query)

    with pytest.raises(HTTPException) as exc:
        require_localization_job_access(_request("7"), SimpleNamespace(id=3), db)

    assert exc.value.status_code == 404
