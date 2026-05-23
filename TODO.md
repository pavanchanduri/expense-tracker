# Spendly — Feature Backlog

A prioritized list of good-to-have features. Tick items as they ship. Within each tier, the order is roughly the recommended sequence.

## Tier 1 — High impact, fills core gaps

- [ ] **Budgets & spending limits** — Set a monthly cap per category (e.g., ₹8,000 dining). Progress bar on profile/analytics; soft warning at 80%.
- [ ] **Recurring expenses** — "Repeats monthly/weekly" toggle that auto-creates entries (rent, OTT subs, EMIs).
- [ ] **Search & filters on expense list** — Filter by date range, category, amount range, and text search inside the app (today only export supports slicing).
- [ ] **Income & net savings view** — Track inflows alongside expenses; show "this month you saved ₹X (Y%)".
- [ ] **Payment method tracking** — Tag each expense as Cash / UPI / Credit Card / Debit Card / Wallet.

## Tier 2 — Engagement and stickiness

- [ ] **Receipt attachment** — Upload photo/PDF per expense; store on disk, link from row.
- [ ] **Custom categories & icons** — User-defined categories with emoji/icon.
- [ ] **Smart category suggestions** — Suggest category from prior descriptions on add-expense (SQL lookup, no ML).
- [ ] **Quick-add bar** — Keyboard-shortcut overlay with natural input: `500 lunch yesterday #food`.
- [ ] **Anomaly alerts on analytics** — Callouts like "You spent 42% more on Dining vs. your 3-month average".

## Tier 3 — Trust, polish, retention

- [ ] **Password reset / forgot-password flow** — Currently absent; blocker for returning users.
- [ ] **Weekly email digest** — "Last week you spent ₹X across Y categories".
- [ ] **Dark mode** — Toggle in profile; leverages existing `:root` design tokens.
- [ ] **PWA / installable** — Manifest + small service worker; installs on Android, offline reads.
- [ ] **CSV import from bank / credit-card statements** — Column-mapping page to remove cold-start pain.

## Tier 4 — Differentiators

- [ ] **Split-with-friend tracking** — Mark expense as split 50/50; track who owes whom.
- [ ] **Savings goals** — "Save ₹50k for a Goa trip by Dec" with progress ring fed by net savings.
- [ ] **Tax-deductible flag + year-end PDF** — Useful for freelancers/consultants filing ITR.
- [ ] **Multi-currency for travel** — Default INR; log USD/EUR with stored FX rate when abroad.

---

**Recommended next 3 to ship:** Budgets → Recurring expenses → Search/filters.
