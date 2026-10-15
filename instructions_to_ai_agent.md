# AI Agentへの指示（imcシステム）

design.md から切り出した、AI Agentが必ず守るべき操作手順。  

## 触ってよいもの / いけないもの

- `.env` は**読まない・書かない**。ユーザーが `.env.template` からコピーして手で書く。
  AI Agent が編集してよいのは `.env.template` のみ。  
- `_var/` 配下はすべて生成物。手で編集しない。壊れたら `initialize.sh` で作り直す。
- `tag_rules.tsv`・`tag_rules.local.tsv` は一次データ。AI Agent は**提案のみ**行い、適用前に必ず人間の確認を得る。
- `tag_rules.tsv` はpublicリポジトリにcommitされる。送信者（`from`）ルールは
  「どの銀行・税務署等を使っているか」を特定しうるので書かない。件名ベースの
  ルールを優先する。どうしても送信者ルールが必要な場合のみ、gitignore対象の
  `tag_rules.local.tsv`（`tag_rules.local.tsv.template`から作る）へ書く。
- この文書と `design.md` はエージェントへの指示を含む一次文書。プロンプトで明示されない限り編集禁止。

## 通知本文の制約

通知本文に載せてよいのは**差出人と件名だけ**である。  
本文・添付・URL・認証コードは絶対に載せない。公開 ntfy サーバーを経由するためである。  

公開サーバーでは `IMC_NTFY_TOPIC`（トピック名）が事実上のパスワードである。  
キーの安全性確保はユーザーの責任とする。  

## ルールを変更するときの手順（DJC）

```bash
RULES=(tag_rules.tsv)
[ -f tag_rules.local.tsv ] && RULES+=(tag_rules.local.tsv)

imc_mail_list.sh '*' tsv > before.tsv
# tag_rules.tsv / tag_rules.local.tsv を編集（AI Agentはここまで。以降は人間の確認後）
imc_mail_list.sh '*' json | imc_tag_apply.sh "${RULES[@]}" --dry-run > plan.tsv
# plan.tsv が変更の全体。人間が見るのはこれだけでよい
imc_mail_list.sh '*' json | imc_tag_apply.sh "${RULES[@]}" --confirm > /dev/null
imc_mail_list.sh '*' tsv > after.tsv
diff before.tsv after.tsv
```

- ルールの良し悪しを**読んで判断しない**。適用して差分を見る。
- `plan.tsv` が空なら、そのルール変更は何も変えていない。採用も却下も意味がない。
- `imc_tag_apply.sh` には**必ず全件**（`'*'`）を渡す。
  絞り込んだ一覧を渡すと、範囲外のメッセージに古いタグが残る。
- `tag_rules.local.tsv` が存在するなら必ず一緒に渡す。片方だけ渡すと、
  もう片方由来のタグが消えてしまう（`imc_tag_apply.sh`は渡されなかった
  ファイルのタグを「もう要らない」と判断するため）。

## 日次実行

Windows タスクスケジューラから `imc_morning_run.sh` を1日1回呼ぶ。  
WSL の cron は使わない。WSL が落ちていれば動かず、動かなかったことに気づけないからである。  

```
wsl.exe -d <distro> -u developer -- /home/developer/imc/imc_morning_run.sh 'tag:actionable and not tag:done'
```


## 失敗しても通知は送る

`imc_morning_run.sh` は同期や仕分けが失敗しても `imc_digest_notify.sh` まで  
必ず到達する。第2引数の異常メモに失敗内容を渡し、通知本文の先頭へ `⚠` 付きで出す。  
**この経路を「失敗したら exit する」形に直してはならない。**
静かに古い「要対応 0件」が届くことが、この仕組みで最も危険な故障だからである。  

このコマンドだけは絶対パスを使う。Windows 側からは `$PATH` が無いためである。  
