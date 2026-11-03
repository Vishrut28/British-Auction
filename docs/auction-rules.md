# Auction rules

The assignment leaves some behaviour open. This file pins each rule down, so the
code, the tests and the UI all follow the same reading. Rules marked
**(interpretation)** are choices we made where the brief was silent.

## Time

- The **server clock** decides everything. Clients never send a bid time.
- All timestamps are stored as `timestamptz` in UTC. The UI shows local time.
- An RFQ has three close-related times:
  - `bid_close_at`: the close time the buyer first set. It never changes.
  - `current_close_at`: the close time now in force. It starts equal to
    `bid_close_at` and only moves later.
  - `forced_close_at`: the hard stop. It must be later than `bid_close_at`.

## Accepting a bid

A bid is accepted only if all of these hold:

1. `bid_start_at <= now < current_close_at`. A bid at exactly the close time
   is too late.
2. Every charge (freight, origin, destination) is `>= 0`, and the total is `> 0`.
3. If the supplier already has a bid on this RFQ, the new total must be
   **strictly lower** than their previous total. In a British auction, suppliers
   only lower their own price. **(interpretation)**
4. A bid does **not** have to beat the current L1. A supplier may improve from
   L4 to L2.

Bid price = `freight_charges + origin_charges + destination_charges`.

## Ranking

- Each supplier is ranked by their **latest** bid. Rule 3 above makes it their
  lowest bid as well.
- Lower total ranks higher: L1 is the lowest price.
- On a tie, the supplier who reached that price **first** ranks higher. **(interpretation)**

## Trigger window (X)

A bid placed at time `t` is *inside the trigger window* when

```
current_close_at - X minutes <= t < current_close_at
```

The window is measured from the **current** close time, which may already have
been extended. It is not measured from the original one.

## Extension triggers

The buyer picks one trigger type per RFQ. A bid inside the trigger window
extends the auction if:

| Trigger type      | Extends when                                                              |
|-------------------|---------------------------------------------------------------------------|
| `BID_RECEIVED`    | any accepted bid lands in the window                                      |
| `ANY_RANK_CHANGE` | a supplier who was **already ranked** has a different rank after the bid  |
| `L1_CHANGE`       | the L1 supplier after the bid is a different supplier than before, **and** there was an L1 before |

**(interpretation)** These definitions nest: every `L1_CHANGE` is also an
`ANY_RANK_CHANGE` (the old L1 drops to L2 or lower), and every `ANY_RANK_CHANGE`
is also a `BID_RECEIVED`. Some edge cases follow:

- The **first bid** of an auction changes no existing rank and replaces no L1,
  so it triggers only `BID_RECEIVED`.
- A new supplier who enters **last** moves nobody, so it does not trigger
  `ANY_RANK_CHANGE`.
- A supplier who is already L1 and lowers their own price moves nobody either.

## Extension (Y)

When a trigger fires:

```
new_close_at = min(current_close_at + Y minutes, forced_close_at)
```

This adds Y to the **close time**, not to the bid time, as in the brief's
example where 6:00 PM becomes 6:05 PM.

- If the cap cuts the extension short, the activity log says so.
- If `current_close_at` already equals `forced_close_at`, nothing is extended,
  and the log records that the forced-close cap blocked the extension.
- The auction can never run past `forced_close_at`. The database enforces this
  as well (see [schema.md](schema.md)).

## Status

| Status         | When                                                                     |
|----------------|--------------------------------------------------------------------------|
| `SCHEDULED`    | `now < bid_start_at`                                                     |
| `ACTIVE`       | `bid_start_at <= now < current_close_at`                                 |
| `CLOSED`       | `now >= current_close_at` and `current_close_at < forced_close_at`       |
| `FORCE_CLOSED` | `now >= current_close_at` and `current_close_at = forced_close_at`       |

`FORCE_CLOSED` means extensions pushed the auction all the way to the hard
stop. The status is always computed from these times. The stored `status`
column is a cache that the closing job keeps up to date for fast listing.
Reads never depend on that job having run.

## Concurrency

Placing a bid locks the RFQ row (`SELECT ... FOR UPDATE`) for the whole
transaction: validate, rank, decide on an extension, write. Two bids landing at
the same moment are handled one after the other, so neither can work from a
stale close time or a stale ranking.

## Out of scope

- **Authentication.** The UI picks a supplier from a list. Real login would
  replace that picker.
- **Multiple currencies.** All amounts are in one currency.
- **Editing or withdrawing a bid.** Suppliers place a new, lower bid instead.
