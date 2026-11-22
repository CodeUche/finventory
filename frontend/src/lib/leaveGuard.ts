// A page that holds unsaved work (the register's half-rung basket) can register a question here.
// Places that move the user elsewhere without a plain link click (the Ctrl+K palette) ask it first.
type Guard = () => Promise<boolean>
let guard: Guard | null = null

export function setLeaveGuard(g: Guard | null): void { guard = g }

/** True when it is fine to go ahead and navigate. */
export async function canLeave(): Promise<boolean> {
  return guard ? guard() : true
}
