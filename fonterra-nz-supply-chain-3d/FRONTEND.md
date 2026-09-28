# Frontend architecture

React 19, TypeScript, Vite and Three.js provide an actual WebGL factory cutaway,
keyboard-accessible selectors, an order ledger, order inspection and event history.
Colours derive from the Clawpilot light/dark tokens in `index.html`. There are no
runtime CDN fonts, external image resources or bundled sample orders.

For dependency access, configuration and commands, use [README.md](README.md).

## Transport boundary

`src/services/snapshotLoader.ts` exports:

```ts
type SnapshotLoader = (signal: AbortSignal) => Promise<Snapshot>;
loadHttpSnapshot: SnapshotLoader;
loadSnapshot: SnapshotLoader;
validateSnapshot(value: unknown): Snapshot;
```

Local/default builds use same-origin `GET /api/factory/snapshot`. Only a build with
mode `fabric` selects the native adapter. Neither mode silently falls back to the
other. `useSnapshot` owns polling, stale retention, cancellation and single-flight
protection independently of the transport.

Polls begin five seconds after the previous request completes. HTTP requests use a
15-second subscriber timeout; the uncancellable native request remains single-flight
until completion or the bridge's 30-second timeout. A failed poll retains the last
good data as stale, never as a successful empty result.

The shared contract requires explicit ISO dates, decimal-string money, the fixed
24-hour NZ supermarket scope, list bounds and latest-event consistency. Full-window
totals are not recomputed from the capped or filtered order list.

## Native Fabric bridge

`src/services/fabricSnapshot.ts` uses the pinned Rayfin auth SDK, then sends the
fixed query `EVALUATE FactorySnapshotRows` to the Fabric parent frame. The request
has channel `fabric-app-data-semantic-model` and the **outer**
`method: "semanticModel.executeDaxJson"` property; the generic SDK auth bridge does
not encode this semantic-model method.

Responses require the exact parent window, origin, channel and request ID. Optional
version/kind/success fields must not contradict the protocol. Explicit errors fail;
successful data must pass both row reconstruction and the Snapshot schema.
`snapshotRows.ts` accepts bare or Power BI-prefixed column names, requires one
`SnapshotId` cohort, unique row identities and metadata `__rowCounts`, and rejects
partial or mixed results.

No browser Kusto call, user-entered DAX, experimental connector or bearer token is
sent through postMessage. Consumers use their own Fabric/model/KQL permissions.

### Pinned SDK origin adaptation

Rayfin auth-provider 1.35.0 internally omits an auth-handoff target origin because
Fabric places an extension frame between the app and portal.
`build/fabricAuthOrigin.ts` narrowly adds the exact immediate-parent origin during
native builds. It does not alter installed packages, PKCE, state or session logic.
A changed/missing SDK source pattern fails the build. Native dev serving is rejected
so it cannot bypass that build-time adaptation.

`fabricHostOrigin.ts` separates the outer portal from the extension using native
browser `ancestorOrigins`. The outer origin must be exactly
`https://app.fabric.microsoft.com` or `https://app.powerbi.com`; all frames must be
HTTPS, and a referrer, when present, must agree with the immediate parent. Without
native ancestry, only a direct verified-portal parent is accepted.

This permits an SDK PKCE handoff attempt, not a data request. A session must first
be established by exchanging the handoff code at the configured app's HTTPS auth
endpoint. Both transports pin the parent origin/window. Changes after or during
authentication/querying require a reload rather than session reuse.

Auth is configured with `storage: false`, `persistSession: false` and
`multiTabSync: false`. Tokens and PKCE verifiers remain in memory. The SDK may store
only its non-secret `fabricEmbedded=true` mode flag in sessionStorage.

## Rendering and business meaning

- The 3D site, category machines, conveyors and trucks are illustrative, not measured
  production throughput, inventory, GPS positions or real factory equipment.
- No event for 60 seconds means a quiet stream. A failed poll or snapshot older than
  30 seconds means stale data. Both stop illustrative motion.
- Received orders permit motion only while data are recent/fresh and motion is
  enabled. Reduced-motion preferences disable it. All-sold history remains static.
- Truck/dock highlights reflect the last recorded Dispatched state, not proof that
  trucks are currently moving. Unfinished notebook orders remain unfinished.
- Lane counts are line items and unique assigned orders, not physical output.
  Quantity groups preserve product, unit and pack size.
- Times use `Pacific/Auckland` and `en-NZ`; money uses decimal-string cent rounding.
- Keyboard controls complement OrbitControls/raycast selection. A WebGL failure
  leaves the ledger, filters and selectors usable.
- Static scenes render on demand. Illustrative animation is capped at 30 FPS.

## Test boundaries

Unit tests cover DTO validation, row cohorts/counts, money, filtering, polling,
host identity, exact envelopes, cancellation, authentication failure and SDK origin
adaptation. Component tests use a test-only 3D boundary stub.

The local browser suite exercises real WebGL, selection/camera controls, responsive
layouts, filtering, errors, reduced motion and fallback states using intercepted
synthetic snapshots.

The native browser suite loads the actual native bundle in intercepted nested
cross-origin pages, executes installed SDK PKCE/state handling against a synthetic
token endpoint, and checks zero-to-six-to-seven orders, matching lines and selected
line quantity updates. Every test request is intercepted; tests neither authenticate
against a tenant nor send producer events. Top-level and untrusted embeds fail closed.

Passing browser tests is not a claim that the deployed tenant's SSO/model permissions
have been verified. Keep test fixtures, traces and real validation captures out of
production bundles and Git.
