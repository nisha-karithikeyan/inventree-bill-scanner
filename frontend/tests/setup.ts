import '@testing-library/jest-dom/vitest';

// Mantine needs these browser APIs, which jsdom lacks.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false
  })
});
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(window as any).ResizeObserver = ResizeObserverStub;
window.HTMLElement.prototype.scrollIntoView = () => undefined;
