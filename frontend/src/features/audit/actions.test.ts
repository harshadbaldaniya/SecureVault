import { expect, it } from "vitest";

import shared from "../../../../shared/audit-actions.json";

import { AUDIT_ACTIONS } from "./actions";

it("matches the action list shared with the backend", () => {
  expect([...AUDIT_ACTIONS]).toEqual(shared);
});
