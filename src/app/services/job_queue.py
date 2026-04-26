from dataclasses import dataclass
import os

import httpx
from flask import current_app, has_request_context, request


class JobQueueError(Exception):
    pass


@dataclass(slots=True)
class JobMessage:
    job_type: str
    submission_public_id: str
    requested_by: str

    def as_payload(self) -> dict[str, str]:
        return {
            "job_type": self.job_type,
            "submission_public_id": self.submission_public_id,
            "requested_by": self.requested_by,
        }


class _StubJobQueue:
    def enqueue(self, message: JobMessage, *, idempotency_key: str | None = None) -> None:
        queue_state = current_app.extensions.setdefault("job_queue_stub", {"jobs": []})
        queue_state["jobs"].append(message.as_payload())


class _InlineJobQueue:
    def enqueue(self, message: JobMessage, *, idempotency_key: str | None = None) -> None:
        from .jobs import process_job_message

        process_job_message(
            job_type=message.job_type,
            submission_public_id=message.submission_public_id,
        )


class _VercelJobQueue:
    def enqueue(self, message: JobMessage, *, idempotency_key: str | None = None) -> None:
        token = self._resolve_oidc_token()
        if not token:
            raise JobQueueError("未获取到 Vercel OIDC Token，无法发送队列消息。")

        region = str(current_app.config.get("VERCEL_QUEUE_REGION", "")).strip()
        topic = str(current_app.config.get("VERCEL_QUEUE_TOPIC", "")).strip()
        if not region or not topic:
            raise JobQueueError("未配置 Vercel Queue 区域或主题。")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Vqs-Idempotency-Key"] = idempotency_key
        deployment_id = os.getenv("VERCEL_DEPLOYMENT_ID", "").strip()
        if deployment_id:
            headers["Vqs-Deployment-Id"] = deployment_id

        url = f"https://{region}.vercel-queue.com/api/v3/topic/{topic}"
        payload = message.as_payload()
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise JobQueueError(f"发送队列消息失败：{exc}") from exc

    def _resolve_oidc_token(self) -> str:
        if has_request_context():
            header_value = request.headers.get("x-vercel-oidc-token") or request.headers.get(
                "X-Vercel-Oidc-Token"
            )
            if header_value:
                return header_value.strip()
        return str(current_app.config.get("VERCEL_OIDC_TOKEN", "")).strip()


def enqueue_job(message: JobMessage, *, idempotency_key: str | None = None) -> None:
    backend = _get_queue_backend()
    backend.enqueue(message, idempotency_key=idempotency_key)


def _get_queue_backend():
    backend = current_app.extensions.get("job_queue_backend")
    if backend is not None:
        return backend

    mode = str(current_app.config.get("JOB_QUEUE_BACKEND", "inline")).strip().lower()
    if mode == "stub":
        backend = _StubJobQueue()
    elif mode == "inline":
        backend = _InlineJobQueue()
    elif mode == "vercel":
        backend = _VercelJobQueue()
    else:
        raise JobQueueError(f"不支持的队列后端：{mode}")

    current_app.extensions["job_queue_backend"] = backend
    return backend
