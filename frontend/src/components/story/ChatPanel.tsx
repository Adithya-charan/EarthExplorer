"use client";

import { useRef, useState, type FormEvent } from "react";
import { Send } from "lucide-react";
import { api, toApiError } from "@/lib/api";
import type { ChatAction, ChatResponse } from "@/lib/types";
import { Card, CardBody, CardHeader } from "@/components/ui/primitives";

interface Turn {
  role: "user" | "assistant";
  text: string;
  understood?: Record<string, string>;
}

interface Props {
  datasetId: string;
  region: string | null;
  variable: string | null;
  suggestions: string[];
  onAction: (action: ChatAction) => void;
}

export function ChatPanel({ datasetId, region, variable, suggestions, onAction }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [chips, setChips] = useState<string[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  async function send(message: string) {
    const msg = message.trim();
    if (!msg || busy) return;
    setTurns((t) => [...t, { role: "user", text: msg }]);
    setText("");
    setBusy(true);
    try {
      const res: ChatResponse = await api.chat({ dataset_id: datasetId, message: msg, current_region: region, current_variable: variable });
      setTurns((t) => [...t, { role: "assistant", text: res.reply, understood: res.understood }]);
      setChips(res.suggestions);
      if (res.action.type === "show_story") onAction(res.action);
    } catch (err) {
      setTurns((t) => [...t, { role: "assistant", text: `Sorry, that failed: ${toApiError(err).message}` }]);
    } finally {
      setBusy(false);
      setTimeout(() => endRef.current?.scrollIntoView?.({ block: "nearest" }), 0);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void send(text);
  }

  const shown = chips.length ? chips : suggestions;
  return (
    <Card>
      <CardHeader title="Ask about the data" subtitle="Rule-based: it only understands place, variable and time, shows what it understood, and never invents data or causes." />
      <CardBody>
        <div className="max-h-64 space-y-2 overflow-y-auto pr-1" role="log" aria-live="polite" aria-label="Chat">
          {turns.length === 0 ? (
            <p className="text-sm text-muted">Try one of the questions below, or type your own, for example “What happened in India from 2010 to 2015?”.</p>
          ) : null}
          {turns.map((t, i) => (
            <div key={i} className={t.role === "user" ? "ml-8 rounded-lg bg-accent-soft p-2 text-sm text-ink" : "mr-8 rounded-lg bg-surface-muted p-2 text-sm text-ink"}>
              <p>{t.text}</p>
              {t.understood && Object.keys(t.understood).length ? (
                <p className="mt-1 text-xs text-muted">
                  Understood: {Object.entries(t.understood).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                </p>
              ) : null}
            </div>
          ))}
          {busy ? <p className="text-xs text-muted" role="status">Thinking…</p> : null}
          <div ref={endRef} />
        </div>
        {shown.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {shown.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => void send(s)}
                className="rounded-full border border-line bg-surface px-3 py-1 text-xs text-ink-soft hover:bg-surface-muted"
              >
                {s}
              </button>
            ))}
          </div>
        ) : null}
        <form onSubmit={submit} className="mt-3 flex gap-2">
          <label htmlFor="chat-input" className="sr-only">Your question</label>
          <input
            id="chat-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={500}
            placeholder="Ask what happened, where and when…"
            className="min-h-9 flex-1 rounded-md border border-line bg-surface px-3 text-sm"
          />
          <button
            type="submit"
            disabled={busy || !text.trim()}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-accent bg-accent px-3 text-sm font-medium text-white disabled:opacity-50"
          >
            <Send size={14} aria-hidden="true" /> Ask
          </button>
        </form>
      </CardBody>
    </Card>
  );
}
