import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";
import { act } from "react";

import { ImageDropZone } from "../components/ImageDropZone";
import { deferred, imageStrings, mount, selectFile, unmount, window } from "./dom";

const originalCreateImageBitmap = Object.getOwnPropertyDescriptor(globalThis, "createImageBitmap");
let decoding: Map<File, ReturnType<typeof deferred<ImageBitmap>>>;
let created: { url: string; file: Blob | MediaSource }[];
let revoked: string[];

beforeEach(() => {
  decoding = new Map();
  created = [];
  revoked = [];
  Object.defineProperty(globalThis, "createImageBitmap", {
    configurable: true,
    value: (file: File) => {
      const job = deferred<ImageBitmap>();
      decoding.set(file, job);
      return job.promise;
    },
  });
  mock.method(URL, "createObjectURL", (file: Blob | MediaSource) => {
    const url = `blob:screenshot-${created.length + 1}`;
    created.push({ url, file });
    return url;
  });
  mock.method(URL, "revokeObjectURL", (url: string) => revoked.push(url));
  mock.method(window.HTMLCanvasElement.prototype, "getContext", () => ({
    fillStyle: "",
    fillRect() {},
    drawImage() {},
  }));
  mock.method(window.HTMLCanvasElement.prototype, "toBlob", (callback: BlobCallback) => {
    callback(new File(["prepared screenshot"], "prepared.jpg", { type: "image/jpeg" }));
  });
});

afterEach(() => {
  mock.restoreAll();
  if (originalCreateImageBitmap) {
    Object.defineProperty(globalThis, "createImageBitmap", originalCreateImageBitmap);
  } else {
    Reflect.deleteProperty(globalThis, "createImageBitmap");
  }
});

function screenshot(name: string, large = true) {
  return new File([new Uint8Array(large ? 800 * 1024 : 32)], name, { type: "image/png" });
}

async function picker() {
  const busy: boolean[] = [];
  const container = await mount(
    <form><ImageDropZone strings={imageStrings} onBusy={(value) => busy.push(value)} /></form>,
  );
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  const form = container.querySelector("form")!;
  const hint = () => document.getElementById(input.getAttribute("aria-describedby")!)!.textContent;
  return { container, input, form, hint, busy };
}

async function finish(file: File, outcome: "resolve" | "reject" = "resolve") {
  const job = decoding.get(file);
  assert.ok(job, "the large screenshot must be awaiting decoding");
  const close = mock.fn();
  await act(async () => {
    if (outcome === "reject") job.reject(new Error("decode failed"));
    else job.resolve({ width: 1600, height: 900, close } as unknown as ImageBitmap);
  });
  if (outcome === "resolve") assert.equal(close.mock.callCount(), 1);
}

for (const outcome of ["resolve", "reject"] as const) {
  test(`an earlier decode that ${outcome}s cannot change a newer pending selection or its busy state`, async () => {
    const { container, input, form, hint, busy } = await picker();
    const first = screenshot("first.png");
    const second = screenshot("second.png");
    await selectFile(input, first);
    await selectFile(input, second);

    await finish(first, outcome);

    assert.equal(input.files?.[0], second);
    assert.equal(new FormData(form).get("image"), second);
    assert.equal(container.querySelector("img"), null);
    assert.equal(container.querySelector('[role="alert"]'), null);
    assert.equal(hint(), imageStrings.preparing);
    assert.deepEqual(busy, [true, true]);
    assert.equal(created.length, 0);

    await finish(second);

    assert.equal(input.files?.[0]?.name, "second.jpg");
    assert.equal((new FormData(form).get("image") as File).name, "second.jpg");
    assert.equal(container.querySelector("img")?.getAttribute("src"), created[0].url);
    assert.match(container.textContent ?? "", /second\.jpg/);
    assert.equal(hint(), imageStrings.hint);
    assert.deepEqual(busy, [true, true, false]);
  });
}

test("the latest completed screenshot survives an earlier decode finishing afterward", async () => {
  const { container, input, busy } = await picker();
  const first = screenshot("first.png");
  const second = screenshot("second.png");
  await selectFile(input, first);
  await selectFile(input, second);
  await finish(second);
  const selected = input.files?.[0];
  const preview = container.querySelector("img")?.getAttribute("src");

  await finish(first);

  assert.equal(input.files?.[0], selected);
  assert.equal(selected?.name, "second.jpg");
  assert.equal(container.querySelector("img")?.getAttribute("src"), preview);
  assert.deepEqual(busy, [true, true, false]);
  assert.equal(created.length, 1);
  assert.deepEqual(revoked, []);
});

test("removing a screenshot cancels a pending replacement and releases preview URLs", async () => {
  const { container, input, form, hint, busy } = await picker();
  await selectFile(input, screenshot("original.png", false));
  const originalUrl = created[0].url;
  await selectFile(input, screenshot("replacement.png", false));
  const replacementUrl = created[1].url;
  assert.deepEqual(revoked, [originalUrl]);
  const pending = screenshot("pending.png");
  await selectFile(input, pending);

  const remove = container.querySelector("button")!;
  assert.equal(remove.textContent, imageStrings.remove);
  await act(async () => remove.click());

  assert.equal(input.files?.length, 0);
  assert.equal((new FormData(form).get("image") as File).size, 0);
  assert.equal(container.querySelector("img"), null);
  assert.equal(hint(), imageStrings.hint);
  assert.equal(busy.at(-1), false);
  assert.deepEqual(revoked, [originalUrl, replacementUrl]);
  const callbacksAfterRemoval = [...busy];

  await finish(pending);

  assert.equal(input.files?.length, 0);
  assert.equal(container.querySelector("img"), null);
  assert.equal(container.querySelector('[role="alert"]'), null);
  assert.deepEqual(busy, callbacksAfterRemoval);
  assert.equal(created.length, 2);
  await unmount();
  assert.deepEqual(revoked, [originalUrl, replacementUrl]);
});

test("a newer invalid selection stays rejected after an earlier screenshot finishes", async () => {
  const { container, input, hint, busy } = await picker();
  const pending = screenshot("pending.png");
  await selectFile(input, pending);
  await selectFile(input, new File(["text"], "notes.txt", { type: "text/plain" }));

  await finish(pending);

  assert.equal(input.files?.length, 0);
  assert.equal(container.querySelector("img"), null);
  assert.equal(container.querySelector('[role="alert"]')?.textContent, imageStrings.wrongType);
  assert.equal(hint(), imageStrings.hint);
  assert.deepEqual(busy, [true, false]);
  assert.equal(created.length, 0);
});

test("unmount releases the preview and pending work cannot create URLs or report busy changes", async () => {
  const { input, busy } = await picker();
  await selectFile(input, screenshot("original.png", false));
  const preview = created[0].url;
  const pending = screenshot("pending.png");
  await selectFile(input, pending);
  const callbacksBeforeUnmount = [...busy];

  await unmount();
  assert.deepEqual(revoked, [preview]);
  await finish(pending);

  assert.deepEqual(busy, callbacksBeforeUnmount);
  assert.equal(created.length, 1);
  assert.deepEqual(revoked, [preview]);
  assert.equal(document.body.childElementCount, 0);
});
