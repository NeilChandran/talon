/**
 * Module-level in-memory cache.
 * Survives client-side navigation in Next.js App Router.
 * Data older than `ttl` ms is stale and triggers a background refresh.
 */

interface Entry {
  data: unknown;
  at: number;
}

const store = new Map<string, Entry>();

// Default TTL: 2 minutes — long enough that every page load is instant
export const DEFAULT_TTL = 120_000;

/** Return cached value if it exists (even if stale). */
export function peek<T>(key: string): T | undefined {
  return store.has(key) ? (store.get(key)!.data as T) : undefined;
}

/** Return cached value only if fresh (within ttl). */
export function get<T>(key: string, ttl = DEFAULT_TTL): T | undefined {
  const v = store.get(key);
  if (!v) return undefined;
  if (Date.now() - v.at > ttl) return undefined;
  return v.data as T;
}

/** Write a value into the cache. */
export function put(key: string, data: unknown): void {
  store.set(key, { data, at: Date.now() });
}

/** Invalidate a key so the next read fetches fresh. */
export function invalidate(key: string): void {
  store.delete(key);
}

/** Check if a cached value is stale. */
export function isStale(key: string, ttl = DEFAULT_TTL): boolean {
  const v = store.get(key);
  if (!v) return true;
  return Date.now() - v.at > ttl;
}
