/**
 * One key per submit intent (idempotency-conflicts.md section 1).
 *
 * The key changes only when the form signature changes: a network retry of the
 * same intent reuses it, editing any field produces a new one.
 */

export function createIdempotencyKey(): string {
  const webCrypto = globalThis.crypto;
  if (webCrypto && typeof webCrypto.randomUUID === "function") {
    return webCrypto.randomUUID();
  }
  return `idem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortValue);
  }
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(record).sort()) {
      sorted[key] = sortValue(record[key]);
    }
    return sorted;
  }
  return value;
}

/** Deterministic form signature: key order does not create a new intent. */
export function stableSignature(value: unknown): string {
  return JSON.stringify(sortValue(value));
}

export class IdempotencyIntent {
  private readonly generate: () => string;
  private signature: string | null = null;
  private key: string | null = null;

  constructor(generate: () => string = createIdempotencyKey) {
    this.generate = generate;
  }

  keyFor(form: unknown): string {
    const signature = stableSignature(form);
    if (this.key === null || signature !== this.signature) {
      this.signature = signature;
      this.key = this.generate();
    }
    return this.key;
  }

  get current(): string | null {
    return this.key;
  }

  reset(): void {
    this.signature = null;
    this.key = null;
  }
}
