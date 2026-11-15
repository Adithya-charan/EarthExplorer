import { describe, expect, it } from "vitest";
import { describeCommand, parseCommand, voiceErrorMessage } from "./voice";

describe("parseCommand", () => {
  it.each([
    ["Take me to Hyderabad", "Hyderabad"],
    ["Show Bellandur Lake", "Bellandur Lake"],
    ["Explore the Sundarbans", "Sundarbans"],
    ["go to Uttarakhand", "Uttarakhand"],
    ["Show the Himalayas", "Himalayas"],
  ])("%s → go to a place", (text, place) => {
    expect(parseCommand(text)).toEqual({ type: "goto", place });
  });

  it("reads a year range", () => {
    expect(parseCommand("Compare this location between 2000 and 2020")).toEqual({ type: "compare", start: 2000, end: 2020 });
    expect(parseCommand("compare 2020 and 2005")).toEqual({ type: "compare", start: 2005, end: 2020 });
  });

  it("does not invent years: a compare without two years is not understood", () => {
    expect(parseCommand("compare this location").type).toBe("unknown");
    expect(parseCommand("compare 2010").type).toBe("unknown");
  });

  it.each([
    ["Show the latest available observation", "latest"],
    ["Show the historical changes", "history"],
    ["Show the change detection results", "changes"],
    ["show hotspots", "hotspots"],
    ["Zoom into this location", "zoom"],
    ["Go back to the previous location", "back"],
    ["go forward", "forward"],
  ])("%s → %s", (text, type) => {
    expect(parseCommand(text).type).toBe(type);
  });

  it("never guesses on gibberish or questions", () => {
    expect(parseCommand("").type).toBe("unknown");
    expect(parseCommand("what is the meaning of life and why do glaciers melt so quickly please").type).toBe("unknown");
  });

  it("describes every command in plain words", () => {
    expect(describeCommand({ type: "goto", place: "Hyderabad" })).toBe("Going to Hyderabad");
    expect(describeCommand({ type: "unknown", text: "x" })).toMatch(/did not understand/);
  });

  it("maps recognition errors to guidance, and ignores deliberate aborts", () => {
    expect(voiceErrorMessage("not-allowed")).toMatch(/blocked/);
    expect(voiceErrorMessage("no-speech")).toMatch(/did not hear/);
    expect(voiceErrorMessage("aborted")).toBe("");
  });
});
