from pathlib import Path

import pytest

from relay.experiments import calibration_profile


def test_profile_uses_only_successful_real_timings_and_retains_error_counts():
    records = [
        {
            "attempts": [
                {"status": "ok", "first_token_ms": 20, "total_ms": 40, "http_status": 200},
                {"status": "ok", "first_token_ms": 40, "total_ms": 80, "http_status": 200},
                {
                    "status": "rate_limited",
                    "first_token_ms": None,
                    "total_ms": 5,
                    "http_status": 429,
                },
            ]
        }
    ]
    profile = calibration_profile(records, Path("raw.json"))
    assert profile["attempts"] == 3 and profile["successful_attempts"] == 2
    assert profile["median_first_token_ms"] == 30
    assert profile["median_total_ms"] == 60
    assert profile["observed_http_statuses"] == [200, 429]
    assert len(profile["samples"]) == 2


def test_profile_cannot_invent_calibration_without_successes():
    with pytest.raises(ValueError):
        calibration_profile([], Path("raw.json"))


async def test_real_calibration_json_mode_and_stop_on_bad_request(tmp_path, monkeypatch):
    import json

    from relay import experiments
    from relay.config import Settings
    from relay.provider import ProviderError

    calls = []

    class Rejected:
        def __init__(self, settings, client):
            pass

        async def complete(self, messages, *, stage, trace):
            calls.append(messages)
            assert "json" in messages[0]["content"].lower()
            trace.append({"status": "error", "http_status": 400})
            raise ProviderError("error", "bad request")

    monkeypatch.setattr(experiments, "GroqProvider", Rejected)
    with pytest.raises(ValueError, match="No successful"):
        await experiments.calibrate(
            Settings(_env_file=None, groq_api_key="fixture", relay_runs_dir=tmp_path), 4
        )
    assert len(calls) == 1
    raw = json.loads(next(tmp_path.glob("calibration-*.json")).read_text())
    assert raw["records"][0]["status"] == "error"
