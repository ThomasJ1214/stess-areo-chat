/** Decimal and scientific notation only; reject hex and other JavaScript literals. */
export function parseNumberInput(raw: string): number | null {
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw.trim()))
    return null;
  const number = Number(raw);
  return Number.isFinite(number) ? number : null;
}

export function numberInputIssue(
  raw: string,
  min?: number,
  max?: number,
): string {
  if (!raw.trim()) return "";
  const value = parseNumberInput(raw);
  if (value === null) return "Enter a finite decimal number.";
  if (min !== undefined && value < min) return `Must be at least ${min}.`;
  if (max !== undefined && value > max) return `Must be at most ${max}.`;
  return "";
}

/** Prevent running with an unfinished numeric edit and silently using an older value. */
export function assertValidNumberFields() {
  const input = document.querySelector<HTMLInputElement>(
    '.inspector input[aria-invalid="true"]',
  );
  if (!input) return;
  input.focus();
  throw new Error(
    `Correct ${input.getAttribute("aria-label") || "the highlighted number"} before continuing.`,
  );
}
