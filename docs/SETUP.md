# 不動産受付帳 抽出ツール — セットアップ & デプロイ手順

## 1. ローカル開発環境

### 前提
- Python 3.11 以上
- Git

### 初回セットアップ

```powershell
# 仮想環境作成 & 有効化
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell

# 依存パッケージインストール (開発用)
pip install -r requirements-dev.txt
```

### 認証設定 (ローカル用)

```powershell
# テンプレートをコピー
Copy-Item config\auth.yaml.example config\auth.yaml
```

`config/auth.yaml` を開いてユーザー名・パスワードハッシュを設定します。

パスワードハッシュの生成:
```powershell
.venv\Scripts\python.exe -c "import streamlit_authenticator as s; print(s.Hasher.hash('新しいパスワード'))"
```

### 起動

```powershell
streamlit run app.py
```

### テスト実行

```powershell
pytest tests/ -v
```

---

## 2. GitHub Private リポジトリへのプッシュ

### 初回

```powershell
git init
git add .
git commit -m "feat: 不動産受付帳 抽出ツール 初回リリース"
```

GitHub でプライベートリポジトリ `touki-extractor` を作成してから:

```powershell
git remote add origin https://github.com/<your-org>/touki-extractor.git
git branch -M main
git push -u origin main
```

---

## 3. Streamlit Community Cloud へのデプロイ

### 手順

1. [share.streamlit.io](https://share.streamlit.io) にアクセスしてログイン
2. **New app** → リポジトリ `touki-extractor` を選択
3. Branch: `main` / Main file path: `app.py`
4. **Advanced settings** → **Secrets** タブを開く
5. `.streamlit/secrets.toml.example` の内容を参考に、実際の値を入力して保存

### Secrets の形式 (Streamlit Cloud ダッシュボードに貼り付け)

```toml
[credentials.usernames.harada1]
name = "原田 太郎"
email = "harada1@harada-tatemono.example"
password = "$2b$12$..."

[credentials.usernames.harada2]
name = "原田 花子"
email = "harada2@harada-tatemono.example"
password = "$2b$12$..."

[cookie]
name = "touki_auth"
key = "ランダムな秘密鍵 (secrets.token_urlsafe(32) で生成)"
expiry_days = 30
```

6. **Deploy** をクリック → 数分でデプロイ完了

### 注意事項

- `config/auth.yaml` はローカル開発専用。リポジトリには含まれません (.gitignore 済み)
- 本番環境では Streamlit Secrets のみが認証情報の参照先になります
- PDF はサーバーのメモリ上で処理され、永続化されません
- アップロード上限は `.streamlit/config.toml` の `maxUploadSize = 50` (MB) で設定

---

## 4. パスワード変更手順

1. 新しいハッシュを生成:
   ```powershell
   .venv\Scripts\python.exe -c "import streamlit_authenticator as s; print(s.Hasher.hash('新パスワード'))"
   ```
2. ローカル: `config/auth.yaml` の該当ユーザーの `password` を更新
3. 本番: Streamlit Cloud ダッシュボード → Secrets → 該当ハッシュを更新 → **Save**
4. アプリが自動再起動し、新パスワードが有効になります
