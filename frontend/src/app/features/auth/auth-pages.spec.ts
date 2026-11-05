import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { ENVELOPE, provideAuthTesting, TOKENS, USER } from '@core/auth/auth-testing';
import { LoginPage } from './login.page';
import { RegisterPage } from './register.page';

const UNAUTHORIZED = { status: 401, statusText: 'Unauthorized' };

function fill(root: HTMLElement, id: string, value: string): void {
  const input = root.querySelector(`#${id}`) as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event('input'));
  input.dispatchEvent(new Event('blur'));
}
function submit(root: HTMLElement): void {
  (root.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
}
const text = (root: HTMLElement, selector: string): string =>
  root.querySelector(selector)?.textContent?.trim() ?? '';

describe('LoginPage', () => {
  const setup = async () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    const router = TestBed.inject(Router);
    const navigate = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    const fixture: ComponentFixture<LoginPage> = TestBed.createComponent(LoginPage);
    await fixture.whenStable();
    return {
      fixture,
      root: fixture.nativeElement as HTMLElement,
      backend: TestBed.inject(HttpTestingController),
      navigate,
    };
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('submit_emptyForm_showsRequiredMessagesAndSendsNothing', async () => {
    const { fixture, root, backend } = await setup();
    submit(root);
    await fixture.whenStable();
    expect(text(root, '#login-email-error')).toBe('Email is required.');
    expect(text(root, '#login-password-error')).toBe('Password is required.');
    expect(root.querySelector('#login-email')?.getAttribute('aria-invalid')).toBe('true');
    backend.expectNone('/api/v1/auth/login');
  });

  it('submit_invalidEmail_showsEmailMessage', async () => {
    const { fixture, root, backend } = await setup();
    fill(root, 'login-email', 'not-an-email');
    fill(root, 'login-password', 'whatever');
    submit(root);
    await fixture.whenStable();
    expect(text(root, '#login-email-error')).toBe('Enter a valid email address.');
    backend.expectNone('/api/v1/auth/login');
  });

  it('submit_valid_isBusyThenSignsInAndNavigatesHome', async () => {
    const { fixture, root, backend, navigate } = await setup();
    fill(root, 'login-email', 'ada@example.com');
    fill(root, 'login-password', 'a-long-password');
    submit(root);
    await fixture.whenStable();
    const button = root.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.textContent).toContain('Signing in');
    backend.expectOne('/api/v1/auth/login').flush(TOKENS('t1'));
    backend.expectOne('/api/v1/auth/me').flush(USER);
    await fixture.whenStable();
    expect(navigate).toHaveBeenCalledWith('/');
    expect(button.disabled).toBe(false);
  });

  it('submit_pressedTwiceWhileInFlight_sendsOneRequest', async () => {
    const { fixture, root, backend } = await setup();
    fill(root, 'login-email', 'ada@example.com');
    fill(root, 'login-password', 'a-long-password');
    submit(root);
    submit(root);
    await fixture.whenStable();
    expect(backend.match('/api/v1/auth/login').length).toBe(1);
  });

  it('submit_wrongPassword_showsMappedMessageAndAllowsRetry', async () => {
    const { fixture, root, backend, navigate } = await setup();
    fill(root, 'login-email', 'ada@example.com');
    fill(root, 'login-password', 'wrong-password');
    submit(root);
    backend.expectOne('/api/v1/auth/login').flush(ENVELOPE('invalid_credentials'), UNAUTHORIZED);
    await fixture.whenStable();
    expect(text(root, '[role="alert"]')).toBe('Incorrect email or password.');
    expect((root.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
  });
});

describe('RegisterPage', () => {
  const setup = async () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    const fixture = TestBed.createComponent(RegisterPage);
    await fixture.whenStable();
    return {
      fixture,
      root: fixture.nativeElement as HTMLElement,
      backend: TestBed.inject(HttpTestingController),
      navigate,
    };
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  const fillAll = (root: HTMLElement, password = 'a-long-password') => {
    fill(root, 'register-name', 'Ada');
    fill(root, 'register-email', 'ada@example.com');
    fill(root, 'register-password', password);
  };

  it('submit_shortPassword_showsLengthMessageAndSendsNothing', async () => {
    const { fixture, root, backend } = await setup();
    fillAll(root, 'short');
    submit(root);
    await fixture.whenStable();
    expect(text(root, '#register-password-error')).toBe('Password must be at least 12 characters.');
    backend.expectNone('/api/v1/auth/register');
  });

  it('submit_valid_registersSignsInAndNavigatesHome', async () => {
    const { fixture, root, backend, navigate } = await setup();
    fillAll(root);
    submit(root);
    backend.expectOne('/api/v1/auth/register').flush(USER);
    backend.expectOne('/api/v1/auth/login').flush(TOKENS('t1'));
    backend.expectOne('/api/v1/auth/me').flush(USER);
    await fixture.whenStable();
    expect(navigate).toHaveBeenCalledWith('/');
  });

  it('submit_emailAlreadyRegistered_showsInlineEmailMessage', async () => {
    const { fixture, root, backend } = await setup();
    fillAll(root);
    submit(root);
    backend
      .expectOne('/api/v1/auth/register')
      .flush(ENVELOPE('conflict'), { status: 409, statusText: 'Conflict' });
    await fixture.whenStable();
    expect(text(root, '#register-email-error')).toBe('An account with this email already exists.');
    expect(root.querySelector('[role="alert"]')).toBeNull();
  });

  it('submit_serverValidationDetails_areShownNextToTheirFields', async () => {
    const { fixture, root, backend } = await setup();
    fillAll(root);
    submit(root);
    backend
      .expectOne('/api/v1/auth/register')
      .flush(ENVELOPE('validation_error', [{ field: 'password', message: 'Rejected by server' }]), {
        status: 422,
        statusText: 'Unprocessable',
      });
    await fixture.whenStable();
    expect(text(root, '#register-password-error')).toBe('Rejected by server');
  });

  describe('auth forms behaviour', () => {
    afterEach(() => TestBed.inject(HttpTestingController).verify());

    it('loginSubmitInvalid_movesFocusToTheFirstInvalidField', async () => {
      TestBed.configureTestingModule({ providers: provideAuthTesting() });
      const fixture = TestBed.createComponent(LoginPage);
      await fixture.whenStable();
      const root = fixture.nativeElement as HTMLElement;
      submit(root);
      await fixture.whenStable();
      expect(document.activeElement).toBe(root.querySelector('#login-email'));
    });

    it('loginServerFieldError_disappearsWhenTheFieldIsEditedAgain', async () => {
      TestBed.configureTestingModule({ providers: provideAuthTesting() });
      vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
      const fixture = TestBed.createComponent(LoginPage);
      await fixture.whenStable();
      const root = fixture.nativeElement as HTMLElement;
      fill(root, 'login-email', 'ada@example.com');
      fill(root, 'login-password', 'whatever-it-is');
      submit(root);
      TestBed.inject(HttpTestingController)
        .expectOne('/api/v1/auth/login')
        .flush(ENVELOPE('validation_error', [{ field: 'email', message: 'Server says no' }]), {
          status: 422,
          statusText: 'Unprocessable',
        });
      await fixture.whenStable();
      expect(text(root, '#login-email-error')).toBe('Server says no');
      fill(root, 'login-email', 'ada2@example.com');
      await fixture.whenStable();
      expect(text(root, '#login-email-error')).toBe('');
    });

    it('registerWhitespaceOnlyName_isRejectedAsRequired', async () => {
      TestBed.configureTestingModule({ providers: provideAuthTesting() });
      const fixture = TestBed.createComponent(RegisterPage);
      await fixture.whenStable();
      const root = fixture.nativeElement as HTMLElement;
      fill(root, 'register-name', '   ');
      fill(root, 'register-email', 'ada@example.com');
      fill(root, 'register-password', 'a-long-password');
      submit(root);
      await fixture.whenStable();
      expect(text(root, '#register-name-error')).toBe('Name is required.');
      TestBed.inject(HttpTestingController).expectNone('/api/v1/auth/register');
    });

    it('registerSucceedsButSignInFails_sendsTheUserToSignInInsteadOfRegisteringAgain', async () => {
      TestBed.configureTestingModule({ providers: provideAuthTesting() });
      const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
      const fixture = TestBed.createComponent(RegisterPage);
      await fixture.whenStable();
      const root = fixture.nativeElement as HTMLElement;
      fill(root, 'register-name', 'Ada');
      fill(root, 'register-email', 'ada@example.com');
      fill(root, 'register-password', 'a-long-password');
      submit(root);
      const backend = TestBed.inject(HttpTestingController);
      backend.expectOne('/api/v1/auth/register').flush(USER);
      backend
        .expectOne('/api/v1/auth/login')
        .flush(null, { status: 500, statusText: 'Server Error' });
      await fixture.whenStable();
      expect(navigate).toHaveBeenCalledWith('/login');
    });
  });
});
