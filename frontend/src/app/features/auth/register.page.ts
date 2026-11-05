import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { AuthService } from '@core/auth/auth.service';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { validationMessage } from '@shared/forms/validation-messages';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { FieldErrorComponent } from '@shared/ui/field-error/field-error.component';

type Field = 'display_name' | 'email' | 'password';
const LABELS: Readonly<Record<Field, string>> = {
  display_name: 'Name',
  email: 'Email',
  password: 'Password',
};

@Component({
  selector: 'cd-register-page',
  imports: [ReactiveFormsModule, RouterLink, ButtonComponent, FieldErrorComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="cd-card">
      <h1>Create your account</h1>
      <form class="cd-form" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <div class="cd-field">
          <label for="register-name">Name</label>
          <input
            id="register-name"
            class="cd-input"
            type="text"
            formControlName="display_name"
            autocomplete="name"
            aria-describedby="register-name-error"
            [attr.aria-invalid]="messages().display_name ? 'true' : null"
            (blur)="validate('display_name')"
            (input)="validate('display_name')"
          />
          <cd-field-error fieldId="register-name-error" [message]="messages().display_name" />
        </div>
        <div class="cd-field">
          <label for="register-email">Email</label>
          <input
            id="register-email"
            class="cd-input"
            type="email"
            formControlName="email"
            autocomplete="email"
            aria-describedby="register-email-error"
            [attr.aria-invalid]="messages().email ? 'true' : null"
            (blur)="validate('email')"
            (input)="validate('email')"
          />
          <cd-field-error fieldId="register-email-error" [message]="messages().email" />
        </div>
        <div class="cd-field">
          <label for="register-password">Password</label>
          <input
            id="register-password"
            class="cd-input"
            type="password"
            formControlName="password"
            autocomplete="new-password"
            aria-describedby="register-password-hint register-password-error"
            [attr.aria-invalid]="messages().password ? 'true' : null"
            (blur)="validate('password')"
            (input)="validate('password')"
          />
          <p id="register-password-hint" class="cd-hint">12 to 128 characters.</p>
          <cd-field-error fieldId="register-password-error" [message]="messages().password" />
        </div>
        @if (formError(); as message) {
          <p class="cd-form-error" role="alert">{{ message }}</p>
        }
        <button cd-button type="submit" [busy]="submitting()">
          {{ submitting() ? 'Creating account…' : 'Create account' }}
        </button>
      </form>
      <p class="cd-hint">Already registered? <a routerLink="/login">Sign in</a></p>
    </section>
  `,
})
export class RegisterPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly resolver = inject(ErrorResolver);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly form = inject(NonNullableFormBuilder).group({
    display_name: ['', [Validators.required, Validators.maxLength(100)]],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(12), Validators.maxLength(128)]],
  });
  protected readonly submitting = signal(false);
  protected readonly formError = signal<string | null>(null);
  private readonly localErrors = signal<Readonly<Partial<Record<Field, string | null>>>>({});
  private readonly serverErrors = signal<Readonly<Record<string, string>>>({});

  protected readonly messages = computed(() => ({
    display_name: this.localErrors().display_name ?? this.serverErrors()['display_name'] ?? null,
    email: this.localErrors().email ?? this.serverErrors()['email'] ?? null,
    password: this.localErrors().password ?? this.serverErrors()['password'] ?? null,
  }));

  protected validate(field: Field): void {
    this.localErrors.update((errors) => ({
      ...errors,
      [field]: validationMessage(this.form.controls[field], LABELS[field]),
    }));
  }

  protected submit(): void {
    if (this.submitting()) {
      return;
    }
    (Object.keys(LABELS) as Field[]).forEach((field) => this.validate(field));
    if (this.form.invalid) {
      return;
    }
    this.submitting.set(true);
    this.formError.set(null);
    this.serverErrors.set({});
    const { email, password, display_name: displayName } = this.form.getRawValue();
    this.auth
      .registerAndSignIn(email, password, displayName)
      .pipe(
        finalize(() => this.submitting.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: () => void this.router.navigateByUrl('/'),
        error: (error: unknown) => {
          const resolved = this.resolver.resolve(error);
          if (resolved.code === 'conflict') {
            this.serverErrors.set({ email: 'An account with this email already exists.' });
          } else {
            this.formError.set(resolved.message);
            this.serverErrors.set(resolved.fieldErrors);
          }
        },
      });
  }
}
