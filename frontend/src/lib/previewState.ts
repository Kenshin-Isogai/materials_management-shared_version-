export function resolvePreviewSelection<T>(
  selections: Record<string | number, T | null>,
  rowNumber: string | number,
  fallback: T | null
): T | null {
  return Object.prototype.hasOwnProperty.call(selections, rowNumber)
    ? selections[rowNumber] ?? null
    : fallback;
}

export function formatActionError(prefix: string, error: unknown): string {
  const rawMessage = error instanceof Error ? error.message : String(error ?? "");
  const message = rawMessage.trim();
  return message ? `${prefix}: ${message}` : prefix;
}
