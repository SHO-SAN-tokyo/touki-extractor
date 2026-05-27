# samples/

実際のPDFサンプルを配置するディレクトリ。

| ファイル | 用途 |
|---|---|
| `sakai_march_sample.pdf` | 堺支局 令和8年3月分 (開発・テスト用) |
| `sakai_raw.txt` | pdftotext -layout で抽出した生テキスト (解析用) |

## 注意

`*.pdf` および `*_raw.txt` は `.gitignore` により Git 管理外。
実データを誤ってコミットしないよう注意。
