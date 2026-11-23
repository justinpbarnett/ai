export function deadlineSignal(timeoutMs: number, caller?: AbortSignal) {
  const deadline = AbortSignal.timeout(timeoutMs);
  return {
    deadline,
    signal: caller ? AbortSignal.any([caller, deadline]) : deadline,
  };
}
