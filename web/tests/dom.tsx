import { createRequire } from "node:module";
import { resolve } from "node:path";
import { afterEach } from "node:test";
import { JSDOM } from "jsdom";
import { act, type ReactNode } from "react";
import type { Root } from "react-dom/client";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost/",
});
export const window = dom.window;

for (const key of [
  "window", "document", "navigator", "HTMLElement", "HTMLInputElement",
  "HTMLTextAreaElement", "Event", "MouseEvent", "File", "Blob", "FormData",
]) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    writable: true,
    value: key === "window" ? window : window[key as keyof typeof window],
  });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// jsdom has no native file picker or DataTransfer. Build its actual FileList
// so FormData and native form.reset() still exercise real DOM file handling.
const load = createRequire(resolve("package.json"));
const { create: createFileList } = load("jsdom/lib/generated/idl/FileList.js");
const { implForWrapper } = load("jsdom/lib/generated/idl/utils.js");
class TestDataTransfer {
  files: FileList = createFileList(window);
  items = {
    add: (file: File) => implForWrapper(this.files).push(implForWrapper(file)),
  };
}
Object.assign(globalThis, { DataTransfer: TestDataTransfer });

let root: Root | undefined;
export async function mount(element: ReactNode) {
  const container = document.createElement("div");
  document.body.append(container);
  // React DOM must see the installed window when it initializes event support.
  const { createRoot } = await import("react-dom/client");
  root = createRoot(container);
  await act(async () => root!.render(element));
  return container;
}

export async function unmount() {
  await act(async () => root?.unmount());
  root = undefined;
  document.body.replaceChildren();
}
afterEach(unmount);

export async function selectFile(input: HTMLInputElement, file: File) {
  const transfer = new TestDataTransfer();
  transfer.items.add(file);
  await act(async () => {
    input.files = transfer.files;
    input.dispatchEvent(new window.Event("change", { bubbles: true }));
  });
}

export async function typeText(input: HTMLTextAreaElement, text: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")!
      .set!.call(input, text);
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

export const imageStrings = {
  label: "Or a screenshot", hint: "Choose an image", browse: "Choose file",
  preview: "Selected screenshot", remove: "Remove", preparing: "Preparing image",
  tooLarge: "Image is too large", wrongType: "Unsupported image type",
};
