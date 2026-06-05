"""Celery background jobs."""
import asyncio
import uuid

from celery_app import celery_app


@celery_app.task(name="tasks.build_search_task")
def build_search_task(search_id: str, prompt: str, resume: bool = False) -> dict:
    from services.search_runner import run_search, search_jobs

    search_jobs[search_id] = {"status": "running", "step": "Queued…", "count": 0}
    asyncio.run(run_search(uuid.UUID(search_id), prompt, resume=resume))
    return search_jobs.get(search_id, {})


@celery_app.task(name="tasks.build_workspace_list")
def build_workspace_list(list_id: str, prompt: str) -> dict:
    """Legacy workspace list builder."""
    from services.list_builder import build_jobs, run_list_build

    build_jobs[list_id] = {"status": "running", "step": "Queued…", "count": 0}
    asyncio.run(run_list_build(uuid.UUID(list_id), prompt))
    return build_jobs.get(list_id, {})
