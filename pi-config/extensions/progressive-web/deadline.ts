export function deadlineSignal(timeoutMs: number, caller?: AbortSignal) {
  const deadline = AbortSignal.timeout(timeoutMs);
  return {
    deadline,
    signal: caller ? AbortSignal.any([caller, deadline]) : deadline,
  };
}

export function deadlineFailure(
  error: unknown,
  caller: AbortSignal | undefined,
  deadline: AbortSignal,
  timeoutMessage: string,
): unknown {
  caller?.throwIfAborted();
  return deadline.aborted ? new Error(timeoutMessage) : error;
}
