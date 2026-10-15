# imc — Integrated Message Client

各所に届く自分宛てメッセージ（自前メール・Gmail・Outlook・Teamsなど）を毎朝1か所に
集約し、要対応のものだけをスマートフォンへプッシュ通知する、個人用のメッセージ集約基盤。

きっかけは、自前メールサーバー宛ての米国銀行ログイン通知を見逃し、口座が無効化され
かけたことの再発。詳細は [`design.md`](design.md) を参照。

## 使い方

```bash
cp .env.template .env && chmod 600 .env
vi .env                    # IMAP情報と、乱数つきのntfyトピックを書く
vi tag_rules.tsv           # 要対応と判定する送信者・件名のルールを書く
./initialize.sh            # isync/notmuch/neomutt/mblazeの導入、設定の生成
./imc_mail_sync.sh all     # 初回同期
./imc_mail_list.sh '*' tsv | less
./imc_digest_notify.sh 'tag:actionable and not tag:done' '' --dry-run
```

スマートフォンへの通知を確認できたら、`imc_morning_run.sh` をWindowsタスク
スケジューラから毎朝1回呼ぶ。手順は [`instructions_to_ai_agent.md`](instructions_to_ai_agent.md) にある。

## 構造

- [`design.md`](design.md) — 目的・入力・交換形式・出力・構造（一次情報）
- [`instructions_to_ai_agent.md`](instructions_to_ai_agent.md) — AI Agentへの操作規則（一次情報・編集禁止）
- 英語版はそれぞれ `.en.md`

## 機密情報

`.env` には IMAP パスワードと ntfy トピックが入る。`.gitignore` 対象で、
コミットされない。`.env.template` が必要なキーの一覧。

`_var/` 配下（Maildirの複製・notmuchの索引・生成済み設定）はすべて再生成可能な
二次情報であり、メール本文という機密を含むため同様にコミットされない。
