import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
} from "axios";
import * as fetchIntercept from "fetch-intercept";
import { useEffect } from "react";
import { IS_AUTO_LOGIN } from "@/constants/constants";
import { baseURL } from "@/customization/constants";
import { useCustomApiHeaders } from "@/customization/hooks/use-custom-api-headers";
import {
  getAxiosWithCredentials,
  getFetchCredentials,
} from "@/customization/utils/get-fetch-credentials";
import useAuthStore from "@/stores/authStore";
import { useUtilityStore } from "@/stores/utilityStore";
import { BuildStatus, type EventDeliveryType } from "../../constants/enums";
import useAlertStore from "../../stores/alertStore";
import useFlowStore from "../../stores/flowStore";
import { checkDuplicateRequestAndStoreRequest } from "./helpers/check-duplicate-requests";
import { useLogout, useRefreshAccessToken } from "./queries/auth";

// Create a new Axios instance
const api: AxiosInstance = axios.create({
  baseURL: baseURL,
  withCredentials: getAxiosWithCredentials(),
});

// URL fragments for auth-maintenance endpoints. A 401/403 on any of these
// must NOT trigger the refresh-then-retry branch — that path itself goes
// through this same axios instance, so retrying would recurse. Exported
// for unit testing.
export const AUTH_MAINTENANCE_PATHS = [
  "/refresh",
  "/login",
  "/logout",
  "/auto_login",
];

export function isAuthMaintenanceURL(url: string | undefined): boolean {
  if (!url) return false;
  return AUTH_MAINTENANCE_PATHS.some((path) => {
    const idx = url.indexOf(path);
    if (idx === -1) return false;
    const charAfter = url[idx + path.length];
    return (
      charAfter === undefined ||
      charAfter === "/" ||
      charAfter === "?" ||
      charAfter === "#"
    );
  });
}

function ApiInterceptor() {
  const autoLogin = useAuthStore((state) => state.autoLogin);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const accessToken = useAuthStore((state) => state.accessToken);
  const authenticationErrorCount = useAuthStore(
    (state) => state.authenticationErrorCount,
  );
  const setAuthenticationErrorCount = useAuthStore(
    (state) => state.setAuthenticationErrorCount,
  );

  const { mutate: mutationLogout } = useLogout();
  const { mutateAsync: mutationRenewAccessToken } = useRefreshAccessToken();
  const isLoginPage = location.pathname.includes("login");
  const customHeaders = useCustomApiHeaders();

  const setHealthCheckTimeout = useUtilityStore(
    (state) => state.setHealthCheckTimeout,
  );

  useEffect(() => {
    const unregister = fetchIntercept.register({
      request: (url, config) => {
        // Browser automatically sends cookies with requests (including HttpOnly cookies)
        // No need to manually add Authorization header from cookies

        if (!isExternalURL(url)) {
          for (const [key, value] of Object.entries(customHeaders)) {
            config.headers[key] = value;
          }
        }

        return [url, config];
      },
    });

    const interceptor = api.interceptors.response.use(
      (response) => {
        setHealthCheckTimeout(null);
        return response;
      },
      async (error: AxiosError) => {
        const isAuthenticationError =
          error?.response?.status === 403 || error?.response?.status === 401;

        const shouldRetryRefresh =
          (isAuthenticationError && !IS_AUTO_LOGIN) ||
          (isAuthenticationError && !autoLogin && autoLogin !== undefined);

        if (shouldRetryRefresh) {
          if (
            error?.config?.url?.includes("github") ||
            error?.config?.url?.includes("public")
          ) {
            return Promise.reject(error);
          }
          // Auth-maintenance endpoints must not trigger refresh themselves.
          // The refresh mutation uses this same axios instance, so if
          // ``/refresh`` returns 401 (expired refresh token) it would
          // re-enter this branch and recurse. Same for login/logout/
          // auto_login. Reject the original failure and let the caller
          // (typically the refresh mutation's catch block) drive logout.
          if (isAuthMaintenanceURL(error?.config?.url)) {
            await clearBuildVerticesState(error);
            return Promise.reject(error);
          }
          const stillRefresh = checkErrorCount();
          if (!stillRefresh) {
            return Promise.reject(error);
          }

          try {
            await tryToRenewAccessToken(error);
          } catch {
            // Refresh failed (already logged + logout dispatched in the
            // helper). Reject with the original error so callers see a
            // clean failure instead of a swallowed undefined response.
            await clearBuildVerticesState(error);
            return Promise.reject(error);
          }
          await clearBuildVerticesState(error);
          return await remakeRequest(error);
        }

        await clearBuildVerticesState(error);

        // Non-recoverable failure path: always reject so callers and
        // React Query see a real error rather than an undefined response.
        // This used to silently swallow auth errors under AUTO_LOGIN,
        // producing infinite "Loading models…" spinners on fresh installs.
        return Promise.reject(error);
      },
    );

    const isAuthorizedURL = (url) => {
      const authorizedDomains = [
        "https://raw.githubusercontent.com/langflow-ai/langflow_examples/main/examples",
        "https://api.github.com/repos/langflow-ai/langflow_examples/contents/examples",
        "https://api.github.com/repos/langflow-ai/langflow",
        "auto_login",
      ];

      const authorizedEndpoints = ["auto_login"];

      try {
        const parsedURL = new URL(url);
        const isDomainAllowed = authorizedDomains.some(
          (domain) => parsedURL.origin === new URL(domain).origin,
        );
        const isEndpointAllowed = authorizedEndpoints.some((endpoint) =>
          parsedURL.pathname.includes(endpoint),
        );

        return isDomainAllowed || isEndpointAllowed;
      } catch (_e) {
        // Invalid URL
        return false;
      }
    };

    // Check for external url which we don't want to add custom headers to
    const isExternalURL = (url: string): boolean => {
      const EXTERNAL_DOMAINS = [
        "https://raw.githubusercontent.com",
        "https://api.github.com",
        "https://api.segment.io",
        "https://cdn.sprig.com",
      ];

      try {
        const parsedURL = new URL(url);
        return EXTERNAL_DOMAINS.some((domain) => parsedURL.origin === domain);
      } catch (_e) {
        return false;
      }
    };

    // Request interceptor to add custom headers
    // Browser automatically sends cookies (including HttpOnly) with requests
    const requestInterceptor = api.interceptors.request.use(
      async (config) => {
        const controller = new AbortController();
        try {
          checkDuplicateRequestAndStoreRequest(config);
        } catch (e) {
          const error = e as Error;
          controller.abort(error.message);
          console.error(error.message);
        }

        const currentOrigin = window.location.origin;
        const requestUrl = new URL(config?.url as string, currentOrigin);

        const urlIsFromCurrentOrigin = requestUrl.origin === currentOrigin;
        if (urlIsFromCurrentOrigin) {
          for (const [key, value] of Object.entries(customHeaders)) {
            config.headers[key] = value;
          }
        }

        return {
          ...config,
          signal: controller.signal,
        };
      },
      (error) => {
        return Promise.reject(error);
      },
    );

    return () => {
      // Clean up the interceptors when the component unmounts
      api.interceptors.response.eject(interceptor);
      api.interceptors.request.eject(requestInterceptor);
      unregister();
    };
  }, [accessToken, setErrorData, customHeaders, autoLogin]);

  function checkErrorCount(): boolean {
    if (isLoginPage) return false;

    setAuthenticationErrorCount(authenticationErrorCount + 1);

    if (authenticationErrorCount > 3) {
      setAuthenticationErrorCount(0);
      mutationLogout();
      return false;
    }

    return true;
  }

  async function tryToRenewAccessToken(error: AxiosError) {
    if (isLoginPage) throw error;
    if (error.config?.headers) {
      for (const [key, value] of Object.entries(customHeaders)) {
        error.config.headers[key] = value;
      }
    }
    try {
      await mutationRenewAccessToken(undefined);
      setAuthenticationErrorCount(0);
    } catch (refreshError) {
      console.error(refreshError);
      const isNetworkError =
        (refreshError as AxiosError)?.response === undefined;
      if (!isNetworkError) {
        mutationLogout();
      }
      throw refreshError;
    }
  }

  async function clearBuildVerticesState(error) {
    if (error?.response?.status === 500) {
      const vertices = useFlowStore.getState().verticesBuild;
      useFlowStore
        .getState()
        .updateBuildStatus(vertices?.verticesIds ?? [], BuildStatus.BUILT);
      useFlowStore.getState().setIsBuilding(false);
    }
  }

  async function remakeRequest(error: AxiosError) {
    const originalRequest = error.config as AxiosRequestConfig;

    // Return the full AxiosResponse so when this value resolves the
    // outer interceptor promise, callers see a normal axios response and
    // can read ``response.data`` as usual. Returning ``response.data``
    // here would double-unwrap and produce ``undefined`` at the call site.
    return axios.request(originalRequest);
  }

  return null;
}

// Maximum time (ms) to wait without data before timing out the stream.
const STREAM_TIMEOUT_MS = 120_000; // 2 minutes

// Helper to race reader.read() against a timeout and abort signal.
async function readWithTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  timeoutMs: number,
  abortSignal: AbortSignal,
): Promise<{ done: boolean; value?: Uint8Array }> {
  const readPromise = reader.read();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`Stream timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Stream aborted", "AbortError"));
    };
    abortSignal.addEventListener("abort", onAbort, { once: true });
    readPromise
      .then((result) => {
        clearTimeout(timer);
        abortSignal.removeEventListener("abort", onAbort);
        resolve(result);
      })
      .catch((err) => {
        clearTimeout(timer);
        abortSignal.removeEventListener("abort", onAbort);
        reject(err);
      });
  });
}
export type StreamingRequestParams = {
  method: string;
  url: string;
  onData: (event: object) => Promise<boolean>;
  onDataBatch?: (events: object[]) => Promise<boolean>;
  body?: object;
  onError?: (statusCode: number) => void;
  onNetworkError?: (error: Error) => void;
  buildController: AbortController;
  eventDeliveryConfig?: EventDeliveryType;
};

// Helper function to sanitize JSON strings
function sanitizeJsonString(jsonStr: string): string {
  // Replace NaN with null (valid JSON)
  return jsonStr
    .replace(/:\s*NaN\b/g, ": null")
    .replace(/\[\s*NaN\s*\]/g, "[null]")
    .replace(/,\s*NaN\s*,/g, ", null,")
    .replace(/,\s*NaN\s*\]/g, ", null]");
}

/**
 * Main-thread streaming fallback — preserves the original heartbeat + yield
 * logic for environments where Web Workers are not available.
 */
async function performStreamingOnMainThread({
  method,
  url,
  onData,
  onDataBatch,
  body,
  onError,
  onNetworkError,
  buildController,
}: StreamingRequestParams) {
  const params: RequestInit = {
    method: method,
    headers: { "Content-Type": "application/json" },
    signal: buildController.signal,
    credentials: "include",
  };
  if (body) {
    params.body = JSON.stringify(body);
  }
  let current: string[] = [];
  const textDecoder = new TextDecoder();

  try {
    const response = await fetch(url, params);
    if (!response.ok) {
      if (onError) {
        onError(response.status);
      } else {
        throw new Error("Error in streaming request.");
      }
    }
    if (response.body === null) {
      return;
    }
    const reader = response.body.getReader();
    let lastHeartbeat = Date.now();
    while (true) {
      // Yield to browser rendering cycle every 500ms
      const now = Date.now();
      if (now - lastHeartbeat >= 500) {
        await new Promise((resolve) => requestAnimationFrame(resolve));
        lastHeartbeat = now;
      }
      const { done, value } = await readWithTimeout(
        reader,
        STREAM_TIMEOUT_MS,
        buildController.signal,
      );
      if (done) {
        break;
      }
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
          } catch (_e) {
            current.push(str);
          }
        } else {
          current.push(str);
        }
      }

      if (onDataBatch && parsedEvents.length > 0) {
        const shouldContinue = await onDataBatch(parsedEvents);
        if (!shouldContinue) {
          buildController.abort();
          return;
        }
      } else {
        for (const data of parsedEvents) {
          const shouldContinue = await onData(data);
          if (!shouldContinue) {
            buildController.abort();
            return;
          }
        }
      }
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    if (current.length > 0) {
      const allString = current.join("");
      if (allString) {
        const sanitizedJson = sanitizeJsonString(allString);
        const data = JSON.parse(sanitizedJson);
        await onData(data);
      }
    }
  } catch (e: unknown) {
    if (onNetworkError) {
      onNetworkError(e as Error);
    } else {
      throw e;
    }
  }
}


async function performStreamingRequest({
  method,
  url,
  onData,
  onDataBatch,
  body,
  onError,
  onNetworkError,
  buildController,
}: StreamingRequestParams) {
  // Web Worker path — SSE stream is read + parsed in a background thread
  // so the main thread is never blocked by stream processing.
  // Falls back to main-thread streaming when Workers are unavailable.
  let worker: Worker | null = null;
  const useWorker = typeof Worker !== "undefined";

  if (useWorker) {
    try {
      worker = new Worker(new URL("./sse-worker.ts", import.meta.url), {
        type: "module",
      });
    } catch {
      worker = null;
    }
  }

  if (!worker) {
    // Fallback: main-thread streaming
    return performStreamingOnMainThread({
      method,
      url,
      onData,
      onDataBatch,
      body,
      onError,
      onNetworkError,
      buildController,
    });
  }

  // === Web Worker path ===
  return new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      if (worker) {
        worker.terminate();
        worker = null;
      }
    };

    worker.onmessage = async (e: MessageEvent) => {
      const msg = e.data;
      try {
        switch (msg.type) {
          case "events": {
            if (onDataBatch) {
              const cont = await onDataBatch(msg.data);
              if (!cont) {
                worker?.postMessage({ type: "abort" });
                cleanup();
                resolve();
              }
            }
            break;
          }
          case "event": {
            if (onData) {
              const cont = await onData(msg.data);
              if (!cont) {
                worker?.postMessage({ type: "abort" });
                cleanup();
                resolve();
              }
            }
            break;
          }
          case "done":
            cleanup();
            resolve();
            break;
          case "error":
            if (msg.statusCode) {
              onError?.(msg.statusCode);
            } else if (onNetworkError) {
              onNetworkError(new Error(msg.message || "Stream error"));
            }
            cleanup();
            resolve();
            break;
          case "aborted":
            cleanup();
            resolve();
            break;
        }
      } catch (err) {
        cleanup();
        reject(err);
      }
    };

    worker.onerror = (err) => {
      if (onNetworkError) {
        onNetworkError(new Error(err.message));
      }
      cleanup();
      resolve();
    };

    // Wire up the build controller abort to the worker
    const onAbort = () => {
      worker?.postMessage({ type: "abort" });
      cleanup();
      resolve();
    };
    if (buildController.signal.aborted) {
      onAbort();
      return;
    }
    buildController.signal.addEventListener("abort", onAbort, { once: true });

    // Start the worker
    worker.postMessage({ type: "start", method, url, body });
  });
}

export { api, ApiInterceptor, performStreamingRequest };

