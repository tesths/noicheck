from __future__ import annotations

import os

from redis import Redis
from rq import Queue, Worker


def main() -> None:
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        raise RuntimeError("REDIS_URL 未配置，无法启动 worker")

    queue_name = os.getenv("RQ_QUEUE_NAME", "submission-analysis").strip() or "submission-analysis"
    job_timeout = int(os.getenv("WORKER_JOB_TIMEOUT", "300"))
    connection = Redis.from_url(redis_url)
    queue = Queue(queue_name, connection=connection, default_timeout=job_timeout)
    worker = Worker([queue], connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
