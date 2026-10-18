import { imageStrings, mount, selectFile, typeText } from "./dom";
import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";
import { act, type ReactNode } from "react";
import { AnalyzeForm } from "../components/AnalyzeForm";

const strings = {
  label: "Message to check", placeholder: "Paste a message", submit: "Check",
  submitting: "Checking", counter: "{n} / {max}", turnstileHint: "Confirm",
  image: imageStrings,
};

beforeEach(() => {
  mock.method(URL, "createObjectURL", () => "blob:test-screenshot");
  mock.method(URL, "revokeObjectURL", () => {});
});
afterEach(() => mock.restoreAll());

test("a fulfilled error action retains text and screenshot for an identical retry", async () => {
  const submitted: { text: string; name: string; size: number }[] = [];
  const action = async (_previous: ReactNode, data: FormData) => {
    const image = data.get("image") as File;
    submitted.push({ text: String(data.get("text")), name: image.name, size: image.size });
    return <p role="alert">The check could not be completed.</p>;
  };
  const view = await mount(<AnalyzeForm action={action} strings={strings} />);
  const form = view.querySelector("form")!;
  const text = view.querySelector("textarea")!;
  const input = view.querySelector<HTMLInputElement>('input[type="file"]')!;
  const message = "Please check this suspicious message.";
  const screenshot = new File(["synthetic image bytes"], "message.png", { type: "image/png" });
  await typeText(text, message);
  await selectFile(input, screenshot);
  let resets = 0;
  form.addEventListener("reset", () => resets++);

  for (let attempt = 0; attempt < 2; attempt++) {
    await act(async () => form.requestSubmit());
    assert.equal(view.querySelector('[role="alert"]')?.textContent,
      "The check could not be completed.");
    assert.equal(text.value, message);
    assert.equal(input.files?.[0]?.name, screenshot.name);
    assert.equal(view.querySelector("img")?.getAttribute("src"), "blob:test-screenshot");
    assert.ok(view.textContent?.includes(`${message.length} / 8000`));
  }

  assert.equal(resets, 2, "both real React actions attempted a native form reset");
  assert.deepEqual(submitted, Array(2).fill({
    text: message, name: screenshot.name, size: screenshot.size,
  }));

  // Explicit removal still clears the native field, unlike the prevented resets.
  const remove = [...view.querySelectorAll("button")].find((button) => button.textContent === "Remove")!;
  await act(async () => remove.click());
  assert.equal(input.files?.length, 0);
  assert.equal(view.querySelector("img"), null);
  assert.equal((new FormData(form).get("image") as File).size, 0);
});

test("a successful check replaces its example while keeping editable input and counter", async () => {
  const action = async () => <p role="status">Checked successfully</p>;
  const view = await mount(
    <AnalyzeForm action={action} strings={strings} defaultValue="Example text"
      fallback={<p>Saved example result</p>} />,
  );
  const text = view.querySelector("textarea")!;
  await typeText(text, "My edited message");
  await act(async () => view.querySelector("form")!.requestSubmit());

  assert.equal(view.querySelector('[role="status"]')?.textContent, "Checked successfully");
  assert.ok(!view.textContent?.includes("Saved example result"));
  assert.equal(text.value, "My edited message");
  assert.ok(view.textContent?.includes("17 / 8000"));
});
