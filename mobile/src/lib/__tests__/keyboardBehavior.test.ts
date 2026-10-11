import { keyboardAvoidBehavior } from "../keyboardBehavior";

describe("keyboardAvoidBehavior", () => {
  it("pads on iOS", () => {
    expect(keyboardAvoidBehavior("ios")).toBe("padding");
  });

  it("never returns undefined on Android, where nothing else moves the form", () => {
    expect(keyboardAvoidBehavior("android")).toBe("height");
  });

  it("uses height for any other platform", () => {
    expect(keyboardAvoidBehavior("web")).toBe("height");
  });
});
