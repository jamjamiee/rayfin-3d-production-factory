type JsonRecord = Record<string, unknown>;

function record(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function column(row: JsonRecord, name: string): unknown {
  const keys = [name, `[${name}]`, `FactorySnapshotRows[${name}]`].filter((key) =>
    Object.prototype.hasOwnProperty.call(row, key),
  );
  const key = keys[0];
  if (keys.length !== 1 || key === undefined) {
    throw new Error(`The Fabric model response is missing or has ambiguous ${name} columns.`);
  }
  return row[key];
}

export function reconstructSnapshot(rows: unknown): unknown {
  if (!Array.isArray(rows) || rows.length > 841) {
    throw new Error("The Fabric model returned an invalid or oversized snapshot.");
  }
  let metadata: JsonRecord | undefined;
  const orders: JsonRecord[] = [];
  const lines: JsonRecord[] = [];
  const activity: JsonRecord[] = [];
  const keys = new Set<string>();
  let snapshotId: string | undefined;
  for (const row of rows) {
    if (!record(row)) throw new Error("The Fabric model returned an invalid row.");
    const kind = column(row, "Kind");
    const key = column(row, "RowKey");
    const json = column(row, "PayloadJson");
    const rowSnapshotId = column(row, "SnapshotId");
    if (typeof rowSnapshotId !== "string" || !rowSnapshotId
        || (snapshotId !== undefined && snapshotId !== rowSnapshotId)) {
      throw new Error("Fabric returned rows from different snapshots. Refresh to obtain a consistent view.");
    }
    snapshotId = rowSnapshotId;
    if (typeof key !== "string" || keys.has(key) || typeof json !== "string") {
      throw new Error("The Fabric model returned duplicate or invalid row identities.");
    }
    keys.add(key);
    let payload: unknown;
    try {
      payload = JSON.parse(json);
    } catch (error) {
      if (error instanceof SyntaxError) {
        throw new Error("A Fabric snapshot record contains invalid JSON.");
      }
      throw error;
    }
    if (!record(payload)) throw new Error("A Fabric snapshot record is not an object.");
    if (kind === "meta") {
      if (metadata || key !== "meta") throw new Error("The Fabric snapshot has duplicate metadata.");
      metadata = payload;
    } else {
      if (typeof payload.id !== "string" || key !== `${kind}:${payload.id}`) {
        throw new Error("A Fabric snapshot record has an inconsistent identity.");
      }
      if (kind === "order") orders.push(payload);
      else if (kind === "line") lines.push(payload);
      else if (kind === "activity") activity.push(payload);
      else throw new Error("The Fabric snapshot includes an unsupported record kind.");
    }
  }
  if (!metadata || orders.length > 200 || lines.length > 600 || activity.length > 40) {
    throw new Error("The Fabric snapshot is incomplete or exceeds its supported limits.");
  }
  const counts = metadata.__rowCounts;
  if (!record(counts) || counts.orders !== orders.length || counts.lines !== lines.length
      || counts.activity !== activity.length) {
    throw new Error("Fabric returned a truncated or incomplete snapshot; the previous data has not been replaced.");
  }
  const snapshot: JsonRecord = { ...metadata, orders, lines, activity };
  delete snapshot.__rowCounts;
  return snapshot;
}

export function rowsFromDaxResult(value: unknown): unknown {
  if (!record(value) || value.error || !Array.isArray(value.results) || value.results.length !== 1) {
    throw new Error("Fabric did not return a successful semantic-model query result.");
  }
  const result = value.results[0];
  if (!record(result) || result.error || !Array.isArray(result.tables) || result.tables.length !== 1) {
    throw new Error("The semantic-model query failed or returned unexpected tables.");
  }
  const table = result.tables[0];
  if (!record(table) || table.error || !Array.isArray(table.rows)) {
    throw new Error("The semantic-model query returned missing or incomplete rows.");
  }
  return table.rows;
}
