// SSE Worker — reads SSE stream + parses NDJSON in a background thread.
// Main thread receives already-parsed events via postMessage.

let abortController: AbortController | null = null;
let textDecoder = new TextDecoder();

// Properly regex-safe version of sanitizeJsonString
function sanitizeJsonString(jsonStr: string): string {
  return jsonStr
    .replace(/:\s*NaN\b/g, ": null")
    .replace(/\[\s*NaN\s*\]/g, "[null]")
    .replace(/,\s*NaN\s*,/g, ", null,")
    .replace(/,\s*NaN\s*\]/g, ", null]");
}

self.onmessage = async (e: MessageEvent) => {
  const msg = e.data;

  if (msg.type === "start") {
    abortController = new AbortController();
    try {
      await startStreaming(msg, abortController.signal);
    } finally {
      abortController = null;
    }
  } else if (msg.type === "abort") {
    abortController?.abort();
  }
};

async function startStreaming(
  msg: { method: string; url: string; body?: unknown },
  signal: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const params: RequestInit = {
    method: msg.method,
    headers,
    signal,
    credentials: "include",
  };
  if (msg.body) {
    params.body = JSON.stringify(msg.body);
  }

  const response = await fetch(msg.url, params);
  if (!response.ok) {
    self.postMessage({ type: "error", statusCode: response.status });
    return;
  }

  if (!response.body) {
    self.postMessage({ type: "error", message: "No response body" });
    return;
  }

  const reader = response.body.getReader();
  let current: string[] = [];

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const decodedChunk = textDecoder.decode(value);
    const all = decodedChunk.split("\n\n");

    const parsedEvents: object[] = [];
    for (const str of all) {
      if (str.endsWith("}")) {
        const allString = current.join("") + str;
        try {
          const sanitizedJson = sanitizeJsonString(allString);
          parsedEvents.push(JSON.parse(sanitizedJson));
          current = [];
        } catch {
          current.push(str);
        }
      } else {
        current.push(str);
      }
    }

    if (parsedEvents.length > 0) {
      self.postMessage({ type: "events", data: parsedEvents });
    }
  }

  // Remaining buffer
  if (current.length > 0) {
    const allString = current.join("");
    if (allString) {
      const sanitizedJson = sanitizeJsonString(allString);
      try {
        const data = JSON.parse(sanitizedJson);
        self.postMessage({ type: "event", data });
      } catch {
        // ignore trailing garbage
      }
    }
  }

  self.postMessage({ type: "done" });
}
