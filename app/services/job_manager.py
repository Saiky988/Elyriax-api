import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Literal, Optional
from uuid import uuid4

logger = logging.getLogger("JobManager")

JobStatusType = Literal["queued", "processing", "completed", "failed"]


@dataclass
class JobData:
    job_id: str
    status: JobStatusType = "queued"
    progress: int = 0
    message: str = "Waiting for renderer..."
    output_path: Optional[str] = None
    error: Optional[str] = None
    job_dir: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobManager:
    def __init__(self):
        self._jobs: Dict[str, JobData] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, job_dir: Path) -> str:
        job_id = uuid4().hex
        async with self._lock:
            self._jobs[job_id] = JobData(
                job_id=job_id,
                status="queued",
                progress=0,
                message="Job queued in memory",
                job_dir=str(job_dir.resolve())
            )
        return job_id

    async def get_job(self, job_id: str) -> Optional[JobData]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def update_progress(self, job_id: str, progress: int, message: str = "Rendering video"):
        async with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.status = "processing"
                job.progress = max(0, min(100, progress))
                job.message = message
                job.updated_at = time.time()

    async def set_completed(self, job_id: str, output_path: str):
        async with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.status = "completed"
                job.progress = 100
                job.message = "Render completed successfully"
                job.output_path = output_path
                job.updated_at = time.time()

    async def set_failed(self, job_id: str, error_message: str):
        async with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.status = "failed"
                job.progress = 0
                job.message = "Render failed"
                job.error = error_message
                job.updated_at = time.time()

    async def cleanup_expired_jobs(self, ttl_seconds: int = 3600):
        now = time.time()
        expired_ids = []
        async with self._lock:
            for job_id, job in self._jobs.items():
                if now - job.created_at > ttl_seconds:
                    expired_ids.append(job_id)

            for job_id in expired_ids:
                job = self._jobs.pop(job_id, None)
                if job and job.job_dir:
                    job_path = Path(job.job_dir)
                    if job_path.exists() and job_path.is_dir():
                        try:
                            shutil.rmtree(job_path, ignore_errors=True)
                            logger.info(f"Cleaned up expired job directory: {job_id}")
                        except Exception as e:
                            logger.error(f"Error cleaning job dir {job_id}: {e}")


job_manager = JobManager()
