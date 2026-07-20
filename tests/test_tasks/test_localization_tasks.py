import threading

from src.tasks import localization_tasks


def test_parallel_preprocessing_starts_visual_and_audio_branches(monkeypatch):
    started = []
    lock = threading.Lock()
    both_started = threading.Event()

    def fake_run_job_branch(job_id, branch, runner):
        with lock:
            started.append(branch)
            if len(started) == 2:
                both_started.set()
        assert both_started.wait(timeout=2)
        return f"{branch}-result"

    monkeypatch.setattr(localization_tasks, "_run_job_branch", fake_run_job_branch)

    results = localization_tasks.run_parallel_preprocessing(job_id=123)

    assert set(started) == {"visual_cleaning", "audio_asr"}
    assert results == {
        "visual_cleaning": "visual_cleaning-result",
        "audio_asr": "audio_asr-result",
    }
