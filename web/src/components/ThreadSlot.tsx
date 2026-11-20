// SPDX-License-Identifier: Apache-2.0
// TASK 12 SLOT: replace this placeholder with the Thread tab (GET /api/patches/<name>/mails).
export function ThreadSlot({ name }: { name: string }) {
  return <div className="muted" data-testid="thread-slot" data-name={name}>The thread view comes next.</div>;
}
