2026-10-14 07:44:41(JST) translate.sh: asking claude to translate Japanese -> English... (can take a few minutes for long documents)
2026-10-14 07:44:42(JST) translate.sh: still running, elapsed 1s (not blocked)
2026-10-14 07:44:43(JST) translate.sh: still running, elapsed 2s (not blocked)
2026-10-14 07:44:44(JST) translate.sh: still running, elapsed 3s (not blocked)
2026-10-14 07:44:45(JST) translate.sh: still running, elapsed 4s (not blocked)
2026-10-14 07:44:46(JST) translate.sh: still running, elapsed 5s (not blocked)
2026-10-14 07:44:47(JST) translate.sh: still running, elapsed 6s (not blocked)
2026-10-14 07:44:48(JST) translate.sh: still running, elapsed 7s (not blocked)
2026-10-14 07:44:49(JST) translate.sh: still running, elapsed 8s (not blocked)
2026-10-14 07:44:50(JST) translate.sh: still running, elapsed 9s (not blocked)
2026-10-14 07:44:51(JST) translate.sh: still running, elapsed 10s (not blocked)
2026-10-14 07:44:51(JST) translate.sh: done (exit 0). Next: review the translated output.
# AI Agent Instructions (imc System)

Operating procedures that AI Agents must follow, extracted from design.md.  

## What You May and May Not Touch

- Do **not read or write** `.env`. The user copies it from `.env.template` and fills it in by hand.
  The only file an AI Agent may edit is `.env.template`.  
- Everything under `_var/` is generated output. Do not edit it by hand. If it breaks, rebuild it with `initialize.sh`.
- `tag_rules.tsv` is primary data. The AI Agent only **makes proposals**, and must always get human confirmation before applying them.
- This document and `design.md` are primary documents that contain instructions for agents. Do not edit them unless the prompt explicitly says to.

## Restrictions on Notification Body

The notification body may contain **only the sender and the subject**.  
Never include the body text, attachments, URLs, or authentication codes. This is because notifications go through the public ntfy server.  

`IMC_NTFY_TOPIC` must not be a guessable name.  
On a public server, the topic name is effectively a password.  
`imc_digest_notify.sh` rejects any topic that lacks a random part of at least 32 hexadecimal characters.  
Do not loosen this check.  

## Procedure for Changing Rules (DJC)

```bash
imc_mail_list.sh '*' tsv > before.tsv
# Edit tag_rules.tsv (the AI Agent stops here. Everything after this happens after human confirmation)
imc_mail_list.sh '*' json | imc_tag_apply.sh tag_rules.tsv --dry-run > plan.tsv
# plan.tsv is the entire change. This is all a human needs to look at
imc_mail_list.sh '*' json | imc_tag_apply.sh tag_rules.tsv --confirm > /dev/null
imc_mail_list.sh '*' tsv > after.tsv
diff before.tsv after.tsv
```

- Do not judge whether a rule is good or bad **by reading it**. Apply it and look at the diff.
- If `plan.tsv` is empty, that rule change changes nothing. Adopting or rejecting it is meaningless.
- Always pass **all messages** (`'*'`) to `imc_tag_apply.sh`.
  If you pass a narrowed list, stale tags remain on messages outside the range.  

## Daily Run

Call `imc_morning_run.sh` once a day from Windows Task Scheduler.  
Do not use WSL cron. If WSL is down, it won't run, and you won't notice that it didn't run.  

```
wsl.exe -d <distro> -u developer -- /home/developer/imc/imc_morning_run.sh 'tag:actionable and not tag:done'
```


## Send the Notification Even on Failure

`imc_morning_run.sh` always reaches `imc_digest_notify.sh`, even if sync or sorting fails.  
Pass the details of the failure in the second argument, the anomaly memo, and it appears at the top of the notification body with a `⚠`.  
**Do not change this path into a form that exits on failure.**
The most dangerous failure in this system is quietly receiving a stale "0 actionable" message.  

Only this command uses an absolute path. This is because there is no `$PATH` when it is run from the Windows side.
