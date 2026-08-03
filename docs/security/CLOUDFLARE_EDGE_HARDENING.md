# Cloudflareエッジ層での多層防御設定（S-11）

**前提**: 本書はCloudflare Tunnelを公式デプロイ手段とする現行構成向けの設定ガイドである。
将来Tailscale・Nginx・Traefik・Caddyや、リバースプロキシを介さない直接公開など別の
デプロイ手段を公式サポートする場合は、それぞれの経路に応じた設定を別途検討すること。

`def_kari/api/routes/session.py` のアプリ内対策（クライアントIP解決・生成系レート制限）
はアプリコードの正しさに依存する「内側の層」である。本書のエッジ層設定は、それを
すり抜けた場合の「外側の層」として機能し、アプリ側にバグがあっても防御が持続する。

## 1. Cloudflare Rate Limiting Rules

Cloudflareダッシュボード → Security → WAF → Rate limiting rules で以下を設定する
（Terraformで管理する場合は `cloudflare_rate_limit` / `cloudflare_ruleset` リソースを使用）。

### 招待コード試行の制限

```
Rule name: invite-join-rate-limit
When incoming requests match: (http.request.uri.path eq "/api/session/join")
Rate: 10 requests per 1 minute (per IP)
Action: Block for 3600 seconds
```

### 生成系エンドポイントの制限

```
Rule name: generate-image-rate-limit
When incoming requests match: (http.request.uri.path matches "^/api/session/[^/]+/generate-image$")
Rate: 6 requests per 1 minute (per IP)
Action: Block for 60 seconds
```

これらはエッジが実クライアントIPを直接見ているため、アプリ内の
`_resolve_client_ip()` が万一誤動作しても独立して機能する。

## 2. Cloudflare WAF マネージドルール

Security → WAF → Managed rules で "Cloudflare Managed Ruleset" および
"Cloudflare OWASP Core Ruleset" を有効化する。既知の攻撃パターン（インジェクション試行、
異常なペイロード等）をアプリに到達する前に弾ける。

## 3. Cloudflare Access（Zero Trust）— 任意・推奨

招待制セッションをさらに保護したい場合、Cloudflare Access で「このセッションのURLは
事前に許可されたメールアドレス/ワンタイムPINでしか到達できない」というエッジでの
認証ゲートを重ねることができる。招待コード運用のUXを変えずに、後ろにもう1枚
シークレットレイヤーを足す形で導入できる。

## 4. 設定の管理方針

エッジ層の設定はコード外（Cloudflareダッシュボード）で管理されるため、設定変更が
コードレビュー・バージョン管理の対象から漏れやすい。Terraformの
[`cloudflare` provider](https://registry.terraform.io/providers/cloudflare/cloudflare) 等で
IaC化し、本リポジトリ内（例: `infra/cloudflare/`）で設定をレビュー可能にすることを推奨する。
本書はその設定内容の一次ドキュメントとして、Terraform化後も同期を保つこと。
