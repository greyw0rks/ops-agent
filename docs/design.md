# Design

The dashboard has one job: make a business owner willing to let software spend their
money. Everything below follows from that.

The visual system was generated with Muse, an OKLCH design engine, and then corrected in
the two places the engine itself flagged. The interesting parts are the corrections.

## Who is reading

A three-person cleaning company's owner. Not technical, time-poor, reading in short
bursts between jobs, as often on a phone as a laptop. They are not evaluating an AI —
they are deciding whether to trust a member of staff who never sleeps.

That rules out a lot. No dashboards-as-art. No sparklines. No "AI" chrome. What earns
trust here is the same thing that earns it from a bookkeeper: legible records, plain
numbers, and no surprises.

## Archetype

**Dense utility.** Sidebar navigation, hairline dividers, no zebra striping, expandable
detail rows, medium-high information density. The reference is an operations ledger, not
a trading terminal — dense because there is genuinely a lot to show, not to look
sophisticated.

## Colour

Generated from a 255° OKLCH seed with warm-gray neutrals, restrained accent ratio and a
high contrast target.

| Role | Value | Measured |
|---|---|---|
| background | `#FDFDFC` | warm near-white |
| text | `#2E2C2A` | 13.66:1, APCA Lc 99 |
| muted text | `#78726F` | 4.65:1 |
| primary | `#3175C6` | 4.68:1 with white |
| border | `#DAD5D3` | Lc 20, separators only |

Two deliberate constraints:

**The accent is blue, and it is blue because of what it is not.** The status system
needs green, amber and red to be unambiguous. A brand colour in any of those hues
competes with them — which is exactly what the first candidate palette did, pairing a
red accent (`#D54232`) with a red error (`#D6403A`). Blue keeps maximum semantic
distance from all three.

**Blue never appears on a consequential action.** It is for navigation, links and
"Save". Approve and Reject are green and red respectively, at identical size, weight and
shape. A filled primary *Approve* beside a ghost *Reject* is a nudge, and the one screen
in this product that must not have an opinion is the one where the owner decides.

## The two engine corrections

**Success and warning solids are unusable on this page.** The engine returned
`#68F690` and `#DFA54D` for steps 9 of those ramps and measured them at **1.36:1** and
**2.14:1** against the background. They are dark-mode fills. So every status is built
from the steps actually solved for the job — step 3 surface, step 6 border, step 11 text
— and step 9 is never used on light.

```css
--ok-surface: #e8f5ea;  --ok-border: #b5e0bd;  --ok-text: #438252;  /* 4.53:1 */
```

**Primary and error are grayscale-fragile.** Separable by hue (ΔEOK 0.211) but only
0.060 apart in simulated lightness, so the distinction disappears in grayscale, in print
and under some colour-vision deficiencies. Every status therefore carries a glyph as
well as a colour, and nothing in the interface depends on hue alone:

| State | Glyph | Where |
|---|---|---|
| done | `✓` | tool ran, action logged |
| waiting on you | `!` | run paused for a decision |
| refused | `⊘` | blocked by policy |
| failed | `×` | the tool errored |

Four characters, all verified as actually rendering in the loaded fonts. An earlier set
used `⏸ ✕ ◍ ▤ ⚖`, which rendered as tofu boxes in Chromium on this machine — glyph
coverage is a thing to check in a browser, not to assume from a codepoint chart.

## Type

**Inter at 18px**, which is derived rather than defaulted: 18px is Inter's critical
print size — 0.2° of x-height at its measured 0.5459 ratio — and 1.756 line-height is
what yields one x-height of visible gap given its 1.21em content area.

Metadata drops to 13–14px because density is the brief, but anything the owner *reads*
— page ledes, the agent's reasoning on a decision card — stays at 16–18px.

**JetBrains Mono carries identifiers.** Booking references, run ids, customer ids, tool
names. This is the single most load-bearing typographic decision in the product: it is
what makes the activity feed read as a record rather than as prose, and it is why
`run_d189e767` beside a sentence looks like evidence rather than clutter.

Numbers use `font-variant-numeric: tabular-nums` everywhere. A column of money that does
not align is a column nobody checks.

## Space, shape, motion

4px grid unit; space steps are multiples of the body size so the two scales stay
commensurate. Radius 10px, 6px on small controls. Hairline borders carry structure and
elevation is reserved for overlays — a dense interface with shadows on every card reads
as noise.

Motion is Material 3's tokens at the short end: 150–200ms on
`cubic-bezier(0.2, 0, 0, 1)`, and a 3px rise on newly-arrived content so a decision
appearing while you read is noticed rather than startling. Everything animated is behind
`prefers-reduced-motion`.
