/**
 * Look of the two sides of a chat, shared by the Messages page.
 * The colours are kit tokens in src/styles/ds.css (.chat-bubble-mine / .chat-bubble-theirs).
 */

/** Bubble class for a message: "mine" is blue with white text, "theirs" is a lavender tint with dark text. */
export function bubbleClass(side: 'mine' | 'theirs'): string {
  return side === 'mine' ? 'chat-bubble-mine' : 'chat-bubble-theirs'
}

// DERIVED - not designer-approved: the designer drew no Messages screen. Each name colour
// has a deep shade for the light page and a pale shade for the dark page (the old single
// "-400" shades, such as lime, were about 1.4:1 on the ivory page).
export const TEAMMATE_PALETTE = [
  { text: 'text-rose-800 dark:text-rose-300', bg: 'bg-rose-500/20' },
  { text: 'text-sky-800 dark:text-sky-300', bg: 'bg-sky-500/20' },
  { text: 'text-violet-800 dark:text-violet-300', bg: 'bg-violet-500/20' },
  { text: 'text-cyan-900 dark:text-cyan-300', bg: 'bg-cyan-500/20' },
  { text: 'text-lime-900 dark:text-lime-300', bg: 'bg-lime-500/20' },
  { text: 'text-fuchsia-800 dark:text-fuchsia-300', bg: 'bg-fuchsia-500/20' },
  { text: 'text-teal-800 dark:text-teal-300', bg: 'bg-teal-500/20' },
  { text: 'text-indigo-800 dark:text-indigo-300', bg: 'bg-indigo-500/20' },
] as const
