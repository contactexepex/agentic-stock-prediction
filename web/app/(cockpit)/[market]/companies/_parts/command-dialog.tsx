// Moved: the company-command dialog is B7's shared component since 2026-10-08
// (web/components/blocks/company-command-dialog.tsx). This re-export only keeps B15's company page building until it
// imports the shared component directly; B14 deletes this file then.
export { CommandDialog, type Intent, type Recorded } from "../../../../../components/blocks/company-command-dialog.tsx";
