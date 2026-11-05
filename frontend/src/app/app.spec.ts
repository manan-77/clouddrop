import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([])],
    }).compileComponents();
  });

  it('render_default_showsSkipLinkLandmarksAndBrand', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('a.skip-link')?.getAttribute('href')).toBe('#main');
    expect(root.querySelector('nav[aria-label="Primary"]')).not.toBeNull();
    expect(root.querySelector('main#main')).not.toBeNull();
    expect(root.querySelector('.brand')?.textContent).toContain('CloudDrop AI');
  });

  it('skipLink_click_movesFocusToMainWithoutNavigating', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const root = fixture.nativeElement as HTMLElement;
    const click = new MouseEvent('click', { bubbles: true, cancelable: true });
    root.querySelector('a.skip-link')?.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);
    expect(TestBed.inject(DOCUMENT).activeElement).toBe(root.querySelector('main#main'));
  });
});
