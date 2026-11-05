import { type ValidatorFn } from '@angular/forms';

/** Rejects text made only of whitespace (the server trims, so it would store an empty value). */
export const notBlank: ValidatorFn = (control) =>
  typeof control.value === 'string' && control.value.length > 0 && control.value.trim() === ''
    ? { blank: true }
    : null;
