# Brokerage Boundary

This project must remain separate from brokerage systems.

## Prohibited

- Connecting to brokerage APIs.
- Reading, requesting, storing, or generating broker credentials.
- Reading, requesting, storing, or generating bank, debit card, credit card, password, API key, token, cookie, or broker login information.
- Placing trades.
- Submitting, modifying, canceling, or routing live orders.
- Adding live trading, margin, options, short selling, or automatic execution features.

## Allowed

- Educational research.
- Local CSV watchlists.
- Public filing downloads from sources such as SEC endpoints.
- Position-size and risk calculations.
- Paper trade journaling.
- Drafting trade plans for human review.

## Human Responsibility

Any real trade decision and any interaction with a brokerage account must happen outside this repo by the human account owner.
