from __future__ import annotations

from flask import current_app
from redis import Redis
from rq import Queue, Retry

JOB_PATH = "src.app.jobs.process_submission.process_submission_job"


class QueueServiceError(Exception):
    pass


def _get_required_config(name: str) -> str:
    value = str(current_app.config.get(name, "")).strip()
    if not value:
        raise QueueServiceError(f"缺少配置：{name}")
    return value


def _build_retry_policy() -> Retry | None:
    retry_max = int(current_app.config["WORKER_RETRY_MAX"])
    if retry_max <= 0:
        return None

    retry_interval = max(int(current_app.config["WORKER_RETRY_INTERVAL"]), 0)
    return Retry(max=retry_max, interval=[retry_interval] * retry_max)


def get_submission_queue() -> Queue:
    redis_url = _get_required_config("REDIS_URL")
    queue_name = _get_required_config("RQ_QUEUE_NAME")
    connection = Redis.from_url(redis_url)
    return Queue(
        queue_name,
        connection=connection,
        default_timeout=int(current_app.config["WORKER_JOB_TIMEOUT"]),
    )


def enqueue_submission(public_id: str):
    if not public_id:
        raise QueueServiceError("submission public_id 不能为空")

    queue = get_submission_queue()
    retry = _build_retry_policy()
    enqueue_kwargs = {
        "job_timeout": int(current_app.config["WORKER_JOB_TIMEOUT"]),
    }
    if retry is not None:
        enqueue_kwargs["retry"] = retry

    try:
        return queue.enqueue(JOB_PATH, public_id, **enqueue_kwargs)
    except Exception as exc:  # pragma: no cover - 依赖外部 Redis/RQ 的异常类型较多
        raise QueueServiceError(f"加入后台队列失败：{exc}") from exc
