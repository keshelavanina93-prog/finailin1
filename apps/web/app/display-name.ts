/** Presentation only: original strings, aliases and canonical identities remain intact. */
export function displayName(value: string): string {
  const choices = value.split(/\s*\/\/\s*/).map(part => part.trim()).filter(Boolean);
  const preferred = choices.find(part => !/\p{Script=Cyrillic}/u.test(part));
  if (preferred) return preferred;
  // Never invent a translation or let a Russian-only source title become the main UI name.
  return "Name awaiting localization";
}
