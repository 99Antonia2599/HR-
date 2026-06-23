name: Weekly HR News Digest

on:
  schedule:
    # Jeden Montag um 07:00 UTC = 09:00 Uhr deutsche Zeit (Sommerzeit)
    - cron: '0 7 * * 1'
  workflow_dispatch: # Damit du es auch manuell starten kannst

jobs:
  generate-digest:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run HR Digest
        run: python hr_digest.py

      - name: Move docx to output folder
        run: mv *.docx output/ 2>/dev/null || true

      - name: Commit & push
        run: |
          git config user.name "HR News Bot"
          git config user.email "bot@noreply.github.com"
          git add output/
          git diff --staged --quiet || git commit -m "📰 HR News Digest $(date +%Y-%m-%d)"
          git push
