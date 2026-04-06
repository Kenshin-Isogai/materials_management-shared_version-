# オペレーター操作ガイド

> **対象読者:** 日常的にシステムを操作するオペレーター（在庫管理・発注・プロジェクト管理を担当する方）  
> **前提:** 管理者からアプリケーションの URL を受け取り、ブラウザでアクセスできる状態

---

## 目次

1. [はじめに：アカウント登録とサインイン](#0-はじめにアカウント登録とサインイン)
2. [基本的な画面構成](#1-基本的な画面構成)
3. [発注データのインポート（Orders）](#2-発注データのインポートorders)
4. [部品マスタ登録（Items）](#3-部品マスタ登録items)
5. [利用可能な在庫数の確認（Snapshot）](#4-利用可能な在庫数の確認snapshot)
6. [プロジェクトの作成と部品要件の登録](#5-プロジェクトの作成と部品要件の登録)
7. [プランニングボードで不足分を確認する](#6-プランニングボードで不足分を確認する)
8. [Confirm Allocation（確保の確定）](#7-confirm-allocation確保の確定)
9. [不足分の調達依頼（Procurement Batch / RFQ）](#8-不足分の調達依頼procurement-batch--rfq)
10. [予約（Reservation）の管理](#9-予約reservationの管理)
11. [入荷処理（Arrival）](#10-入荷処理arrival)
12. [よくある操作フローのまとめ](#11-よくある操作フローのまとめ)

---

## 0. はじめに：アカウント登録とサインイン

本アプリケーションは Google Cloud 上で稼働しており、利用にはメールアドレスとパスワードによるアカウントが必要です。初回アクセス時にアカウントを作成し、管理者の承認を受けてから使い始めます。

### 0.1 初回アカウント登録の手順

1. 管理者から受け取った URL をブラウザで開く
2. **サインイン画面** が表示されるので、**「アカウントを作成」** または **「Sign Up」** のリンクをクリック
3. メールアドレスとパスワードを入力して登録を送信する
4. **メール確認（Email Verification）** のメールが登録アドレスに届く

   > ⚠️ **迷惑メールフォルダに注意**  
   > 確認メールは Firebase（Google）が送信するため、**件名が英語のデフォルトメール** になります。**迷惑メール（スパム）フォルダに振り分けられることが多いです**。  
   > 数分待ってもメールが届かない場合は、まず迷惑メールフォルダを確認してください。
   >
   > - 送信元: `noreply@[プロジェクト名].firebaseapp.com` のようなアドレス
   > - 件名: `Verify your email address` などの英語タイトル

5. メール本文の **確認リンク（Verify email address）** をクリックする
6. 確認後、再度アプリの URL を開き、登録したメールアドレスとパスワードでサインイン
7. **登録申請画面** が表示される。以下の項目を入力して申請を送信する

   | 項目 | 説明 |
   |-----|------|
   | Display Name | 表示名（必須） |
   | Username | ログイン用ユーザー名（必須） |
   | Requested Role | 希望するロール（`operator` を選択） |
   | Memo | 申請理由など（任意） |

8. 管理者が申請を承認するまで待つ（承認前はアプリの操作画面にアクセスできません）
9. 管理者から承認の連絡を受けたら、再度サインインして利用開始

### 0.2 2 回目以降のサインイン

1. アプリの URL をブラウザで開く
2. メールアドレスとパスワードを入力して **Sign In**

> パスワードを忘れた場合はサインイン画面の **「パスワードをお忘れですか？」** からリセットメールを送れます（こちらも迷惑メールフォルダをご確認ください）。

---

## 1. 基本的な画面構成

左サイドバーに主要なページへのリンクが並んでいます。

| ページ名 | 主な用途 |
|---------|---------|
| **Dashboard** | 期限超過の注文・在庫アラート・直近のアクティビティ概要 |
| **Workspace** | プロジェクト横断の計画ボード（推奨メイン画面） |
| **Items** | 部品マスタの確認・登録・CSV インポート |
| **Orders** | 発注データのインポート・管理 |
| **Arrival** | 入荷処理（注文の到着登録） |
| **Reserve** | 予約の作成・管理 |
| **Movements** | 在庫移動・消費・調整 |
| **Snapshot** | 任意の日時点での在庫スナップショット確認 |
| **Projects** | プロジェクト定義・要件管理 |
| **Planning** | プロジェクトの順次ネッティング分析 |
| **Procurement** | 調達バッチ（RFQ）の管理 |
| **History** | 操作ログ・操作の取り消し |

---

## 2. 発注データのインポート（Orders）

### 2.1 インポートの流れ概要

発注 CSV を取り込む際は **プレビュー → 内容確認 → 確定** の 3 ステップを踏みます。途中で未登録の部品番号が見つかった場合は、先に部品マスタを登録してから再インポートします。
部品は、 (Supplier, item_number) の組によって uniquely identified です。

```
CSV アップロード
    ↓
プレビュー（行ごとにマッチング状態を確認）
    ↓
未解決品番あり？
  Yes → missing_items_registration.csv をダウンロード
        → Items ページで部品を登録
        → 同じ CSV を再インポート
  No  → 確定（インポート実行）
```

### 2.2 CSV の準備

インポートできる CSV の必須列は以下のとおりです（テンプレートは `Orders` ページの **Download Template** から取得できます）。

| 列名 | 必須 | 説明 |
|-----|-----|------|
| `supplier` | ✅ | サプライヤー名（全行に記載が必要） |
| `item_number` | ✅ | 発注時の品番 |
| `quantity` | ✅ | 発注数量 |
| `quotation_number` | ✅ | 見積番号 |
| `issue_date` | ✅ | 見積発行日（YYYY-MM-DD） |
| `order_date` | ✅ | 発注日（YYYY-MM-DD） |
| `quotation_document_url` | ✅ | 見積書の URL または識別文字列（SharePoint リンク等） |
| `expected_arrival` | — | 入荷予定日（YYYY-MM-DD） |
| `purchase_order_document_url` | — | 発注書の URL（任意） |
| `purchase_order_number` | — | 発注番号（重複インポート防止に使用） |

> ⚠️ **注意:** 
> 見積書, 発注書のURLは暫定的に　見積番号, 注文番号 と同一のものにしてください。
> (見積書, 発注書の Storage 場所が未確定のため)

> **ヒント:** 同じ発注番号 `(supplier + purchase_order_number)` を再インポートしようとするとロックエラーになります。意図的な再インポートが必要な場合はプレビュー画面で該当発注にチェックを入れて **Unlock** を選択してください。

### 2.3 操作手順

1. 左メニューから **Orders** を開く
2. **Import Purchase Order Lines CSV** セクションで CSV ファイルを選択（複数ファイル同時選択可）
3. **Preview** ボタンをクリック
4. プレビュー画面で各行のマッチング状態を確認する

   | 状態 | 意味 |
   |-----|-----|
   | `exact` | 完全一致。そのまま確定できる |
   | `high_confidence` | 高確信度の候補あり。内容を確認して確定 |
   | `needs_review` | 要確認。手動で正しい品番を選択 |
   | `unresolved` | 解決できない品番。部品マスタ登録が必要 |

5. `unresolved` 行がある場合 → **Download Missing Items CSV** をクリックして CSV を保存
6. その CSV を編集し（下記 [3.3 未登録品番の一括登録](#33-未登録品番の一括登録) 参照）、Items ページで登録
7. 同じ発注 CSV を再度インポートすると今度は解決できる
8. 全行が解決済みになったら **Confirm Import** をクリックして確定

### 2.4 エイリアス（Alias）について

サプライヤーが使う品番（例：パック品番）とシステム内の正規品番が異なる場合、**エイリアス** を登録することで次回以降の自動マッチングが機能します。プレビュー画面で行を修正した際に **Save as Alias** オプションが表示された場合はチェックを入れると便利です。

---

## 3. 部品マスタ登録（Items）

### 3.1 手動での 1 件登録

1. **Items** ページを開く
2. **Create Item** フォームに品番・メーカー・カテゴリ等を入力
3. **Save** をクリック

### 3.2 CSV による一括登録

1. **Items** ページの **Import Items CSV** セクションからテンプレート CSV をダウンロード
2. テンプレートを埋めて保存
3. CSV をアップロードして **Preview** → 内容確認 → **Confirm Import**

CSV の主な列：

| 列名 | 説明 |
|-----|------|
| `item_number` | 正規品番 |
| `manufacturer_name` | メーカー名 |
| `category` | カテゴリ（任意） |
| `row_type` | `item`（通常品）または `alias`（別名） |
| `canonical_item_number` | `alias` 行のとき：紐付け先の正規品番 |
| `units_per_order` | `alias` 行のとき：発注単位の倍率（例：10 入り箱 → `10`） |

### 3.3 未登録品番の一括登録

発注インポートで生成された `missing_items_registration.csv` を使う場合：

1. ダウンロードした CSV を開く
2. 各行の `resolution_type` 列を確認・編集する
   - `new_item`（デフォルト）：新規に部品マスタを作成
   - `alias`：既存の正規品番へのエイリアスとして登録（`canonical_item_number` 列に正規品番を記入）
3. 必要に応じて `manufacturer_name`、`category`、`description` を記入
4. **Items** ページの Import フォームで編集済み CSV をアップロード
5. **Preview** → **Confirm Import**
6. 登録完了後、発注インポートを再実行

---

## 4. 利用可能な在庫数の確認（Snapshot）

### 4.1 Snapshot ページの使い方

**Snapshot** ページでは、指定した日付時点での在庫状況を確認できます。ページを開くと当日 JST の `net available`（予約を差し引いた残数）が自動表示されます。

| 設定項目 | 説明 |
|--------|------|
| **Date** | 確認したい日付。過去・未来どちらも指定可 |
| **Mode** | `future`（現在 + 今後の入荷を加算）または `past`（過去時点の再現） |
| **Basis** | `net available`（予約分を差し引いた残数）または `raw`（物理在庫そのまま） |

> **推奨設定:** 「今この部品を何個使えるか」を確認したい場合は **Basis = net available**、**Mode = future** で未来の入荷込みの残数が確認できます。

### 4.2 表示される列の意味

| 列名 | 意味 |
|-----|-----|
| `quantity` | 指定基準での在庫数 |
| `allocated_quantity` | アクティブな予約によって確保されている数量 |
| `active_reservation_count` | アクティブな予約件数 |
| `allocated_project_names` | この在庫を予約しているプロジェクト名一覧 |

### 4.3 絞り込みとエクスポート

- ページ上部のフィルター（ロケーション・カテゴリ・キーワード・在庫不足のみ表示）で絞り込み可能
- **Export CSV** ボタンで現在の表示内容を CSV でダウンロードできます（オペレーター以上の権限が必要）

### 4.4 ロケーション別の在庫確認

**Location** ページでは、各ロケーション（保管場所）に何がいくつあるかを確認できます。

---

## 5. プロジェクトの作成と部品要件の登録

### 5.1 プロジェクトのライフサイクル

```
PLANNING（計画中）
    ↓ 要件が固まったら
CONFIRMED（確定済み）← 在庫・調達リソースをプロジェクト専用に確保
    ↓ 実作業開始
ACTIVE（進行中）
    ↓ 完了
COMPLETED（完了）
```

> ⚠️ **重要:** `PLANNING` 状態のプロジェクトは Planning Board での分析には「プレビュー」として表示され、後続プロジェクトのリソース計算に影響しません。`CONFIRMED` にすることで初めて計画パイプラインに組み込まれます。

### 5.2 プロジェクトの作成手順

1. **Projects** ページを開く
2. **Create Project** フォームに以下を入力

   | 項目 | 説明 |
   |-----|------|
   | Name | プロジェクト名（一意である必要あり） |
   | Description | 説明（任意） |
   | Planned Start | 開始予定日（YYYY-MM-DD）。Planning Board での分析基準日になる |
   | Status | 通常は `PLANNING` で作成し、後から変更する |

3. **Create Project** をクリック

### 5.3 部品要件（Requirements）の登録

プロジェクトに必要な部品の種類と数を登録します。

#### 方法 A：Projects ページから編集

1. プロジェクト一覧の **Edit** ボタンをクリック
2. **Requirements** セクションで部品を追加
3. `item_number,quantity` 形式（例：`ABC-123,5`）でテキスト入力し **Preview & Apply** → 解決状況を確認して **Apply to Requirements**

#### 方法 B：Workspace の Project ドロワーから

1. **Workspace** ページを開く
2. プロジェクトカードの **Edit** をクリックしてドロワーを開く
3. ドロワー内の要件グリッドで直接追加・編集

#### 要件の種類（requirement_type）

| 種類 | 用途 |
|-----|-----|
| `INITIAL` | 初期構成に必要な部品（デフォルト） |
| `SPARE` | 予備品 |
| `REPLACEMENT` | 交換用部品 |

---

## 6. プランニングボードで不足分を確認する

**Planning Board** は、プロジェクトが必要とする部品に対して、いつ・何個確保できるかを分析する画面です。プロジェクトの開始予定日に間に合う供給元をネッティング（順次割り当て）して計算します。

### 6.1 画面の開き方

- **Workspace** → **Planning Board** タブ または、
- 左メニューの **Planning**

### 6.2 基本的な操作手順

1. 画面上部のドロップダウンからプロジェクトを選択
2. **Date** フィールドに分析したい基準日（開始予定日）を入力
3. **Preview Impact** をクリックして分析を実行
4. Netting Grid でアイテムごとの状況を確認する

### 6.3 Netting Grid の読み方

| 列名 | 意味 |
|-----|-----|
| **Item** | 部品番号・メーカー |
| **Required** | プロジェクトで必要な総数量 |
| **Covered By Start** | 基準日までに確保できる数量 |
| **On-Time Gap** | 基準日に間に合わない不足数量 |
| **Recovered Later** | 基準日以降に回収（入荷等で補填）できる数量 |
| **Remaining** | 最終的に補填できない残不足 |
| **Coverage Breakdown** | 確保手段の内訳（下記） |
| **Recovery Breakdown** | 回収手段の内訳 |

#### Coverage Breakdown の色タグ

| タグ | 意味 |
|-----|-----|
| 🔵 `stock` | 現在の STOCK 在庫から充当 |
| 🌐 `generic_order` | プロジェクト未割当の汎用入荷予定 |
| 🟢 `dedicated_order` | このプロジェクト専用の入荷予定 |
| 🟡 `quoted_rfq` | RFQ で見積・確認済みの入荷予定 |

### 6.4 サマリー指標の意味

画面右上に表示される 6 つの指標：

| 指標 | 意味 |
|-----|-----|
| Required | プロジェクト全体の必要数合計 |
| Covered On Time | 基準日までに確保できる数合計 |
| On-Time Gap | 基準日に間に合わない不足合計 |
| Remaining | 最終的に解消できない不足合計 |
| Generic Committed | このプロジェクトが使う汎用在庫合計 |
| Generic Before | より優先度の高い前置プロジェクトが使い切る汎用在庫合計 |

> **Generic Before** が大きい場合、前置プロジェクトが汎用在庫を多く消費しているため、自プロジェクトの汎用在庫が減る可能性があります。

---

## 7. Confirm Allocation（確保の確定）

Planning Board で見つかった「確保可能な供給」を、実際にこのプロジェクト専用のリソースとして確定する操作です。

### 7.1 何をする操作か

Confirm Allocation を実行すると以下の 2 つが行われます：

| 処理 | 内容 |
|-----|-----|
| **在庫の予約（Reservation）作成** | STOCK 在庫からの充当分 → プロジェクト紐付きの Reservation レコードが作成される |
| **汎用発注のプロジェクト割当** | 汎用入荷予定からの充当分 → その発注の `project_id` にこのプロジェクトが設定される（必要に応じて発注を分割） |

> この操作は在庫を物理的に移動しません。「このプロジェクトのために確保した」という記録を作る操作です。

### 7.2 手順（必ず Preview → Confirm の 2 ステップで実行）

**ステップ 1：Preview Confirm（プレビュー）**

1. Planning Board で対象プロジェクトを選択し、分析日を設定して **Preview Impact** を実行
2. アクション欄の **Preview Confirm** をクリック
3. 画面に **Allocation Preview** パネルが表示される

   表示内容の確認ポイント：
   - **Orders assigned**：汎用発注として直接プロジェクトに割り当てられる件数
   - **Orders split**：一部のみ使用するため分割される発注と数量
   - **Reservations**：STOCK から確保される予約の件数と数量
   - **Skipped**：何らかの理由でスキップされた行（理由も表示される）

> ⚠️ プレビューはまだ何も変更しません。内容を確認してから次のステップへ進んでください。

**ステップ 2：Confirm Allocation（実行）**

1. Allocation Preview の内容を確認してよければ **Confirm Allocation** をクリック
2. 確認ダイアログで **OK** をクリック
3. 処理結果が画面に表示される（割り当て数・分割数・予約数）

> ⚠️ **注意点：**
> - Confirm Allocation を実行すると Planning Board の表示が更新されます。プレビューを見た後に日付を変更した場合は、**Preview Impact** を再実行してからでないと Confirm Allocation ボタンは無効のままです。
> - 既に RFQ/調達管理下にある発注は自動で割当対象から除外されます（Skipped に表示）。
> - スナップショットが変化した場合（他の操作で在庫が変わった等）、実行時に `409 PLANNING_SNAPSHOT_CHANGED` エラーが出ることがあります。その場合は **Preview Confirm** をやり直してください。

### 7.3 Confirm Allocation 後の状態

| 変化 | 確認場所 |
|-----|---------|
| Reservation が作成された | **Reserve** ページ → Project フィルターで確認 |
| 発注の project_id が設定された | **Orders** ページ → 該当発注の詳細 |
| Planning Board の Coverage が更新 | 再度 **Preview Impact** を実行 |

---

## 8. 不足分の調達依頼（Procurement Batch / RFQ）

Planning Board で `On-Time Gap > 0` の行がある場合、不足分を調達依頼に回します。

### 8.1 Procurement Batch の作成

1. Planning Board で対象プロジェクトを選択し分析を実行
2. `On-Time Gap` が 0 より大きい行が存在することを確認
3. **Create Procurement Batch** ボタンをクリック
   - `PLANNING` 状態のプロジェクトの場合、この操作で自動的に `CONFIRMED` へステータスが昇格します
4. 確認ダイアログで **OK**
5. 調達バッチが作成され、画面に `Created procurement batch #X` と表示される

### 8.2 Procurement ページでの管理

1. **Procurement** ページを開く（または左メニューの **RFQ**）
2. 作成されたバッチが一覧に表示される
3. バッチを開いて各行（RFQ Line）を管理する

#### RFQ Line のステータス遷移

```
DRAFT（初期）
    ↓ サプライヤーに問い合わせ後
SENT（送付済み）
    ↓ 見積取得後
QUOTED（見積取得済み）← expected_arrival を設定するとプランニングで供給扱いになる
    ↓ 発注確定後
ORDERED（発注済み）← linked_purchase_order_line_id を設定する
    ↓ キャンセル時
CANCELLED
```

> **QUOTED + expected_arrival 設定** → Planning Board で `quoted_rfq` タグとして表示され、その分は「確保済み」として計算されます。

### 8.3 発注が完了したら

1. 実際の発注インポートを行い（[2.3 操作手順](#23-操作手順) 参照）、発注レコードを作成
2. **Procurement** ページの該当 RFQ Line の `linked_purchase_order_line_id` に実際の発注 ID を設定し、ステータスを `ORDERED` に更新
3. 発注の `project_id` が自動的に設定される

---

## 9. 予約（Reservation）の管理

### 9.1 予約とは

予約（Reservation）は在庫を物理的に移動せずに「このプロジェクト（または用途）のために確保した」と記録する仕組みです。在庫数から差し引かれて計算されますが、部品は元のロケーションに留まります。

### 9.2 手動での予約作成

1. **Reserve** ページを開く
2. **Reservation Entry** フォームに入力

   | 項目 | 説明 |
   |-----|------|
   | Item | 予約する部品（品番検索） |
   | Quantity | 予約数量 |
   | Purpose | 用途・目的（任意） |
   | Deadline | 締切日（任意） |
   | Project | 関連プロジェクト（任意） |
   | Note | メモ（任意） |

3. **Reserve** をクリック

### 9.3 予約の状態

| 状態 | 意味 |
|-----|-----|
| `ACTIVE` | 有効。在庫から差し引き中 |
| `RELEASED` | 解放済み。在庫に戻った |
| `CONSUMED` | 消費済み。部品を実際に使用して在庫から取り出した |

### 9.4 予約の解放・消費

**Reserve** ページの予約一覧で対象行を選び：

- **Release**：予約を解放する（在庫に戻す）。全量または一部数量の指定が可能
- **Consume**：部品を実際に使用したとして在庫から削除。全量または一部数量の指定が可能

### 9.5 プロジェクト経由での予約作成（Projects ページから）

**Projects** ページで対象プロジェクトの **Reserve** ボタンをクリックすると、プロジェクトの全要件をまとめて予約できます（在庫が足りない場合は不足分はスキップされます）。

### 9.6 Confirm Allocation との関係

[第 7 章](#7-confirm-allocation確保の確定) の Confirm Allocation は STOCK 在庫分の予約を自動作成します。手動 **Reserve** と同じ仕組みで、`project_id` が設定された予約レコードが作成されます。

---

## 10. 入荷処理（Arrival）

発注した部品が届いたら **Arrival** ページで入荷処理を行います。

### 10.1 入荷処理の手順

1. **Arrival** ページを開く
2. 左ペインに ETA 別（期限超過・スケジュール済み・ETA なし）で発注一覧が表示される
3. 入荷した発注行を選択してクリック
4. 右ペインの詳細で **Process Arrival** をクリック（全量入荷の場合）
5. 一部のみ入荷した場合は **Partial Arrival** を選択し、実際の入荷数量を入力

> 部分入荷を処理すると、元の発注が「入荷済み（Arrived）」と「残残（Ordered）」の 2 行に自動分割されます。

---

## 11. よくある操作フローのまとめ

### フロー A：新規発注 CSV をインポートして在庫に反映するまで

```
1. Orders → CSV インポート → Preview → 確定
   └─ 未登録品番あり → Items で登録 → 再インポート
2. Arrival → 入荷処理
```

### フロー B：新プロジェクトの立ち上げから部品確保まで

```
1. Projects → プロジェクト作成（PLANNING）
2. Projects → 要件登録（必要部品・数量）
3. Planning Board → Preview Impact で不足確認
4. 在庫・汎用発注で充当できる部品 → Preview Confirm → Confirm Allocation
5. 不足が残る → Create Procurement Batch
6. Procurement → RFQ Line を管理し、見積・発注を進める
7. 実際の発注 CSV インポート → Arrival で入荷処理
```

### フロー C：現在使える部品点数を素早く確認する

```
Snapshot ページを開く
→ Basis = net available, Mode = future で当日スナップショットを確認
→ アイテムで絞り込み or CSV エクスポートして確認
```

### よくある疑問と回答

**Q: Confirm Allocation と Projects > Reserve の違いは何ですか？**  
A: 機能は同じで「プロジェクトのために在庫を予約すること」ですが、Planning Board の **Confirm Allocation** は計画ボードの分析結果（stock + 汎用発注）を根拠に、どの発注を割り当て・どれを分割するかまで自動計算します。Projects の **Reserve** ボタンは現在の在庫から直接予約するシンプルな一括操作です。

**Q: PLANNING と CONFIRMED の違いは何ですか？**  
A: `PLANNING` は下書き状態で、Planning Board では「What-If Preview（仮想シミュレーション）」として扱われます。他のプロジェクトの在庫計算には影響しません。`CONFIRMED` にすると計画パイプラインに正式に組み込まれ、このプロジェクトの需要が後続プロジェクトの利用可能在庫を減らします。

**Q: On-Time Gap と Remaining の違いは何ですか？**  
A: `On-Time Gap` は開始予定日までに間に合わない不足数量です。`Remaining` はその後の入荷予定なども含めて最終的に補填できない残不足数量です。Remaining が 0 でも On-Time Gap が残る場合は「後から届くが間に合わない」状況を意味します。

**Q: 409 PLANNING_SNAPSHOT_CHANGED エラーが出ました**  
A: Preview Confirm を実行してから実際の Confirm Allocation ボタンを押すまでの間に、他の操作で在庫や発注の状態が変化したためです。**Preview Confirm** を再実行してから Confirm Allocation を実行してください。

**Q: 発注インポートで "locked" エラーが出ます**  
A: 同じ `(サプライヤー + 発注番号)` の組み合わせはデフォルトで再インポートがロックされます。意図的に再インポートする場合はプレビュー画面で該当行の **Unlock** にチェックを入れてから確定してください。
