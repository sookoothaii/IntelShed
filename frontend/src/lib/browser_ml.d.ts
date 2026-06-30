/**
 * Ambient declarations for optional browser ML dependencies.
 * These packages are loaded via dynamic import at runtime and are
 * not required for the core app to function.
 */

declare module '@huggingface/transformers' {
  export function pipeline(
    task: string,
    model: string,
    options?: { quantized?: boolean; [key: string]: unknown }
  ): Promise<any>;
  export const env: { [key: string]: unknown };
}

declare module '@xenova/transformers' {
  export function pipeline(
    task: string,
    model: string,
    options?: { quantized?: boolean; [key: string]: unknown }
  ): Promise<any>;
  export const env: { [key: string]: unknown };
}
