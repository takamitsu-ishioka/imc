2026-10-14 07:45:15(JST) translate.sh: asking claude to translate Japanese -> English... (can take a few minutes for long documents)
2026-10-14 07:45:17(JST) translate.sh: still running, elapsed 2s (not blocked)
2026-10-14 07:45:18(JST) translate.sh: still running, elapsed 3s (not blocked)
2026-10-14 07:45:19(JST) translate.sh: still running, elapsed 4s (not blocked)
2026-10-14 07:45:20(JST) translate.sh: still running, elapsed 5s (not blocked)
2026-10-14 07:45:21(JST) translate.sh: still running, elapsed 6s (not blocked)
2026-10-14 07:45:22(JST) translate.sh: still running, elapsed 7s (not blocked)
2026-10-14 07:45:23(JST) translate.sh: still running, elapsed 8s (not blocked)
2026-10-14 07:45:24(JST) translate.sh: still running, elapsed 9s (not blocked)
2026-10-14 07:45:24(JST) translate.sh: done (exit 0). Next: review the translated output.
# imc — Integrated Message Client

A personal message aggregation platform that gathers messages addressed to me from various places (self-hosted mail, Gmail, Outlook, Teams, etc.) into one place every morning, and sends push notifications to my smartphone only for the ones that need action.

It was prompted by a recurrence-prevention concern: I missed a US bank's login notification sent to my self-hosted mail server, and my account almost got deactivated. See [`design.md`](design.md) for details.

## Usage

```bash
cp .env.template .env && chmod 600 .env
vi .env                    # Write the IMAP info and a randomized ntfy topic
vi tag_rules.tsv           # Write rules for the senders and subjects to be judged as actionable
./initialize.sh            # Install isync/notmuch/neomutt and generate the configuration
./imc_mail_sync.sh all     # Initial sync
./imc_mail_list.sh '*' tsv | less
./imc_digest_notify.sh 'tag:actionable and not tag:done' '' --dry-run
```

Once you have confirmed that notifications reach your smartphone, call `imc_morning_run.sh` once every morning from Windows Task Scheduler. The steps are in [`instructions_to_ai_agent.md`](instructions_to_ai_agent.md).

## Structure

- [`design.md`](design.md) — Purpose, inputs, exchange formats, outputs, and structure (primary source)
- [`instructions_to_ai_agent.md`](instructions_to_ai_agent.md) — Operating rules for the AI Agent (primary source; do not edit)
- The English versions of each are `.en.md`

## Confidential information

`.env` contains the IMAP password and the ntfy topic. It is covered by `.gitignore` and will not be committed. `.env.template` lists the required keys.

Everything under `_var/` (the Maildir copy, the notmuch index, and the generated configuration) is secondary information that can be regenerated, and it contains confidential material in the form of message bodies, so it is likewise not committed.
