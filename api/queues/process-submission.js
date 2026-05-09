function resolveBaseUrl() {
  const explicit = (process.env.APP_BASE_URL || "").trim();
  if (explicit) {
    return explicit.replace(/\/$/, "");
  }

  const vercelUrl = (process.env.VERCEL_URL || "").trim();
  if (vercelUrl) {
    return `https://${vercelUrl.replace(/\/$/, "")}`;
  }

  return "";
}

function normalizePayload(body) {
  if (!body) {
    return null;
  }
  if (typeof body === "string") {
    const parsed = parseJsonString(body);
    return parsed === null ? null : normalizePayload(parsed);
  }
  if (Buffer.isBuffer(body) || body instanceof Uint8Array) {
    return normalizePayload(Buffer.from(body).toString("utf8"));
  }
  if (body instanceof ArrayBuffer) {
    return normalizePayload(Buffer.from(body).toString("utf8"));
  }
  if (typeof body !== "object") {
    return null;
  }
  if (body.job_type && body.submission_public_id) {
    return body;
  }

  for (const key of ["message", "body", "payload", "data"]) {
    if (key in body) {
      const nested = normalizePayload(body[key]);
      if (nested) {
        return nested;
      }
    }
  }
  return null;
}

function parseJsonString(value) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

function describePayload(body) {
  if (body === null || body === undefined) {
    return { type: String(body) };
  }
  if (typeof body === "string") {
    return {
      type: "string",
      preview: body.slice(0, 200),
    };
  }
  if (Buffer.isBuffer(body) || body instanceof Uint8Array) {
    return {
      type: body.constructor?.name || "Uint8Array",
      byteLength: body.byteLength,
      preview: Buffer.from(body).toString("utf8", 0, 200),
    };
  }
  if (body instanceof ArrayBuffer) {
    return {
      type: "ArrayBuffer",
      byteLength: body.byteLength,
      preview: Buffer.from(body).toString("utf8", 0, 200),
    };
  }
  if (typeof body === "object") {
    return {
      type: "object",
      keys: Object.keys(body).slice(0, 20),
    };
  }
  return { type: typeof body };
}

function getHeader(headers, name) {
  if (!headers || typeof headers !== "object") {
    return null;
  }
  const target = name.toLowerCase();
  for (const [key, value] of Object.entries(headers)) {
    if (String(key).toLowerCase() !== target) {
      continue;
    }
    if (Array.isArray(value)) {
      return value[0] ?? null;
    }
    return value ?? null;
  }
  return null;
}

function parseQueueCallbackMetadata(headers) {
  const eventType = getHeader(headers, "ce-type");
  if (eventType !== "com.vercel.queue.v2beta") {
    return null;
  }

  const queueName = getHeader(headers, "ce-vqsqueuename");
  const consumerGroup = getHeader(headers, "ce-vqsconsumergroup");
  const messageId = getHeader(headers, "ce-vqsmessageid");
  if (!queueName || !consumerGroup || !messageId) {
    return null;
  }

  return {
    queueName: String(queueName),
    consumerGroup: String(consumerGroup),
    messageId: String(messageId),
    region: String(getHeader(headers, "ce-vqsregion") || "").trim() || null,
    oidcToken: String(getHeader(headers, "x-vercel-oidc-token") || "").trim() || null,
  };
}

async function resolveRequestBody(req) {
  if (req.body !== undefined) {
    return req.body;
  }
  return readRawRequestBody(req);
}

async function readRawRequestBody(req) {
  if (!req || typeof req[Symbol.asyncIterator] !== "function") {
    return undefined;
  }

  const chunks = [];
  for await (const chunk of req) {
    if (typeof chunk === "string") {
      chunks.push(Buffer.from(chunk));
      continue;
    }
    if (Buffer.isBuffer(chunk)) {
      chunks.push(chunk);
      continue;
    }
    if (chunk instanceof Uint8Array) {
      chunks.push(Buffer.from(chunk));
    }
  }

  if (!chunks.length) {
    return undefined;
  }
  return Buffer.concat(chunks);
}

function resolveQueueApiBaseUrl(region) {
  const effectiveRegion = String(region || process.env.VERCEL_REGION || "iad1").trim();
  return `https://${effectiveRegion}.vercel-queue.com/api/v3/topic`;
}

async function fetchQueueMessagePayload(metadata) {
  const token = metadata.oidcToken || String(process.env.VERCEL_OIDC_TOKEN || "").trim();
  if (!token) {
    throw new Error("missing_queue_oidc_token");
  }

  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: "multipart/mixed",
  };
  const deploymentId = String(process.env.VERCEL_DEPLOYMENT_ID || "").trim();
  if (deploymentId) {
    headers["Vqs-Deployment-Id"] = deploymentId;
  }

  const queueName = encodeURIComponent(metadata.queueName);
  const consumerGroup = encodeURIComponent(metadata.consumerGroup);
  const messageId = encodeURIComponent(metadata.messageId);
  const response = await fetch(
    `${resolveQueueApiBaseUrl(metadata.region)}/${queueName}/consumer/${consumerGroup}/id/${messageId}`,
    {
      method: "POST",
      headers,
    },
  );

  const text = await response.text();
  if (!response.ok) {
    throw new Error(`queue_receive_failed:${response.status}:${text}`);
  }

  return parseMultipartJsonPayload(text, response.headers);
}

function parseMultipartJsonPayload(bodyText, headers) {
  const contentType =
    typeof headers?.get === "function"
      ? headers.get("content-type")
      : getHeader(headers, "content-type");
  const boundaryMatch = String(contentType || "").match(/boundary="?([^";]+)"?/i);
  if (!boundaryMatch) {
    throw new Error("missing_multipart_boundary");
  }

  const boundary = `--${boundaryMatch[1]}`;
  const parts = String(bodyText).split(boundary);
  for (const rawPart of parts) {
    const part = rawPart.trim();
    if (!part || part === "--") {
      continue;
    }

    const separatorMatch = rawPart.match(/\r?\n\r?\n/);
    if (!separatorMatch || separatorMatch.index === undefined) {
      continue;
    }

    const payloadStart = separatorMatch.index + separatorMatch[0].length;
    const payloadText = rawPart.slice(payloadStart).trim().replace(/--$/, "").trim();
    const parsed = parseJsonString(payloadText);
    if (parsed !== null) {
      return parsed;
    }
  }

  throw new Error("missing_queue_payload");
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }

  const requestBody = await resolveRequestBody(req);
  let payload = normalizePayload(requestBody);
  if (!payload) {
    const metadata = parseQueueCallbackMetadata(req.headers);
    if (metadata) {
      try {
        payload = normalizePayload(await fetchQueueMessagePayload(metadata));
      } catch (error) {
        console.error("Queue consumer failed to fetch payload by message id", {
          queueName: metadata.queueName,
          consumerGroup: metadata.consumerGroup,
          messageId: metadata.messageId,
          error: error instanceof Error ? error.message : String(error),
        });
        return res.status(500).json({ ok: false, error: "queue_message_fetch_failed" });
      }
    }
  }
  if (!payload) {
    console.error("Queue consumer received unsupported payload shape", describePayload(requestBody));
    return res.status(400).json({ ok: false, error: "invalid_payload" });
  }

  const baseUrl = resolveBaseUrl();
  const internalToken = (process.env.INTERNAL_JOB_TOKEN || "").trim();
  if (!baseUrl || !internalToken) {
    return res.status(500).json({ ok: false, error: "missing_internal_job_config" });
  }

  const response = await fetch(`${baseUrl}/internal/jobs/process`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Job-Token": internalToken,
    },
    body: JSON.stringify(payload),
  });

  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { ok: false, error: "invalid_internal_response", raw: text };
  }

  if (!response.ok) {
    return res.status(500).json({
      ok: false,
      error: "internal_processor_failed",
      detail: data,
    });
  }

  return res.status(200).json({
    ok: true,
    status: data.status || "success",
  });
};
