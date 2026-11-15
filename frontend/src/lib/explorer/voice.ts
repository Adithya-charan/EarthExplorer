/**
 * Deterministic voice / text command parser. No model is involved: a command either matches a documented pattern or it is
 * reported as not understood. A place name is never guessed here; "goto" only carries the words the person said, and the
 * app resolves them with the same search the search box uses.
 */

export type VoiceCommand =
  | { type: "goto"; place: string }
  | { type: "compare"; start: number; end: number }
  | { type: "latest" }
  | { type: "history" }
  | { type: "changes" }
  | { type: "hotspots" }
  | { type: "beforeafter" }
  | { type: "swipe" }
  | { type: "zoom" }
  | { type: "back" }
  | { type: "forward" }
  | { type: "unknown"; text: string };

export const VOICE_EXAMPLES = [
  "Take me to Hyderabad",
  "Show Bellandur Lake",
  "Explore the Sundarbans",
  "Go to Uttarakhand",
  "Show the Himalayas",
  "Compare this location between 2000 and 2020",
  "Show the latest available observation",
  "Show the historical changes",
  "Zoom into this location",
  "Go back to the previous location",
  "Show the change detection results",
];

const MIN_YEAR = 1950;
const MAX_YEAR = 2100;

const clean = (t: string) =>
  t
    .toLowerCase()
    .replace(/[“”"'.!?]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

function years(t: string): number[] {
  return [...t.matchAll(/\b(19[5-9]\d|20\d\d|21\d\d)\b/g)].map((m) => Number(m[1])).filter((y) => y >= MIN_YEAR && y <= MAX_YEAR);
}

const LEADING = /^(?:(?:please|can you|could you|would you)\s+)?(?:(?:take me|bring me|fly me|navigate|go|fly|zoom|travel|jump)\s+to|show me|show|explore|open|find|search for|search|look at|visit|locate)\s+(?:the\s+)?/;

/** Turn recognised or typed words into a command. Specific phrases are tested before the generic "go to a place" form. */
export function parseCommand(input: string): VoiceCommand {
  const t = clean(input);
  if (!t) return { type: "unknown", text: input };

  if (/\b(go|come|navigate)?\s*back\b|previous (location|place|view|search)|last (location|place)/.test(t) && !/\bback ?ground\b/.test(t) && t.split(" ").length <= 8) return { type: "back" };
  if (/\b(go\s+)?forward\b|next (location|place|view)/.test(t) && t.split(" ").length <= 8) return { type: "forward" };

  if (/\bcompare\b|\bbetween\b.+\band\b|\bfrom\b.+\bto\b/.test(t) && years(t).length >= 2) {
    const ys = years(t).slice(0, 2).sort((a, b) => a - b);
    if (ys[0] < ys[1]) return { type: "compare", start: ys[0], end: ys[1] };
  }
  if (/\bcompare\b/.test(t) && years(t).length < 2) return { type: "unknown", text: input };

  if (/\b(latest|most recent|newest|current)\b.*\b(observation|image|imagery|data|view|scene|picture)\b|\b(show|display)\b.*\blatest\b/.test(t)) return { type: "latest" };
  if (/\b(histor(y|ical)|over time|timeline|time machine|past)\b/.test(t) && /\b(show|play|open|display|see|view)\b/.test(t)) return { type: "history" };
  if (/\b(change detection|detected change|changes?|differences?|what changed)\b/.test(t) && /\b(show|display|open|see|view|results?)\b/.test(t)) return { type: "changes" };
  if (/\bhot ?spots?\b/.test(t)) return { type: "hotspots" };
  if (/\bbefore (and|&|\/)? ?after\b/.test(t)) return { type: "beforeafter" };
  if (/\bswipe\b/.test(t)) return { type: "swipe" };
  if (/\bzoom( in(to)?)?\b.*\b(this|here|location|place|it)\b|\bzoom in\b|\bzoom into\b\s*$/.test(t) && !/\bzoom (in)?to [a-z]/.test(t.replace(/\bthis (location|place)\b/, ""))) return { type: "zoom" };

  const m = t.match(LEADING);
  if (m) {
    const place = t.slice(m[0].length).trim();
    if (place && place.split(" ").length <= 8) return { type: "goto", place: titleCase(place) };
    return { type: "unknown", text: input };
  }
  // A bare phrase of a few words is treated as a place name, exactly like typing it in the search box.
  const words = t.split(" ");
  if (words.length <= 6 && !/\b(please|what|why|how|when|where|who)\b/.test(t)) return { type: "goto", place: titleCase(t) };
  return { type: "unknown", text: input };
}

function titleCase(s: string): string {
  return s.replace(/\b([a-z])([a-z']*)/g, (_m, a: string, b: string) => a.toUpperCase() + b);
}

/** Human-readable confirmation shown before / while a command runs. */
export function describeCommand(c: VoiceCommand): string {
  switch (c.type) {
    case "goto":
      return `Going to ${c.place}`;
    case "compare":
      return `Comparing ${c.start} and ${c.end}`;
    case "latest":
      return "Showing the latest available observation";
    case "history":
      return "Showing the historical observations";
    case "changes":
      return "Showing the change detection results";
    case "hotspots":
      return "Showing the change hotspots";
    case "beforeafter":
      return "Showing before and after";
    case "swipe":
      return "Showing the swipe comparison";
    case "zoom":
      return "Zooming into this location";
    case "back":
      return "Going back to the previous location";
    case "forward":
      return "Going forward";
    case "unknown":
      return "Sorry, I did not understand that";
  }
}

/** Web Speech API wrapper types (not in lib.dom for every TypeScript version). */
interface RecognitionResultEvent {
  resultIndex: number;
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: RecognitionResultEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

export function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function voiceErrorMessage(code: string): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access was blocked. Allow the microphone in the browser, or type the command instead.";
    case "no-speech":
      return "I did not hear anything. Try again, or type the command.";
    case "audio-capture":
      return "No microphone was found. You can type the command instead.";
    case "network":
      return "Speech recognition needs a network connection in this browser. You can type the command instead.";
    case "aborted":
      return "";
    default:
      return "Voice input stopped unexpectedly. You can type the command instead.";
  }
}
