// Strict runtime parsers for API responses. A parser either returns a value of the declared
// type or throws ApiContractError naming the first field that broke the contract; it never
// fills in a default for a field the server should have sent.
import { ApiContractError, isRecord } from "./shared";

export type Parser<T> = (value: unknown, path: string) => T;

function fail(path: string, expected: string): never {
  throw new ApiContractError(`Invalid API response: ${path} must be ${expected}`);
}

export const str: Parser<string> = (value, path) => (typeof value === "string" ? value : fail(path, "a string"));

export const num: Parser<number> = (value, path) =>
  typeof value === "number" && Number.isFinite(value) ? value : fail(path, "a number");

export const bool: Parser<boolean> = (value, path) => (typeof value === "boolean" ? value : fail(path, "a boolean"));

export const anyRecord: Parser<Record<string, unknown>> = (value, path) => (isRecord(value) ? value : fail(path, "an object"));

export function literal<const T extends string>(...values: T[]): Parser<T> {
  return (value, path) =>
    typeof value === "string" && (values as string[]).includes(value) ? (value as T) : fail(path, `one of ${values.join(", ")}`);
}

/** `null` is allowed; a missing field is not. */
export function nullable<T>(parser: Parser<T>): Parser<T | null> {
  return (value, path) => (value === null ? null : parser(value, path));
}

/** The field may be missing or null; both read as `undefined`. */
export function optional<T>(parser: Parser<T>): Parser<T | undefined> {
  return (value, path) => (value === undefined || value === null ? undefined : parser(value, path));
}

export function array<T>(parser: Parser<T>): Parser<T[]> {
  return (value, path) => (Array.isArray(value) ? value.map((item, index) => parser(item, `${path}[${index}]`)) : fail(path, "an array"));
}

export function record<T>(parser: Parser<T>): Parser<Record<string, T>> {
  return (value, path) => {
    const source = anyRecord(value, path);
    const out: Record<string, T> = {};
    for (const [key, item] of Object.entries(source)) out[key] = parser(item, `${path}.${key}`);
    return out;
  };
}

type Shape<S> = { [K in keyof S]-?: Parser<S[K]> };

/** Reads exactly the declared fields; every field of `S`, optional ones included, needs a parser. */
export function object<S>(shape: Shape<S>): Parser<S> {
  return (value, path) => {
    const source = anyRecord(value, path);
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(shape) as (keyof S & string)[]) {
      const parsed = shape[key](source[key], `${path}.${key}`);
      if (parsed !== undefined) out[key] = parsed;
    }
    return out as S;
  };
}

/** Turns a parser into the `(raw) => T` form `apiGet` and friends take. */
export function response<T>(parser: Parser<T>): (raw: unknown) => T {
  return (raw) => parser(raw, "response");
}

export function listResponse<T>(item: Parser<T>): (raw: unknown) => { items: T[] } {
  return response(object<{ items: T[] }>({ items: array(item) }));
}

export function itemResponse<T>(item: Parser<T>): (raw: unknown) => { item: T | null } {
  return response(object<{ item: T | null }>({ item: nullable(item) }));
}
