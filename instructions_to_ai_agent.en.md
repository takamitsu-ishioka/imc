2026-10-14 14:09:26(JST) translate.sh: asking claude to translate Japanese -> English... (can take a few minutes for long documents)
2026-10-14 14:09:27(JST) translate.sh: still running, elapsed 1s (not blocked)
2026-10-14 14:09:28(JST) translate.sh: still running, elapsed 2s (not blocked)
2026-10-14 14:09:29(JST) translate.sh: still running, elapsed 3s (not blocked)
2026-10-14 14:09:30(JST) translate.sh: still running, elapsed 4s (not blocked)
2026-10-14 14:09:31(JST) translate.sh: still running, elapsed 5s (not blocked)
2026-10-14 14:09:32(JST) translate.sh: still running, elapsed 6s (not blocked)
2026-10-14 14:09:33(JST) translate.sh: still running, elapsed 7s (not blocked)
2026-10-14 14:09:34(JST) translate.sh: still running, elapsed 8s (not blocked)
2026-10-14 14:09:35(JST) translate.sh: still running, elapsed 9s (not blocked)
2026-10-14 14:09:36(JST) translate.sh: still running, elapsed 10s (not blocked)
2026-10-14 14:09:37(JST) translate.sh: still running, elapsed 11s (not blocked)
2026-10-14 14:09:38(JST) translate.sh: still running, elapsed 12s (not blocked)
2026-10-14 14:09:39(JST) translate.sh: still running, elapsed 13s (not blocked)
2026-10-14 14:09:39(JST) translate.sh: done (exit 0). Next: review the translated output.
# Instructions for the AI Agent (imc system)

Operating procedures that the AI Agent must follow, extracted from design.md.  

## What you may and may not touch

- Do **not read or write** `.env`. The user copies it from `.env.template` and writes it by hand.
  The only file the AI Agent may edit is `.env.template`.  
- Everything under `_var/` is generated output. Do not edit it by hand. If it breaks, rebuild it with `initialize.sh`.
- `tag_rules.tsv` and `tag_rules.local.tsv` are primary data. The AI Agent only **makes proposals** and must always get human confirmation before applying them.
- `tag_rules.tsv` is committed to a public repository. Sender (`from`) rules could reveal
  which bank, tax office, etc. is being used, so do not write them there. Prefer subject-based
  rules. Only when a sender rule is truly necessary, write it in the gitignored
  `tag_rules.local.tsv` (created from `tag_rules.local.tsv.template`).
- This document and `design.md` are primary documents that contain instructions for the agent. Do not edit them unless the prompt explicitly says so.

## Constraints on notification body

The only things allowed in the notification body are the **sender and subject**.  
Never include the body text, attachments, URLs, or authentication codes. This is because the notification goes through the public ntfy server.  

`IMC_NTFY_TOPIC` must not be a guessable name.  
On a public server, the topic name is effectively a password.  
`imc_digest_notify.sh` rejects any topic that lacks a random part of 32 or more hexadecimal characters.  
Do not loosen this check.  

## Procedure for changing rules (DJC)

```bash
RULES=(tag_rules.tsv)
[ -f tag_rules.local.tsv ] && RULES+=(tag_rules.local.tsv)

imc_mail_list.sh '*' tsv > before.tsv
# Edit tag_rules.tsv / tag_rules.local.tsv (the AI Agent stops here. Everything after requires human confirmation)
imc_mail_list.sh '*' json | imc_tag_apply.sh "${RULES[@]}" --dry-run > plan.tsv
# plan.tsv is the entire change. This is all the human needs to look at
imc_mail_list.sh '*' json | imc_tag_apply.sh "${RULES[@]}" --confirm > /dev/null
imc_mail_list.sh '*' tsv > after.tsv
diff before.tsv after.tsv
```

- Do not **judge whether a rule is good by reading it**. Apply it and look at the diff.
- If `plan.tsv` is empty, that rule change changes nothing. Accepting or rejecting it is meaningless.
- **Always** pass **all messages** (`'*'`) to `imc_tag_apply.sh`.
  If you pass a narrowed-down list, stale tags remain on messages outside the range.
- If `tag_rules.local.tsv` exists, always pass it together with the other file. If you pass
  only one of them, the tags derived from the other get removed (`imc_tag_apply.sh` judges
  the tags of any file not passed to it as "no longer needed").

## Daily run

Call `imc_morning_run.sh` once a day from Windows Task Scheduler.  
Do not use WSL cron. If WSL is down it does not run, and you would not notice that it did not run.  

```
wsl.exe -d <distro> -u developer -- /home/developer/imc/imc_morning_run.sh 'tag:actionable and not tag:done'
```


## Send the notification even on failure

`imc_morning_run.sh` always reaches `imc_digest_notify.sh`, even if sync or sorting fails.  
It passes the failure details as the second argument, the anomaly note, and the note appears at the top of the notification body with a `⚠`.  
**Do not change this path into a form that exits on failure.**
The most dangerous failure in this system is a stale "0 actionable items" notification arriving silently.  

Only this command uses an absolute path. This is because `$PATH` is not available from the Windows side.
