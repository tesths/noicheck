const test = require("node:test");
const assert = require("node:assert/strict");
const { Readable } = require("node:stream");
const path = require("node:path");

const handler = require(path.resolve(__dirname, "../../api/queues/process-submission.js"));

function createResponse() {
  return {
    statusCode: 200,
    headers: {},
    body: undefined,
    setHeader(name, value) {
      this.headers[name] = value;
    },
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(payload) {
      this.body = payload;
      return this;
    },
  };
}

test("process-submission forwards parsed object payloads", async () => {
  let forwardedPayload = null;
  global.fetch = async (_url, options) => {
    forwardedPayload = JSON.parse(String(options.body));
    return {
      ok: true,
      text: async () => JSON.stringify({ status: "success" }),
    };
  };

  process.env.APP_BASE_URL = "https://example.com";
  process.env.INTERNAL_JOB_TOKEN = "test-token";

  const req = {
    method: "POST",
    body: {
      job_type: "fetch-problem",
      submission_public_id: "abc123",
    },
  };
  const res = createResponse();

  await handler(req, res);

  assert.equal(res.statusCode, 200);
  assert.deepEqual(forwardedPayload, req.body);
});

test("process-submission forwards stringified json payloads", async () => {
  let forwardedPayload = null;
  global.fetch = async (_url, options) => {
    forwardedPayload = JSON.parse(String(options.body));
    return {
      ok: true,
      text: async () => JSON.stringify({ status: "success" }),
    };
  };

  process.env.APP_BASE_URL = "https://example.com";
  process.env.INTERNAL_JOB_TOKEN = "test-token";

  const rawPayload = {
    job_type: "fetch-problem",
    submission_public_id: "abc123",
  };
  const req = {
    method: "POST",
    body: JSON.stringify(rawPayload),
  };
  const res = createResponse();

  await handler(req, res);

  assert.equal(res.statusCode, 200);
  assert.deepEqual(forwardedPayload, rawPayload);
});

test("process-submission reads raw request stream when req.body is undefined", async () => {
  let forwardedPayload = null;
  global.fetch = async (_url, options) => {
    forwardedPayload = JSON.parse(String(options.body));
    return {
      ok: true,
      text: async () => JSON.stringify({ status: "success" }),
    };
  };

  process.env.APP_BASE_URL = "https://example.com";
  process.env.INTERNAL_JOB_TOKEN = "test-token";

  const rawPayload = {
    job_type: "fetch-problem",
    submission_public_id: "stream123",
  };
  const req = Readable.from([JSON.stringify(rawPayload)]);
  req.method = "POST";
  req.headers = {};
  req.body = undefined;
  const res = createResponse();

  await handler(req, res);

  assert.equal(res.statusCode, 200);
  assert.deepEqual(forwardedPayload, rawPayload);
});

test("process-submission fetches queue payload from cloud event headers when body is missing", async () => {
  const fetchCalls = [];
  global.fetch = async (url, options = {}) => {
    fetchCalls.push({ url, options });
    if (fetchCalls.length === 1) {
      return {
        ok: true,
        headers: new Headers({
          "content-type": 'multipart/mixed; boundary="test-boundary"',
        }),
        text: async () =>
          [
            "--test-boundary",
            "Content-Type: application/json",
            "Vqs-Message-Id: msg-1",
            "",
            '{"job_type":"fetch-problem","submission_public_id":"cloud123","requested_by":"queue"}',
            "--test-boundary--",
            "",
          ].join("\r\n"),
      };
    }
    return {
      ok: true,
      headers: new Headers(),
      text: async () => JSON.stringify({ status: "success" }),
    };
  };

  process.env.APP_BASE_URL = "https://example.com";
  process.env.INTERNAL_JOB_TOKEN = "test-token";
  process.env.VERCEL_DEPLOYMENT_ID = "dpl_test";

  const req = {
    method: "POST",
    body: undefined,
    headers: {
      "ce-type": "com.vercel.queue.v2beta",
      "ce-vqsqueuename": "noi_submission_jobs",
      "ce-vqsconsumergroup": "api/queues/process-submission.js",
      "ce-vqsmessageid": "msg-1",
      "ce-vqsregion": "iad1",
      "x-vercel-oidc-token": "oidc-token",
    },
  };
  const res = createResponse();

  await handler(req, res);

  assert.equal(res.statusCode, 200);
  assert.equal(fetchCalls.length, 2);
  assert.equal(
    fetchCalls[0].url,
    "https://iad1.vercel-queue.com/api/v3/topic/noi_submission_jobs/consumer/api%2Fqueues%2Fprocess-submission.js/id/msg-1",
  );
  assert.equal(fetchCalls[0].options.headers.Authorization, "Bearer oidc-token");
  assert.equal(fetchCalls[0].options.headers["Vqs-Deployment-Id"], "dpl_test");
  assert.deepEqual(JSON.parse(String(fetchCalls[1].options.body)), {
    job_type: "fetch-problem",
    submission_public_id: "cloud123",
    requested_by: "queue",
  });
});

test("process-submission reads cloud event metadata from Headers instances", async () => {
  const fetchCalls = [];
  global.fetch = async (url, options = {}) => {
    fetchCalls.push({ url, options });
    if (fetchCalls.length === 1) {
      return {
        ok: true,
        headers: new Headers({
          "content-type": 'multipart/mixed; boundary="test-boundary"',
        }),
        text: async () =>
          [
            "--test-boundary",
            "Content-Type: application/json",
            "Vqs-Message-Id: msg-headers",
            "",
            '{"job_type":"fetch-problem","submission_public_id":"headers123"}',
            "--test-boundary--",
            "",
          ].join("\r\n"),
      };
    }
    return {
      ok: true,
      headers: new Headers(),
      text: async () => JSON.stringify({ status: "success" }),
    };
  };

  process.env.APP_BASE_URL = "https://example.com";
  process.env.INTERNAL_JOB_TOKEN = "test-token";
  process.env.VERCEL_DEPLOYMENT_ID = "dpl_test";

  const req = {
    method: "POST",
    body: undefined,
    headers: new Headers({
      "ce-type": "com.vercel.queue.v2beta",
      "ce-vqsqueuename": "noi_submission_jobs",
      "ce-vqsconsumergroup": "api/queues/process-submission.js",
      "ce-vqsmessageid": "msg-headers",
      "ce-vqsregion": "iad1",
      "x-vercel-oidc-token": "oidc-token",
    }),
  };
  const res = createResponse();

  await handler(req, res);

  assert.equal(res.statusCode, 200);
  assert.equal(fetchCalls.length, 2);
  assert.deepEqual(JSON.parse(String(fetchCalls[1].options.body)), {
    job_type: "fetch-problem",
    submission_public_id: "headers123",
  });
});

test("returns controlled 502 when internal processor request throws", async () => {
  process.env.APP_BASE_URL = "https://example.com";
  process.env.INTERNAL_JOB_TOKEN = "secret";
  global.fetch = async () => {
    throw new Error("network down");
  };

  const req = {
    method: "POST",
    body: { job_type: "fetch-problem", submission_public_id: "sub-1" },
  };
  const res = createResponse();

  await handler(req, res);

  assert.equal(res.statusCode, 502);
  assert.equal(res.body.ok, false);
  assert.equal(res.body.error, "internal_processor_unreachable");
  assert.equal(res.body.retryable, true);
});

test("passes through retryable business failure from internal processor", async () => {
  process.env.APP_BASE_URL = "https://example.com";
  process.env.INTERNAL_JOB_TOKEN = "secret";
  global.fetch = async () => ({
    ok: false,
    status: 503,
    async text() {
      return JSON.stringify({ ok: false, error: "internal_error", retryable: true });
    },
  });

  const req = {
    method: "POST",
    body: { job_type: "fetch-problem", submission_public_id: "sub-1" },
  };
  const res = createResponse();

  await handler(req, res);

  assert.equal(res.statusCode, 503);
  assert.equal(res.body.ok, false);
  assert.equal(res.body.error, "internal_processor_failed");
  assert.equal(res.body.retryable, true);
});
