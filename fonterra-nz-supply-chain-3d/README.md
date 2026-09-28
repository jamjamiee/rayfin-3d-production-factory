# Fonterra NZ Supply Chain 3D

Source for the separate, read-only React 19 / TypeScript / Three.js factory and
NZ supermarket-dispatch monitoring app. Publishing this folder does not redeploy
or change either Fabric AppBackend.

## What is included

- `src/`: selectable 3D factory, illustrative category lanes and dispatch docks,
  order filters, line items, inspection panel, event journal and five-second polling.
- `backend/`: optional loopback-only Python adapter for local KQL development.
- `fabric/`: snapshot queries and the reference DirectQuery model definition.
- `build/`: pinned Rayfin SDK exact-origin authentication adaptation.
- `tests/`: synthetic unit/component/browser fixtures; no real order export.
- `.env.fabric.example`: empty public frontend configuration template.

Dependencies, browser downloads, built bundles, local environments, deployment
registries, credentials, screenshots, traces and the source ZIP are intentionally
excluded. This folder does not depend on Copilot session files or sibling tools.

## Data and meaning

The data path is:

`Notebook -> Eventstream -> FonterraSales KQL -> DirectQuery semantic model -> Fabric bridge -> app`

Use the notebook and typed tables documented in the [repository README](../README.md).
This app monitors **NZ supermarket orders updated within the last 24 hours**:

| Source | Purpose |
|---|---|
| `FonterraOrdersCurrent` | Latest order headers |
| `FonterraOrderLinesUnique` | Lines joined to each order's latest event ID |
| `FonterraOrderEventsUnique` | Deduplicated lifecycle activity |

Totals cover the entire window; lists are limited to 200 orders, 600 lines and
40 activity events. Monetary values are NZD. Quantities retain their selling units;
packs, tubs and bags must not be summed into a physical-volume total.

**Received** means a customer order was received, not raw materials.
**Dispatched** means products were sent to the customer. **Delivered** means they
arrived. **Sold** records completion of the simulated wholesale sale, not supermarket
checkout activity or payment collection. The Delivered KPI groups Delivered and Sold.

The factory geometry, lane assignments and motion are **illustrative**, not machine,
inventory or manufacturing telemetry. All source products, orders, outlets, retailer
relationships and routes are synthetic. NZ consumer scopes retain their
`DivestedComparison` labels following the Mainland Group sale to Lactalis.
Unfinished orders do not complete themselves when the notebook stops. Quiet and
stale streams remain visibly distinct, and illustrative motion stops.

## Dependencies and package registry

Use Node.js 22 and npm 10, plus Python 3.11+ for the optional local API.

**The pinned Microsoft Rayfin SDK packages at version 1.35.0 were not available
from public npm when this source was published.** An authorized package registry
providing those exact packages is required, including the transitive
`@microsoft/fabric-embedded-host` package. Configure your user-level npm registry
and authentication using the provider's instructions. Do not commit registry
credentials or copy access tokens into project configuration.

The lockfile keeps exact versions and integrity hashes but omits registry download
addresses. The project `.npmrc` preserves that behavior during updates. `npm ci`
uses your configured registry. A 404 or authorization error means access must be
resolved; do not substitute an arbitrary SDK version because the build checks a
version-specific authentication transport.

```powershell
Set-Location .\fonterra-nz-supply-chain-3d
npm ci
```

## Local development

The Python adapter is development infrastructure, **not a Fabric-hosted Python
backend**. It uses the server's Azure CLI identity, keeps tokens in memory and
accepts only a fixed read-only KQL query. Do not expose it on a public interface.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
az login

$env:FONTERRA_KQL_CLUSTER = 'https://<your-query-endpoint>.kusto.fabric.microsoft.com'
$env:FONTERRA_KQL_DATABASE = '<FonterraSales-database-GUID>'

npm run build
.\.venv\Scripts\python.exe -m backend.server --port 8787
```

Open `http://127.0.0.1:8787`. Start the backend after building so it mounts `dist`.
For hot reload, run `npm run dev` in another terminal. Vite proxies `/api` to
`http://127.0.0.1:8787`, or the origin specified by `API_PROXY_TARGET`.

`GET /api/factory/snapshot` returns validated orders and lines; `/api/health`
checks the adapter process, not KQL access. Failed requests remain errors rather
than silently displaying sample data.

## Fabric-native configuration and build

The native adapter is an explicit build choice, separate from the local HTTP mode:

```powershell
Copy-Item .\.env.fabric.example .\.env.fabric.local
# Fill the ignored .env.fabric.local file with your deployment's public values.
npm run build:fabric
```

| Variable | Value |
|---|---|
| `VITE_RAYFIN_API_URL` | HTTPS Rayfin endpoint ending in `/workspaces/{workspaceId}/appbackends/{itemId}/` |
| `VITE_RAYFIN_PUBLISHABLE_KEY` | Client-safe `pk-` publishable key, never a service secret |
| `VITE_RAYFIN_ITEM_ID` | The intended new AppBackend GUID |
| `VITE_RAYFIN_WORKSPACE_ID` | Its Fabric workspace GUID |
| `VITE_RAYFIN_MODEL_ID` | The DirectQuery semantic-model GUID |

All `VITE_*` values become public frontend code. Never place passwords, bearer tokens,
Event Hubs connection strings or service credentials in them.

`npm run build` produces local HTTP mode in `dist`; `npm run build:fabric` produces
portal-only mode in `dist-fabric`. Do not deploy the local HTTP bundle as the Fabric
app. `npm run preview:fabric` serves the native bundle locally but cannot supply a
real Fabric parent frame.

The reference TMDL retains the original deployment's **non-secret KQL endpoint and
database ID**; replace those for a different environment. `src/App.tsx` retains the
reference app/notebook links. The native browser tests assert the original reference
workspace/item/model IDs; the Tests section supplies synthetic build configuration.
These identifiers and links are not credentials and grant no access by themselves.
The environment file, publishable key and deployment receipt are not committed.

`FonterraSupplyChainAppRows()` returns `Kind`, `RowKey`, `PayloadJson` and `SnapshotId`.
The decoder checks a shared snapshot ID, unique identities and expected row counts
before replacing the displayed data. The model must use DirectQuery with Kusto
end-user Entra SSO. Consumers need app access, model Read + Build, and KQL read
permissions. No user permissions are granted by this repository.

The adapter separates the enclosing Fabric portal from its extension frame. Browser
ancestry, exact-origin/window binding and an SDK PKCE-backed session precede the
fixed DAX query. Failed authentication, query errors and invalid results stay visible.
See [FRONTEND.md](FRONTEND.md) for protocol and rendering details.

## Deployment

Use the official Rayfin CLI with an explicitly reviewed workspace and AppBackend
binding. Do not copy an existing app's deployment registry or point a new project
at the original `rayfin-3d-production-factory` AppBackend.

This folder intentionally does not include a pre-bound deployment registry or an
automatic publishing command. In your separate, correctly bound Rayfin project,
configure static hosting to package the native `dist-fabric` output, include the
runtime dependencies' license notices, review `rayfin up --dry-run`, deploy with
`rayfin up`, and inspect `rayfin up status`. Deploy static assets only, not this whole
source folder or the local Python API.

Source publication does not prove native tenant-side connectivity. After deployment,
open the app through Fabric in Edge or Chrome, confirm a successful snapshot, then
run the existing notebook with NZ supermarket orders enabled. Compare new order IDs,
line items and last-event times with KQL. Five-second polling is not a guaranteed
end-to-end latency; ingestion and DirectQuery add delay.

## Tests

```powershell
npm test
npm run build
npm run test:browser

.\.venv\Scripts\python.exe -m unittest backend.test_backend -q
```

For the isolated native browser suite, use a separate PowerShell terminal in this
folder with the following **test-only** values. No live endpoint or publishable key
is needed. Never deploy this test bundle; close the test terminal and rebuild using
your deployment configuration afterward.

```powershell
$env:VITE_RAYFIN_WORKSPACE_ID = 'd93a2e35-f91d-4e31-a905-d0c503821af7'
$env:VITE_RAYFIN_ITEM_ID = '8d68a675-6533-476f-94e6-e74e45c997a9'
$env:VITE_RAYFIN_MODEL_ID = 'bde0a59e-f906-4876-aa15-5baaef99df12'
$env:VITE_RAYFIN_API_URL = "https://test-only.pbidedicated.windows.net/workspaces/$env:VITE_RAYFIN_WORKSPACE_ID/appbackends/$env:VITE_RAYFIN_ITEM_ID/"
$env:VITE_RAYFIN_PUBLISHABLE_KEY = 'pk-test-only-publishable'
npm run build:fabric
npm run test:browser:fabric
```

If Playwright reports a missing browser:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
npx playwright install chromium
```

Browser tests intercept synthetic services and do not start notebook jobs or access
live Fabric. Native tests execute the built SDK code in nested test frames and verify
successive order/line updates. They are not a substitute for a signed-in tenant-side
connection check. `SNAPSHOT_VALIDATION_FILE` optionally validates a local real capture;
never commit that capture or use it as a runtime fallback.
