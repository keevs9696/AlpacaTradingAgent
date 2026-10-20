# Trading analysis pipeline

This diagram follows one symbol from the dashboard to its final decision. When multiple symbols are selected, the queue processes them one at a time; the selected analysts for each symbol run in parallel by default.

```mermaid
flowchart TD
    UI[Dashboard settings and Start] --> MODE{Run mode}

    MODE -->|Single run| NOW[Start immediately]
    MODE -->|Loop| LOOP[Analyze symbols, wait interval, repeat]
    MODE -->|Market-hour schedule| SCHEDULE[Wait for configured Eastern time and verify market is open]

    NOW --> QUEUE[Symbol queue — one symbol at a time]
    LOOP --> QUEUE
    SCHEDULE --> QUEUE
    QUEUE --> SETUP[Build per-symbol config and initial state]
    SETUP --> AUDIT[Open run audit log]
    AUDIT --> ANALYSTS[Selected analysts run in parallel]

    ANALYSTS --> CALLS[Analysts request data and indicators through tools]
    CALLS --> BARS{Historical bars in SQLite and still fresh?}
    BARS -->|Yes| DB[(SQLite market-data cache)]
    BARS -->|Missing history or stale recent bars| ALPACA[Fetch bars from Alpaca]
    ALPACA --> WRITE[Upsert bars and fetched-range coverage]
    WRITE --> DB
    DB --> CALLS
    CALLS --> OTHER[Other requested sources: news, social, fundamentals, and macro]
    OTHER --> REPORTS[Analyst reports]

    REPORTS --> CONTEXT[Build compact evidence context]
    CONTEXT --> DEBATE[Bull and Bear research debate]
    DEBATE --> PLAN[Research Manager writes investment plan]
    PLAN --> PROPOSAL[Trader creates trade proposal]
    PROPOSAL --> RISK[Risky, Safe, and Neutral review]
    RISK --> JUDGE[Risk Judge produces final decision]
    JUDGE --> INTENT[Typed TradeIntent and recommendation]

    INTENT --> DISPLAY[Update dashboard with reports and status]
    INTENT --> PERSIST[Persist final state and decision]
    PERSIST --> RUNJSON[(Per-run audit JSON)]
    PERSIST --> FULLSTATE[(Consolidated symbol state)]
    PERSIST --> MEMORY[(Decision log and ChromaDB agent memory)]

    INTENT --> AUTO{Place order after analysis enabled?}
    AUTO -->|No| FINISH[Finish symbol]
    AUTO -->|Yes| SIZE[Apply portfolio and market-regime sizing]
    SIZE --> POSITION[Verify current position with Alpaca]
    POSITION --> SAFETY[Run deterministic safety and order checks]
    SAFETY -->|Allowed| ORDER[Submit order to Alpaca paper account]
    SAFETY -->|Blocked or unverifiable| BLOCK[Skip new exposure and record reason]
    ORDER --> FINISH
    BLOCK --> FINISH
    FINISH --> QUEUE

    classDef decision fill:#17212b,stroke:#43d6bd,color:#e6edf2;
    classDef storage fill:#101820,stroke:#6c8a99,color:#e6edf2;
    class MODE,BARS,AUTO decision;
    class DB,RUNJSON,FULLSTATE,MEMORY storage;
```

## Notes

- Analyst tool calls can lead to additional LLM calls. Their number depends on the evidence requested, so each run can take a different amount of time.
- The SQLite bar cache is persistent in Docker. It fills missing historical ranges and refreshes the recent two-day tail after its cache time-to-live expires. News and other non-bar sources may still be fetched on each analysis.
- The quick and deep LLM settings are separate roles in one run, not automatic error fallback models. The dashboard can override the configured defaults.
- Orders are attempted only when order execution is enabled and the deterministic safety checks allow them. Market-hour scheduling and loop state live in the running application process, so restarting the container does not resume an active schedule.

For the implementation details, see [ARCHITECTURE.md](../ARCHITECTURE.md), [graph setup](../tradingagents/graph/setup.py), [data cache](../tradingagents/dataflows/market_data_cache.py), and [order execution](../tradingagents/dataflows/alpaca_utils.py).
