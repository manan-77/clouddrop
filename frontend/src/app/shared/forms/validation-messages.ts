import { type AbstractControl } from '@angular/forms';

/** Client-side validation text. It mirrors the server rules; the server stays the authority. */
export function validationMessage(control: AbstractControl, label: string): string | null {
  const errors = control.errors;
  if (!errors) {
    return null;
  }
  if (errors['required'] || errors['blank']) {
    return `${label} is required.`;
  }
  if (errors['email']) {
    return 'Enter a valid email address.';
  }
  if (errors['minlength']) {
    return `${label} must be at least ${errors['minlength'].requiredLength} characters.`;
  }
  if (errors['maxlength']) {
    return `${label} must be at most ${errors['maxlength'].requiredLength} characters.`;
  }
  return `${label} is not valid.`;
}
