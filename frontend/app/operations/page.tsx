"use client";

import { useChrome } from "@/components/app-shell";
import { Inbound } from "@/components/inbound";
import { PageTitle } from "@/components/shell";
import { Pill } from "@/components/status";
import { Card, EmptyState, ErrorNote, SectionHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, dayTime, money, titleCase } from "@/lib/format";
import { usePoll } from "@/lib/use-poll";

/** Jobs, threads and the two ways to give the agent something to do.
 *
 *  The send-a-message box is not a chat. It is the same seam a real channel plugs into
 *  — an inbound email, a WhatsApp webhook — so the demo drives the product through its
 *  actual front door rather than a special path.
 */
export default function OperationsPage() {
  const { currency } = useChrome();
  const bookings = usePoll(() => api.bookings(true), 15_000);
  const conversations = usePoll(api.conversations, 8_000);
  const tasks = usePoll(api.tasks, 15_000);

  const error = bookings.error ?? conversations.error ?? tasks.error;
  if (error) return <ErrorNote message={error} />;

  return (
    <>
      <PageTitle
        title="Operations"
        lede="What is on the calendar, which threads are open, and what the agent has put on your list."
      />

      <Inbound
        onSent={() => {
          void conversations.refresh();
        }}
      />

      <div className="mt-6 space-y-6">
        <Card>
          <SectionHeader
            title="Threads"
            count={conversations.data?.count}
            hint="Anything awaiting the customer is chased once, then let go"
          />
          {conversations.loading ? (
            <Skeleton className="m-5 h-32" />
          ) : conversations.data && conversations.data.conversations.length > 0 ? (
            <ul>
              {conversations.data.conversations.map((thread) => (
                <li
                  key={thread.conversation_id}
                  className="flex flex-wrap items-baseline justify-between gap-2 border-b px-5 py-3 last:border-b-0"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[15px]">{thread.subject ?? "No subject"}</p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
                      <span>{thread.channel}</span>
                      <span>·</span>
                      <span className="tnum">{thread.message_count ?? 0} messages</span>
                      <span>·</span>
                      <span>{ago(thread.last_message_at)}</span>
                      {thread.follow_up_due_at && (
                        <>
                          <span>·</span>
                          <span>chase due {dayTime(thread.follow_up_due_at)}</span>
                        </>
                      )}
                    </p>
                  </div>
                  <ThreadStatus status={thread.status} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState glyph="—" title="No threads yet" />
          )}
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <SectionHeader title="Upcoming jobs" count={bookings.data?.count} />
            {bookings.data && bookings.data.bookings.length > 0 ? (
              <ul>
                {bookings.data.bookings.map((booking) => (
                  <li key={booking.booking_id} className="border-b px-5 py-3 last:border-b-0">
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="min-w-0 truncate text-[15px]">{booking.service_name}</p>
                      <p className="tnum shrink-0 text-[15px]">
                        {money(booking.price, currency)}
                      </p>
                    </div>
                    <p className="mt-0.5 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
                      <span className="ident">{booking.reference}</span>
                      <span>·</span>
                      <span>{dayTime(booking.starts_at)}</span>
                      {booking.created_by === "agent" && (
                        <Pill tone="ok" glyph="✓">
                          booked by the agent
                        </Pill>
                      )}
                    </p>
                    {booking.notes && (
                      <p className="mt-1 text-[13px] text-muted-foreground">{booking.notes}</p>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState glyph="—" title="Nothing on the calendar" />
            )}
          </Card>

          <Card>
            <SectionHeader
              title="Your list"
              count={tasks.data?.count}
              hint={tasks.data?.overdue ? `${tasks.data.overdue} overdue` : undefined}
            />
            {tasks.data && tasks.data.tasks.length > 0 ? (
              <ul>
                {tasks.data.tasks.map((task) => (
                  <li key={task.task_id} className="border-b px-5 py-3 last:border-b-0">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <p className="text-[15px] leading-snug">{task.title}</p>
                      {(task.priority === "high" || task.priority === "urgent") && (
                        <Pill tone="wait">{task.priority}</Pill>
                      )}
                    </div>
                    {task.description && (
                      <p className="mt-0.5 text-[13px] text-muted-foreground">{task.description}</p>
                    )}
                    <p className="mt-0.5 text-[13px] text-muted-foreground">
                      {task.due_at ? `due ${dayTime(task.due_at)}` : "no due date"}
                      {task.created_by === "agent" && " · opened by the agent"}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState glyph="✓" title="Nothing outstanding" />
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

function ThreadStatus({ status }: { status: string }) {
  const tone =
    status === "awaiting_business" ? "wait" : status === "resolved" ? "ok" : "neutral";
  const label =
    status === "awaiting_business"
      ? "waiting on the agent"
      : status === "awaiting_customer"
        ? "waiting on customer"
        : titleCase(status);
  return <Pill tone={tone}>{label}</Pill>;
}
