import { type ValidatorFn } from '@angular/forms';

/** Rejects text made only of whitespace (the server trims, so it would store an empty value). */
export const notBlank: ValidatorFn = (control) =>
  typeof control.value === 'string' && control.value.length > 0 && control.value.trim() === ''
    ? { blank: true }
    : null;

/** Needs a dotted domain, like the server's email check (Angular's own check accepts `a@b`). */
export const dottedEmail: ValidatorFn = (control) =>
  typeof control.value !== 'string' ||
  control.value.length === 0 ||
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(control.value.trim())
    ? null
    : { email: true };
