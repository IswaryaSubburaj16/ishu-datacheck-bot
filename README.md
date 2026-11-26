# Ishu's DataCheck Bot (Prototype)

A chatbot that checks a CSV table for possible data quality problems and answers questions about it.

**Try the web app:** https://ishu-datacheck-bot.streamlit.app

## What it does
- Flags missing values, repeated rows or IDs, negative or unusual numbers, mixed spelling, invalid dates and some age problems
- Answers counts, percentages, averages, totals, top results and simple links between two number columns

## Files
- `app.py`: the web app (Streamlit)
- `requirements.txt`: packages the web app needs
- `ishu_datacheck_bot.ipynb`: the Colab version

## How it works
1. Simple questions and data checks are handled by Python rules.
2. For other questions, Google Gemini turns the question into a fixed plan.
3. Python checks the plan and does the calculation. No AI-written code is run.
4. AI-planned calculations show an "I understood" line so you can check the meaning.

For AI questions, Gemini receives the question, column names and column types. Data rows are not sent to it. Your CSV is uploaded to the server that runs the app (Streamlit for the web app, Google Colab for the notebook), so use public or fake data only.

## Run it

### Web app
1. Open https://ishu-datacheck-bot.streamlit.app
2. Upload a CSV file, or use the practice data.
3. Optional, for AI questions: paste your own Gemini API key in the sidebar. The **Get a key** button shows the steps.
4. Try `check all`.

### Google Colab notebook
1. In Google Colab choose **File > Open notebook > GitHub** and open `ishu_datacheck_bot.ipynb` from this repository.
2. Optional, for AI questions: add your own Gemini API key in Colab Secrets as `GEMINI_API_KEY` and allow notebook access.
3. Click **Run all** and scroll to the chat window.
4. Try `check all`, or press **CSV** to load your own file.

## Testing during development
- Practice data with planted errors: the check results matched the planted errors.
- Titanic data (891 rows): found 177 missing ages.
- Student performance data (1,000 rows), with real Gemini: average score by group, a percentage question, and a "why" question that was correctly declined. These two calculated results were not separately verified by hand.
- Web app, student survey data (4,464 rows): a count matched the Colab result (3,619), and a percentage question with real Gemini returned 258 of 1,527 rows (16.90%).
- Superstore sample (9,994 rows), web app: total sales (2,297,200.86), West region rows (3,203) and negative profit rows (1,871) matched a separate calculation. This test showed that US-style dates were wrongly flagged, which was then fixed.

## Limits
- It cannot explain causes, predict, give advice, draw charts or join files.
- The AI can misunderstand a question.
- Flagged values may be correct. It does not change your data.
- Some checks give false alarms, for example a date column that mixes formats. The date check uses the most common format in each column. Some ID column names are not recognised.
- The duplicate row check compares whole rows, so a row number column can hide repeated records.
- CSV files only: under 5 MB in the web app, under 1 MB in the Colab notebook.
- Free hosting and the free AI model can be slow or unavailable.

Built by Iswarya Subburaj (Ishu), with AI assistance.
