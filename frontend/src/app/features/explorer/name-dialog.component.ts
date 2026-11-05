import {
  ChangeDetectionStrategy,
  Component,
  inject,
  input,
  type OnInit,
  output,
  signal,
} from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { notBlank } from '@shared/forms/validators';
import { validationMessage } from '@shared/forms/validation-messages';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';
import { FieldErrorComponent } from '@shared/ui/field-error/field-error.component';

/** Asks for one name (create or rename). The parent runs the request and reports busy/error. */
@Component({
  selector: 'cd-name-dialog',
  imports: [ReactiveFormsModule, ButtonComponent, DialogComponent, FieldErrorComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <cd-dialog [title]="title()" (dismissed)="dismissed.emit()">
      <form class="cd-form" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <div class="cd-field">
          <label for="name-dialog-input">{{ label() }}</label>
          <input
            id="name-dialog-input"
            class="cd-input"
            type="text"
            autocomplete="off"
            aria-describedby="name-dialog-error"
            formControlName="name"
            [attr.aria-invalid]="message() ? 'true' : null"
            (input)="message.set(null)"
          />
          <cd-field-error fieldId="name-dialog-error" [message]="message()" />
        </div>
        @if (error(); as text) {
          <p class="cd-form-error" role="alert">{{ text }}</p>
        }
        <div class="cd-actions">
          <button cd-button variant="secondary" type="button" (click)="dismissed.emit()">
            Cancel
          </button>
          <button cd-button type="submit" [busy]="busy()">{{ submitLabel() }}</button>
        </div>
      </form>
    </cd-dialog>
  `,
})
export class NameDialogComponent implements OnInit {
  readonly title = input.required<string>();
  readonly label = input.required<string>();
  readonly submitLabel = input.required<string>();
  readonly initialValue = input('');
  readonly busy = input(false);
  readonly error = input<string | null>(null);
  readonly submitted = output<string>();
  readonly dismissed = output<void>();

  protected readonly form = inject(NonNullableFormBuilder).group({
    name: ['', [Validators.required, notBlank, Validators.maxLength(255)]],
  });
  protected readonly message = signal<string | null>(null);

  ngOnInit(): void {
    this.form.controls.name.setValue(this.initialValue());
  }

  protected submit(): void {
    if (this.busy()) {
      return;
    }
    const problem = validationMessage(this.form.controls.name, 'Name');
    this.message.set(problem);
    if (!problem) {
      this.submitted.emit(this.form.controls.name.value.trim());
    }
  }
}
