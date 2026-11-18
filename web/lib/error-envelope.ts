// The engine's error shape, for errors the web server raises itself (proxy refusals, engine
// unreachable), so the browser reads one format. The request id is generated here, never
// taken from the client.
export function errorResponse(status: number, code: string, message: string): Response {
  const requestId = crypto.randomUUID();
  return Response.json(
    { error: { code, message, request_id: requestId }, detail: message },
    { status, headers: { "X-Request-ID": requestId } },
  );
}
