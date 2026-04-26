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
  if (!body || typeof body !== "object") {
    return null;
  }
  if (body.job_type && body.submission_public_id) {
    return body;
  }
  if (body.message && typeof body.message === "object") {
    return normalizePayload(body.message);
  }
  if (body.body && typeof body.body === "object") {
    return normalizePayload(body.body);
  }
  return null;
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }

  const payload = normalizePayload(req.body);
  if (!payload) {
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
