import { ApiError } from "@/lib/api";

/** An error's message, with the request id (copy.md "Error pattern") when the API gave one. */
export function ErrorText({ error }: { error: string | Error }) {
  const requestId = error instanceof ApiError ? error.requestId : "";
  return (
    <>
      {typeof error === "string" ? error : error.message}
      {requestId && <span className="block text-xs text-muted">Request id {requestId}</span>}
    </>
  );
}
