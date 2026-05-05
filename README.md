# Vinted Dashboard

> **⚠️ Legal notice:** The use of automated scraping tools may violate [Vinted's Terms of Service](https://www.vinted.es/terms-and-conditions). This project is intended for educational and personal use only. The author is not responsible for any use third parties make of this software.

A local dashboard for analysing Vinted listings with price history, interactive charts, and saved searches. All data is stored on your own machine. The UI is available in **English** and **Spanish**.


![Header](Docs/Header.png)


---

## Features

- **Search with filters** — free text, price range, category, condition, and sort order
- **10 countries** — Spain, France, Germany, Italy, United Kingdom, and more
- **Price history** — save multiple snapshots and track the evolution of mean, median, min, and max prices over time
- **Interactive charts** — publication timeline, price distribution, item condition breakdown, and top brands
- **Filterable table** — filter results by brand, size, and condition in one click
- **Fully local** — no data leaves your machine; everything is stored in SQLite
- **EN / ES interface** — switch language from the sidebar toggle

## Requirements

- Python 3.11 or higher
- Internet connection

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/vinted-dashboard.git
cd vinted-dashboard
pip install -r requirements.txt
```

## Usage

```bash
streamlit run app.py
```

The browser will open automatically at `http://localhost:8501`.

1. Open the left sidebar → **New search**
2. Give it a descriptive name (e.g. *"White Nike Air Force size 42"*)
3. Choose country, search text, category, and any other filters
4. Select a scan mode (**Normal** or **Cautious** recommended)
5. Click **Search & save**

To track market evolution, click **🔄 Update** a few days later and compare snapshots in the **History** tab.

## Scan modes

| Mode | Delay between pages | Recommended for |
|---|---|---|
| Fast | 1–2 s | Small searches (< 200 items) |
| Normal | 2–4 s | Everyday use |
| Cautious | 4–8 s | Large searches or when errors occur |

The scraper automatically refreshes the session cookie every ~650 items to avoid temporary blocks.

## Project structure

```
├── app.py          # Streamlit UI — layout, charts, navigation logic
├── scraper.py      # Vinted API client — pagination, retries, item parsing
├── db.py           # SQLite layer — searches, runs, items
├── i18n.py         # UI translations (English / Spanish)
└── requirements.txt
```

## Acknowledgements

This project uses [vinted-scraper](https://github.com/Jihed-Yahyaoui/vinted-scraper) by [Jihed Yahyaoui](https://github.com/Jihed-Yahyaoui), released under the MIT licence, to handle authentication and calls to Vinted's internal API.

## Licence

[MIT](LICENSE)
