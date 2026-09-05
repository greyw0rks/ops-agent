"use client";

import { useState } from "react";

import { api } from "@/lib/api";

import { Pill } from "./status";
import { Button, Card, SectionHeader } from "./ui";

const EXAMPLES = [
  {
    label: "A booking request",
    name: "Amaka Eze",
    body: "Hi, I'd like to book a standard cleaning for my 3-bedroom flat on Saturday afternoon if you have anything free.",
  },
  {
    label: "A complaint",
    name: "Sarah Johnson",
    body: "I'm really disappointed with yesterday's deep clean. The oven wasn't touched and there was still dust on the skirting in both bedrooms. I'd like a refund.",
  },
  {
    label: "A reschedule",
    name: "Daniel Okoro",
    body: "Something's come up — can we move the office clean to Friday evening instead?",
  },
];

/** Hand the agent an inbound customer message.
 *
 *  This posts to the same `POST /api/messages` endpoint an SES inbound rule or a
 *  WhatsApp webhook would, so nothing here is a demo-only path. The agent then works
 *  in the background; the run appears in Activity when it lands.
 */
export function Inbound({ onSent }: { onSent?: () => void }) {
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    if (!body.trim()) return;
    setSending(true);
    setError(null);
    setSent(false);
    try {
      await api.sendMessage({
        body: body.trim(),
        customer_name: name.trim() || undefined,
      });
      setSent(true);
      setBody("");
      onSent?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSending(false);
    }
  }

  async function sweep() {
    setSending(true);
    setError(null);
    try {
      const result = await api.sweepFollowUps();
      setSent(result.due > 0);
      if (result.due === 0) setError("Nothing is due to be chased right now.");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSending(false);
    }
  }

  return (
    <Card>
      <SectionHeader
        title="Give the agent something to do"
        hint="Posts to the same endpoint a real email or WhatsApp webhook would"
      />
      <div className="px-5 py-4">
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <Button
              key={example.label}
              size="sm"
              onClick={() => {
                setName(example.name);
                setBody(example.body);
                setSent(false);
                setError(null);
              }}
            >
              {example.label}
            </Button>
          ))}
        </div>

        <div className="mt-3 space-y-2">
          <label className="block">
            <span className="text-[14px]">From</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Customer name — left blank, the agent works it out or creates a record"
              className="mt-1 w-full rounded-md border border-[--color-border-strong] bg-background px-3 py-2 text-[15px] placeholder:text-muted-foreground/70"
            />
          </label>
          <label className="block">
            <span className="text-[14px]">Message</span>
            <textarea
              value={body}
              onChange={(event) => {
                setBody(event.target.value);
                setSent(false);
              }}
              rows={3}
              placeholder="What the customer wrote…"
              className="mt-1 w-full resize-y rounded-md border border-[--color-border-strong] bg-background px-3 py-2 text-[15px] placeholder:text-muted-foreground/70"
            />
          </label>
        </div>

        {error && (
          <p className="mt-3 rounded-md border border-wait-border bg-wait-surface px-3 py-2 text-[14px] text-wait-text">
            {error}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button tone="primary" onClick={() => void send()} disabled={sending || !body.trim()}>
            {sending ? "Handing it over…" : "Send to the agent"}
          </Button>
          <Button onClick={() => void sweep()} disabled={sending} title="Fire the scheduled sweep">
            Run the follow-up sweep
          </Button>
          {sent && (
            <Pill tone="ok" glyph="✓">
              Working on it — watch Activity
            </Pill>
          )}
        </div>
        <p className="mt-2 text-[13px] text-muted-foreground">
          A run takes 20–50 seconds. It appears in Activity as it goes, and in Decisions if the
          agent hits one of your limits.
        </p>
      </div>
    </Card>
  );
}
