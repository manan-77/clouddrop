import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  ElementRef,
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

type Field = 'email' | 'password';
const FIELDS: readonly Field[] = ['email', 'password'];
const LABELS: Readonly<Record<Field, string>> = { email: 'Email', password: 'Password' };

@Component({
  selector: 'cd-login-page',
  imports: [ReactiveFormsModule, RouterLink, ButtonComponent, FieldErrorComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="cd-card">
      <h1>Sign in</h1>
      <form class="cd-form" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <div class="cd-field">
          <label for="login-email">Email</label>
          <input
            id="login-email"
            class="cd-input"
            type="email"
            formControlName="email"
            autocomplete="username"
            aria-describedby="login-email-error"
            [attr.aria-invalid]="emailMessage() ? 'true' : null"
            (blur)="validate('email')"
            (input)="edited('email')"
          />
          <cd-field-error fieldId="login-email-error" [message]="emailMessage()" />
        </div>
        <div class="cd-field">
          <label for="login-password">Password</label>
          <input
            id="login-password"
            class="cd-input"
            type="password"
            formControlName="password"
            autocomplete="current-password"
            aria-describedby="login-password-error"
            [attr.aria-invalid]="passwordMessage() ? 'true' : null"
            (blur)="validate('password')"
            (input)="edited('password')"
          />
          <cd-field-error fieldId="login-password-error" [message]="passwordMessage()" />
        </div>
        @if (formError(); as message) {
          <p class="cd-form-error" role="alert">{{ message }}</p>
        }
        <button cd-button type="submit" [busy]="submitting()">
          {{ submitting() ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>
      <p class="cd-hint">No account yet? <a routerLink="/register">Create one</a></p>
    </section>
  `,
})
export class LoginPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly resolver = inject(ErrorResolver);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  protected readonly form = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });
  protected readonly submitting = signal(false);
  protected readonly formError = signal<string | null>(null);
  private readonly localErrors = signal<Readonly<Partial<Record<Field, string | null>>>>({});
  private readonly serverErrors = signal<Readonly<Record<string, string>>>({});

  protected readonly emailMessage = computed(
    () => this.localErrors().email ?? this.serverErrors()['email'] ?? null,
  );
  protected readonly passwordMessage = computed(
    () => this.localErrors().password ?? this.serverErrors()['password'] ?? null,
  );

  protected validate(field: Field): void {
    this.localErrors.update((errors) => ({
      ...errors,
      [field]: validationMessage(this.form.controls[field], LABELS[field]),
    }));
  }

  /** Typing again dismisses the server's complaint about that field. */
  protected edited(field: Field): void {
    this.serverErrors.update((errors) =>
      Object.fromEntries(Object.entries(errors).filter(([name]) => name !== field)),
    );
    this.validate(field);
  }

  protected submit(): void {
    if (this.submitting()) {
      return;
    }
    FIELDS.forEach((field) => this.validate(field));
    const firstInvalid = FIELDS.find((field) => this.form.controls[field].invalid);
    if (firstInvalid) {
      this.host.nativeElement.querySelector<HTMLElement>(`#login-${firstInvalid}`)?.focus();
      return;
    }
    this.submitting.set(true);
    this.formError.set(null);
    this.serverErrors.set({});
    const { email, password } = this.form.getRawValue();
    this.auth
      .login(email, password)
      .pipe(
        finalize(() => this.submitting.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: () => void this.router.navigateByUrl('/'),
        error: (error: unknown) => {
          const resolved = this.resolver.resolve(error);
          this.formError.set(resolved.message);
          this.serverErrors.set(resolved.fieldErrors);
        },
      });
  }
}
