const test = require("node:test");
const assert = require("node:assert/strict");

const handler = require("./process-submission");

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
