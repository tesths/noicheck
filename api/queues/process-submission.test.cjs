const test = require("node:test");
const assert = require("node:assert/strict");
const { Readable } = require("node:stream");

const handler = require("./process-submission.js");

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
