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

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }

  const requestBody = await resolveRequestBody(req);
  const payload = normalizePayload(requestBody);
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
