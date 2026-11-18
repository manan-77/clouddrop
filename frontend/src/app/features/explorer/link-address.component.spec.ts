import { DOCUMENT } from '@angular/common';
import { type ComponentFixture, TestBed } from '@angular/core/testing';

import { LinkAddressComponent } from './link-address.component';

describe('LinkAddressComponent', () => {
  let fixture: ComponentFixture<LinkAddressComponent>;
  const navigatorOf = () => TestBed.inject(DOCUMENT).defaultView!.navigator;
  const original = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(navigator), 'clipboard');
  const root = () => fixture.nativeElement as HTMLElement;

  const setup = () => {
    fixture = TestBed.createComponent(LinkAddressComponent);
    fixture.componentRef.setInput('address', 'https://x.test/s#tok');
    fixture.detectChanges();
  };
  const setClipboard = (value: unknown) =>
    Object.defineProperty(navigatorOf(), 'clipboard', { value, configurable: true });
  afterEach(() => {
    // Remove what a test defined on the shared navigator.
    delete (navigatorOf() as unknown as { clipboard?: unknown }).clipboard;
    if (original) {
      Object.defineProperty(Object.getPrototypeOf(navigator), 'clipboard', original);
    }
  });

  it('showsTheAddressSelectedAndFocused', async () => {
    setup();
    await fixture.whenStable();
    const field = root().querySelector('input') as HTMLInputElement;
    expect(field.value).toBe('https://x.test/s#tok');
    expect(document.activeElement).toBe(field);
    expect(field.selectionStart).toBe(0);
    expect(field.selectionEnd).toBe(field.value.length);
  });

  it('copy_writesTheAddressAndSaysSo', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    setup();
    (root().querySelector('button') as HTMLButtonElement).click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(writeText).toHaveBeenCalledWith('https://x.test/s#tok');
    expect(root().textContent).toContain('Copied.');
  });

  it('copy_aRefusedWriteTellsTheUserToCopyByHand', async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error('denied')) });
    setup();
    (root().querySelector('button') as HTMLButtonElement).click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root().textContent).toContain('Could not copy.');
  });

  it('copy_withoutAClipboardTellsTheUserToCopyByHand', () => {
    setClipboard(undefined);
    setup();
    (root().querySelector('button') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(root().textContent).toContain('Select the address and copy it.');
  });
});
